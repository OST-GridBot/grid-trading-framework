"""
components/sidebar.py
=====================
Wiederverwendbare Sidebar-Komponenten fuer alle Streamlit-Seiten.

Enthaelt:
    coin_selector()      -> Coin-Auswahl (Dropdown oder freie Eingabe)
    interval_selector()  -> Intervall-Auswahl (Radio)
    capital_input()      -> Startkapital-Eingabe
    parameter_inputs()   -> Grid-Parameter (lower/upper/grids/modus/fees)
    advanced_settings()  -> Erweiterte Einstellungen (Expander)
    render_sidebar()     -> Komplette Sidebar auf einmal

Autor: Enes Eryilmaz
Projekt: Grid-Trading-Framework (Bachelorarbeit OST)
"""

import streamlit as st
from typing import Optional
from src.data.cache_manager import get_price_data
from src.analysis.indicators import get_atr_stats
from src.strategy.grid_builder import suggest_grid_range
from config.settings import (
    DEFAULT_NUM_GRIDS, DEFAULT_GRID_MODE, DEFAULT_FEE_RATE,
    DEFAULT_RESERVE_PCT, DEFAULT_BACKTEST_DAYS,
)

# Top-20 Coins als Standard (CMC Top-100 wird dynamisch geladen)
DEFAULT_COINS = [
    "BTC", "ETH", "BNB", "SOL", "XRP",
    "ADA", "DOGE", "AVAX", "DOT", "MATIC",
    "LINK", "UNI", "ATOM", "LTC", "BCH",
    "NEAR", "APT", "OP", "ARB", "FTM",
]

INTERVALS = ["1m", "5m", "15m", "1h", "4h", "1d"]
INTERVAL_DEFAULT = 3  # 1h


def coin_selector(key: str = "coin") -> str:
    """
    Coin-Auswahl: Dropdown mit Top-20 + freie Eingabe.

    Returns:
        Ausgewaehltes Coin-Symbol (z.B. "BTC")
    """
    st.sidebar.subheader("Coin")
    mode = st.sidebar.radio(
        "Auswahl",
        ["Aus Liste", "Eigene Eingabe"],
        horizontal=True,
        key=f"{key}_mode",
        label_visibility="collapsed",
    )
    if mode == "Aus Liste":
        coin = st.sidebar.selectbox(
            "Coin auswaehlen",
            DEFAULT_COINS,
            index=0,
            key=f"{key}_select",
            label_visibility="collapsed",
        )
    else:
        coin = st.sidebar.text_input(
            "Symbol eingeben (z.B. BTC)",
            value="BTC",
            key=f"{key}_input",
            label_visibility="collapsed",
        ).upper().strip()
    return coin


def interval_selector(key: str = "interval") -> str:
    """
    Intervall-Auswahl als Radio-Buttons.

    Returns:
        Ausgewaehltes Intervall (z.B. "1h")
    """
    st.sidebar.subheader("Intervall")
    interval = st.sidebar.radio(
        "Intervall",
        INTERVALS,
        index=INTERVAL_DEFAULT,
        horizontal=True,
        key=key,
        label_visibility="collapsed",
    )
    return interval


def capital_input(
    default: float = 10_000.0,
    key: str = "capital",
) -> float:
    """
    Startkapital-Eingabe.

    Returns:
        Startkapital in USDT
    """
    st.sidebar.subheader("Startkapital")
    capital = st.sidebar.number_input(
        "USDT",
        min_value=100.0,
        max_value=1_000_000.0,
        value=default,
        step=500.0,
        key=key,
        label_visibility="collapsed",
    )
    return float(capital)


def days_selector(
    default: int = DEFAULT_BACKTEST_DAYS,
    key: str = "days",
) -> int:
    """
    Zeitraum-Auswahl fuer Backtesting.

    Returns:
        Zeitraum in Tagen
    """
    st.sidebar.subheader("Zeitraum")
    days = st.sidebar.slider(
        "Tage",
        min_value=7,
        max_value=365,
        value=default,
        step=7,
        key=key,
        label_visibility="collapsed",
    )
    return days


def parameter_inputs(
    coin:     str,
    interval: str,
    key:      str = "params",
) -> dict:
    """
    Grid-Parameter Eingabe mit Auto-Vorschlag via ATR.

    Laedt aktuellen Preis und berechnet ATR-basierte Vorschlaege
    fuer lower/upper Grenzen.

    Returns:
        Dictionary mit allen Grid-Parametern
    """
    st.sidebar.subheader("Grid-Parameter")

    # Aktuellen Preis laden fuer Vorschlaege
    current_price = None
    suggested_lower = None
    suggested_upper = None

    try:
        df, _ = get_price_data(coin, days=14, interval=interval)
        if df is not None and not df.empty:
            current_price = float(df["close"].iloc[-1])
            lower_s, upper_s, _ = suggest_grid_range(df, current_price)
            suggested_lower = lower_s
            suggested_upper = upper_s
    except Exception:
        pass

    # Fallback-Werte
    if current_price is None:
        current_price = 68000.0
    if suggested_lower is None:
        suggested_lower = current_price * 0.85
    if suggested_upper is None:
        suggested_upper = current_price * 1.15

    # Auto-Vorschlag anzeigen
    if current_price:
        st.sidebar.caption(
            f"Aktueller Preis: **{current_price:,.2f} USDT** | "
            f"Vorschlag: {suggested_lower:,.0f} – {suggested_upper:,.0f}"
        )

    # Range-Eingabe
    col1, col2 = st.sidebar.columns(2)
    with col1:
        lower = st.number_input(
            "Lower ($)",
            min_value=0.0001,
            value=float(round(suggested_lower, 2)),
            step=float(round(current_price * 0.01, 2)),
            key=f"{key}_lower",
        )
    with col2:
        upper = st.number_input(
            "Upper ($)",
            min_value=0.0001,
            value=float(round(suggested_upper, 2)),
            step=float(round(current_price * 0.01, 2)),
            key=f"{key}_upper",
        )

    # Grid-Anzahl
    num_grids = st.sidebar.slider(
        "Anzahl Grids",
        min_value=5,
        max_value=100,
        value=DEFAULT_NUM_GRIDS,
        step=5,
        key=f"{key}_grids",
    )

    # Grid-Modus
    grid_mode = st.sidebar.radio(
        "Grid-Modus",
        ["arithmetic", "geometric"],
        index=0 if DEFAULT_GRID_MODE == "arithmetic" else 1,
        horizontal=True,
        key=f"{key}_mode",
    )

    # Gebuehrenrate
    fee_rate = st.sidebar.number_input(
        "Gebuehrenrate (%)",
        min_value=0.0,
        max_value=1.0,
        value=DEFAULT_FEE_RATE * 100,
        step=0.01,
        format="%.3f",
        key=f"{key}_fee",
    ) / 100

    return {
        "lower_price": lower,
        "upper_price": upper,
        "num_grids":   num_grids,
        "grid_mode":   grid_mode,
        "fee_rate":    fee_rate,
        "current_price": current_price,
    }


def advanced_settings(key: str = "advanced") -> dict:
    """
    Erweiterte Einstellungen in einem Expander.

    Returns:
        Dictionary mit erweiterten Parametern
    """
    with st.sidebar.expander("Erweiterte Einstellungen"):
        # Kapitalreserve
        reserve_pct = st.slider(
            "Kapitalreserve (%)",
            min_value=0.0,
            max_value=20.0,
            value=DEFAULT_RESERVE_PCT * 100,
            step=1.0,
            key=f"{key}_reserve",
            help="Anteil des Kapitals das als Reserve gehalten wird",
        ) / 100

        # Stop-Loss
        stop_loss_enabled = st.checkbox(
            "Stop-Loss aktivieren",
            value=False,
            key=f"{key}_sl_enabled",
        )
        stop_loss_pct = None
        if stop_loss_enabled:
            stop_loss_pct = st.slider(
                "Stop-Loss Schwelle (%)",
                min_value=5.0,
                max_value=50.0,
                value=20.0,
                step=5.0,
                key=f"{key}_sl_pct",
                help="Bot stoppt wenn Portfolio um X% faellt",
            ) / 100

        # Recentering
        enable_recentering = st.checkbox(
            "Recentering aktivieren",
            value=False,
            key=f"{key}_recenter",
            help="Grid automatisch neu zentrieren wenn Preis Range verlaesst",
        )
        recenter_threshold = 0.05
        if enable_recentering:
            recenter_threshold = st.slider(
                "Recentering-Schwelle (%)",
                min_value=1.0,
                max_value=20.0,
                value=5.0,
                step=1.0,
                key=f"{key}_recenter_thr",
            ) / 100

    return {
        "reserve_pct":        reserve_pct,
        "stop_loss_pct":      stop_loss_pct,
        "enable_recentering": enable_recentering,
        "recenter_threshold": recenter_threshold,
    }


def render_sidebar(
    show_days:     bool = True,
    show_advanced: bool = True,
    key:           str  = "sidebar",
) -> dict:
    """
    Rendert die komplette Sidebar und gibt alle Parameter zurueck.

    Verwendung in jeder Page:
        params = render_sidebar()
        coin     = params["coin"]
        interval = params["interval"]
        ...

    Args:
        show_days    : Zeitraum-Slider anzeigen (nur Backtest)
        show_advanced: Erweiterte Einstellungen anzeigen
        key          : Eindeutiger Key fuer Streamlit

    Returns:
        Dictionary mit allen Parametern
    """
    st.sidebar.title("Grid Bot Parameter")
    st.sidebar.divider()

    coin     = coin_selector(key=f"{key}_coin")
    interval = interval_selector(key=f"{key}_interval")
    capital  = capital_input(key=f"{key}_capital")
    days     = days_selector(key=f"{key}_days") if show_days else DEFAULT_BACKTEST_DAYS
    params   = parameter_inputs(coin, interval, key=f"{key}_params")
    advanced = advanced_settings(key=f"{key}_advanced") if show_advanced else {}

    st.sidebar.divider()

    return {
        "coin":               coin,
        "interval":           interval,
        "total_investment":   capital,
        "days":               days,
        "lower_price":        params["lower_price"],
        "upper_price":        params["upper_price"],
        "num_grids":          params["num_grids"],
        "grid_mode":          params["grid_mode"],
        "fee_rate":           params["fee_rate"],
        "current_price":      params["current_price"],
        **advanced,
    }