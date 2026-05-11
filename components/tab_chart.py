"""
components/tab_chart.py
=======================
Render-Komponente fuer den Chart-Tab in der Bot-Detail-Ansicht.

Konsumiert eine BotView und zeichnet:
    - Preis-Candles + Volumen (via plot_grid_chart_v2)
    - Grid-Linien (aus bot.state.grids falls vorhanden, sonst live aus config)
    - Trade-Marker auf den Candles

Verwendet die zentrale Lightweight-Charts-Komponente; kein eigenes
Chart-Rendering.

Autor: Enes Eryilmaz
Projekt: Grid-Trading-Framework (Bachelorarbeit OST)
"""

from typing import Optional

import pandas as pd
import streamlit as st

from components.chart_v2 import plot_grid_chart_v2
from src.data.cache_manager import get_price_data
from src.strategy.grid_builder import calculate_grid_lines
from src.utils.timezone import convert_df_timestamps, utc_to_zurich


# Days-Map fuer den Chart-Default je Intervall.
# Bei BT wird stattdessen view["period"]["days"] verwendet (falls vorhanden).
_DAYS_BY_INTERVAL = {
    "1m": 1, "5m": 1, "15m": 2, "1h": 7, "4h": 14, "1d": 30,
}


def render_tab_chart(
    view:        dict,
    df:          Optional[pd.DataFrame] = None,
    show_volume: bool = True,
    height:      int  = 560,
) -> None:
    """
    Rendert den Chart-Tab fuer eine BotView.

    Args:
        view        : BotView-Dict (siehe components/bot_view.py)
        df          : Optional. Wenn None, wird via get_price_data geladen.
        show_volume : Volumen-Reihe anzeigen
        height      : Chart-Hoehe in Pixel
    """
    coin     = view.get("coin", "")
    interval = view.get("interval", "1h")
    cfg      = view.get("config", {})

    # ── DataFrame beschaffen ────────────────────────────────────────────────
    if df is None:
        days = _DAYS_BY_INTERVAL.get(interval, 7)
        # BT: verwende den vollstaendigen Sim-Zeitraum
        period = view.get("period")
        if period and period.get("days"):
            try:
                days = max(days, int(period["days"]))
            except Exception:
                pass
        try:
            df, _ = get_price_data(coin, days=days, interval=interval)
        except Exception as e:
            st.warning(f"Chart-Fehler: {e}")
            return

    if df is None or df.empty:
        st.info("Keine Chart-Daten verfügbar.")
        return

    df_display = convert_df_timestamps(df)

    # ── Grid-Linien bestimmen ───────────────────────────────────────────────
    # Bevorzugt die echten Bot-Grid-Positionen aus dem State (PT/LT mit
    # laufendem Bot); sonst live aus der Config berechnen (BT, oder PT/LT
    # ohne State).
    state       = view.get("state") or {}
    state_grids = state.get("grids") or {}
    grid_lines  = []
    if state_grids:
        try:
            grid_lines = sorted([float(k) for k in state_grids.keys()])
        except Exception:
            grid_lines = []
    if not grid_lines:
        try:
            grid_lines = calculate_grid_lines(
                float(cfg.get("lower_price", 0)),
                float(cfg.get("upper_price", 0)),
                int(cfg.get("num_grids", 10)),
                cfg.get("grid_mode", "arithmetic"),
            )
        except Exception:
            grid_lines = []

    # ── Trade-Log: Timestamps nach Zurich konvertieren ─────────────────────
    trade_log_display = []
    for t in view.get("trade_log", []):
        t2 = dict(t)
        try:
            t2["timestamp"] = utc_to_zurich(t2["timestamp"])
        except Exception:
            pass
        trade_log_display.append(t2)

    # ── Render ──────────────────────────────────────────────────────────────
    upper = float(grid_lines[-1]) if grid_lines else float(cfg.get("upper_price", 0))
    lower = float(grid_lines[0])  if grid_lines else float(cfg.get("lower_price", 0))

    plot_grid_chart_v2(
        df          = df_display,
        grid_lines  = grid_lines,
        trade_log   = trade_log_display,
        coin        = coin,
        interval    = interval,
        show_volume = show_volume,
        upper_price = upper,
        lower_price = lower,
        height      = height,
    )
