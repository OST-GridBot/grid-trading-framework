"""
pages/page_market.py
====================
Marktübersicht – Startseite des Grid-Trading-Frameworks.
Zeigt den Kursverlauf der gewählten Kryptowährung.

Autor: Enes Eryilmaz
Projekt: Grid-Trading-Framework (Bachelorarbeit OST)
"""

import streamlit as st
import pandas as pd
from src.data.cache_manager import get_price_data
from src.utils.timezone import convert_df_timestamps
from components.chart import plot_grid_chart
from components.chart_v2 import plot_grid_chart_v2

COINS = [
    "BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "DOGE", "AVAX",
    "DOT", "MATIC", "LINK", "UNI", "ATOM", "LTC", "BCH",
    "NEAR", "APT", "OP", "ARB", "FTM",
]

INTERVALS = {
    "1m":  ("1 Minute",   1),
    "5m":  ("5 Minuten",  5),
    "15m": ("15 Minuten", 14),
    "1h":  ("1 Stunde",   30),
    "4h":  ("4 Stunden",  90),
    "1d":  ("1 Tag",      365),
}

LABEL_STYLE = (
    "font-size:1.15rem; font-weight:600; color:#CBD5E1; "
    "font-family:Inter,-apple-system,sans-serif; text-transform:uppercase; "
    "letter-spacing:0.06em; margin-bottom:4px;"
)

def _label(text):
    return f"<div style='{LABEL_STYLE}'>{text}</div>"


def show_market():
    # -----------------------------------------------------------------------
    # Sidebar
    # -----------------------------------------------------------------------
    st.sidebar.markdown(_label("Coin"), unsafe_allow_html=True)
    coin_mode = st.sidebar.radio(
        "", ["Aus Liste", "Eigene Eingabe"],
        horizontal=True, key="mkt_coin_mode"
    )
    if coin_mode == "Aus Liste":
        coin = st.sidebar.selectbox(
            "", COINS, label_visibility="collapsed", key="mkt_coin"
        )
    else:
        coin = st.sidebar.text_input(
            "", value="BTC", label_visibility="collapsed",
            key="mkt_coin_input"
        ).upper().strip()

    st.sidebar.markdown("<div style='margin-top:12px'></div>", unsafe_allow_html=True)
    st.sidebar.markdown(_label("Intervall"), unsafe_allow_html=True)
    interval = st.sidebar.radio(
        "", list(INTERVALS.keys()),
        index=3, horizontal=True,
        key="mkt_interval", label_visibility="collapsed"
    )

    st.sidebar.markdown("<div style='margin-top:12px'></div>", unsafe_allow_html=True)
    st.sidebar.markdown(_label("Zeitraum"), unsafe_allow_html=True)
    _, default_days = INTERVALS[interval]
    days = st.sidebar.slider(
        "", min_value=1, max_value=365,
        value=default_days, key="mkt_days",
        label_visibility="collapsed"
    )
    st.sidebar.caption(f"→ Letzte {days} Tage")

    st.sidebar.markdown("<div style='margin-top:12px'></div>", unsafe_allow_html=True)
    st.sidebar.markdown(_label("Chart"), unsafe_allow_html=True)
    chart_type  = st.sidebar.selectbox(
        "", ["Candlestick", "Linie"],
        key="mkt_chart_type", label_visibility="collapsed"
    )
    show_volume = st.sidebar.checkbox(
        "Volumen anzeigen", value=True, key="mkt_volume"
    )

    # -----------------------------------------------------------------------
    # Header
    # -----------------------------------------------------------------------
    st.markdown("# Cockpit")

    # Marktübersicht Section Header
    st.markdown("""
    <div style="display:flex; align-items:center; gap:10px; margin-bottom:16px; margin-top:8px;">
        <span style="font-size:1.2rem;">🌐</span>
        <span style="font-size:1.15rem; font-weight:600; color:#CBD5E1;
                     text-transform:uppercase; letter-spacing:0.06em;">
            Marktübersicht
        </span>
    </div>
    """, unsafe_allow_html=True)


    # -----------------------------------------------------------------------
    # Preisdaten laden
    # -----------------------------------------------------------------------
    with st.spinner(f"Lade {coin}/USDT..."):
        df, from_cache = get_price_data(coin, days=days, interval=interval)

    if df is None or df.empty:
        st.error(f"Keine Daten für {coin}/USDT verfügbar.")
        return

    # UTC → MEZ
    df_display = convert_df_timestamps(df)

    # -----------------------------------------------------------------------
    # Aktuelle Kennzahlen
    # -----------------------------------------------------------------------
    last_price  = float(df["close"].iloc[-1])
    first_price = float(df["close"].iloc[0])
    change_pct  = (last_price - first_price) / first_price * 100
    high        = float(df["high"].max())
    low         = float(df["low"].min())
    color       = "#34D399" if change_pct >= 0 else "#F87171"
    arrow       = "▲" if change_pct >= 0 else "▼"

    col1, col2, col3, col4 = st.columns(4)
    col1.metric(
        f"{coin}/USDT",
        f"${last_price:,.2f}",
        f"{arrow} {change_pct:+.2f}% ({days}d)"
    )
    col2.metric("Hoch", f"${high:,.2f}")
    col3.metric("Tief", f"${low:,.2f}")
    col4.metric("Kerzen", f"{len(df):,}")

    st.markdown("<div style='margin-top:8px'></div>", unsafe_allow_html=True)

    # -----------------------------------------------------------------------
    # Chart
    # -----------------------------------------------------------------------
    plot_grid_chart_v2(
        df          = df_display,
        grid_lines  = [],
        trade_log   = [],
        coin        = coin,
        interval    = interval,
        show_volume = show_volume,
        height      = 620,
    )

    # Cache-Info
    cache_txt = "aus Cache" if from_cache else "live von Binance"
    st.caption(f"Daten: {cache_txt} · {len(df)} Kerzen · {coin}/USDT {interval}")


    # -----------------------------------------------------------------------
    # Bot-Status Felder
    # -----------------------------------------------------------------------
    st.markdown("<div style='margin-top:32px'></div>", unsafe_allow_html=True)

    # Paper Trading
    st.markdown("""
    <div style="display:flex; align-items:center; gap:10px; margin-bottom:10px;">
        <span style="font-size:1.2rem;">📄</span>
        <span style="font-size:1.15rem; font-weight:600; color:#CBD5E1;
                     text-transform:uppercase; letter-spacing:0.06em;">Paper Trading</span>
    </div>
    <div style="background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.08);
                border-radius:10px; padding:20px 24px; margin-bottom:20px;">
        <div style="color:#475569; font-size:0.85rem; font-style:italic;">
            🔧 Wird noch implementiert
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Live Trading
    st.markdown("""
    <div style="display:flex; align-items:center; gap:10px; margin-bottom:10px;">
        <span style="font-size:1.2rem;">🔴</span>
        <span style="font-size:1.15rem; font-weight:600; color:#CBD5E1;
                     text-transform:uppercase; letter-spacing:0.06em;">Live Trading</span>
    </div>
    <div style="background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.08);
                border-radius:10px; padding:20px 24px; margin-bottom:20px;">
        <div style="color:#475569; font-size:0.85rem; font-style:italic;">
            🔧 Wird noch implementiert
        </div>
    </div>
    """, unsafe_allow_html=True)
