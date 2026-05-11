"""
components/tab_trades.py
========================
Render-Komponente fuer den Trade-Log-Tab in der Bot-Detail-Ansicht.

Konsumiert eine BotView und delegiert die eigentliche Tabellen-Darstellung
an render_trade_log() in metrics_display.py - duenne Schicht, damit alle
drei Tabs (chart/trades/configuration) ein einheitliches Aufruf-Pattern
haben.

Autor: Enes Eryilmaz
Projekt: Grid-Trading-Framework (Bachelorarbeit OST)
"""

import streamlit as st

from components.metrics_display import render_trade_log


def render_tab_trades(view: dict, max_rows: int = 100000) -> None:
    """
    Rendert den Trade-Log-Tab fuer eine BotView.

    Args:
        view     : BotView-Dict (siehe components/bot_view.py)
        max_rows : Maximale Anzahl anzuzeigender Zeilen
    """
    trade_log = view.get("trade_log", [])
    mode      = view.get("mode", "")

    # Mode-spezifischer Hinweis bei leerem Trade-Log fuer laufende Bots
    if not trade_log and mode in ("paper", "live"):
        st.info("Noch keine Trades — Bot wartet auf Grid-Auslösung.")
        return

    render_trade_log(trade_log, max_rows=max_rows)
