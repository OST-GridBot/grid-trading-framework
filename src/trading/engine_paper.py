"""
src/trading/engine_paper.py
===========================
BotRunner fuer Paper-Trading.

Erbt die gesamte Logik (initialize, step, _save_state, run_update) von
BotRunnerBase. Kein eigener Broker, keine echten Orders — der GridBot
simuliert Trades direkt via process_candle.

PaperRunner existiert als eigene Klasse, damit der Modus in Tracebacks
und Logs klar identifizierbar ist und Phase Live-2 die LiveRunner-Klasse
eigenstaendig erweitern kann, ohne PaperRunner anzufassen.

Autor: Enes Eryilmaz
Projekt: Grid-Trading-Framework (Bachelorarbeit OST)
"""
from src.trading.engine_base import BotRunnerBase


class PaperRunner(BotRunnerBase):
    """BotRunner fuer Paper-Trading. Erbt alles, kein Broker noetig."""
    pass
