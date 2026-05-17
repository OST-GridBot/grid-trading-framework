"""
src/trading/engine.py
=====================
Dispatcher: leitet je nach Bot-Modus an den richtigen Runner weiter.

    paper / backtest / unbekannt  -> engine_paper.PaperRunner
    live                          -> engine_live.LiveRunner

Aufrufer (Pages/Komponenten) nutzen ausschliesslich make_bot_runner(bot_id)
und muessen den Modus selbst nicht kennen. Gemeinsame Logik (initialize,
step, _save_state, run_update) lebt in engine_base.BotRunnerBase, Modus-
spezifische Erweiterungen (LiveBroker-Init in Phase Live-1, LIMIT-Polling
in Phase Live-2) in engine_paper / engine_live.

Backtest-Pfad nutzt diesen Dispatcher NICHT — BT laeuft ueber
src/backtesting/engine.py::run_backtest mit simulate_grid_bot, ohne
BotRunner.

Autor: Enes Eryilmaz
Projekt: Grid-Trading-Framework (Bachelorarbeit OST)
"""
from src.trading.bot_store import store as default_store


def make_bot_runner(bot_id: str, store=None):
    """
    Liefert die passende Runner-Instanz fuer den Bot.

    Args:
        bot_id : Bot-ID aus dem BotStore
        store  : Optional BotStore-Instanz (Default: globaler Store)

    Returns:
        LiveRunner (mode=="live") oder PaperRunner (sonst)

    Raises:
        ValueError wenn der Bot im Store nicht existiert.
    """
    store = store or default_store
    bot   = store.get_bot(bot_id)
    if bot is None:
        raise ValueError(f"Bot {bot_id} nicht gefunden")
    if bot.get("mode") == "live":
        from src.trading.engine_live import LiveRunner
        return LiveRunner(bot_id, store)
    # paper / backtest / unbekannt -> PaperRunner (Simulation, kein Broker)
    from src.trading.engine_paper import PaperRunner
    return PaperRunner(bot_id, store)
