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
        Live-Mode-Initialisierung. Ruft super().initialize() (GridBot wird
        konstruiert + intern _perform_initial_setup ausgefuehrt) und setzt
        danach den simulierten Initial-Buy-State zurueck, damit der spaetere
        _ensure_initial_buys() echte Orders senden kann, ohne doppelte
        Buchung.

        Begruendung: GridBot.__init__ ruft bei bot_status='active' selbst
        _perform_initial_setup (grid_bot.py:291), das die Sell-Linien-Buys
        SIMULIERT (trade_log + coin_inventory + position). Im Live-Modus
        sind das aber keine echten Trades — wir wollen sie durch echte
        MARKET-Buys via _broker.execute_market_buy_real ersetzen.

        Reset betrifft:
          - trade_log[]              -> []
          - coin_inventory[]         -> []
          - position                 -> {"usdt": eff_capital, "coin": 0}
          - initial_buy_*-Aggregate  -> 0
          - Grid-Sides + Pufferzone bleiben (B-2-Filter aktiv)
        """
        ok, err = super().initialize()
        if not ok or self._grid_bot is None:
            return ok, err
        gb  = self._grid_bot
        cfg = self._bot.get("config", {})
        # Effektives Kapital nach reserve_pct (= base_amount_usdt * num_grids)
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

            # Aggregat-Tracking analog zur Simulation
            self._grid_bot.initial_buy_coin_amount += exec_qty
            self._grid_bot.initial_buy_fee         += commission
            self._grid_bot.initial_buy_value_usdt  += cost_usdt

            success_count += 1

        # Variante A: Flag nur setzen wenn mindestens 1 Buy erfolgreich war.
        # Sonst Retry beim naechsten Aufruf.
        if success_count > 0:
            bot_state["live_initial_buys_done"] = True
            # Trade-Log + Inventar persistieren via _save_state-Aufruf
            # NICHT hier — _save_state ist ein Base-Helper, ruft sich
            # selbst in step() auf. In Live-2.2 koennen wir aber
            # zumindest den State + trade_log direkt schreiben:
            self.store.update_bot(self.bot_id, {
                "state":     bot_state,
                "trade_log": list(self._grid_bot.trade_log),
            })
        # Bei success_count == 0: keine Persistierung, Flag bleibt False,
        # naechster step() wird's nochmal probieren.
