"""
components/chart.py
===================
Plotly-Charts fuer den Grid-Bot.

Enthaelt:
    plot_grid_chart()      -> Hauptchart: Preis + Grid-Linien + Trades
    plot_equity_curve()    -> Portfolio-Wert ueber Zeit
    plot_drawdown_chart()  -> Drawdown-Verlauf
    plot_regime_chart()    -> Marktregime-Visualisierung

Autor: Enes Eryilmaz
Projekt: Grid-Trading-Framework (Bachelorarbeit OST)
"""

import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
from typing import Optional


# ---------------------------------------------------------------------------
# Farben
# ---------------------------------------------------------------------------

COLORS = {
    "price":       "#E2E8F0",
    "grid":        "rgba(100, 160, 255, 0.35)",
    "grid_active": "rgba(100, 160, 255, 0.80)",
    "buy":         "#34D399",
    "sell":        "#F87171",
    "portfolio":   "#60A5FA",
    "benchmark":   "rgba(148, 163, 184, 0.6)",
    "drawdown":    "rgba(248, 113, 113, 0.4)",
    "range":       "rgba(52, 211, 153, 0.12)",
    "trend_up":    "rgba(251, 191, 36, 0.12)",
    "trend_down":  "rgba(248, 113, 113, 0.12)",
    "bg":          "#0F1117",
    "grid_color":  "rgba(255,255,255,0.06)",
}

LAYOUT_BASE = dict(
    paper_bgcolor = COLORS["bg"],
    plot_bgcolor  = COLORS["bg"],
    font          = dict(family="monospace", color="#94A3B8", size=12),
    margin        = dict(l=10, r=10, t=40, b=10),
    legend        = dict(
        bgcolor     = "rgba(15,17,23,0.8)",
        bordercolor = "rgba(255,255,255,0.1)",
        borderwidth = 1,
        font        = dict(size=11),
    ),
    xaxis = dict(
        gridcolor    = COLORS["grid_color"],
        showgrid     = True,
        zeroline     = False,
        tickfont     = dict(size=10),
        showspikes   = True,
        spikecolor   = "rgba(255,255,255,0.3)",
        spikethickness = 1,
        spikedash    = "dot",
        spikemode    = "across",
    ),
    yaxis = dict(
        gridcolor    = COLORS["grid_color"],
        showgrid     = True,
        zeroline     = False,
        tickfont     = dict(size=10),
        side         = "right",
        showspikes   = True,
        spikecolor   = "rgba(255,255,255,0.3)",
        spikethickness = 1,
        spikedash    = "dot",
        spikemode    = "across",
    ),
    hovermode    = "x unified",
    hoverdistance = 50,
    spikedistance = 50,
)


# ---------------------------------------------------------------------------
# Hauptchart: Preis + Grid-Linien + Trades
# ---------------------------------------------------------------------------

def plot_grid_chart(
    df:          pd.DataFrame,
    grid_lines:  list,
    trade_log:   list,
    coin:        str        = "BTC",
    show_volume: bool       = True,
    title:       str        = "",
) -> go.Figure:
    """
    Hauptchart mit Kerzen, Grid-Linien und Trade-Markern.

    Args:
        df          : OHLCV-DataFrame
        grid_lines  : Liste der Grid-Preise
        trade_log   : Liste der Trades aus grid_bot
        coin        : Coin-Symbol fuer Titel
        show_volume : Volumen-Subplot anzeigen
        title       : Chart-Titel

    Returns:
        Plotly Figure
    """
    rows   = 2 if show_volume else 1
    heights = [0.75, 0.25] if show_volume else [1.0]

    fig = make_subplots(
        rows=rows, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.02,
        row_heights=heights,
    )

    # Candlestick
    fig.add_trace(go.Candlestick(
        x     = df["timestamp"],
        open  = df["open"],
        high  = df["high"],
        low   = df["low"],
        close = df["close"],
        name  = f"{coin}/USDT",
        increasing = dict(line=dict(color="#34D399", width=1), fillcolor="#34D399"),
        decreasing = dict(line=dict(color="#F87171", width=1), fillcolor="#F87171"),
        showlegend = True,
    ), row=1, col=1)

    # Grid-Linien
    price_min = float(df["low"].min())
    price_max = float(df["high"].max())

    for i, grid_price in enumerate(grid_lines):
        if not (price_min * 0.95 <= grid_price <= price_max * 1.05):
            continue
        fig.add_hline(
            y           = grid_price,
            line_width  = 1,
            line_dash   = "dot",
            line_color  = COLORS["grid"],
            row=1, col=1,
            annotation  = dict(
                text      = f"{grid_price:,.0f}",
                font      = dict(size=9, color=COLORS["grid_active"]),
                bgcolor   = "rgba(15,17,23,0.7)",
                borderpad = 2,
                x         = 1.0,
                xanchor   = "left",
            ) if i % 2 == 0 else None,
        )

    # Trade-Marker
    buys  = [t for t in trade_log if "BUY"  in t.get("type", "").upper()]
    sells = [t for t in trade_log if "SELL" in t.get("type", "").upper()
             and "Initial" not in t.get("type", "")]

    if buys:
        fig.add_trace(go.Scatter(
            x      = [t["timestamp"] for t in buys],
            y      = [t["price"]     for t in buys],
            mode   = "markers",
            name   = "BUY",
            marker = dict(
                symbol = "triangle-up",
                size   = 10,
                color  = COLORS["buy"],
                line   = dict(color="white", width=1),
            ),
        ), row=1, col=1)

    if sells:
        fig.add_trace(go.Scatter(
            x      = [t["timestamp"] for t in sells],
            y      = [t["price"]     for t in sells],
            mode   = "markers",
            name   = "SELL",
            marker = dict(
                symbol = "triangle-down",
                size   = 10,
                color  = COLORS["sell"],
                line   = dict(color="white", width=1),
            ),
        ), row=1, col=1)

    # Volumen
    if show_volume and "volume" in df.columns:
        colors = [
            COLORS["buy"] if c >= o else COLORS["sell"]
            for c, o in zip(df["close"], df["open"])
        ]
        fig.add_trace(go.Bar(
            x          = df["timestamp"],
            y          = df["volume"],
            name       = "Volumen",
            marker     = dict(color=colors, opacity=0.6),
            showlegend = False,
        ), row=2, col=1)

    # Layout
    layout = {**LAYOUT_BASE}
    layout["title"] = dict(
        text  = title or f"{coin}/USDT – Grid Chart",
        font  = dict(size=14, color="#E2E8F0"),
        x     = 0.01,
    )
    layout["xaxis_rangeslider_visible"] = False
    layout["height"] = 550 if show_volume else 450
    layout["yaxis2"] = dict(
        gridcolor = COLORS["grid_color"],
        showgrid  = False,
        tickfont  = dict(size=9),
        side      = "right",
    )
    fig.update_layout(**layout)
    return fig


# ---------------------------------------------------------------------------
# Equity Curve
# ---------------------------------------------------------------------------

def plot_equity_curve(
    daily_values:    dict,
    initial_value:   float,
    bh_prices:       Optional[pd.Series] = None,
    title:           str                 = "Portfolio-Entwicklung",
) -> go.Figure:
    """
    Portfolio-Wert ueber Zeit mit Buy-and-Hold Vergleich.

    Args:
        daily_values  : Dict {date_str: portfolio_value}
        initial_value : Startkapital
        bh_prices     : Preisreihe fuer Buy-and-Hold Vergleich
        title         : Chart-Titel
    """
    if not daily_values:
        return _empty_chart(title)

    dates  = list(daily_values.keys())
    values = list(daily_values.values())

    fig = go.Figure()

    # Portfolio-Linie
    fig.add_trace(go.Scatter(
        x          = dates,
        y          = values,
        mode       = "lines",
        name       = "Grid Bot",
        line       = dict(color=COLORS["portfolio"], width=2),
        fill       = "tozeroy",
        fillcolor  = "rgba(96, 165, 250, 0.08)",
    ))

    # Buy-and-Hold Vergleich
    if bh_prices is not None and len(bh_prices) > 0:
        bh_initial = float(bh_prices.iloc[0])
        bh_values  = [initial_value * (p / bh_initial) for p in bh_prices]
        fig.add_trace(go.Scatter(
            x    = bh_prices.index,
            y    = bh_values,
            mode = "lines",
            name = "Buy & Hold",
            line = dict(color=COLORS["benchmark"], width=1.5, dash="dash"),
        ))

    # Startkapital-Linie
    fig.add_hline(
        y          = initial_value,
        line_width = 1,
        line_dash  = "dot",
        line_color = "rgba(255,255,255,0.2)",
        annotation = dict(text="Start", font=dict(size=9, color="#64748B")),
    )

    layout = {**LAYOUT_BASE}
    layout["title"]  = dict(text=title, font=dict(size=13, color="#E2E8F0"), x=0.01)
    layout["height"] = 300
    layout["yaxis"]  = {**LAYOUT_BASE["yaxis"], "tickprefix": "$", "tickformat": ",.0f"}
    fig.update_layout(**layout)
    return fig


# ---------------------------------------------------------------------------
# Drawdown Chart
# ---------------------------------------------------------------------------

def plot_drawdown_chart(
    daily_values: dict,
    title:        str = "Drawdown",
) -> go.Figure:
    """
    Drawdown-Verlauf ueber Zeit.

    Args:
        daily_values : Dict {date_str: portfolio_value}
        title        : Chart-Titel
    """
    if not daily_values or len(daily_values) < 2:
        return _empty_chart(title)

    values = list(daily_values.values())
    dates  = list(daily_values.keys())
    peak   = values[0]
    dds    = []

    for v in values:
        if v > peak:
            peak = v
        dds.append((v - peak) / peak * 100 if peak > 0 else 0)

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x         = dates,
        y         = dds,
        mode      = "lines",
        name      = "Drawdown",
        line      = dict(color=COLORS["sell"], width=1.5),
        fill      = "tozeroy",
        fillcolor = COLORS["drawdown"],
    ))

    layout = {**LAYOUT_BASE}
    layout["title"]  = dict(text=title, font=dict(size=13, color="#E2E8F0"), x=0.01)
    layout["height"] = 200
    layout["yaxis"]  = {**LAYOUT_BASE["yaxis"], "ticksuffix": "%"}
    fig.update_layout(**layout)
    return fig


# ---------------------------------------------------------------------------
# Regime Chart
# ---------------------------------------------------------------------------

def plot_regime_chart(
    df:      pd.DataFrame,
    regime:  str,
    adx_col: str = "adx14",
    title:   str = "Marktregime",
) -> go.Figure:
    """
    ADX-Verlauf mit Regime-Hintergrund.

    Args:
        df      : DataFrame mit ADX-Werten
        regime  : Aktuelles Regime (range/trend_up/trend_down)
        adx_col : Spaltenname fuer ADX
        title   : Chart-Titel
    """
    if df is None or df.empty or adx_col not in df.columns:
        return _empty_chart(title)

    bg_color = {
        "range":      COLORS["range"],
        "trend_up":   COLORS["trend_up"],
        "trend_down": COLORS["trend_down"],
    }.get(regime, "rgba(100,100,100,0.1)")

    fig = go.Figure()

    # Hintergrund
    fig.add_hrect(y0=0, y1=25,  fillcolor=COLORS["range"],     opacity=1, line_width=0)
    fig.add_hrect(y0=25, y1=100, fillcolor=COLORS["trend_up"], opacity=1, line_width=0)

    # ADX-Linie
    fig.add_trace(go.Scatter(
        x    = df["timestamp"] if "timestamp" in df.columns else df.index,
        y    = df[adx_col],
        mode = "lines",
        name = "ADX",
        line = dict(color="#FBBF24", width=2),
    ))

    # Schwellenlinie bei 25
    fig.add_hline(
        y=25, line_width=1, line_dash="dot",
        line_color="rgba(255,255,255,0.3)",
        annotation=dict(text="ADX 25", font=dict(size=9, color="#94A3B8")),
    )

    layout = {**LAYOUT_BASE}
    layout["title"]  = dict(
        text = f"{title} – {regime.replace('_', ' ').title()}",
        font = dict(size=13, color="#E2E8F0"), x=0.01,
    )
    layout["height"] = 200
    layout["yaxis"]  = {**LAYOUT_BASE["yaxis"], "range": [0, 60]}
    fig.update_layout(**layout)
    return fig


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def _empty_chart(title: str = "") -> go.Figure:
    """Gibt einen leeren Chart mit Hinweis zurueck."""
    fig = go.Figure()
    fig.add_annotation(
        text      = "Keine Daten verfuegbar",
        xref      = "paper", yref="paper",
        x=0.5, y=0.5, showarrow=False,
        font      = dict(size=14, color="#64748B"),
    )
    layout = {**LAYOUT_BASE}
    layout["title"]  = dict(text=title, font=dict(size=13, color="#E2E8F0"), x=0.01)
    layout["height"] = 200
    fig.update_layout(**layout)
    return fig