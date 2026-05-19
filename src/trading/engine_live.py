"""
src/trading/engine_live.py
==========================
BotRunner fuer Live-Trading.

Erbt von BotRunnerBase und ueberschreibt __init__, um zusaetzlich
einen LiveBroker zu instanziieren (Phase Live-1: time-sync, exchange-
Info, canTrade-Check).

Reihenfolge im Konstruktor:
    1. super().__init__(bot_id, store)
       -> setzt self.bot_id, self.store, self._bot, self._grid_bot=None,
          self._broker=None
    2. LiveBroker instanziieren + ggf. Bot-Status="error" setzen

Damit ist self.store fuer Status-Updates bei Init-Fail bereits verfueg-
bar. Logik 1:1 aus der frueheren engine.py (Phase Live-1 + PT-2-Fix):
status="error" lowercase, defensiv gegen Konstruktor-Exceptions.

Phase Live-2 Erweiterungen (kommen schrittweise):
    Live-2.2: _ensure_initial_buys(current_price)  [diese Datei]
    Live-2.3: _sync_limit_orders(current_price)
    Live-2.4: _poll_open_orders() + step()-Override

Autor: Enes Eryilmaz
Projekt: Grid-Trading-Framework (Bachelorarbeit OST)
"""
import pandas as pd

from config.settings import (
    DEFAULT_FEE_RATE,
    RESYNC_MIN_INTERVAL_SECONDS,
    COIN_BALANCE_DIFF_PCT_WARNING,
)
from src.utils.timezone import naive_utc_now
from src.trading.live_broker import fill_time_or_now
from src.trading.engine_base import BotRunnerBase
from src.trading.bot_store import BotStore


class LiveRunner(BotRunnerBase):
    """BotRunner fuer Live-Trading mit echtem Binance-Broker."""

    def __init__(self, bot_id: str, store: BotStore = None):
        # Base-Init zuerst — danach sind self.bot_id, self.store, self._bot
        # gesetzt und self._broker ist None (Default aus BotRunnerBase).
        super().__init__(bot_id, store)

        # Phase Live-1 (L-1): LiveBroker instanziieren. Der Block ist
        # identisch zur frueheren engine.py BotRunner.__init__ Z 56-84
        # (Stand 6d27c42, PT-2-Fix integriert).
        try:
            from config.settings import (
                BINANCE_API_KEY, BINANCE_SECRET_KEY
            )
            from src.trading.live_broker import LiveBroker
            cfg = self._bot.get("config", {})
            self._broker = LiveBroker(
                api_key    = BINANCE_API_KEY,
                api_secret = BINANCE_SECRET_KEY,
                coin       = self._bot["coin"],
                testnet    = False,
                fee_rate   = cfg.get("fee_rate", DEFAULT_FEE_RATE),
            )
            if not self._broker.init_ok:
                self.store.update_bot(self.bot_id, {
                    "status":     "error",
                    "last_error": self._broker.init_error,
                })
        except Exception as e:
            # Defensiv: falls Import/Instanziierung crasht, Bot in
            # Error-Status setzen, aber LiveRunner-Konstruktor selbst
            # nicht aufgeben (UI soll Bot weiter anzeigen koennen).
            self._broker = None
            self.store.update_bot(self.bot_id, {
                "status":     "error",
                "last_error": f"Broker-Init fehlgeschlagen: {e}",
            })

    # =======================================================================
    # Phase Live-2.2 (L-16): Initial-Buy real ausfuehren
    # =======================================================================

    def initialize(self) -> tuple:
        """
        Live-Mode-Initialisierung.

        Phase Live-2.5 (L-12 + L-2 Fix):
        State-Reset NUR bei echtem Erst-Init (live_initial_buys_done=False).
        Bei Re-Init (UI-Refresh, neuer LiveRunner aus Dispatcher) ist
        super().initialize() bereits via GridBot.load_state(saved_state)
        durchgelaufen und coin_inventory/trade_log/position sind aus dem
        persistierten Bot-State wiederhergestellt. Ein Reset hier wuerde
        sie vernichten und Coins bei Binance "verwaisen".

        Begruendung Reset bei Erst-Init: GridBot.__init__ ruft bei
        bot_status='active' selbst _perform_initial_setup (grid_bot.py:291),
        das die Sell-Linien-Buys SIMULIERT (trade_log + coin_inventory +
        position). Im Live-Modus sind das keine echten Trades — wir wollen
        sie durch echte MARKET-Buys via _broker.execute_market_buy_real
        ersetzen.

        Reset betrifft (nur Erst-Init):
          - trade_log[]              -> []
          - coin_inventory[]         -> []
          - position                 -> {"usdt": eff_capital, "coin": 0}
          - initial_buy_*-Aggregate  -> 0
          - Grid-Sides + Pufferzone bleiben (B-2-Filter aktiv)
        """
        ok, err = super().initialize()
        if not ok or self._grid_bot is None:
            return ok, err

        # Live-2.5: Re-Init eines bestehenden Bots → State erhalten
        bot_state = self._bot.get("state") or {}
        if bot_state.get("live_initial_buys_done"):
            # Phase Live-4.3 (L-8): Bestehender Bot → Resync mit Binance.
            # Defensiv: jegliche Exception darf den Init-Pfad nicht stoppen.
            # Resync hat eigenen Cooldown (10 Min) damit Worker-Ticks alle
            # 30s nicht jedesmal 2 API-Calls ausloesen.
            try:
                self._resync_from_binance()
            except Exception as e:
                print(f"[LiveRunner] Resync-Exception (best-effort skip): "
                      f"{type(e).__name__}: {e}")
            return ok, err

        # Erst-Init: GridBot hat simulierte Buys gemacht → resetten
        gb  = self._grid_bot
        cfg = self._bot.get("config", {})
        effective_investment = (cfg["total_investment"]
                                * (1 - cfg.get("reserve_pct", 0.03)))
        gb.trade_log               = []
        gb.coin_inventory          = []
        gb.position                = {"usdt": effective_investment, "coin": 0.0}
        gb.initial_buy_coin_amount = 0.0
        gb.initial_buy_fee         = 0.0
        gb.initial_buy_value_usdt  = 0.0
        return ok, err

    def _ensure_initial_buys(self, current_price: float) -> None:
        """
        Sendet beim ersten Aufruf echte MARKET-BUYs an Binance fuer alle
        Sell-Linien des aktiven Grids (Binance-Standard-Initial-Setup).

        Idempotenz: state['live_initial_buys_done'] verhindert Doppel-
        Ausfuehrung. Bei Total-Fehlschlag bleibt das Flag False, damit
        beim naechsten step() erneut versucht wird (Variante A).

        Format der erzeugten Trade-Log-Eintraege: identisch zur Simulation
        in GridBot._perform_initial_setup (cprice = exec_avg, price =
        Grid-Linie, initial=True, fee = echte Binance-Commission aus L-6).

        Args:
            current_price: aktueller Marktpreis (z.B. close der letzten Kerze)
        """
        # Guard 1: Broker muss verfuegbar und initialisiert sein
        if self._broker is None or not getattr(self._broker, "init_ok", False):
            return

        # Guard 2: GridBot muss initialisiert sein (sonst keine grids)
        if self._grid_bot is None:
            return

        # Guard 3: Bot-State aktualisieren (frische Sicht)
        self._bot      = self.store.get_bot(self.bot_id) or self._bot
        bot_state      = (self._bot.get("state") or {}).copy()
        if bot_state.get("live_initial_buys_done"):
            return  # schon erledigt

        # Guard 4: Config-Flag
        cfg = self._bot.get("config", {})
        if not cfg.get("enable_initial_buy", True):
            # Kein Initial-Buy gewuenscht — Flag setzen, fertig
            bot_state["live_initial_buys_done"] = True
            self.store.update_bot(self.bot_id, {"state": bot_state})
            return

        # Sell-Linien sammeln. Pufferzonen-Linie ist bereits side='blocked'
        # (siehe GridBot._perform_initial_setup mit B-2-Filter), also nicht
        # in dieser Liste enthalten.
        sell_grids = [
            (price, grid)
            for price, grid in self._grid_bot.grids.items()
            if grid.side == "sell" and grid.trade_amount > 0
        ]
        if not sell_grids:
            # Keine Sell-Linien -> trivial fertig
            bot_state["live_initial_buys_done"] = True
            self.store.update_bot(self.bot_id, {"state": bot_state})
            return

        # Phase Live-2.4: parallele sell_lines-Liste pflegen
        sell_lines_list = list(bot_state.get("live_inventory_sell_lines") or [])

        # Order-Loop: pro Sell-Linie einen MARKET-Buy senden
        success_count = 0
        for price, grid in sell_grids:
            # quoteOrderQty = Coin-Menge der Linie * aktueller Marktpreis
            # (entspricht semantisch dem cost_usdt in der Simulation, Z395)
            cost_usdt = grid.trade_amount * current_price

            order = self._broker.execute_market_buy_real(
                amount_usdt=cost_usdt,
            )
            if order.get("error"):
                # Einzel-Fehler: weiterlaufen (Variante A — Total-Retry beim
                # naechsten step nur, wenn alle scheitern). TODO Live-4:
                # zentrales Logging des Fehlers.
                continue

            exec_qty         = float(order["exec_qty"])
            exec_price       = float(order["exec_price"])
            commission       = float(order["commission"])
            commission_asset = order.get("commission_asset") or ""
            # MLT-1b (H-1): coin_commission ist die Summe NUR der COIN-
            # Anteile der commission ueber alle fills. Funktioniert auch
            # bei commission_asset="mixed" (Multi-Fill mit BNB-Discount-
            # Teil + COIN-Teil). Vor MLT-1b wurde nur der single-asset
            # Fall (commission_asset == coin) gefangen → mixed-Fills
            # speicherten Brutto trotz Coin-Abzug bei Binance.
            coin_commission  = float(order.get("coin_commission", 0) or 0)

            # MLT-1b (H-1 + H-3): net_qty mit Outer-Cap min(exec_qty, ...)
            # schuetzt zusaetzlich vor negativer commission (theoretisch
            # unmoeglich aber defensive). max(0, ...) bleibt fuer den
            # Fall commission > exec_qty (Edge).
            net_qty = min(exec_qty, max(0.0, exec_qty - coin_commission))

            # Trade-Log-Eintrag (Format identisch zur Simulation, mit
            # zusaetzlichen Live-Feldern client_order_id / binance_order_id).
            # amount = net_qty (was tatsaechlich im Wallet landet, MLT-1 LF-N1).
            self._grid_bot.trade_log.append({
                "timestamp":        order["timestamp"],
                "type":             "BUY",
                "cprice":           exec_price,         # Marktpreis (B-1)
                "price":            float(price),       # Grid-Linie
                "amount":           net_qty,
                "fee":              commission,         # echte Fee (L-6)
                "profit":           0.0,
                "profit_gross":     0.0,
                "initial":          True,
                "client_order_id":  order.get("client_order_id"),
                "binance_order_id": order.get("binance_order_id"),
                "commission_asset": commission_asset or None,
            })

            # MLT-1 B-5: buy_price = exec_price (echter Ausfuehrungspreis aus
            # fills), NICHT current_price (Markt-Mid vor Submit). Bei MARKET-
            # Buy entstehen ggf. Slippage zwischen current und exec — fuer
            # spaetere Sell-Profit-Berechnung (sell_price - buy_price) muss
            # der TATSAECHLICH gezahlte Preis verwendet werden.
            # MLT-1 LF-N1: net_qty (Brutto-exec_qty minus Commission falls
            # commission_asset == coin) — entspricht der real verfuegbaren
            # Coin-Menge fuer spaetere SELL-Orders, sonst lehnt Binance ab.
            # Cascade-Hinweis: L-24 (Skip-Buy-bei-Inventar-Linie) nutzt
            # inventory_buy_prices als Match-Key. Nach B-5-Fix sind diese
            # Werte exec_price (~current_price, nicht grid_p). L-24 wirkt
            # damit nur fuer Normal-Buys (die grid_p als buy_price haben)
            # — Initial-Buys sind auf Sell-Linien, keine Kollision moeglich.
            self._grid_bot.coin_inventory.append(
                (net_qty, exec_price, pd.Timestamp(order["timestamp"]))
            )

            # Phase Live-2.4: parallele sell_lines-Liste
            # Initial-Buy auf Sell-Linie X -> Coin soll auf X verkauft werden.
            sell_lines_list.append(float(price))

            # Aggregat-Tracking analog zur Simulation
            # MLT-1: net_qty fuer initial_buy_coin_amount (Brutto verbleibt
            # in initial_buy_value_usdt fuer korrekte Cash-Flow-Math).
            self._grid_bot.initial_buy_coin_amount += net_qty
            self._grid_bot.initial_buy_fee         += commission
            self._grid_bot.initial_buy_value_usdt  += cost_usdt

            success_count += 1

        # Variante A: Flag nur setzen wenn mindestens 1 Buy erfolgreich war.
        # Sonst Retry beim naechsten Aufruf.
        if success_count > 0:
            bot_state["live_initial_buys_done"]      = True
            bot_state["live_inventory_sell_lines"]   = sell_lines_list
            # Live-2.6 (L-16): Persist-Fehler-Handling nach erfolgreichen
            # MARKET-Buys. BotStore.update_bot returnt False bei Schreib-
            # fehler (kein Exception, siehe bot_store.py:329-348). Wenn
            # State nicht persistiert wird, sind echte Coins bei Binance
            # aber das Bot-State weiss nichts davon — beim naechsten Run
            # wuerden Initial-Buys wiederholt (Doppel-Kauf).
            persist_ok = self.store.update_bot(self.bot_id, {
                "state":     bot_state,
                "trade_log": list(self._grid_bot.trade_log),
            })
            if not persist_ok:
                # Bot in error-Status setzen damit Worker stoppt und
                # User manuell eingreifen kann.
                self.store.update_bot(self.bot_id, {
                    "status":     "error",
                    "last_error": (
                        f"Initial-Buy-Persistierung fehlgeschlagen. "
                        f"{success_count} MARKET-BUYs bei Binance ausgefuehrt, "
                        f"aber Bot-State nicht gespeichert. Manuelle "
                        f"Kontrolle/Abgleich noetig vor Bot-Reaktivierung."
                    ),
                })
        # Bei success_count == 0: keine Persistierung, Flag bleibt False,
        # naechster step() wird's nochmal probieren.

    # =======================================================================
    # Phase Live-2.3 (L-13): LIMIT-Orders auf Grid-Linien
    # =======================================================================

    def _sync_limit_orders(self, current_price: float) -> None:
        """
        Stellt sicher, dass auf jeder aktiven Grid-Linie eine LIMIT-Order
        bei Binance liegt. Idempotent: bestehende Orders (tracked via
        state['live_open_orders']) werden nicht doppelt platziert.

        Order-Logik pro Linie:
          - grid.side == 'buy'      -> LIMIT BUY  auf grid.price mit
                                       grid.trade_amount
          - grid.side == 'sell' und Initial-Buy auf dieser Linie vorhanden
            -> LIMIT SELL auf trade.price mit trade.amount (echte
               exec_qty aus Live-2.2, nicht grid.trade_amount — wegen
               Slippage)
          - grid.side == 'blocked'  -> keine Order (Pufferzone)

        Idempotenz-Schluessel: (side, grid_price). Pro Linie und Richtung
        max. 1 Order. State wird nur bei mind. 1 neuer Order geschrieben
        (vermeidet leere Store-Writes bei No-Op-Sync).

        Failure-Resilience: einzelne Order-Fails werden geloggt
        (Phase Live-4 zentralisiert), nicht in live_open_orders eingetragen
        — naechster Sync retried sie.

        Args:
            current_price: aktueller Marktpreis (Argument fuer Symmetrie
                           mit _ensure_initial_buys; aktuell nicht direkt
                           genutzt, kann fuer kuenftige Plausibilitaets-
                           checks dienen).
        """
        # Guards
        if self._broker is None or not getattr(self._broker, "init_ok", False):
            return
        if self._grid_bot is None:
            return

        self._bot   = self.store.get_bot(self.bot_id) or self._bot
        bot_state   = (self._bot.get("state") or {}).copy()
        open_orders = dict(bot_state.get("live_open_orders") or {})

        # Schon belegte (side, grid_price)-Tupel
        occupied = {(o["side"], float(o["grid_price"]))
                    for o in open_orders.values()}

        # Live-2.6 (L-24): Skip-Set fuer Buy-Linien deren Coin schon im
        # Inventar liegt. Wirkt nur fuer Normal-Buys (buy_price=Grid-
        # Linie); Initial-Buys (buy_price=Marktpreis) kollidieren
        # konstruktionsbedingt nicht mit Buy-Linien.
        # Convention (siehe gridbot.py + engine_live.py):
        #   Initial-Buy : coin_inventory[i].buy_price = current_price
        #   Normal-Buy  : coin_inventory[i].buy_price = grid_p
        inventory_buy_prices = {
            float(item[1]) for item in self._grid_bot.coin_inventory
        }

        new_count = 0

        # ── BUY-Linien ───────────────────────────────────────────────────
        for price, grid in self._grid_bot.grids.items():
            if grid.side != "buy":
                continue
            # L-24: Coin von dieser Linie schon gekauft -> kein Re-Buy
            # bis die Gegen-Sell-Order gefuellt ist.
            if float(price) in inventory_buy_prices:
                continue
            key = ("BUY", float(price))
            if key in occupied:
                continue
            result = self._broker.place_limit_order(
                side="BUY",
                price=float(price),
                quantity=float(grid.trade_amount),
            )
            if result.get("error"):
                continue
            open_orders[result["client_order_id"]] = {
                "side":             "BUY",
                "grid_price":       float(price),
                "quantity":         float(result["quantity"]),
                "binance_order_id": result["binance_order_id"],
                "placed_at":        result["timestamp"],
            }
            occupied.add(key)
            new_count += 1

        # ── SELL-Orders pro Inventar-Eintrag ────────────────────────────
        # Phase Live-2.6 (L-25): 1 SELL-Order pro Coin mit eigener
        # clientOrderId. Tracking via inventory_idx im live_open_orders.
        # Mehrere Coins auf gleicher sell_line bekommen jetzt jeweils
        # eigene Order (vorher: occupied-Set blockte zweite Order ->
        # Coin steckte fest).
        sell_lines_list = list(bot_state.get("live_inventory_sell_lines") or [])
        inv = self._grid_bot.coin_inventory
        # Indizes mit bereits offener SELL-Order
        covered_indices = {
            info["inventory_idx"]
            for info in open_orders.values()
            if info.get("side") == "SELL"
               and info.get("inventory_idx") is not None
        }
        # Gleiche Laenge erwarten; defensiv das Minimum nehmen
        n = min(len(inv), len(sell_lines_list))
        for i in range(n):
            if i in covered_indices:
                continue
            qty    = float(inv[i][0])
            target = float(sell_lines_list[i])
            if qty <= 0 or target <= 0:
                continue
            result = self._broker.place_limit_order(
                side="SELL", price=target, quantity=qty,
            )
            if result.get("error"):
                continue
            open_orders[result["client_order_id"]] = {
                "side":             "SELL",
                "grid_price":       target,
                "quantity":         float(result["quantity"]),
                "binance_order_id": result["binance_order_id"],
                "placed_at":        result["timestamp"],
                "inventory_idx":    i,
            }
            new_count += 1

        # Persistieren nur wenn was Neues platziert wurde
        if new_count > 0:
            bot_state["live_open_orders"] = open_orders
            self.store.update_bot(self.bot_id, {"state": bot_state})

    # =======================================================================
    # Phase Live-2.4 (L-13, L-6): Polling + step()-Override
    # =======================================================================

    def _poll_open_orders(self) -> None:
        """
        Status-Check fuer alle tracked Orders via batched openOrders-Call.
        Verschwundene Orders -> Einzel-Status fuer Fill-Details.

        Buchhaltung (Variante 2 — Trennung Poll/Sync):
          FILLED BUY  -> coin_inventory.append + sell_lines.append(
                          next_grid_above(grid_price)) + trade_log-Eintrag
          FILLED SELL -> coin_inventory.pop(0)   + sell_lines.pop(0) (FIFO)
                          + trade_log-Eintrag (matched_buy_price, profit)
          CANCELED/REJECTED/EXPIRED -> nur aus live_open_orders raus
          PARTIALLY_FILLED -> bleibt offen (taucht weiter in openOrders auf)

        Gegen-Orders werden NICHT hier platziert. _sync_limit_orders
        macht das beim naechsten Aufruf automatisch (idempotent, sieht
        neue sell_lines-Eintraege ohne korrespondierende SELL-Order).
        """
        # Guards
        if self._broker is None or not getattr(self._broker, "init_ok", False):
            return
        if self._grid_bot is None:
            return

        self._bot   = self.store.get_bot(self.bot_id) or self._bot
        bot_state   = (self._bot.get("state") or {}).copy()
        open_orders = dict(bot_state.get("live_open_orders") or {})
        if not open_orders:
            return  # Nichts zu pollen

        sell_lines = list(bot_state.get("live_inventory_sell_lines") or [])

        # 1. Batched fetch
        binance_open = self._broker.get_open_orders()
        # Live-2.5 (L-22): API-Fehler -> None. Wir wissen nicht welche
        # Orders wirklich offen sind, also keine Diff-Verarbeitung.
        # State bleibt unveraendert, naechster step retried.
        if binance_open is None:
            return
        still_open_cids = {o.get("clientOrderId") for o in binance_open}

        # 2. Diff: state-CIDs nicht mehr in Binance-openOrders
        disappeared = [
            (cid, info) for cid, info in open_orders.items()
            if cid not in still_open_cids
        ]
        if not disappeared:
            return  # Alle Orders unveraendert offen

        grid_lines_sorted = sorted(self._grid_bot.grids.keys())
        changed = False

        for cid, info in disappeared:
            details = self._broker.get_order_status(cid)
            status  = (details.get("status") or "").upper()
            side    = info.get("side", "")
            grid_p  = float(info.get("grid_price", 0))

            # Live-2.5 (L-7): Fill-Erkennung via has_fill statt nur
            # status=FILLED. Bei CANCELED/EXPIRED mit executedQty>0
            # (Partial-Fill + Cancel) wurden Coins tatsaechlich
            # gehandelt — muessen analog verbucht werden, sonst gehen
            # sie im Bot-State verloren.
            fills        = details.get("fills", []) or []
            executed_qty = float(details.get("executedQty", 0) or 0)
            has_fill     = executed_qty > 0 or any(
                float(f.get("qty", 0)) > 0 for f in fills
            )

            # Live-4.1 (L-5): GET /api/v3/order liefert KEIN fills[]-Array
            # fuer LIMIT-Orders. Konsequenz vor diesem Fix: commission=0
            # bei allen LIMIT-Fills. Loesung: bei has_fill und leerem
            # fills[] zusaetzlich myTrades anfragen, das die echten
            # commission/commissionAsset pro Match liefert.
            # Backward-Compat: Alte Trade-Log-Eintraege werden NICHT
            # retrospektiv geaendert — der Fix wirkt nur fuer Fills die
            # ab jetzt durch _poll_open_orders gehen.
            if has_fill and not fills:
                bin_order_id = info.get("binance_order_id")
                if bin_order_id:
                    fills = self._broker.get_my_trades(bin_order_id) or []

            if has_fill:
                # MLT-1b (H-1): _aggregate_fills mit coin-Param liefert
                # zusaetzlich coin_commission_total — Summe NUR der COIN-
                # Anteile. Damit funktioniert die Netto-Berechnung auch
                # bei mixed-asset-fills (BNB-Discount Teil + COIN Teil).
                agg             = self._broker._aggregate_fills(
                    fills, coin=self._broker.coin,
                )
                exec_avg        = (agg["avg_price"]
                                   if agg["total_qty"] > 0 else grid_p)
                exec_qty        = (agg["total_qty"]
                                   if agg["total_qty"] > 0 else executed_qty)
                commission      = agg["total_commission"]
                comm_asset      = agg["commission_asset"]
                coin_commission = agg["coin_commission_total"]
                # Phase Live-4.6: ts aus echter Binance-Fill-Zeit ableiten.
                # Vorher: naive_utc_now() = Worker-Poll-Time, bei Resync
                # nach Worker-Pause/Offline-Phase Stunden daneben. Helper
                # liest max(fills[].time) und faellt defensiv zurueck auf
                # naive_utc_now() wenn time-Feld fehlt. fills wurde oben
                # ggf. via L-5 myTrades-Fallback nachgeladen (Z.519-522).
                ts              = fill_time_or_now(fills)

                if side == "BUY":
                    # MLT-1b (H-1 + H-3): Netto via coin_commission (statt
                    # commission_asset-Strikt-Vergleich), Outer-Cap
                    # min(exec_qty, ...) gegen negative-commission-Bug.
                    # Vor MLT-1b: nur single-asset SOL → net_qty richtig,
                    # aber bei mixed/None → Brutto gespeichert →
                    # Insufficient-Balance-Risk fuer SELL.
                    net_qty = min(
                        exec_qty,
                        max(0.0, exec_qty - coin_commission),
                    )

                    self._grid_bot.coin_inventory.append(
                        (net_qty, grid_p, pd.Timestamp(ts))
                    )
                    next_above = next(
                        (g for g in grid_lines_sorted if g > grid_p),
                        None,
                    )
                    sell_lines.append(float(next_above) if next_above else 0.0)
                    self._grid_bot.trade_log.append({
                        "timestamp":        ts,
                        "type":             "BUY",
                        "cprice":           exec_avg,
                        "price":            grid_p,
                        "amount":           net_qty,
                        "fee":              commission,
                        "profit":           0.0,
                        "profit_gross":     0.0,
                        "initial":          False,
                        "client_order_id":  cid,
                        "binance_order_id": info.get("binance_order_id"),
                        "commission_asset": comm_asset,
                    })
                elif side == "SELL":
                    # Live-2.6 (L-25): 3-stufiger Match-Algorithmus.
                    #   1) inventory_idx aus live_open_orders[cid]
                    #      (vom Sync gesetzt, eindeutig pro Coin)
                    #   2) L-1 Linien-Match (sell_lines[i] == grid_p)
                    #      — defensiv bei Crash/Stale inventory_idx
                    #   3) FIFO-Fallback (letzte Notnagel-Stufe)
                    matched_buy_price = None
                    matched_idx = None

                    # Stufe 1: inventory_idx
                    recorded_idx = info.get("inventory_idx")
                    if (isinstance(recorded_idx, int)
                            and 0 <= recorded_idx < len(self._grid_bot.coin_inventory)
                            and recorded_idx < len(sell_lines)
                            and abs(float(sell_lines[recorded_idx]) - grid_p) < 1e-6):
                        matched_idx = recorded_idx

                    # Stufe 2: Linien-Match (L-1)
                    if matched_idx is None:
                        for j, sl in enumerate(sell_lines):
                            if abs(float(sl) - grid_p) < 1e-6:
                                matched_idx = j
                                break

                    # Stufe 3: FIFO-Fallback
                    if (matched_idx is None
                            and self._grid_bot.coin_inventory):
                        matched_idx = 0

                    if (matched_idx is not None
                            and matched_idx < len(self._grid_bot.coin_inventory)):
                        matched = self._grid_bot.coin_inventory.pop(matched_idx)
                        matched_buy_price = float(matched[1])
                        if matched_idx < len(sell_lines):
                            sell_lines.pop(matched_idx)
                        # Re-Indizierung der noch offenen SELL-Orders:
                        # Eintraege mit inventory_idx > matched_idx
                        # zeigen jetzt auf den falschen Index, weil
                        # pop(matched_idx) alle nachfolgenden um 1 nach
                        # links verschoben hat.
                        for other_cid, other_info in open_orders.items():
                            if other_cid == cid:
                                continue
                            if other_info.get("side") != "SELL":
                                continue
                            other_idx = other_info.get("inventory_idx")
                            if isinstance(other_idx, int) and other_idx > matched_idx:
                                other_info["inventory_idx"] = other_idx - 1
                    profit_gross = (
                        (exec_avg - matched_buy_price) * exec_qty
                        if matched_buy_price is not None else 0.0
                    )
                    profit = profit_gross - commission
                    self._grid_bot.trade_log.append({
                        "timestamp":         ts,
                        "type":              "SELL",
                        "cprice":            exec_avg,
                        "price":             grid_p,
                        "amount":            exec_qty,
                        "fee":               commission,
                        "matched_buy_price": matched_buy_price,
                        "profit_gross":      profit_gross,
                        "profit":            profit,
                        "initial":           False,
                        "client_order_id":   cid,
                        "binance_order_id":  info.get("binance_order_id"),
                        "commission_asset":  comm_asset,
                    })

                # Phase Live-4.5: Pufferzone nach erstem realen Trade
                # aufheben — analog BT/PT-Logik in grid_bot.py:764. Vor
                # diesem Fix blieb _buffer_zone_price im LT permanent
                # gesetzt → 1 Grid-Linie dauerhaft "blocked" (siehe
                # grid_bot.py:461-463 _update_grid_sides), weil
                # _sync_limit_orders auf blocked-Linien keine LIMIT-Order
                # platziert. Reset wirkt symmetrisch fuer BUY- und SELL-
                # Branch — egal auf welcher Linie der erste reale Trade
                # fiel. Idempotent: bei mehreren Fills im selben Poll
                # macht der None-Check nichts mehr nach erstem Reset.
                # Initial-Buys (_ensure_initial_buys) sind separater
                # Pfad — beruehren _buffer_zone_price NICHT (analog BT/
                # PT, wo Initial-Buys in _perform_initial_setup ohne
                # _execute_trade laufen). Persistierung erfolgt unten
                # via update_bot (Z.659).
                if self._grid_bot._buffer_zone_price is not None:
                    self._grid_bot._buffer_zone_price = None

            # Order in jedem Fall aus tracked-Liste raus
            open_orders.pop(cid, None)
            changed = True

        if changed:
            bot_state["live_open_orders"]          = open_orders
            bot_state["live_inventory_sell_lines"] = sell_lines
            persist_ok = self.store.update_bot(self.bot_id, {
                "state":     bot_state,
                "trade_log": list(self._grid_bot.trade_log),
            })
            # MLT-1b (H-PERSIST): analog Live-2.6 L-16 fuer
            # _ensure_initial_buys. Wenn update_bot fehlschlaegt (Disk
            # full, JSON-Error, etc.), ist das in-memory _grid_bot bereits
            # mutiert (coin_inventory.append, sell_lines.append). Beim
            # naechsten Runner-Init wird der State frisch aus dem Store
            # geladen (ohne die Appends), aber bei Binance ist die Order
            # gefuellt → naechstes _poll_open_orders sieht sie als
            # 'disappeared' und verbucht sie nochmal → Doppel-Inventar.
            # Mitigation: Bot in error setzen, Worker pausiert ihn, User
            # muss manuell pruefen und Bot ggf. neu-initialisieren.
            if not persist_ok:
                self.store.update_bot(self.bot_id, {
                    "status":     "error",
                    "last_error": (
                        f"_poll_open_orders Persist fehlgeschlagen nach "
                        f"{len(disappeared)} Fill-Buchung(en). In-Memory-"
                        f"Stand nicht gesichert. Bot gestoppt zur "
                        f"Vermeidung von Doppel-Verbuchung beim naechsten "
                        f"Tick. Manuelle Bot-State-Kontrolle/Re-Init noetig."
                    ),
                })

    # =======================================================================
    # Live-2.5 (L-23): _save_state-Override um Live-spezifische State-Felder
    # gegen Ueberschreibung durch Base zu schuetzen.
    # =======================================================================

    _LIVE_STATE_FIELDS = (
        "live_initial_buys_done",
        "live_inventory_sell_lines",
        "live_open_orders",
    )

    def _save_state(self, current_price: float, df=None) -> None:
        """
        Phase Live-2.5 (L-23): BotRunnerBase._save_state ersetzt bot['state']
        komplett mit GridBot.get_state(). Unsere Live-spezifischen Felder
        (live_initial_buys_done, live_inventory_sell_lines, live_open_orders)
        sind aber nicht in GridBot.get_state() — sie wuerden bei jedem
        Step verloren gehen. Multi-Step-Tests vor diesem Fix zeigten:
        nach 30 Steps 120 statt 4 Inventar-Eintraege (Flag wurde
        ueberschrieben -> Initial-Buys wiederholt).

        Fix: vor super()._save_state Snapshot der Live-Felder nehmen,
        danach in den frisch geschriebenen State zurueckmergen.
        """
        # Snapshot vor Base-Save
        bot_before = self.store.get_bot(self.bot_id) or {}
        state_before = bot_before.get("state") or {}
        live_snapshot = {
            k: state_before[k]
            for k in self._LIVE_STATE_FIELDS
            if k in state_before
        }

        super()._save_state(current_price, df)

        if not live_snapshot:
            return  # Nichts zu mergen (z.B. ganz neuer Bot)

        bot_after = self.store.get_bot(self.bot_id) or {}
        state_after = dict(bot_after.get("state") or {})
        state_after.update(live_snapshot)
        self.store.update_bot(self.bot_id, {"state": state_after})

    # =======================================================================
    # Phase Live-4.3 (L-8): Inventar-Resync gegen Binance bei Bot-Start
    # =======================================================================

    def _resync_from_binance(self) -> dict:
        """
        Gleicht den lokalen Bot-State gegen Binance ab, wenn ein bestehender
        Bot (live_initial_buys_done=True) initialisiert wird. Wird aus
        initialize() aufgerufen — NICHT in jedem step().

        Drei Pruefungen:
          1. Open-Orders-Resync: Orders die lokal getrackt aber bei Binance
             nicht mehr offen sind, werden via _poll_open_orders verbucht
             (FILLED/CANCELED/EXPIRED).
          2. Coin-Balance-Check: lokales sum(coin_inventory) gegen Binance
             free+locked am Symbol-Coin. Diskrepanz >
             COIN_BALANCE_DIFF_PCT_WARNING -> Warning im state.
          3. Fremde Orders: openOrders mit clientOrderId NICHT in unserem
             tracked-state werden gezaehlt (sowohl 'gbf_*'-Stale aus
             geloeschten Bots als auch User-Manual-Orders). Nur Log,
             kein Auto-Adopt.

        Cooldown: state["last_resync_at"] verhindert Doppel-Sync innerhalb
        RESYNC_MIN_INTERVAL_SECONDS (Default 600s). Worker-Ticks alle 30s
        loesen so nicht jedesmal 2 zusaetzliche API-Calls aus.

        Failure-Verhalten: best-effort skip. API-Fehler setzen kein
        status='error' — Bot laeuft weiter, naechster initialize() versucht
        Resync neu.

        Returns dict (auch fuer Tests):
            {
                "skipped":              bool,
                "skip_reason":          str | None,
                "orders_disappeared":   int,
                "other_open_orders":    int,
                "balance_diff_pct":     float | None,
                "warning":              str | None,
            }
        """
        result = {
            "skipped":            False,
            "skip_reason":        None,
            "orders_disappeared": 0,
            "other_open_orders":  0,
            "balance_diff_pct":   None,
            "warning":            None,
        }

        # Guards
        if self._broker is None or not getattr(self._broker, "init_ok", False):
            result["skipped"]     = True
            result["skip_reason"] = "broker_not_ready"
            return result
        if self._grid_bot is None:
            result["skipped"]     = True
            result["skip_reason"] = "gridbot_not_ready"
            return result

        # Frische Sicht
        self._bot   = self.store.get_bot(self.bot_id) or self._bot
        bot_state   = (self._bot.get("state") or {}).copy()

        # ── Cooldown-Check ───────────────────────────────────────────────
        last = bot_state.get("last_resync_at")
        if last:
            try:
                last_dt = pd.Timestamp(last)
                if last_dt.tzinfo is None:
                    last_dt = last_dt.tz_localize("UTC")
                now = pd.Timestamp.now(tz="UTC")
                delta = (now - last_dt).total_seconds()
                # Live-4.3b LF-A1: Skip nur wenn delta im plausiblen
                # Cooldown-Fenster liegt (0 <= delta < INTERVAL).
                # Negative delta = Timestamp in der Zukunft (NTP-Drift
                # oder korrupter alter State) — Resync laeuft, ueber-
                # schreibt am Ende last_resync_at mit now → selbstheilend.
                if 0 <= delta < RESYNC_MIN_INTERVAL_SECONDS:
                    result["skipped"]     = True
                    result["skip_reason"] = (
                        f"cooldown ({int(delta)}s < "
                        f"{RESYNC_MIN_INTERVAL_SECONDS}s)"
                    )
                    return result
            except Exception:
                # Parse-Fehler → kein Skip, Resync laeuft durch
                pass

        # ── 1. Open-Orders-Resync ────────────────────────────────────────
        binance_open = self._broker.get_open_orders()
        if binance_open is None:
            # API-Fehler: best-effort skip, kein State-Update
            result["skipped"]     = True
            result["skip_reason"] = "openOrders_api_error"
            return result

        our_cids = set((bot_state.get("live_open_orders") or {}).keys())

        # Live-4.3b LF-E1: Direkt iterieren statt Set-Dedup, damit Orders
        # mit clientOrderId=None / fehlendem Key korrekt einzeln gezaehlt
        # werden. Vorher: {None, None} → dedupliziert auf 1 → falsch.
        # binance_cids bleibt als Set fuer disappeared-Check, enthaelt
        # aber nur echte (nicht-None) cids.
        binance_cids = set()
        other_count  = 0
        for o in binance_open:
            cid = o.get("clientOrderId")
            if cid is not None:
                binance_cids.add(cid)
            # Fremde Orders: bei Binance offen aber nicht in unserem state.
            # Erfasst sowohl manuelle User-Orders (cid != gbf_*) als auch
            # Stale-gbf_-Orders aus geloeschten Bots sowie cid=None.
            if cid not in our_cids:
                other_count += 1
        result["other_open_orders"] = other_count

        # Disappeared: in unserem state aber nicht mehr bei Binance.
        # _poll_open_orders haendelt die Buchhaltung (fills nachladen via
        # L-5-myTrades-Fallback, Inventar-Update, sell_lines-Pflege).
        disappeared = our_cids - binance_cids
        result["orders_disappeared"] = len(disappeared)
        if disappeared:
            try:
                self._poll_open_orders()
            except Exception as e:
                print(f"[LiveRunner Resync] _poll_open_orders-Exception: "
                      f"{type(e).__name__}: {e}")
            # Bot-State neu laden (poll hat ggf. persistiert)
            self._bot = self.store.get_bot(self.bot_id) or self._bot
            bot_state = (self._bot.get("state") or {}).copy()

        # ── 2. Coin-Balance-Check (free + locked) ────────────────────────
        try:
            account = self._broker._signed_request(
                "GET", "/api/v3/account", {}
            )
        except Exception as e:
            account = {"error": f"{type(e).__name__}: {e}"}

        if isinstance(account, dict) and "error" not in account:
            free   = 0.0
            locked = 0.0
            for asset in account.get("balances", []):
                if asset.get("asset") == self._broker.coin:
                    free   = float(asset.get("free",   0) or 0)
                    locked = float(asset.get("locked", 0) or 0)
                    break
            binance_total = free + locked
            # Live-4.3b LF-F3: coin_inventory or [] schuetzt vor TypeError
            # falls Inventar irrtuemlich None ist (defensive Migration).
            inventory_sum = sum(
                float(item[0])
                for item in (self._grid_bot.coin_inventory or [])
            )

            warning_msg = None
            if binance_total > 0:
                diff_pct = (abs(inventory_sum - binance_total)
                            / binance_total * 100)
                result["balance_diff_pct"] = round(diff_pct, 2)
                if diff_pct > COIN_BALANCE_DIFF_PCT_WARNING:
                    warning_msg = (
                        f"Coin-Balance-Diskrepanz {self._broker.coin}: "
                        f"inventory={inventory_sum:.8f}, Binance "
                        f"(free+locked)={binance_total:.8f} "
                        f"({diff_pct:.1f}%)"
                    )
            elif inventory_sum > 0:
                # Binance hat 0, wir denken wir besitzen Coins
                result["balance_diff_pct"] = 100.0
                warning_msg = (
                    f"Coin-Balance-Diskrepanz {self._broker.coin}: "
                    f"inventory={inventory_sum:.8f}, Binance "
                    f"(free+locked)=0"
                )

            if warning_msg:
                result["warning"] = warning_msg
                bot_state["last_resync_warning"] = warning_msg
                print(f"[LiveRunner Resync] {warning_msg}")
            else:
                # Alte Warning loeschen wenn jetzt OK
                bot_state.pop("last_resync_warning", None)

        # ── 3. State-Update (last_resync_at + Resync-Statistiken) ────────
        bot_state["last_resync_at"]           = pd.Timestamp.now(
            tz="UTC"
        ).isoformat()
        bot_state["last_resync_other_orders"] = other_count
        self.store.update_bot(self.bot_id, {"state": bot_state})

        return result

    # =======================================================================
    # Phase Live-4.2 (L-4): Cancel-on-Stop fuer offene LIMIT-Orders
    # =======================================================================

    def cancel_all_open_orders(self) -> dict:
        """
        Storniert alle in state['live_open_orders'] getrackte LIMIT-Orders
        bei Binance. Wird vom UI-Stop-Button aufgerufen, BEVOR der Bot-
        Status auf 'stopped' gesetzt wird.

        WICHTIG (CLAUDE.md regel 10): Diese Methode wird NICHT vom Worker-
        Shutdown (Ctrl+C im live_worker.py) aufgerufen. Worker-Stop laesst
        Orders absichtlich offen, Bot ruht nur. Cancel passiert ausschliesslich
        bei explizitem User-Stop ueber die UI.

        Fehler-Verhalten: Wenn eine Order nicht stornierbar ist (z.B. weil
        sie zwischenzeitlich gefuellt wurde, oder API-Error), wird sie
        einzeln geloggt und uebersprungen. Die anderen Orders werden
        weiterhin versucht. Bot geht NICHT in error-Status, weil ein
        Cancel-Miss kein Datenintegritaets-Problem ist (Order ist halt
        schon weg — der naechste run_update wuerde das via _poll_open_orders
        ohnehin verbuchen).

        Returns:
            {
                "n_canceled":  int,    # erfolgreich storniert
                "n_failed":    int,    # Cancel-Versuche mit Fehler
                "n_total":     int,    # Gesamt verarbeitete Orders
                "errors":      list,   # Fehler-Strings (fuer UI-Anzeige)
            }
        """
        result = {"n_canceled": 0, "n_failed": 0, "n_total": 0, "errors": []}

        # Guards
        if self._broker is None or not getattr(self._broker, "init_ok", False):
            return result

        # Aktuellen Bot-State holen
        self._bot   = self.store.get_bot(self.bot_id) or self._bot
        bot_state   = (self._bot.get("state") or {}).copy()
        open_orders = dict(bot_state.get("live_open_orders") or {})

        if not open_orders:
            return result

        result["n_total"] = len(open_orders)
        remaining = dict(open_orders)  # Working-Copy

        for cid, info in list(open_orders.items()):
            try:
                response = self._broker.cancel_order(cid)
            except Exception as e:
                # Defensive: Network-Fehler etc.
                err = f"{cid}: Exception {type(e).__name__}: {e}"
                result["errors"].append(err)
                result["n_failed"] += 1
                print(f"[LiveRunner] Cancel-Fehler {err}")
                continue

            if isinstance(response, dict) and "error" in response:
                # Binance hat Cancel abgelehnt (z.B. Order schon FILLED).
                # Wir entfernen sie trotzdem aus dem getrackten state —
                # _poll_open_orders wuerde sie ohnehin als "disappeared"
                # verbuchen, also ist sie hier nicht mehr relevant.
                err = f"{cid}: {response['error']}"
                result["errors"].append(err)
                result["n_failed"] += 1
                print(f"[LiveRunner] Cancel-Fehler {err}")
                remaining.pop(cid, None)
                continue

            # Erfolg — aus tracked entfernen
            remaining.pop(cid, None)
            result["n_canceled"] += 1

        # State persistieren
        bot_state["live_open_orders"] = remaining
        self.store.update_bot(self.bot_id, {"state": bot_state})

        return result

    def _record_daily_value(self, cprice: float) -> None:
        """
        MLT-2 (C-1): Aktualisiert daily_values[heute] mit dem aktuellen
        Portfolio-Wert (echte Binance-Balance free+locked × cprice +
        USDT-Balance). Wird in step() nach _save_state aufgerufen.

        Variante B (gemaess Mini-Plan): basiert auf echter Binance-
        Balance via _update_balances, NICHT auf lokalem position-State
        (der im LT nicht aktiv gepflegt wird).

        Letzter Wert pro Tag bleibt (mehrfache step-Aufrufe innerhalb
        eines Tages ueberschreiben mit jeweils aktuellem Stand).
        Voraussetzung fuer DD-Drosselung in Phase Live-7 (braucht
        daily_values fuer Drawdown-Berechnung).

        Defensive: jegliche Exception abgefangen — wenn API hin ist,
        skip silent (nicht Bot-blockierend).
        """
        if (self._broker is None
                or not getattr(self._broker, "init_ok", False)):
            return
        try:
            # Frische Balance von Binance holen (1 zusaetzlicher API-Call
            # pro step, alle 30s → unkritisch fuer Rate-Limit)
            self._broker._update_balances()
            bal_usdt = float(getattr(self._broker.state, "balance_usdt", 0) or 0)
            bal_coin = float(getattr(self._broker.state, "balance_coin", 0) or 0)
            portfolio_value = bal_usdt + bal_coin * float(cprice)
            date_str = pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%d")
            self._grid_bot.daily_values[date_str] = round(portfolio_value, 4)
        except Exception as e:
            print(f"[LiveRunner] daily_value-Update fehlgeschlagen "
                  f"(uebersprungen): {type(e).__name__}: {e}")

    def step(self, candle: dict) -> list:
        """
        Phase Live-2.4 / 2.6: Override von BotRunnerBase.step.
        Live-Pipeline statt Simulation:
            0. _update_grid_sides   (L-29, dynamische Side-Reklassifikation)
            1. _poll_open_orders    (Status-Check + Buchhaltung)
            2. _ensure_initial_buys (einmalig, idempotent)
            3. _sync_limit_orders   (fehlende + Gegen-Orders)
            4. _save_state          (Metriken)
            5. _record_daily_value  (MLT-2 C-1, daily_values fuer DD-Tracking)

        GridBot.process_candle wird NICHT aufgerufen — keine Simulation
        im Live-Modus. Trades entstehen ausschliesslich durch echte
        Binance-Fills, verbucht im Poll.

        L-29 (Live-2.6): _update_grid_sides analog BT/PT (gridbot.py:603).
        Damit wechseln Linien dynamisch zwischen 'buy'/'sell' je nach
        Markt — Standard-Binance-Grid-Verhalten. Pufferzone bleibt durch
        _buffer_zone_price geschuetzt (siehe gridbot.py:461-463).

        Returns: Liste der neu hinzugekommenen Trades seit letztem step.
        """
        if self._grid_bot is None:
            return []
        cprice = float(candle.get("close", 0))
        trades_before = len(self._grid_bot.trade_log)

        # L-29: Side-Reklassifikation als Pre-Step
        self._grid_bot._update_grid_sides(cprice)

        self._poll_open_orders()
        self._ensure_initial_buys(cprice)
        self._sync_limit_orders(cprice)
        self._save_state(cprice)
        self._record_daily_value(cprice)  # MLT-2 C-1

        return self._grid_bot.trade_log[trades_before:]
