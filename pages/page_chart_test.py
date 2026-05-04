"""
pages/page_backtesting.py
Autor: Enes Eryilmaz – Grid-Trading-Framework (Bachelorarbeit OST)
"""

import streamlit as st
import pandas as pd
from datetime import date, timedelta

from components.chart import plot_grid_chart, plot_equity_curve, plot_drawdown_chart
from components.chart_v2 import plot_grid_chart_v2
from components.metrics_display import render_metrics_row, render_trade_log

from src.backtesting.engine import run_backtest
from src.backtesting.optimizer import optimize_num_grids
from src.data.cache_manager import get_price_data
from src.strategy.grid_builder import suggest_grid_range, build_grid_config, calculate_grid_lines
from config.settings import DEFAULT_NUM_GRIDS, DEFAULT_GRID_MODE, DEFAULT_FEE_RATE, DEFAULT_RESERVE_PCT

COINS = ["BTC","ETH","BNB","SOL","XRP","ADA","DOGE","AVAX","DOT","MATIC",
         "LINK","UNI","ATOM","LTC","BCH","NEAR","APT","OP","ARB","FTM"]

LABEL_STYLE = (
    "font-size:1.15rem; font-weight:600; color:#CBD5E1; "
    "font-family:Inter,-apple-system,sans-serif; text-transform:uppercase; "
    "letter-spacing:0.06em; margin-bottom:4px; margin-top:0px;"
)
CAPTION_STYLE = (
    "font-size:0.75rem; color:#94A3B8; "
    "font-family:Inter,-apple-system,sans-serif; margin-bottom:2px;"
)

def _label(text):
    return f"<div style='{LABEL_STYLE}'>{text}</div>"

def _caption(text):
    return f"<div style='{CAPTION_STYLE}'>{text}</div>"

def _calc_grid_profit(lower, upper, num_grids, grid_mode, fee_rate):
    try:
        if grid_mode == "arithmetic":
            step = (upper - lower) / num_grids
            min_profit = step / lower - 2 * fee_rate
            max_profit = step / upper - 2 * fee_rate
        else:
            ratio = (upper / lower) ** (1 / num_grids)
            min_profit = ratio - 1 - 2 * fee_rate
            max_profit = ratio - 1 - 2 * fee_rate
        return min_profit * 100, max_profit * 100
    except Exception:
        return None, None


def show_chart_test():

    st.markdown("""
    <style>
        [data-testid="stSidebar"] .stRadio,
        [data-testid="stSidebar"] .stSelectbox,
        [data-testid="stSidebar"] .stNumberInput,
        [data-testid="stSidebar"] .stSlider,
        [data-testid="stSidebar"] .stDateInput,
        [data-testid="stSidebar"] .stCheckbox {
            margin-top: 0px !important;
            margin-bottom: 0px !important;
            padding-top: 0px !important;
            padding-bottom: 0px !important;
        }
        [data-testid="stSidebar"] .stRadio > label,
        [data-testid="stSidebar"] .stSelectbox > label,
        [data-testid="stSidebar"] .stNumberInput > label,
        [data-testid="stSidebar"] .stSlider > label {
            display: none !important;
        }
        [data-testid="stSidebar"] div[data-testid="stVerticalBlock"] > div {
            padding-top: 0px !important;
            padding-bottom: 0px !important;
            gap: 0px !important;
        }
    </style>
    """, unsafe_allow_html=True)

    if "cv2_result" not in st.session_state:
        st.session_state.bt_result = None
    if "cv2_df" not in st.session_state:
        st.session_state.bt_df = None

    # -----------------------------------------------------------------------
    # Sidebar
    # -----------------------------------------------------------------------

    # COIN
    st.sidebar.markdown(_label("Coin"), unsafe_allow_html=True)
    coin_mode = st.sidebar.radio("", ["Aus Liste","Eigene Eingabe"],
                                 horizontal=True, key="cv2_coin_mode")
    if coin_mode == "Aus Liste":
        coin = st.sidebar.selectbox("", COINS, label_visibility="collapsed", key="cv2_coin")
    else:
        coin = st.sidebar.text_input("", value="BTC", label_visibility="collapsed",
                                     key="cv2_coin_input").upper().strip()

    # INTERVALL
    st.sidebar.markdown("<div style='margin-top:12px'></div>", unsafe_allow_html=True)
    st.sidebar.markdown(_label("Intervall"), unsafe_allow_html=True)
    interval = st.sidebar.radio("", ["1m","5m","15m","1h","4h","1d"],
                                 index=3, horizontal=True, key="cv2_interval",
                                 label_visibility="collapsed")

    # ZEITRAUM
    st.sidebar.markdown("<div style='margin-top:12px'></div>", unsafe_allow_html=True)
    st.sidebar.markdown(_label("Zeitraum"), unsafe_allow_html=True)
    col_d1, col_d2 = st.sidebar.columns(2)
    with col_d1:
        start_date = st.date_input("Von", value=date.today() - timedelta(days=30), key="cv2_start")
    with col_d2:
        end_date = st.date_input("Bis", value=date.today(), key="cv2_end")
    if start_date >= end_date:
        st.sidebar.error("Startdatum muss vor Enddatum liegen!")
    days = max(1, (end_date - start_date).days)
    st.sidebar.caption(f"→ {days} Tage")

    # STARTKAPITAL
    st.sidebar.markdown("<div style='margin-top:12px'></div>", unsafe_allow_html=True)
    st.sidebar.markdown(_label("Startkapital"), unsafe_allow_html=True)
    total_investment = float(st.sidebar.number_input(
        "", min_value=100.0, max_value=1_000_000.0,
        value=10_000.0, step=500.0, label_visibility="collapsed", key="cv2_capital"
    ))

    # GRID-PARAMETER
    st.sidebar.markdown("<div style='margin-top:12px'></div>", unsafe_allow_html=True)
    st.sidebar.markdown(_label("Grid-Parameter"), unsafe_allow_html=True)

    current_price, lower_s, upper_s = None, None, None
    try:
        df_tmp, _ = get_price_data(coin, days=14, interval="1h")
        if df_tmp is not None and not df_tmp.empty:
            current_price = float(df_tmp["close"].iloc[-1])
            _suggestion = suggest_grid_range(df_tmp, current_price)
            lower_s = _suggestion.lower_price
            upper_s = _suggestion.upper_price
    except Exception:
        pass
    current_price = current_price or 68000.0
    lower_s  = lower_s  or current_price * 0.80
    upper_s  = upper_s  or current_price * 1.20
    step_val = float(round(current_price * 0.01, 2))

    pct_lower_default = round((current_price - lower_s) / current_price * 100, 1)
    pct_upper_default = round((upper_s - current_price) / current_price * 100, 1)

    # Aktueller Preis + Vorschlag – mit Zeilenumbruch
    st.sidebar.markdown(
        f"<div style='font-size:0.75rem; color:#94A3B8; margin-bottom:4px;'>"
        f"Aktueller Preis: <b style='color:#E2E8F0'>{current_price:,.2f} USDT</b><br>"
        f"Vorschlag: {lower_s:,.0f} (−{pct_lower_default:.0f}%) – {upper_s:,.0f} (+{pct_upper_default:.0f}%)"
        f"</div>",
        unsafe_allow_html=True
    )

    pct_mode = st.sidebar.checkbox("Preisgrenzen prozentual setzen", value=False, key="cv2_pct_mode")

    if pct_mode:
        c1, c2 = st.sidebar.columns(2)
        with c1:
            st.markdown(_caption("Untere Grenze (%)"), unsafe_allow_html=True)
            pct_lower_val = st.number_input("", 1.0, 50.0, pct_lower_default, 1.0,
                                            key="cv2_pct_lower", label_visibility="collapsed")
        with c2:
            st.markdown(_caption("Obere Grenze (%)"), unsafe_allow_html=True)
            pct_upper_val = st.number_input("", 1.0, 50.0, pct_upper_default, 1.0,
                                            key="cv2_pct_upper", label_visibility="collapsed")
        lower_price = round(current_price * (1 - pct_lower_val / 100), 2)
        upper_price = round(current_price * (1 + pct_upper_val / 100), 2)
        st.sidebar.caption(f"→ {lower_price:,.2f} – {upper_price:,.2f} USDT")
    else:
        c1, c2 = st.sidebar.columns(2)
        with c1:
            st.markdown(_caption("Untere Grenze ($)"), unsafe_allow_html=True)
            lower_price = st.number_input("", min_value=0.001,
                                          value=float(round(lower_s, 2)),
                                          step=step_val, key="cv2_lower",
                                          label_visibility="collapsed")
        with c2:
            st.markdown(_caption("Obere Grenze ($)"), unsafe_allow_html=True)
            upper_price = st.number_input("", min_value=0.001,
                                          value=float(round(upper_s, 2)),
                                          step=step_val, key="cv2_upper",
                                          label_visibility="collapsed")

    # Anzahl Grids
    col_gl, col_gv = st.sidebar.columns([3, 1])
    with col_gl:
        st.markdown(_caption("Anzahl Grids"), unsafe_allow_html=True)
    with col_gv:
        st.markdown(
            f"<div style='text-align:right; color:#3B82F6; font-weight:600;'>"
            f"{st.session_state.get('bt_grids', DEFAULT_NUM_GRIDS)}</div>",
            unsafe_allow_html=True
        )
    num_grids = st.sidebar.number_input(
        "", min_value=1, max_value=100,
        value=st.session_state.get("bt_grids", DEFAULT_NUM_GRIDS),
        step=1, key="cv2_grids", label_visibility="collapsed"
    )

    # Grid-Modus
    st.sidebar.markdown(
        "<div style='display:flex;align-items:center;gap:5px;margin-bottom:2px;'>"
        "<span style='font-size:0.75rem;color:#94A3B8;'>Grid-Modus</span>"
        "<span title='Arithmetisch: gleiche Abst\u00e4nde\nGeometrisch: gleiche % Abst\u00e4nde\nBottom heavy: enger unten\nTop heavy: enger oben' style='cursor:help;color:#94A3B8;'>&#9432;</span></div>",
        unsafe_allow_html=True
    )
    _bt_gm_active = st.sidebar.radio("", ["Symmetrisch", "Asymmetrisch"], horizontal=True, key="cv2_gm_active", label_visibility="collapsed")
    st.sidebar.markdown(_caption("Symmetrisch"), unsafe_allow_html=True)
    _bt_gm_sym = st.sidebar.radio("", ["Arithmetisch", "Geometrisch"], horizontal=True, key="cv2_gm_sym", disabled=(_bt_gm_active != "Symmetrisch"), label_visibility="collapsed")
    st.sidebar.markdown(_caption("Asymmetrisch"), unsafe_allow_html=True)
    _bt_gm_asym = st.sidebar.radio("", ["Bottom heavy", "Top heavy"], horizontal=True, key="cv2_gm_asym", disabled=(_bt_gm_active != "Asymmetrisch"), label_visibility="collapsed")
    if _bt_gm_active == "Symmetrisch":
        grid_mode = "arithmetic" if _bt_gm_sym == "Arithmetisch" else "geometric"
    else:
        grid_mode = "asymmetric_bottom" if _bt_gm_asym == "Bottom heavy" else "asymmetric_top"
    
    # Gebührenrate
    st.sidebar.markdown(_caption("Gebührenrate"), unsafe_allow_html=True)
    fee_rate = st.sidebar.number_input(
        "", 0.0, 1.0, DEFAULT_FEE_RATE * 100, 0.01,
        format="%.3f", key="cv2_fee", label_visibility="collapsed"
    ) / 100

    # Gewinn pro Grid nach Fees
    gmin, gmax = _calc_grid_profit(lower_price, upper_price, num_grids, grid_mode, fee_rate)
    if gmin is not None and gmax is not None:
        color = "#34D399" if gmin > 0 else "#F87171"
        st.sidebar.markdown(
            f'''<div style="margin-top:6px; margin-bottom:4px; padding:8px 10px;
                background:rgba(52,211,153,0.08); border-left:3px solid {color};
                border-radius:4px; font-size:0.8rem;">
                <span style="color:{color}; font-weight:600;">▲ Gewinn pro Grid (nach Fees):</span><br>
                <span style="color:{color};">{gmin:.2f}% – {gmax:.2f}%</span>
            </div>''',
            unsafe_allow_html=True
        )

    # RISIKO & KAPITAL
    st.sidebar.markdown("<div style='margin-top:12px'></div>", unsafe_allow_html=True)
    st.sidebar.markdown(_label("Risiko & Kapital"), unsafe_allow_html=True)
    st.sidebar.markdown(_caption("Kapitalreserve (%)"), unsafe_allow_html=True)
    reserve_pct = st.sidebar.slider("", 0.0, 20.0, DEFAULT_RESERVE_PCT * 100, 1.0,
                         key="cv2_reserve", label_visibility="collapsed") / 100
    vo_enabled = st.sidebar.checkbox("Variable Ordergrössen aktivieren", value=False, key="cv2_vo")
    enable_variable_orders = vo_enabled
    weight_bottom = 2.0
    weight_top    = 0.5
    if vo_enabled:
        st.sidebar.markdown(_caption("Gewichtung unten (x)"), unsafe_allow_html=True)
        weight_bottom = st.sidebar.slider("", 1.0, 5.0, 2.0, 0.1,
                                          key="cv2_vo_bottom", label_visibility="collapsed")
        st.sidebar.markdown(_caption("Gewichtung oben (x)"), unsafe_allow_html=True)
        weight_top = st.sidebar.slider("", 0.0, 1.0, 0.5, 0.1,
                                        key="cv2_vo_top", label_visibility="collapsed")
        st.sidebar.caption(f"Unten: {weight_bottom}x · Oben: {weight_top}x")
    sl_enabled = st.sidebar.checkbox("Stop-Loss aktivieren", value=False, key="cv2_sl")
    stop_loss_pct = None
    if sl_enabled:
        st.sidebar.markdown(_caption("Stop-Loss (%)"), unsafe_allow_html=True)
        stop_loss_pct = st.sidebar.slider("", 5.0, 50.0, 20.0, 5.0, key="cv2_sl_pct",
                                      label_visibility="collapsed") / 100
    dd_enabled = st.sidebar.checkbox("Drawdown-Drosselung aktivieren", value=False, key="cv2_dd")
    enable_dd_throttle = dd_enabled
    dd_threshold_1 = 0.10
    dd_threshold_2 = 0.20
    if dd_enabled:
        st.sidebar.markdown(_caption("Schwelle 1 (%) → 50% Ordergrösse"), unsafe_allow_html=True)
        dd_threshold_1 = st.sidebar.slider("", 5.0, 30.0, 10.0, 1.0, key="cv2_dd_thr1",
                                           label_visibility="collapsed") / 100
        st.sidebar.markdown(_caption("Schwelle 2 (%) → 25% Ordergrösse"), unsafe_allow_html=True)
        dd_threshold_2 = st.sidebar.slider("", 10.0, 50.0, 20.0, 1.0, key="cv2_dd_thr2",
                                           label_visibility="collapsed") / 100

    # DYNAMISCHE GRID-MECHANISMEN
    st.sidebar.markdown("<div style='margin-top:12px'></div>", unsafe_allow_html=True)
    st.sidebar.markdown(_label("Dynamische Grid-Mechanismen"), unsafe_allow_html=True)
    trailing_active = st.session_state.get("bt_trailing", False)
    enable_recentering = st.sidebar.checkbox(
        "Recentering aktivieren",
        value=False, key="cv2_recenter",
        disabled=trailing_active,
        help="Nicht kombinierbar mit Grid Trailing"
    )
    if trailing_active and enable_recentering:
        enable_recentering = False
    recenter_threshold = 0.05
    if enable_recentering:
        st.sidebar.markdown(_caption("Recentering-Schwelle (%)"), unsafe_allow_html=True)
        recenter_threshold = st.sidebar.slider("", 1.0, 20.0, 5.0, 1.0, key="cv2_recenter_thr",
                                            label_visibility="collapsed") / 100

    atr_enabled = st.sidebar.checkbox("Volatilitätsbasierte Anpassung", value=False, key="cv2_atr")
    enable_atr_adjust = atr_enabled
    atr_multiplier = 1.0
    if atr_enabled:
        st.sidebar.markdown(_caption("ATR-Multiplikator"), unsafe_allow_html=True)
        st.sidebar.caption("Grid-Abstand = ATR × Multiplikator")
        atr_multiplier = st.sidebar.slider("", 0.5, 5.0, 1.0, 0.1,
                                            key="cv2_atr_mult",
                                            label_visibility="collapsed")
    trailing_enabled = st.sidebar.checkbox("Grid Trailing aktivieren", value=False, key="cv2_trailing")
    enable_trailing_up   = False
    enable_trailing_down = False
    trailing_up_stop     = None
    trailing_down_stop   = None
    if trailing_enabled:
        enable_trailing_up = st.sidebar.checkbox("Trailing Up", value=True, key="cv2_trailing_up")
        if enable_trailing_up:
            st.sidebar.markdown(_caption("Trailing Up Stop-Preis ($)"), unsafe_allow_html=True)
            trailing_up_stop = st.sidebar.number_input("", min_value=0.0,
                value=0.0, step=100.0, key="cv2_trailing_up_stop",
                label_visibility="collapsed")
            trailing_up_stop = trailing_up_stop if trailing_up_stop > 0 else None
        enable_trailing_down = st.sidebar.checkbox("Trailing Down", value=True, key="cv2_trailing_down")
        if enable_trailing_down:
            st.sidebar.markdown(_caption("Trailing Down Stop-Preis ($)"), unsafe_allow_html=True)
            trailing_down_stop = st.sidebar.number_input("", min_value=0.0,
                value=0.0, step=100.0, key="cv2_trailing_down_stop",
                label_visibility="collapsed")
            trailing_down_stop = trailing_down_stop if trailing_down_stop > 0 else None

    # CHART EINSTELLUNGEN (ganz unten)
    st.sidebar.divider()
    st.sidebar.markdown(_label("Chart Einstellungen"), unsafe_allow_html=True)
    st.sidebar.markdown(_caption("Chart Typ"), unsafe_allow_html=True)
    chart_type   = st.sidebar.selectbox("", ["Candlestick","Linie"], key="cv2_chart_type",
                                    label_visibility="collapsed")
    show_volume  = st.sidebar.checkbox("Volumen anzeigen",     value=True, key="cv2_show_vol")
    show_grid_bg = st.sidebar.checkbox("Gridbereich anzeigen", value=True, key="cv2_show_grid")

    # -----------------------------------------------------------------------
    # Header
    # -----------------------------------------------------------------------
    col_title, col_btn = st.columns([5, 1])
    with col_title:
        st.markdown("# 🧪 Chart V2 Test — TradingView Lightweight Charts")
        st.caption(f"{coin}/USDT · {interval} · {start_date} – {end_date} ({days}d) · {total_investment:,.0f} USDT")
    with col_btn:
        st.markdown("<div style='margin-top:20px'>", unsafe_allow_html=True)
        run_btn = st.button("▶ Simulation starten", type="primary", use_container_width=True)

    st.divider()

    # Preisdaten laden — immer frisch wenn end_date heute ist
    with st.spinner(f"Lade {coin}/USDT Preisdaten..."):
        df_chart, _ = get_price_data(coin, interval=interval,
                                     start_date=start_date, end_date=end_date)
    if df_chart is not None and not df_chart.empty:
        st.session_state.bt_df = df_chart

    # -----------------------------------------------------------------------
    # Backtest ausführen
    # -----------------------------------------------------------------------
    if run_btn:
        if lower_price >= upper_price:
            st.error("Lower muss kleiner als Upper sein!")
        elif start_date >= end_date:
            st.error("Startdatum muss vor Enddatum liegen!")
        else:
            with st.spinner(f"Simuliere {coin}/USDT {start_date} – {end_date}..."):
                result = run_backtest(
                    coin               = coin,
                    lower_price        = lower_price,
                    upper_price        = upper_price,
                    total_investment   = total_investment,
                    num_grids          = num_grids,
                    grid_mode          = grid_mode,
                    fee_rate           = fee_rate,
                    reserve_pct        = reserve_pct,
                    interval           = interval,
                    days               = days,
                    start_date         = start_date,
                    end_date           = end_date,
                    stop_loss_pct      = stop_loss_pct,
                    enable_recentering = enable_recentering,
                    recenter_threshold = recenter_threshold,
                    enable_dd_throttle  = enable_dd_throttle,
                    dd_threshold_1      = dd_threshold_1,
                    dd_threshold_2      = dd_threshold_2,
                    enable_variable_orders = enable_variable_orders,
                    weight_bottom          = weight_bottom,
                    weight_top             = weight_top,
                    enable_atr_adjust      = enable_atr_adjust,
                    atr_multiplier         = atr_multiplier,
                    enable_trailing_up     = enable_trailing_up,
                    enable_trailing_down   = enable_trailing_down,
                    trailing_up_stop       = trailing_up_stop,
                    trailing_down_stop     = trailing_down_stop,
                )
            st.session_state.bt_result = result
            if result.get("error"):
                st.error(f"Fehler: {result['error']}")
            else:
                st.success(
                    f"✅ Simulation abgeschlossen! "
                    f"{result.get('num_trades', 0)} Trades · "
                    f"ROI: {result.get('profit_pct', 0):+.2f}%"
                )
                # Regime-Warnung
                regime = result.get("regime")
                if regime:
                    r_colors = {"range": "#34D399", "trend_up": "#F87171", "trend_down": "#F87171", "neutral": "#FBBF24"}
                    r_labels = {"range": "Range-Markt (Seitwärts) — Grid-Bot geeignet",
                                "trend_up":   "Trend-Markt (Aufwärts) — Grid-Bot weniger geeignet",
                                "trend_down": "Trend-Markt (Abwärts) — Grid-Bot weniger geeignet",
                                "neutral":    "Unklare Marktlage"}
                    rc = r_colors.get(regime.regime, "#FBBF24")
                    rl = r_labels.get(regime.regime, regime.regime)
                    st.markdown(
                        f"<div style='padding:8px 12px; border-left:3px solid {rc}; "
                        f"background:rgba(255,255,255,0.03); border-radius:4px; margin-top:8px; margin-bottom:16px;'>"
                        f"<span style='color:{rc}; font-weight:600;'>Marktregime:</span> "
                        f"<span style='color:#E2E8F0;'>{rl}</span> "
                        f"<span style='color:#64748B; font-size:0.8rem;'>(Konfidenz: {regime.confidence:.0f}% · ADX14: {regime.adx14:.1f})</span>"
                        f"</div>",
                        unsafe_allow_html=True
                    )

    # -----------------------------------------------------------------------
    # Ergebnisse
    # -----------------------------------------------------------------------
    result = st.session_state.bt_result
    df     = st.session_state.bt_df

    if result and not result.get("error"):

        # Neue Metriken berechnen
        from src.metrics import (
            calculate_grid_efficiency, calculate_avg_profit_per_trade,
            calculate_runtime, calculate_unrealized_pnl
        )
        _trade_log   = result.get("trade_log", [])
        _open_buys   = [t for t in _trade_log if t.get("type") == "BUY"]
        _last_price  = float(df["close"].iloc[-1]) if df is not None and not df.empty else 0
        _start_time  = result.get("start_time", None)

        metrics_dict = {
            "roi_pct":              result.get("profit_pct", 0),
            "sharpe":               result.get("sharpe_ratio", 0),
            "max_dd_pct":           result.get("max_drawdown_pct", 0),
            "num_trades":           result.get("num_trades", 0),
            "bh_roi_pct":           result.get("price_change_pct", 0),
            "outperformance":       (result.get("profit_pct") or 0) - (result.get("price_change_pct") or 0),
            "cagr_pct":             result.get("cagr", 0),
            "calmar":               result.get("calmar_ratio", 0),
            "win_rate":             result.get("win_rate", 0),
            "profit_factor":        result.get("profit_factor", 0),
            "fees_paid":            result.get("fees_paid", 0),
            "initial_investment":   result.get("initial_investment", total_investment),
            "final_value":          result.get("final_value", 0),
            "grid_efficiency":      calculate_grid_efficiency(_trade_log, num_grids),
            "avg_profit_per_trade": calculate_avg_profit_per_trade(_trade_log),
            "runtime":              calculate_runtime(_start_time) if _start_time else None,
            "unrealized_pnl":       calculate_unrealized_pnl(_open_buys, _last_price, fee_rate),
        }
        render_metrics_row(metrics_dict, mode="backtest")
        st.markdown("<div style='margin-top:12px'></div>", unsafe_allow_html=True)

    # Vorschau-Gridlinien aus aktuellen Parametern
    try:
        preview_grid_lines = calculate_grid_lines(lower_price, upper_price, num_grids, grid_mode)
    except Exception:
        preview_grid_lines = []

    # Tabs
    tab1, tab2, tab3, tab4 = st.tabs(["Chart", "Equity", "Drawdown", "Trades"])
    trade_log    = result.get("trade_log",    []) if result else []
    grid_lines   = result.get("grid_lines",   []) if result else []
    daily_values = result.get("daily_values", {}) if result else {}

    with tab1:
        if df is not None and not df.empty:
            # Simulation vorhanden: echte Grids — sonst Vorschau aus aktuellen Parametern
            display_grid_lines = grid_lines if grid_lines else preview_grid_lines
            display_upper = float(display_grid_lines[-1]) if display_grid_lines else upper_price
            display_lower = float(display_grid_lines[0])  if display_grid_lines else lower_price
            plot_grid_chart_v2(
                df          = df,
                grid_lines  = display_grid_lines,
                trade_log   = trade_log,
                coin        = coin,
                interval    = interval,
                show_volume = show_volume,
                upper_price = display_upper,
                lower_price = display_lower,
                height      = 560,
            )
        else:
            st.info("Keine Preisdaten verfügbar.")

    with tab2:
        fig2 = plot_equity_curve(daily_values=daily_values, initial_value=total_investment,
                                  title="Portfolio vs. Buy & Hold")
        st.plotly_chart(fig2, use_container_width=True)

    with tab3:
        fig3 = plot_drawdown_chart(daily_values=daily_values, title="Drawdown-Verlauf")
        st.plotly_chart(fig3, use_container_width=True)

    with tab4:
        render_trade_log(trade_log)

    # -----------------------------------------------------------------------
    # Optimizer
    # -----------------------------------------------------------------------
    if result and not result.get("error") and df is not None and not df.empty:
        st.divider()
        st.markdown("### Grid-Anzahl optimieren")
        st.caption("Findet die optimale Anzahl Grids für die gewählten Parameter.")

        col_obj, col_run = st.columns([3, 1])
        with col_obj:
            objective = st.radio(
                "Optimierungsziel",
                ["maximize_sharpe","maximize_roi","maximize_calmar","minimize_drawdown"],
                horizontal=True,
                format_func=lambda x: {
                    "maximize_sharpe":   "Sharpe",
                    "maximize_roi":      "ROI",
                    "maximize_calmar":   "Calmar",
                    "minimize_drawdown": "Min. Drawdown",
                }.get(x, x),
                key="cv2_objective",
            )
        with col_run:
            opt_btn = st.button("Optimieren", use_container_width=True, key="cv2_opt_btn")

        if opt_btn:
            with st.spinner("Optimiere Grid-Anzahl..."):
                opt = optimize_num_grids(
                    df=df, lower_price=lower_price, upper_price=upper_price,
                    total_investment=total_investment, grid_mode=grid_mode,
                    fee_rate=fee_rate, grid_range=range(5, 51, 5), objective=objective,
                )
            if opt.num_tested > 0:
                best = opt.best_params
                st.success(
                    f"Beste Grid-Anzahl: **{int(best.get('num_grids', 0))}** "
                    f"| ROI: {best.get('roi_pct', 0):+.2f}% "
                    f"| Sharpe: {best.get('sharpe', 0):.2f} "
                    f"| Max DD: {best.get('max_dd_pct', 0):.2f}%"
                )
                st.dataframe(
                    opt.all_results[["num_grids","roi_pct","sharpe","max_dd_pct","num_trades","score"]
                    ].rename(columns={
                        "num_grids":"Grids","roi_pct":"ROI %","sharpe":"Sharpe",
                        "max_dd_pct":"Max DD %","num_trades":"Trades","score":"Score",
                    }),
                    use_container_width=True, hide_index=True,
                )
            else:
                st.warning("Optimierung lieferte keine Ergebnisse.")