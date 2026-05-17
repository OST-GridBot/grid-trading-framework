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

from config.settings import DEFAULT_FEE_RATE
from src.utils.timezone import naive_utc_now
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

            exec_qty    = float(order["exec_qty"])
            exec_price  = float(order["exec_price"])
            commission  = float(order["commission"])

            # Trade-Log-Eintrag (Format identisch zur Simulation, mit
            # zusaetzlichen Live-Feldern client_order_id / binance_order_id).
            self._grid_bot.trade_log.append({
                "timestamp":        order["timestamp"],
                "type":             "BUY",
                "cprice":           exec_price,         # Marktpreis (B-1)
                "price":            float(price),       # Grid-Linie
                "amount":           exec_qty,
                "fee":              commission,         # echte Fee (L-6)
                "profit":           0.0,
                "profit_gross":     0.0,
                "initial":          True,
                "client_order_id":  order.get("client_order_id"),
                "binance_order_id": order.get("binance_order_id"),
                "commission_asset": order.get("commission_asset"),
            })

            # FIFO-Inventar: (amount, buy_price_for_matching, timestamp)
            # buy_price_for_matching = current_price (Marktpreis), damit
            # spaetere Sell-Profit-Berechnung (sell_price - buy_price)
            # konsistent zur Simulation arbeitet.
            self._grid_bot.coin_inventory.append(
                (exec_qty, current_price, pd.Timestamp(order["timestamp"]))
            )

            # Phase Live-2.4: parallele sell_lines-Liste
            # Initial-Buy auf Sell-Linie X -> Coin soll auf X verkauft werden.
            sell_lines_list.append(float(price))

            # Aggregat-Tracking analog zur Simulation
            self._grid_bot.initial_buy_coin_amount += exec_qty
            self._grid_bot.initial_buy_fee         += commission
            self._grid_bot.initial_buy_value_usdt  += cost_usdt

            success_count += 1

        # Variante A: Flag nur setzen wenn mindestens 1 Buy erfolgreich war.
        # Sonst Retry beim naechsten Aufruf.
        if success_count > 0:
            bot_state["live_initial_buys_done"]      = True
            bot_state["live_inventory_sell_lines"]   = sell_lines_list
            self.store.update_bot(self.bot_id, {
                "state":     bot_state,
                "trade_log": list(self._grid_bot.trade_log),
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

        new_count = 0

        # ── BUY-Linien ───────────────────────────────────────────────────
        for price, grid in self._grid_bot.grids.items():
            if grid.side != "buy":
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

        # ── SELL-Orders aus live_inventory_sell_lines ───────────────────
        # Phase Live-2.4: Statt aus trade_log mit initial=True iterieren
        # wir ueber die parallele sell_lines-Liste, die fuer JEDEN Inventar-
        # Eintrag die Ziel-Sell-Linie kennt. Initial-Buys haben dort die
        # Sell-Linie aus _ensure_initial_buys, Normal-Buys (gefuellt via
        # _poll_open_orders) haben die naechsthoehere Linie ueber buy_price.
        sell_lines_list = list(bot_state.get("live_inventory_sell_lines") or [])
        inv = self._grid_bot.coin_inventory
        # Gleiche Laenge erwarten; defensiv das Minimum nehmen
        n = min(len(inv), len(sell_lines_list))
        for i in range(n):
            qty    = float(inv[i][0])
            target = float(sell_lines_list[i])
            if qty <= 0 or target <= 0:
                continue
            key = ("SELL", target)
            if key in occupied:
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
            occupied.add(key)
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

            if has_fill:
                agg        = self._broker._aggregate_fills(fills)
                exec_avg   = (agg["avg_price"]
                              if agg["total_qty"] > 0 else grid_p)
                exec_qty   = (agg["total_qty"]
                              if agg["total_qty"] > 0 else executed_qty)
                commission = agg["total_commission"]
                comm_asset = agg["commission_asset"]
                ts         = naive_utc_now().isoformat()

                if side == "BUY":
                    self._grid_bot.coin_inventory.append(
                        (exec_qty, grid_p, pd.Timestamp(ts))
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
                        "amount":           exec_qty,
                        "fee":              commission,
                        "profit":           0.0,
                        "profit_gross":     0.0,
                        "initial":          False,
                        "client_order_id":  cid,
                        "binance_order_id": info.get("binance_order_id"),
                        "commission_asset": comm_asset,
                    })
                elif side == "SELL":
                    # Live-2.5 (L-1): Linien-basiertes Match statt FIFO.
                    # Suche Index in sell_lines, wo sell_lines[i] == grid_p
                    # (float-Toleranz). Pop diesen Index aus beiden
                    # parallelen Listen. FIFO-Fallback bei De-Sync.
                    matched_buy_price = None
                    matched_idx = None
                    for i, sl in enumerate(sell_lines):
                        if abs(float(sl) - grid_p) < 1e-6:
                            matched_idx = i
                            break
                    if (matched_idx is None
                            and self._grid_bot.coin_inventory):
                        # Fallback FIFO (De-Sync oder alter State)
                        matched_idx = 0
                    if (matched_idx is not None
                            and matched_idx < len(self._grid_bot.coin_inventory)):
                        matched = self._grid_bot.coin_inventory.pop(matched_idx)
                        matched_buy_price = float(matched[1])
                        if matched_idx < len(sell_lines):
                            sell_lines.pop(matched_idx)
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

            # Order in jedem Fall aus tracked-Liste raus
            open_orders.pop(cid, None)
            changed = True

        if changed:
            bot_state["live_open_orders"]          = open_orders
            bot_state["live_inventory_sell_lines"] = sell_lines
            self.store.update_bot(self.bot_id, {
                "state":     bot_state,
                "trade_log": list(self._grid_bot.trade_log),
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

    def step(self, candle: dict) -> list:
        """
        Phase Live-2.4: Override von BotRunnerBase.step.
        Live-Pipeline statt Simulation:
            1. _poll_open_orders   (Status-Check + Buchhaltung)
            2. _ensure_initial_buys (einmalig, idempotent)
            3. _sync_limit_orders   (fehlende + Gegen-Orders)
            4. _save_state          (Metriken)

        GridBot.process_candle wird NICHT mehr aufgerufen — keine
        Simulation im Live-Modus. Trades entstehen ausschliesslich
        durch echte Binance-Fills, verbucht im Poll.

        Returns: Liste der neu hinzugekommenen Trades seit letztem step.
        """
        if self._grid_bot is None:
            return []
        cprice = float(candle.get("close", 0))
        trades_before = len(self._grid_bot.trade_log)

        self._poll_open_orders()
        self._ensure_initial_buys(cprice)
        self._sync_limit_orders(cprice)
        self._save_state(cprice)

        return self._grid_bot.trade_log[trades_before:]
