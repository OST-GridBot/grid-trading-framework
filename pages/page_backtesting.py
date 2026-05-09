"""
pages/page_backtesting.py
Autor: Enes Eryilmaz – Grid-Trading-Framework (Bachelorarbeit OST)
"""

import streamlit as st
import pandas as pd
from datetime import date, timedelta

from components.chart_v2 import plot_grid_chart_v2
from components.metrics_display import render_metrics_row, render_trade_log

from src.backtesting.engine import run_backtest
from src.backtesting.optimizer import optimize_num_grids, optimize_full_grid_search, smart_grid_setup
from src.data.cache_manager import get_price_data
from src.strategy.grid_builder import suggest_grid_range, build_grid_config
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


def show_backtesting():

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
        [data-testid="stSidebar"] details summary p {
            font-size: 0.72rem !important;
        }
    </style>
    """, unsafe_allow_html=True)

    if "bt_result" not in st.session_state:
        st.session_state.bt_result = None
    if "bt_df" not in st.session_state:
        st.session_state.bt_df = None

    # -----------------------------------------------------------------------
    # Sidebar
    # -----------------------------------------------------------------------

    # COIN
    st.sidebar.markdown(_label("Coin"), unsafe_allow_html=True)
    coin_mode = st.sidebar.radio("", ["Aus Liste","Eigene Eingabe"],
                                 horizontal=True, key="bt_coin_mode")
    if coin_mode == "Aus Liste":
        coin = st.sidebar.selectbox("", COINS, label_visibility="collapsed", key="bt_coin")
    else:
        coin = st.sidebar.text_input("", value="BTC", label_visibility="collapsed",
                                     key="bt_coin_input").upper().strip()


    st.sidebar.markdown(
        "<hr style='border:none; border-top:1px solid rgba(255,255,255,0.08); margin:8px 0;'>",
        unsafe_allow_html=True
    )
    # INTERVALL
    st.sidebar.markdown("<div style='margin-top:12px'></div>", unsafe_allow_html=True)
    st.sidebar.markdown(_label("Intervall"), unsafe_allow_html=True)
    interval = st.sidebar.radio("", ["1m","5m","15m","1h","4h","1d"],
                                 index=3, horizontal=True, key="bt_interval",
                                 label_visibility="collapsed")


    st.sidebar.markdown(
        "<hr style='border:none; border-top:1px solid rgba(255,255,255,0.08); margin:8px 0;'>",
        unsafe_allow_html=True
    )
    # ZEITRAUM
    st.sidebar.markdown("<div style='margin-top:12px'></div>", unsafe_allow_html=True)
    st.sidebar.markdown(_label("Zeitraum"), unsafe_allow_html=True)
    col_d1, col_d2 = st.sidebar.columns(2)
    with col_d1:
        start_date = st.date_input("Von", value=date.today() - timedelta(days=30), key="bt_start")
    with col_d2:
        end_date = st.date_input("Bis", value=date.today(), key="bt_end")
    if start_date >= end_date:
        st.sidebar.error("Startdatum muss vor Enddatum liegen!")
    days = max(1, (end_date - start_date).days)
    st.sidebar.caption(f"→ {days} Tage")


    st.sidebar.markdown(
        "<hr style='border:none; border-top:1px solid rgba(255,255,255,0.08); margin:8px 0;'>",
        unsafe_allow_html=True
    )
    # STARTKAPITAL
    st.sidebar.markdown("<div style='margin-top:12px'></div>", unsafe_allow_html=True)
    st.sidebar.markdown(_label("Startkapital"), unsafe_allow_html=True)
    total_investment = float(st.sidebar.number_input(
        "", min_value=100.0, max_value=1_000_000.0,
        value=10_000.0, step=500.0, label_visibility="collapsed", key="bt_capital"
    ))


    st.sidebar.markdown(
        "<hr style='border:none; border-top:1px solid rgba(255,255,255,0.08); margin:8px 0;'>",
        unsafe_allow_html=True
    )
    # SMART GRID-BOT
    st.sidebar.markdown("<div style='margin-top:12px'></div>", unsafe_allow_html=True)
    st.sidebar.markdown(_label("Smart Grid-Bot"), unsafe_allow_html=True)

    _smart_obj_options = {
        "maximize_roi":      "Höchster ROI",
        "minimize_drawdown": "Geringstes Risiko",
    }
    _smart_obj = st.sidebar.selectbox(
        "", list(_smart_obj_options.keys()),
        format_func=lambda k: _smart_obj_options[k],
        key="bt_smart_obj", label_visibility="collapsed",
    )
    _smart_help = {
        "maximize_roi":      "Maximiert den Gesamtgewinn ohne Risiko-Berücksichtigung. Aggressivste Strategie.",
        "minimize_drawdown": "Maximiert ROI bei minimalem Verlustrisiko durch Stop-Loss und Drawdown-Drosselung.",
    }
    st.sidebar.caption(_smart_help[_smart_obj])

    if st.sidebar.button("🎯 Optimale Parameter berechnen", use_container_width=True, key="bt_smart_btn"):
        _combos = {
            "maximize_roi":      288,
            "minimize_drawdown": 384,
        }.get(_smart_obj, 288)
        with st.spinner(f"Lade {coin}/USDT Daten und teste {_combos} Kombinationen..."):
            _df_smart, _ = get_price_data(coin, interval=interval, start_date=start_date, end_date=end_date)
            if _df_smart is None or _df_smart.empty:
                st.session_state["bt_smart_result"] = None
                st.session_state["bt_smart_error"]  = "Keine Daten verfügbar."
            else:
                _result = smart_grid_setup(
                    df=_df_smart,
                    total_investment=total_investment,
                    fee_rate=DEFAULT_FEE_RATE,
                    objective=_smart_obj,
                    interval=interval,
                )
                st.session_state["bt_smart_result"] = _result
                st.session_state["bt_smart_error"]  = None

    _smart = st.session_state.get("bt_smart_result")
    _smart_err = st.session_state.get("bt_smart_error")
    if _smart_err:
        st.sidebar.warning(_smart_err)
    elif _smart is not None:
        _mode_lbl = {
            "arithmetic":         "Arithmetisch",
            "geometric":          "Geometrisch",
            "asymmetric_bottom":  "Bottom Heavy",
            "asymmetric_top":     "Top Heavy",
        }.get(_smart.grid_mode, _smart.grid_mode)
        _rc_lbl = "Aktiv" if _smart.enable_recentering else "Inaktiv"
        if _smart.enable_trailing_up or _smart.enable_trailing_down:
            _tr_lbl = "Up + Down"
        else:
            _tr_lbl = "Inaktiv"

        if _smart.expected_roi_pct <= 0:
            st.sidebar.warning(f"Kein profitables Setup gefunden (Bestes ROI: {_smart.expected_roi_pct:+.2f}%)")
        else:
            st.sidebar.success(f"Erwartetes ROI: {_smart.expected_roi_pct:+.2f}%")

        _sl_lbl = f"Aktiv ({int(_smart.stop_loss_pct*100)}%)" if _smart.stop_loss_pct else "Inaktiv"
        _dd_lbl = "Aktiv" if _smart.enable_dd_throttle else "Inaktiv"
        _vo_lbl = "Aktiv" if _smart.enable_variable_orders else "Inaktiv"

        _box_html = (
            f"<div style='font-size:0.78rem; color:#94A3B8; padding:8px 10px; "
            f"background:rgba(255,255,255,0.03); border-radius:4px; margin-top:6px;'>"
            f"<b style='color:#E2E8F0;'>Untere Grenze:</b> ${_smart.lower_price:,.2f}<br>"
            f"<b style='color:#E2E8F0;'>Obere Grenze:</b> ${_smart.upper_price:,.2f}<br>"
            f"<b style='color:#E2E8F0;'>Anzahl Grids:</b> {_smart.num_grids}<br>"
            f"<b style='color:#E2E8F0;'>Grid-Modus:</b> {_mode_lbl}<br>"
            f"<b style='color:#E2E8F0;'>Recentering:</b> {_rc_lbl}<br>"
            f"<b style='color:#E2E8F0;'>Grid Trailing:</b> {_tr_lbl}"
        )
        if _smart_obj == "minimize_drawdown":
            _box_html += f"<br><b style='color:#E2E8F0;'>Stop-Loss:</b> {_sl_lbl}"
            _box_html += f"<br><b style='color:#E2E8F0;'>DD-Drosselung:</b> {_dd_lbl}"
        else:
            if _smart.stop_loss_pct is not None:
                _box_html += f"<br><b style='color:#E2E8F0;'>Stop-Loss:</b> {_sl_lbl}"
            if _smart.enable_dd_throttle:
                _box_html += f"<br><b style='color:#E2E8F0;'>DD-Drosselung:</b> {_dd_lbl}"
            if _smart.enable_variable_orders:
                _box_html += f"<br><b style='color:#E2E8F0;'>Variable Orders:</b> {_vo_lbl}"
        _box_html += "</div>"
        st.sidebar.markdown(_box_html, unsafe_allow_html=True)

        _c1, _c2 = st.sidebar.columns(2)
        with _c1:
            if st.button("Übernehmen", use_container_width=True, key="bt_smart_apply", type="primary"):
                st.session_state["bt_lower"]   = _smart.lower_price
                st.session_state["bt_upper"]   = _smart.upper_price
                st.session_state["bt_grids"]   = _smart.num_grids
                # Grid-Modus
                if _smart.grid_mode in ("arithmetic", "geometric"):
                    st.session_state["bt_gm_active"] = "Symmetrisch"
                    st.session_state["bt_gm_sym"]    = "Arithmetisch" if _smart.grid_mode == "arithmetic" else "Geometrisch"
                else:
                    st.session_state["bt_gm_active"] = "Asymmetrisch"
                    st.session_state["bt_gm_asym"]   = "Bottom heavy" if _smart.grid_mode == "asymmetric_bottom" else "Top heavy"
                st.session_state["bt_recenter"] = _smart.enable_recentering
                st.session_state["bt_trailing"] = _smart.enable_trailing_up or _smart.enable_trailing_down
                if _smart.enable_trailing_up:
                    st.session_state["bt_trailing_up"]      = True
                    st.session_state["bt_trailing_up_stop"] = float(_smart.trailing_up_stop or 0)
                if _smart.enable_trailing_down:
                    st.session_state["bt_trailing_down"]      = True
                    st.session_state["bt_trailing_down_stop"] = float(_smart.trailing_down_stop or 0)
                # Stop-Loss
                if _smart.stop_loss_pct is not None:
                    st.session_state["bt_sl"]     = True
                    st.session_state["bt_sl_pct"] = float(_smart.stop_loss_pct * 100)
                else:
                    st.session_state["bt_sl"] = False
                # DD-Drosselung
                st.session_state["bt_dd"] = _smart.enable_dd_throttle
                # Variable Orders
                st.session_state["bt_vo"] = _smart.enable_variable_orders
                st.session_state["bt_smart_result"] = None
                st.rerun()
        with _c2:
            if st.button("Verwerfen", use_container_width=True, key="bt_smart_dismiss"):
                st.session_state["bt_smart_result"] = None
                st.rerun()


    st.sidebar.markdown(
        "<hr style='border:none; border-top:1px solid rgba(255,255,255,0.08); margin:8px 0;'>",
        unsafe_allow_html=True
    )
    # GRID-PARAMETER
    st.sidebar.markdown("<div style='margin-top:12px'></div>", unsafe_allow_html=True)
    st.sidebar.markdown(_label("Grid-Parameter"), unsafe_allow_html=True)

    current_price, lower_s, upper_s = None, None, None
    df_tmp_atr = None
    try:
        # Preis vom Startdatum laden
        _days_back = max(14, (date.today() - start_date).days + 7)
        df_tmp, _ = get_price_data(coin, days=_days_back, interval="1h")
        if df_tmp is not None and not df_tmp.empty:
            df_tmp["timestamp"] = pd.to_datetime(df_tmp["timestamp"])
            df_start = df_tmp[df_tmp["timestamp"].dt.date >= start_date]
            if not df_start.empty:
                current_price = float(df_start["close"].iloc[0])
            else:
                current_price = float(df_tmp["close"].iloc[0])
            df_tmp_atr = df_tmp
    except Exception:
        pass
    if current_price is None:
        try:
            df_tmp2, _ = get_price_data(coin, days=14, interval="1h")
            if df_tmp2 is not None and not df_tmp2.empty:
                current_price = float(df_tmp2["close"].iloc[-1])
                df_tmp_atr = df_tmp2
        except Exception:
            pass
    current_price = current_price or 68000.0
    # Standard-Vorschlag: ±10%
    lower_s  = round(current_price * 0.90, 2)
    upper_s  = round(current_price * 1.10, 2)
    step_val = float(round(current_price * 0.01, 2))

    # ── Grid-Grenzen ──────────────────────────────────────────
    st.sidebar.markdown(
        "<div style='font-size:1.1rem; font-weight:600; color:#94A3B8; "
        "letter-spacing:0.04em; margin-top:6px; margin-bottom:2px;'>Grid-Grenzen</div>",
        unsafe_allow_html=True
    )
    st.sidebar.markdown(
        f"<div style='font-size:0.75rem; color:#94A3B8; margin-bottom:4px;'>"
        f"Preis am {start_date.strftime('%d.%m.%Y')}: <b style='color:#E2E8F0'>{current_price:,.2f} USDT</b><br>"
        f"Vorschlag: {lower_s:,.2f} (−10%) – {upper_s:,.2f} (+10%)"
        f"</div>",
        unsafe_allow_html=True
    )

    pct_mode = st.sidebar.checkbox("Preisgrenzen prozentual setzen", value=False, key="bt_pct_mode")

    if pct_mode:
        c1, c2 = st.sidebar.columns(2)
        with c1:
            st.markdown(_caption("Untere Grenze (%)"), unsafe_allow_html=True)
            pct_lower_val = st.number_input("", 1.0, 50.0, 10.0, 1.0,
                                            key="bt_pct_lower", label_visibility="collapsed")
        with c2:
            st.markdown(_caption("Obere Grenze (%)"), unsafe_allow_html=True)
            pct_upper_val = st.number_input("", 1.0, 50.0, 10.0, 1.0,
                                            key="bt_pct_upper", label_visibility="collapsed")
        lower_price = round(current_price * (1 - pct_lower_val / 100), 2)
        upper_price = round(current_price * (1 + pct_upper_val / 100), 2)
        st.sidebar.caption(f"→ {lower_price:,.2f} – {upper_price:,.2f} USDT")
    else:
        c1, c2 = st.sidebar.columns(2)
        with c1:
            st.markdown(_caption("Untere Grenze ($)"), unsafe_allow_html=True)
            lower_price = st.number_input("", min_value=0.001,
                                          value=float(lower_s),
                                          step=step_val, key="bt_lower",
                                          label_visibility="collapsed")
        with c2:
            st.markdown(_caption("Obere Grenze ($)"), unsafe_allow_html=True)
            upper_price = st.number_input("", min_value=0.001,
                                          value=float(upper_s),
                                          step=step_val, key="bt_upper",
                                          label_visibility="collapsed")

    # Trennlinie nach Grid-Grenzen
    st.sidebar.markdown(
        "<hr style='border:none; border-top:1px solid rgba(255,255,255,0.08); margin:8px 0;'>",
        unsafe_allow_html=True
    )

    # Anzahl Grids + ATR-Infofeld
    st.sidebar.markdown("<div style='font-size:1.1rem; font-weight:600; color:#94A3B8; letter-spacing:0.04em; margin-top:6px; margin-bottom:2px;'>Anzahl Grids</div>", unsafe_allow_html=True)
    num_grids = st.sidebar.number_input(
        "", min_value=1, max_value=100,
        value=st.session_state.get("bt_grids", DEFAULT_NUM_GRIDS),
        step=1, key="bt_grids", label_visibility="collapsed"
    )

    # Gewinn pro Grid (direkt nach Anzahl Grids)
    _fee_preview = st.session_state.get("bt_fee", DEFAULT_FEE_RATE * 100) / 100
    gmin, gmax = _calc_grid_profit(lower_price, upper_price, num_grids, grid_mode if "grid_mode" in dir() else "arithmetic", _fee_preview)
    if gmin is not None and gmax is not None:
        color = "#34D399" if gmin > 0 else "#F87171"
        st.sidebar.markdown(
            f'''<div style="margin-top:4px; margin-bottom:4px; padding:6px 10px;
                background:rgba(52,211,153,0.07); border-left:3px solid {color};
                border-radius:4px; font-size:0.78rem;">
                <span style="color:{color}; font-weight:600;">Gewinn pro Grid (nach Fees):</span>
                <span style="color:{color};"> {gmin:.2f}% – {gmax:.2f}%</span>
            </div>''',
            unsafe_allow_html=True
        )

    # ATR-Infofeld (dynamisch nach Coin + Zeitraum) — als Expander
    try:
        if df_tmp_atr is not None:
            from src.analysis.indicators import get_atr_stats
            _atr, _ = get_atr_stats(df_tmp_atr)
            _rng    = upper_price - lower_price
            _s05 = max(2, round(_rng / (_atr * 0.5)))
            _s10 = max(2, round(_rng / (_atr * 1.0)))
            _s15 = max(2, round(_rng / (_atr * 1.5)))
            with st.sidebar.expander("Volatilitätsbasierte Vorschläge"):
                st.markdown(
                    f"<div style='font-size:0.75rem; color:#94A3B8;'>"
                    f"<div style='color:#64748B; margin-bottom:6px;'>ATR (14 Kerzen) = <b style='color:#94A3B8;'>{_atr:,.2f} USDT</b></div>"
                    f"<div style='margin-bottom:5px;'>"
                    f"<span style='color:#34D399; font-weight:500;'>× 0.5 → {_s05} Grids</span><br>"
                    f"<span style='color:#64748B;'>Enger, mehr Trades</span></div>"
                    f"<div style='margin-bottom:5px;'>"
                    f"<span style='color:#60A5FA; font-weight:500;'>× 1.0 → {_s10} Grids</span><br>"
                    f"<span style='color:#64748B;'>Neutral, empfohlen</span></div>"
                    f"<div>"
                    f"<span style='color:#FBBF24; font-weight:500;'>× 1.5 → {_s15} Grids</span><br>"
                    f"<span style='color:#64748B;'>Weiter, weniger Trades</span></div>"
                    f"</div>",
                    unsafe_allow_html=True
                )
    except Exception:
        pass

    # Trennlinie nach Anzahl Grids
    st.sidebar.markdown(
        "<hr style='border:none; border-top:1px solid rgba(255,255,255,0.08); margin:8px 0;'>",
        unsafe_allow_html=True
    )

    # Grid-Modus
    st.sidebar.markdown(
        "<div style='display:flex;align-items:center;gap:5px;margin-bottom:2px;'>"
        "<span style='font-size:1.1rem;font-weight:600;color:#94A3B8;letter-spacing:0.04em;'>Grid-Modus</span>"
        "<span title='Arithmetisch: gleiche Abst\u00e4nde\nGeometrisch: gleiche % Abst\u00e4nde\nBottom heavy: enger unten\nTop heavy: enger oben' style='cursor:help;color:#94A3B8;'>&#9432;</span></div>",
        unsafe_allow_html=True
    )
    _bt_gm_active = st.sidebar.radio("", ["Symmetrisch", "Asymmetrisch"], horizontal=True, key="bt_gm_active", label_visibility="collapsed")
    st.sidebar.markdown(_caption("Symmetrisch"), unsafe_allow_html=True)
    _bt_gm_sym = st.sidebar.radio("", ["Arithmetisch", "Geometrisch"], horizontal=True, key="bt_gm_sym", disabled=(_bt_gm_active != "Symmetrisch"), label_visibility="collapsed")
    st.sidebar.markdown(_caption("Asymmetrisch"), unsafe_allow_html=True)
    _bt_gm_asym = st.sidebar.radio("", ["Bottom heavy", "Top heavy"], horizontal=True, key="bt_gm_asym", disabled=(_bt_gm_active != "Asymmetrisch"), label_visibility="collapsed")
    if _bt_gm_active == "Symmetrisch":
        grid_mode = "arithmetic" if _bt_gm_sym == "Arithmetisch" else "geometric"
    else:
        grid_mode = "asymmetric_bottom" if _bt_gm_asym == "Bottom heavy" else "asymmetric_top"
    


    # RISIKO & KAPITAL
    st.sidebar.markdown("<div style='margin-top:12px'></div>", unsafe_allow_html=True)
    st.sidebar.markdown(_label("Risiko & Kapital"), unsafe_allow_html=True)
    st.sidebar.markdown(_caption("Gebührenrate (%)"), unsafe_allow_html=True)
    fee_rate = st.sidebar.number_input(
        "", 0.0, 1.0, DEFAULT_FEE_RATE * 100, 0.01,
        format="%.3f", key="bt_fee", label_visibility="collapsed"
    ) / 100
    st.sidebar.markdown(_caption("Kapitalreserve (%)"), unsafe_allow_html=True)
    reserve_pct = st.sidebar.slider("", 0.0, 20.0, DEFAULT_RESERVE_PCT * 100, 1.0,
                         key="bt_reserve", label_visibility="collapsed") / 100
    vo_enabled = st.sidebar.checkbox("Variable Ordergrössen aktivieren", value=False, key="bt_vo")
    enable_variable_orders = vo_enabled
    weight_bottom = 2.0
    weight_top    = 0.5
    if vo_enabled:
        st.sidebar.markdown(_caption("Gewichtung unten (x)"), unsafe_allow_html=True)
        weight_bottom = st.sidebar.slider("", 1.0, 5.0, 2.0, 0.1,
                                          key="bt_vo_bottom", label_visibility="collapsed")
        st.sidebar.markdown(_caption("Gewichtung oben (x)"), unsafe_allow_html=True)
        weight_top = st.sidebar.slider("", 0.0, 1.0, 0.5, 0.1,
                                        key="bt_vo_top", label_visibility="collapsed")
        st.sidebar.caption(f"Unten: {weight_bottom}x · Oben: {weight_top}x")
    sl_enabled = st.sidebar.checkbox("Stop-Loss aktivieren", value=False, key="bt_sl")
    stop_loss_pct = None
    if sl_enabled:
        st.sidebar.markdown(_caption("Stop-Loss (%)"), unsafe_allow_html=True)
        stop_loss_pct = st.sidebar.slider("", 5.0, 50.0, 20.0, 5.0, key="bt_sl_pct",
                                      label_visibility="collapsed") / 100
    dd_enabled = st.sidebar.checkbox("Drawdown-Drosselung aktivieren", value=False, key="bt_dd")
    enable_dd_throttle = dd_enabled
    dd_threshold_1 = 0.10
    dd_threshold_2 = 0.20
    if dd_enabled:
        st.sidebar.markdown(_caption("Schwelle 1 (%) → 50% Ordergrösse"), unsafe_allow_html=True)
        dd_threshold_1 = st.sidebar.slider("", 5.0, 30.0, 10.0, 1.0, key="bt_dd_thr1",
                                           label_visibility="collapsed") / 100
        st.sidebar.markdown(_caption("Schwelle 2 (%) → 25% Ordergrösse"), unsafe_allow_html=True)
        dd_threshold_2 = st.sidebar.slider("", 10.0, 50.0, 20.0, 1.0, key="bt_dd_thr2",
                                           label_visibility="collapsed") / 100


    st.sidebar.markdown(
        "<hr style='border:none; border-top:1px solid rgba(255,255,255,0.08); margin:8px 0;'>",
        unsafe_allow_html=True
    )
    # DYNAMISCHE GRID-MECHANISMEN
    st.sidebar.markdown("<div style='margin-top:12px'></div>", unsafe_allow_html=True)
    st.sidebar.markdown(_label("Dynamische Grid-Mechanismen"), unsafe_allow_html=True)
    trailing_active = st.session_state.get("bt_trailing", False)
    enable_recentering = st.sidebar.checkbox(
        "Recentering aktivieren",
        value=False, key="bt_recenter",
        disabled=trailing_active,
        help="Nicht kombinierbar mit Grid Trailing" if trailing_active else None,
    )
    if trailing_active and enable_recentering:
        enable_recentering = False
    recenter_threshold = 0.05
    if enable_recentering:
        st.sidebar.markdown(_caption("Recentering-Schwelle (%)"), unsafe_allow_html=True)
        recenter_threshold = st.sidebar.slider("", 1.0, 20.0, 5.0, 1.0, key="bt_recenter_thr",
                                            label_visibility="collapsed") / 100
        _rc_pct = int(recenter_threshold * 100)
        st.sidebar.caption(
            f"Bei {_rc_pct}% wird das Grid neu zentriert, sobald der Preis "
            f"{_rc_pct}% über die Upper- oder unter die Lower-Grenze hinaus läuft. "
            f"Niedriger = häufigeres Anpassen."
        )

    atr_enabled = st.sidebar.checkbox("Volatilitätsbasierte Anpassung", value=False, key="bt_atr")
    enable_atr_adjust     = atr_enabled
    atr_multiplier        = 1.0
    enable_atr_dynamic    = False
    atr_dynamic_threshold = 0.15
    if atr_enabled:
        st.sidebar.markdown(_caption("ATR-Modus"), unsafe_allow_html=True)
        atr_mode = st.sidebar.radio(
            "", ["Statisch (einmalig beim Start)", "Dynamisch (pro Kerze)"],
            horizontal=True, key="bt_atr_mode", label_visibility="collapsed"
        )
        enable_atr_dynamic = (atr_mode == "Dynamisch (pro Kerze)")
        if enable_atr_dynamic:
            st.sidebar.markdown(_caption("Anpassungsschwelle (%)"), unsafe_allow_html=True)
            st.sidebar.caption("Grid nur anpassen wenn ATR um mehr als X% abweicht")
            atr_dynamic_threshold = st.sidebar.slider(
                "", 5.0, 30.0, 15.0, 1.0,
                key="bt_atr_threshold", label_visibility="collapsed"
            ) / 100
        st.sidebar.markdown(_caption("ATR-Multiplikator"), unsafe_allow_html=True)
        st.sidebar.caption("Grid-Abstand = ATR × Multiplikator")
        atr_multiplier = st.sidebar.slider("", 0.5, 5.0, 1.0, 0.1,
                                            key="bt_atr_mult",
                                            label_visibility="collapsed")
    _bt_recenter_active = st.session_state.get("bt_recenter", False)
    trailing_enabled = st.sidebar.checkbox(
        "Grid Trailing aktivieren", value=False, key="bt_trailing",
        disabled=_bt_recenter_active,
        help="Nicht kombinierbar mit Recentering" if _bt_recenter_active else None,
    )
    if _bt_recenter_active and trailing_enabled:
        trailing_enabled = False
    enable_trailing_up   = False
    enable_trailing_down = False
    trailing_up_stop     = None
    trailing_down_stop   = None
    if trailing_enabled:
        _bt_tr_col1, _bt_tr_col2 = st.sidebar.columns([1, 17])
        with _bt_tr_col2:
            _bt_tr_pct_mode = st.checkbox("Trailing Stops prozentual", value=False, key="bt_trailing_pct_mode")
        enable_trailing_up = st.sidebar.checkbox("Trailing Up", value=True, key="bt_trailing_up")
        if enable_trailing_up:
            if _bt_tr_pct_mode:
                st.sidebar.markdown(_caption("Trailing Up Stop (% über Upper)"), unsafe_allow_html=True)
                _tu_pct = st.sidebar.number_input("", min_value=0.0, max_value=200.0,
                    value=10.0, step=1.0, key="bt_trailing_up_pct",
                    label_visibility="collapsed")
                trailing_up_stop = round(upper_price * (1 + _tu_pct / 100), 4) if upper_price > 0 else None
                if trailing_up_stop:
                    st.sidebar.caption(f"→ ${trailing_up_stop:,.2f} absolut")
            else:
                st.sidebar.markdown(_caption("Trailing Up Stop-Preis ($)"), unsafe_allow_html=True)
                trailing_up_stop = st.sidebar.number_input("", min_value=0.0,
                    value=0.0, step=100.0, key="bt_trailing_up_stop",
                    label_visibility="collapsed")
                trailing_up_stop = trailing_up_stop if trailing_up_stop > 0 else None
                if trailing_up_stop and upper_price > 0:
                    _pct_up = (trailing_up_stop - upper_price) / upper_price * 100
                    st.sidebar.caption(f"→ {_pct_up:+.1f}% über Upper-Grenze (${upper_price:,.2f})")
        enable_trailing_down = st.sidebar.checkbox("Trailing Down", value=True, key="bt_trailing_down")
        if enable_trailing_down:
            if _bt_tr_pct_mode:
                st.sidebar.markdown(_caption("Trailing Down Stop (% unter Lower)"), unsafe_allow_html=True)
                _td_pct = st.sidebar.number_input("", min_value=0.0, max_value=99.0,
                    value=10.0, step=1.0, key="bt_trailing_down_pct",
                    label_visibility="collapsed")
                trailing_down_stop = round(lower_price * (1 - _td_pct / 100), 4) if lower_price > 0 else None
                if trailing_down_stop:
                    st.sidebar.caption(f"→ ${trailing_down_stop:,.2f} absolut")
            else:
                st.sidebar.markdown(_caption("Trailing Down Stop-Preis ($)"), unsafe_allow_html=True)
                trailing_down_stop = st.sidebar.number_input("", min_value=0.0,
                    value=0.0, step=100.0, key="bt_trailing_down_stop",
                    label_visibility="collapsed")
                trailing_down_stop = trailing_down_stop if trailing_down_stop > 0 else None
                if trailing_down_stop and lower_price > 0:
                    _pct_dn = (trailing_down_stop - lower_price) / lower_price * 100
                    st.sidebar.caption(f"→ {_pct_dn:+.1f}% unter Lower-Grenze (${lower_price:,.2f})")

    # CHART EINSTELLUNGEN (ganz unten)
    st.sidebar.divider()
    st.sidebar.markdown(_label("Chart Einstellungen"), unsafe_allow_html=True)
    st.sidebar.markdown(_caption("Chart Typ"), unsafe_allow_html=True)
    chart_type   = st.sidebar.selectbox("", ["Candlestick","Linie"], key="bt_chart_type",
                                    label_visibility="collapsed")
    show_volume  = st.sidebar.checkbox("Volumen anzeigen",     value=True, key="bt_show_vol")
    show_grid_bg = st.sidebar.checkbox("Gridbereich anzeigen", value=True, key="bt_show_grid")

    # -----------------------------------------------------------------------
    # Header
    # -----------------------------------------------------------------------
    col_title, col_btn = st.columns([5, 1])
    with col_title:
        st.markdown("# 📊 Backtesting")
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
                    enable_atr_dynamic     = enable_atr_dynamic,
                    atr_dynamic_threshold  = atr_dynamic_threshold,
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
                    f"ROI: {result.get('roi_pct', 0):+.2f}%"
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
        # Schicht 2 (run_backtest) liefert das Standard-Schluesselschema —
        # die Page reicht es direkt an Schicht 3 weiter, ohne Umbau.
        render_metrics_row(
            result,
            mode      = "backtest",
            trade_log = result.get("trade_log", []),
        )
        st.markdown("<div style='margin-top:12px'></div>", unsafe_allow_html=True)

    # Tabs
    tab1, tab2 = st.tabs(["Chart", "Trades"])
    trade_log    = result.get("trade_log",    []) if result else []
    grid_lines   = result.get("grid_lines",   []) if result else []
    daily_values = result.get("daily_values", {}) if result else {}

    with tab1:
        if df is not None and not df.empty:
            from src.utils.timezone import convert_df_timestamps, utc_to_zurich
            df_display = convert_df_timestamps(df)
            trade_log_display = []
            for t in trade_log:
                t2 = dict(t)
                try:
                    t2["timestamp"] = utc_to_zurich(t2["timestamp"])
                except Exception:
                    pass
                trade_log_display.append(t2)
            # Grid-Vorschau wenn noch keine Simulation
            try:
                from src.strategy.grid_builder import calculate_grid_lines
                preview_grid_lines = calculate_grid_lines(lower_price, upper_price, num_grids, grid_mode)
            except Exception:
                preview_grid_lines = []
            display_grid_lines = grid_lines if grid_lines else preview_grid_lines
            display_upper = float(display_grid_lines[-1]) if display_grid_lines else upper_price
            display_lower = float(display_grid_lines[0])  if display_grid_lines else lower_price
            plot_grid_chart_v2(
                df          = df_display,
                grid_lines  = display_grid_lines,
                trade_log   = trade_log_display,
                coin        = coin,
                interval    = interval,
                show_volume = show_volume,
                upper_price = display_upper,
                lower_price = display_lower,
            )
        else:
            st.info("Keine Preisdaten verfügbar.")

    with tab2:
        render_trade_log(trade_log)

    # -----------------------------------------------------------------------
    # Optimizer
    # -----------------------------------------------------------------------
    if result and not result.get("error") and df is not None and not df.empty:
        st.divider()
        st.markdown("### Parameter optimieren")
        st.caption("Findet die optimale Kombination aus Anzahl Grids, Grid-Modus und Recentering.")

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
                key="bt_objective",
            )
        with col_run:
            opt_btn = st.button("Optimieren", use_container_width=True, key="bt_opt_btn")

        if opt_btn:
            with st.spinner("Optimiere Grid-Parameter (Anzahl, Modus, Recentering)..."):
                opt = optimize_full_grid_search(
                    df=df, lower_price=lower_price, upper_price=upper_price,
                    total_investment=total_investment,
                    fee_rate=fee_rate, grid_range=range(5, 51, 5),
                    test_recentering=True,
                    objective=objective,
                    interval=interval,
                )
            if opt.num_tested > 0:
                best = opt.best_params
                _mode_lbl = {
                    "arithmetic":         "Arithmetisch",
                    "geometric":          "Geometrisch",
                    "asymmetric_bottom":  "Bottom Heavy",
                    "asymmetric_top":     "Top Heavy",
                }.get(best.get("grid_mode",""), best.get("grid_mode",""))
                _rc_lbl = "Aktiv" if best.get("enable_recentering") else "Inaktiv"
                st.success(
                    f"**Beste Parametrisierung gefunden:**\n"
                    f"- Anzahl Grids: **{int(best.get('num_grids', 0))}**\n"
                    f"- Grid-Modus: **{_mode_lbl}**\n"
                    f"- Recentering: **{_rc_lbl}**\n"
                    f"- Untere Grenze: **${best.get('lower_price', 0):,.2f}**\n"
                    f"- Obere Grenze: **${best.get('upper_price', 0):,.2f}**\n\n"
                    f"ROI: {best.get('roi_pct', 0):+.2f}% | "
                    f"Sharpe: {best.get('sharpe', 0):.2f} | "
                    f"Max DD: {best.get('max_dd_pct', 0):.2f}%"
                )
                _df_show = opt.all_results.copy()
                _df_show["grid_mode"] = _df_show["grid_mode"].map({
                    "arithmetic": "Arith.", "geometric": "Geom.",
                    "asymmetric_bottom": "Bottom", "asymmetric_top": "Top",
                })
                _df_show["enable_recentering"] = _df_show["enable_recentering"].map({True: "An", False: "Aus"})
                st.dataframe(
                    _df_show[["num_grids","grid_mode","enable_recentering","roi_pct","sharpe","max_dd_pct","num_trades","score"]
                    ].rename(columns={
                        "num_grids":"Grids","grid_mode":"Modus","enable_recentering":"Recenter",
                        "roi_pct":"ROI %","sharpe":"Sharpe",
                        "max_dd_pct":"Max DD %","num_trades":"Trades","score":"Score",
                    }),
                    use_container_width=True, hide_index=True,
                )
            else:
                st.warning("Optimierung lieferte keine Ergebnisse.")