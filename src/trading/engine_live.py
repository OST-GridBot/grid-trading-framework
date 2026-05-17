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

Phase Live-2 wird hier um LIMIT-Order-Polling, Partial-Fill-Aggregation
und Cancel-on-Stop erweitert — ohne BotRunnerBase / PaperRunner anzu-
fassen.

Autor: Enes Eryilmaz
Projekt: Grid-Trading-Framework (Bachelorarbeit OST)
"""
from config.settings import DEFAULT_FEE_RATE
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
