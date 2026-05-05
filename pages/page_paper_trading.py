"""
pages/page_paper_trading.py
============================
Multi-Bot Paper Trading Page.

Funktionen:
    - Neuen Bot konfigurieren und starten (max. 10)
    - Übersicht aller laufenden Paper-Trading Bots
    - Detailansicht pro Bot (Chart, Metriken, Trade-Log)
    - Bot stoppen / löschen

Autor: Enes Eryilmaz
Projekt: Grid-Trading-Framework (Bachelorarbeit OST)
"""

import streamlit as st
import pandas as pd

from src.trading.bot_store import store as bot_store
from src.data.cache_manager import get_price_data
from src.strategy.grid_builder import suggest_grid_range, build_grid_config
from src.utils.timezone import convert_df_timestamps, utc_to_zurich
from components.chart import plot_grid_chart
from components.chart_v2 import plot_grid_chart_v2
from config.settings import (
    DEFAULT_NUM_GRIDS, DEFAULT_GRID_MODE,
    DEFAULT_FEE_RATE, DEFAULT_RESERVE_PCT,
    MAX_BOTS_PER_MODE,
)

COINS = ["BTC","ETH","BNB","SOL","XRP","ADA","DOGE","AVAX","DOT","MATIC",
         "LINK","UNI","ATOM","LTC","BCH","NEAR","APT","OP","ARB","FTM"]

LABEL_STYLE = (
    "font-size:1.15rem; font-weight:600; color:#CBD5E1; "
    "font-family:Inter,-apple-system,sans-serif; text-transform:uppercase; "
    "letter-spacing:0.06em; margin-bottom:4px;"
)
CAPTION_STYLE = (
    "font-size:0.75rem; color:#94A3B8; "
    "font-family:Inter,-apple-system,sans-serif; margin-bottom:2px;"
)

def _label(text):
    return f"<div style='{LABEL_STYLE}'>{text}</div>"

def _caption(text):
    return f"<div style='{CAPTION_STYLE}'>{text}</div>"

def _divider():
    return "<hr style='border:none; border-top:1px solid rgba(255,255,255,0.08); margin:8px 0;'>"

def _status_badge(status: str) -> str:
    colors = {"running": "#34D399", "stopped": "#F87171", "error": "#FBBF24"}
    labels = {"running": "● LÄUFT", "stopped": "■ GESTOPPT", "error": "⚠ FEHLER"}
    color = colors.get(status, "#94A3B8")
    label = labels.get(status, status.upper())
    return (f"<span style='color:{color}; font-weight:700; "
            f"font-size:0.8rem;'>{label}</span>")


def _format_ts(ts_str: str) -> str:
    try:
        from src.utils.timezone import utc_to_zurich
        import pandas as pd
        ts = utc_to_zurich(pd.Timestamp(ts_str))
        return ts.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(ts_str)[:16].replace("T", " ")


def show_paper_trading():

    if "pt_selected_bot" not in st.session_state:
        st.session_state.pt_selected_bot = None
    if "pt_show_new_bot" not in st.session_state:
        st.session_state.pt_show_new_bot = False
    if "pt_show_overview" not in st.session_state:
        st.session_state.pt_show_overview = False
    if "pt_show_portfolio" not in st.session_state:
        st.session_state.pt_show_portfolio = True

    bots        = sorted(bot_store.get_all_bots(mode="paper"), key=lambda b: b.get("created_at",""), reverse=True)
    bot_count   = len(bots)
    can_create  = bot_count < MAX_BOTS_PER_MODE
    running_bots = [b for b in bots if b.get("status") == "running"]

    st.sidebar.markdown(_label("Ansicht"), unsafe_allow_html=True)
    if st.sidebar.button("📊 Portfolio",
                          use_container_width=True,
                          key="pt_btn_portfolio"):
        st.session_state.pt_show_new_bot  = False
        st.session_state.pt_selected_bot  = None
        st.session_state.pt_show_overview = False
        st.rerun()
    if st.sidebar.button("＋ Neuen Bot starten",
                          use_container_width=True,
                          disabled=not can_create,
                          key="pt_btn_new"):
        st.session_state.pt_show_new_bot  = True
        st.session_state.pt_selected_bot  = None
        st.session_state.pt_show_overview = False

    if not can_create:
        st.sidebar.caption(f"Maximum {MAX_BOTS_PER_MODE} Bots erreicht.")

    running_count = sum(1 for b in bots if b["status"] == "running")
    if st.sidebar.button(
        f"Übersicht aktive Bots ({bot_count})",
        use_container_width=True,
        key="pt_btn_overview"
    ):
        st.session_state.pt_show_overview = True
        st.session_state.pt_show_new_bot  = False
        st.session_state.pt_selected_bot  = None

    col_h1, col_h2 = st.columns([4, 1])
    with col_h1:
        st.markdown("# 📄 Paper Trading")
        st.caption(f"{bot_count}/{MAX_BOTS_PER_MODE} Bots aktiv")
    with col_h2:
        pass
    st.divider()

    if st.session_state.pt_show_new_bot:
        _show_new_bot_form()
        return

    if st.session_state.pt_selected_bot:
        bot = bot_store.get_bot(st.session_state.pt_selected_bot)
        if bot:
            _show_bot_detail(bot)
            return
        else:
            st.session_state.pt_selected_bot = None

    if st.session_state.pt_show_overview:
        _show_bots_overview(bots)
        return

    if not bots:
        _show_empty_state()
        return

    # Standard: Portfolio-Ansicht
    _show_portfolio(bots)


# ---------------------------------------------------------------------------
# Neuen Bot erstellen
# ---------------------------------------------------------------------------

def _show_form_chart(coin: str = "BTC", interval: str = "1h"):
    """Zeigt Chart des gewählten Coins mit gewähltem Intervall."""
    days_map = {"1m": 1, "5m": 1, "15m": 2, "1h": 7, "4h": 14}
    days  = days_map.get(interval, 7)
    force = interval in ("1m", "5m")
    try:
        df_chart, _ = get_price_data(coin, days=days, interval=interval, force=force)
        if df_chart is not None and not df_chart.empty:
            df_display = convert_df_timestamps(df_chart)
            plot_grid_chart_v2(
                df          = df_display,
                grid_lines  = [],
                trade_log   = [],
                coin        = coin,
                interval    = interval,
                show_volume = True,
            )
    except Exception as e:
        st.caption(f"Chart nicht verfügbar: {e}")


def _show_portfolio(bots: list):
    """Portfolio-Übersicht aller Paper-Trading Bots."""
    running = [b for b in bots if b.get("status") == "running"]
    stopped = [b for b in bots if b.get("status") != "running"]

    total_invest = sum(b.get("config",{}).get("total_investment",0) for b in running)
    total_roi    = sum((b.get("metrics",{}).get("roi_pct",0) or 0) * b.get("config",{}).get("total_investment",0) for b in running)
    weighted_roi = (total_roi / total_invest) if total_invest > 0 else 0
    total_trades = sum(len(b.get("trade_log",[])) for b in bots)
    total_profit = sum(
        sum(t.get("profit",0) or 0 for t in b.get("trade_log",[]) if t.get("type")=="SELL")
        for b in bots
    )

    st.markdown("### 📊 Portfolio-Übersicht")

    # Metriken-Karten
    c1, c2, c3, c4, c5 = st.columns(5)
    roi_color = "#34D399" if weighted_roi >= 0 else "#F87171"
    profit_color = "#34D399" if total_profit >= 0 else "#F87171"

    for col, label, value in [
        (c1, "Aktive Bots",    f"{len(running)}/{MAX_BOTS_PER_MODE}"),
        (c2, "Gesamtinvest",   f"${total_invest:,.0f}"),
        (c3, "Ø ROI",          f"{weighted_roi:+.2f}%"),
        (c4, "Realisierter Profit", f"${total_profit:+.2f}"),
        (c5, "Trades gesamt",  str(total_trades)),
    ]:
        color = roi_color if label == "Ø ROI" else (profit_color if "Profit" in label else "#E2E8F0")
        col.markdown(
            f"<div style='background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.08); "
            f"border-radius:8px; padding:14px; text-align:center;'>"
            f"<div style='color:#64748B; font-size:0.75rem; margin-bottom:4px;'>{label}</div>"
            f"<div style='color:{color}; font-size:1.3rem; font-weight:700;'>{value}</div>"
            f"</div>",
            unsafe_allow_html=True
        )

    st.markdown("<div style='margin-top:16px'></div>", unsafe_allow_html=True)

    # Bot-Liste kompakt
    if running:
        st.markdown("**Laufende Bots**")
        for bot in running:
            cfg     = bot.get("config", {})
            metrics = bot.get("metrics", {})
            roi     = metrics.get("roi_pct", 0) or 0
            color   = "#34D399" if roi >= 0 else "#F87171"
            st.markdown(
                f"<div style='display:grid; grid-template-columns:1fr auto auto; gap:8px; align-items:center; "
                f"padding:8px 12px; background:rgba(255,255,255,0.02); border-left:3px solid {color}; "
                f"border-radius:4px; margin-bottom:4px;'>"
                f"<span style='color:#E2E8F0; font-weight:500; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;'>{bot.get('name', bot['coin'])}</span>"
                f"<span style='color:#64748B; font-size:0.78rem; white-space:nowrap;'>{bot['coin']} · {bot['interval']} · ${cfg.get('total_investment',0):,.0f}</span>"
                f"<span style='color:{color}; font-weight:600; white-space:nowrap; text-align:right;'>{roi:+.2f}%</span>"
                f"</div>",
                unsafe_allow_html=True
            )
    if stopped:
        st.markdown("**Gestoppte Bots**")
        for bot in stopped:
            cfg = bot.get("config", {})
            metrics = bot.get("metrics", {})
            roi = metrics.get("roi_pct", 0) or 0
            st.markdown(
                f"<div style='display:flex; justify-content:space-between; align-items:center; "
                f"padding:8px 12px; background:rgba(255,255,255,0.02); border-left:3px solid #475569; "
                f"border-radius:4px; margin-bottom:4px; opacity:0.6;'>"
                f"<span style='color:#94A3B8;'>{bot.get('name', bot['coin'])}</span>"
                f"<span style='color:#64748B; font-size:0.8rem;'>{bot['coin']} · {bot['interval']}</span>"
                f"<span style='color:#64748B;'>{roi:+.2f}%</span>"
                f"</div>",
                unsafe_allow_html=True
            )

    st.markdown("<div style='margin-top:16px'></div>", unsafe_allow_html=True)
    col_b1, col_b2 = st.columns(2)
    with col_b1:
        if st.button("＋ Neuen Bot starten", use_container_width=True, type="primary", key="pt_portfolio_new"):
            st.session_state.pt_show_new_bot = True
            st.rerun()
    with col_b2:
        if st.button(f"Übersicht aktive Bots ({len(bots)})", use_container_width=True, key="pt_portfolio_overview"):
            st.session_state.pt_show_overview = True
            st.rerun()


def _show_new_bot_form():
    st.markdown("### Neuen Bot konfigurieren")
    st.markdown("<div style='margin-bottom:16px'></div>", unsafe_allow_html=True)
    st.markdown("""
    <style>details summary p { font-size: 0.72rem !important; }</style>
    """, unsafe_allow_html=True)

    st.markdown(_label("Bot-Name"), unsafe_allow_html=True)
    bot_name = st.text_input(
        "", placeholder="z.B. BTC Range Bot, ETH Swing...",
        label_visibility="collapsed", key="pt_new_name"
    )
    st.markdown(_divider(), unsafe_allow_html=True)

    st.markdown(_label("Coin"), unsafe_allow_html=True)
    coin_mode = st.radio("", ["Aus Liste", "Eigene Eingabe"],
                          horizontal=True, key="pt_new_coin_mode",
                          label_visibility="collapsed")
    if coin_mode == "Aus Liste":
        coin = st.selectbox("", COINS, label_visibility="collapsed", key="pt_new_coin")
    else:
        coin = st.text_input("", value="BTC", label_visibility="collapsed",
                              key="pt_new_coin_input").upper().strip()
    st.markdown(_divider(), unsafe_allow_html=True)

    st.markdown(_label("Intervall"), unsafe_allow_html=True)
    interval = st.radio("", ["1m","5m","15m","1h","4h"],
                         index=3, horizontal=True, key="pt_new_interval",
                         label_visibility="collapsed")
    # Chart mit Grid-Vorschau nach Intervall-Auswahl
    try:
        from src.strategy.grid_builder import calculate_grid_lines
        _days_chart = {"1m":1,"5m":1,"15m":2,"1h":7,"4h":14}.get(interval, 7)
        _df_chart, _ = get_price_data(coin, days=_days_chart, interval=interval)
        if _df_chart is not None and not _df_chart.empty:
            _df_disp = convert_df_timestamps(_df_chart)
            # Grid-Vorschau aus aktuellen Sidebar-Werten
            _p = float(_df_chart["close"].iloc[-1])
            _lo = round(_p * 0.90, 4)
            _hi = round(_p * 1.10, 4)
            _ng = st.session_state.get("pt_new_grids", DEFAULT_NUM_GRIDS)
            try:
                _gl = calculate_grid_lines(_lo, _hi, _ng, "arithmetic")
            except Exception:
                _gl = []
            plot_grid_chart_v2(
                df          = _df_disp,
                grid_lines  = _gl,
                trade_log   = [],
                coin        = coin,
                interval    = interval,
                show_volume = False,
                upper_price = float(_gl[-1]) if _gl else _hi,
                lower_price = float(_gl[0])  if _gl else _lo,
                height      = 420,
            )
    except Exception as e:
        st.caption(f"Chart nicht verfügbar: {e}")

    st.markdown(_divider(), unsafe_allow_html=True)

    st.markdown(_label("Startkapital"), unsafe_allow_html=True)
    total_investment = st.number_input(
        "", min_value=100.0, max_value=1_000_000.0,
        value=10000.0, step=500.0,
        label_visibility="collapsed", key="pt_new_capital"
    )
    st.markdown(_divider(), unsafe_allow_html=True)

    # ── Grid-Parameter ────────────────────────────────────────
    st.markdown(_label("Grid-Parameter"), unsafe_allow_html=True)
    current_price, df_tmp_atr = None, None
    try:
        df_tmp, _ = get_price_data(coin, days=14, interval=interval)
        if df_tmp is not None and not df_tmp.empty:
            current_price = float(df_tmp["close"].iloc[-1])
            df_tmp_atr    = df_tmp
    except Exception:
        pass
    current_price = current_price or 68000.0
    lower_s  = round(current_price * 0.90, 2)
    upper_s  = round(current_price * 1.10, 2)
    step_val = float(round(current_price * 0.01, 2))

    # Grid-Grenzen
    st.markdown(
        "<div style='font-size:1.1rem; font-weight:600; color:#94A3B8; "
        "letter-spacing:0.04em; margin-top:6px; margin-bottom:2px;'>Grid-Grenzen</div>",
        unsafe_allow_html=True
    )
    st.markdown(
        f"<div style='font-size:0.75rem; color:#94A3B8; margin-bottom:4px;'>"
        f"Aktueller Preis: <b style='color:#E2E8F0;'>{current_price:,.2f} USDT</b><br>"
        f"Vorschlag: {lower_s:,.2f} (−10%) – {upper_s:,.2f} (+10%)</div>",
        unsafe_allow_html=True
    )

    pct_mode = st.checkbox("Preisgrenzen prozentual setzen", value=False, key="pt_new_pct_mode")
    if pct_mode:
        col_p1, col_p2 = st.columns(2)
        with col_p1:
            st.markdown(_caption("Untere Grenze (%)"), unsafe_allow_html=True)
            pct_lv = st.number_input("", 1.0, 50.0, 10.0, 1.0,
                                      key="pt_new_pct_lower", label_visibility="collapsed")
        with col_p2:
            st.markdown(_caption("Obere Grenze (%)"), unsafe_allow_html=True)
            pct_uv = st.number_input("", 1.0, 50.0, 10.0, 1.0,
                                      key="pt_new_pct_upper", label_visibility="collapsed")
        lower_price = round(current_price * (1 - pct_lv / 100), 2)
        upper_price = round(current_price * (1 + pct_uv / 100), 2)
        st.caption(f"→ {lower_price:,.2f} – {upper_price:,.2f} USDT")
    else:
        col_g1, col_g2 = st.columns(2)
        with col_g1:
            st.markdown(_caption("Untere Grenze ($)"), unsafe_allow_html=True)
            lower_price = st.number_input("", min_value=0.001,
                                           value=float(lower_s),
                                           step=step_val, key="pt_new_lower",
                                           label_visibility="collapsed")
        with col_g2:
            st.markdown(_caption("Obere Grenze ($)"), unsafe_allow_html=True)
            upper_price = st.number_input("", min_value=0.001,
                                           value=float(upper_s),
                                           step=step_val, key="pt_new_upper",
                                           label_visibility="collapsed")

    st.markdown(_divider(), unsafe_allow_html=True)

    # Anzahl Grids
    st.markdown(
        "<div style='font-size:1.1rem; font-weight:600; color:#94A3B8; "
        "letter-spacing:0.04em; margin-top:6px; margin-bottom:2px;'>Anzahl Grids</div>",
        unsafe_allow_html=True
    )
    num_grids = st.number_input(
        "", min_value=2, max_value=100,
        value=st.session_state.get("pt_new_grids", DEFAULT_NUM_GRIDS),
        step=1, key="pt_new_grids", label_visibility="collapsed"
    )

    # Gewinn pro Grid (Spanne min – max je nach Grid-Modus)
    _fee_preview = st.session_state.get("pt_new_fee", DEFAULT_FEE_RATE * 100) / 100
    _gm_active = st.session_state.get("pt_gm_active", "Symmetrisch")
    _gm_sym    = st.session_state.get("pt_gm_sym", "Arithmetisch")
    _gmode_preview = "arithmetic" if (_gm_active == "Symmetrisch" and _gm_sym == "Arithmetisch") else "geometric"
    try:
        if _gmode_preview == "arithmetic":
            _gstep = (upper_price - lower_price) / num_grids
            _gmin  = (_gstep / upper_price - 2 * _fee_preview) * 100
            _gmax  = (_gstep / lower_price - 2 * _fee_preview) * 100
        else:
            _ratio = (upper_price / lower_price) ** (1 / num_grids)
            _gmin  = (_ratio - 1 - 2 * _fee_preview) * 100
            _gmax  = _gmin
        _gcolor = "#34D399" if _gmin > 0 else "#F87171"
        st.markdown(
            f"<div style='margin-top:4px; margin-bottom:4px; padding:6px 10px; "
            f"background:rgba(52,211,153,0.07); border-left:3px solid {_gcolor}; "
            f"border-radius:4px; font-size:0.78rem;'>"
            f"<span style='color:{_gcolor}; font-weight:600;'>Gewinn pro Grid (nach Fees):</span>"
            f"<span style='color:{_gcolor};'> {_gmin:.2f}% – {_gmax:.2f}%</span></div>",
            unsafe_allow_html=True
        )
    except Exception:
        pass

    # ATR-Infofeld
    try:
        if df_tmp_atr is not None:
            from src.analysis.indicators import get_atr_stats
            _atr, _ = get_atr_stats(df_tmp_atr)
            _rng = upper_price - lower_price
            _s05 = max(2, round(_rng / (_atr * 0.5)))
            _s10 = max(2, round(_rng / (_atr * 1.0)))
            _s15 = max(2, round(_rng / (_atr * 1.5)))
            with st.expander("Volatilitätsbasierte Vorschläge"):
                st.markdown(
                    f"<div style='font-size:0.75rem; color:#94A3B8;'>"
                    f"<div style='color:#64748B; margin-bottom:6px;'>ATR (14 Kerzen) = "
                    f"<b style='color:#94A3B8;'>{_atr:,.2f} USDT</b></div>"
                    f"<div style='margin-bottom:5px;'><span style='color:#34D399; font-weight:500;'>× 0.5 → {_s05} Grids</span><br>"
                    f"<span style='color:#64748B;'>Enger, mehr Trades</span></div>"
                    f"<div style='margin-bottom:5px;'><span style='color:#60A5FA; font-weight:500;'>× 1.0 → {_s10} Grids</span><br>"
                    f"<span style='color:#64748B;'>Neutral, empfohlen</span></div>"
                    f"<div><span style='color:#FBBF24; font-weight:500;'>× 1.5 → {_s15} Grids</span><br>"
                    f"<span style='color:#64748B;'>Weiter, weniger Trades</span></div>"
                    f"</div>",
                    unsafe_allow_html=True
                )
    except Exception:
        pass

    st.markdown(_divider(), unsafe_allow_html=True)

    # Grid-Modus
    st.markdown(
        "<div style='display:flex;align-items:center;gap:5px;margin-bottom:2px;'>"
        "<span style='font-size:1.1rem;font-weight:600;color:#94A3B8;letter-spacing:0.04em;'>Grid-Modus</span>"
        "<span title='Arithmetisch: gleiche Abstände\nGeometrisch: gleiche % Abstände\nBottom heavy: enger unten\nTop heavy: enger oben' style='cursor:help;color:#94A3B8;'>&#9432;</span></div>",
        unsafe_allow_html=True
    )
    _pt_gm_active = st.radio("", ["Symmetrisch", "Asymmetrisch"], horizontal=True, key="pt_gm_active", label_visibility="collapsed")
    st.markdown(_caption("Symmetrisch"), unsafe_allow_html=True)
    _pt_gm_sym = st.radio("", ["Arithmetisch", "Geometrisch"], horizontal=True, key="pt_gm_sym", disabled=(_pt_gm_active != "Symmetrisch"), label_visibility="collapsed")
    st.markdown(_caption("Asymmetrisch"), unsafe_allow_html=True)
    _pt_gm_asym = st.radio("", ["Bottom heavy", "Top heavy"], horizontal=True, key="pt_gm_asym", disabled=(_pt_gm_active != "Asymmetrisch"), label_visibility="collapsed")
    if _pt_gm_active == "Symmetrisch":
        grid_mode = "arithmetic" if _pt_gm_sym == "Arithmetisch" else "geometric"
    else:
        grid_mode = "asymmetric_bottom" if _pt_gm_asym == "Bottom heavy" else "asymmetric_top"

    st.markdown(_divider(), unsafe_allow_html=True)

    # ── Risiko & Kapital ──────────────────────────────────────
    st.markdown(_label("Risiko & Kapital"), unsafe_allow_html=True)
    st.markdown(_caption("Gebührenrate (%)"), unsafe_allow_html=True)
    fee_rate = st.number_input(
        "", 0.0, 1.0, DEFAULT_FEE_RATE * 100, 0.01,
        format="%.3f", key="pt_new_fee", label_visibility="collapsed"
    ) / 100
    st.markdown(_caption("Kapitalreserve (%)"), unsafe_allow_html=True)
    reserve_pct = st.slider("", 0.0, 20.0, DEFAULT_RESERVE_PCT * 100, 1.0,
                             key="pt_new_reserve", label_visibility="collapsed") / 100
    vo_enabled_pt = st.checkbox("Variable Ordergrössen aktivieren", key="pt_vo")
    enable_variable_orders = vo_enabled_pt
    weight_bottom = 2.0
    weight_top    = 0.5
    if vo_enabled_pt:
        st.markdown(_caption("Gewichtung unten (x)"), unsafe_allow_html=True)
        weight_bottom = st.slider("", 1.0, 5.0, 2.0, 0.1,
                                   key="pt_vo_bottom", label_visibility="collapsed")
        st.markdown(_caption("Gewichtung oben (x)"), unsafe_allow_html=True)
        weight_top = st.slider("", 0.0, 1.0, 0.5, 0.1,
                                key="pt_vo_top", label_visibility="collapsed")
        st.caption(f"Unten: {weight_bottom}x · Oben: {weight_top}x")
    sl_enabled = st.checkbox("Stop-Loss aktivieren", key="pt_new_sl")
    stop_loss_pct = None
    if sl_enabled:
        st.markdown(_caption("Stop-Loss (%)"), unsafe_allow_html=True)
        stop_loss_pct = st.slider("", 5.0, 50.0, 20.0, 5.0,
                                   key="pt_new_sl_pct", label_visibility="collapsed") / 100
    dd_enabled = st.checkbox("Drawdown-Drosselung aktivieren", key="pt_new_dd")
    enable_dd_throttle = dd_enabled
    dd_threshold_1 = 0.10
    dd_threshold_2 = 0.20
    if dd_enabled:
        st.markdown(_caption("Schwelle 1 (%) → 50% Ordergrösse"), unsafe_allow_html=True)
        dd_threshold_1 = st.slider("", 5.0, 30.0, 10.0, 1.0,
                                    key="pt_new_dd_thr1", label_visibility="collapsed") / 100
        st.markdown(_caption("Schwelle 2 (%) → 25% Ordergrösse"), unsafe_allow_html=True)
        dd_threshold_2 = st.slider("", 10.0, 50.0, 20.0, 1.0,
                                    key="pt_new_dd_thr2", label_visibility="collapsed") / 100

    st.markdown("<hr style='border:none; border-top:1px solid rgba(255,255,255,0.08); margin:8px 0;'>", unsafe_allow_html=True)
    st.markdown(_label("Dynamische Grid-Mechanismen"), unsafe_allow_html=True)

    trailing_active_pt = st.session_state.get("pt_trailing", False)
    enable_recentering = st.checkbox(
        "Recentering aktivieren",
        key="pt_new_recenter",
        disabled=trailing_active_pt,
        help="Nicht kombinierbar mit Grid Trailing" if trailing_active_pt else None,
    )
    enable_recentering = enable_recentering and not trailing_active_pt
    recenter_threshold = 0.05
    if enable_recentering:
        st.markdown(_caption("Recentering-Schwelle (%)"), unsafe_allow_html=True)
        recenter_threshold = st.slider("", 1.0, 20.0, 5.0, 1.0,
                                        key="pt_recenter_thr",
                                        label_visibility="collapsed") / 100
        _rc_pct = int(recenter_threshold * 100)
        st.caption(
            f"Bei {_rc_pct}% wird das Grid neu zentriert, sobald der Preis "
            f"{_rc_pct}% über die Upper- oder unter die Lower-Grenze hinaus läuft. "
            f"Niedriger = häufigeres Anpassen."
        )
    atr_enabled_pt = st.checkbox("Volatilitätsbasierte Anpassung", key="pt_atr")
    enable_atr_adjust = atr_enabled_pt
    atr_multiplier    = 1.0
    enable_atr_dynamic    = False
    atr_dynamic_threshold = 0.15
    if atr_enabled_pt:
        st.markdown(_caption("ATR-Modus"), unsafe_allow_html=True)
        atr_mode = st.radio(
            "", ["Statisch (einmalig beim Start)", "Dynamisch (pro Kerze)"],
            horizontal=True, key="pt_atr_mode",
            label_visibility="collapsed"
        )
        enable_atr_dynamic = (atr_mode == "Dynamisch (pro Kerze)")
        if enable_atr_dynamic:
            st.markdown(_caption("Anpassungsschwelle (%)"), unsafe_allow_html=True)
            st.caption("Grid nur anpassen wenn ATR um mehr als X% abweicht")
            atr_dynamic_threshold = st.slider(
                "", 5.0, 30.0, 15.0, 1.0,
                key="pt_atr_threshold",
                label_visibility="collapsed"
            ) / 100
        st.markdown(_caption("ATR-Multiplikator"), unsafe_allow_html=True)
        st.caption("Grid-Abstand = ATR × Multiplikator")
        atr_multiplier = st.slider("", 0.5, 5.0, 1.0, 0.1,
                                    key="pt_atr_mult",
                                    label_visibility="collapsed")
    _pt_recenter_active = st.session_state.get("pt_new_recenter", False)
    trailing_enabled_pt = st.checkbox(
        "Grid Trailing aktivieren", key="pt_trailing",
        disabled=_pt_recenter_active,
        help="Nicht kombinierbar mit Recentering" if _pt_recenter_active else None,
    )
    if _pt_recenter_active and trailing_enabled_pt:
        trailing_enabled_pt = False
    enable_trailing_up   = False
    enable_trailing_down = False
    trailing_up_stop     = None
    trailing_down_stop   = None
    if trailing_enabled_pt:
        _pt_tr_col1, _pt_tr_col2 = st.columns([1, 17])
        with _pt_tr_col2:
            _pt_tr_pct_mode = st.checkbox("Trailing Stops prozentual", value=False, key="pt_trailing_pct_mode")
        enable_trailing_up = st.checkbox("Trailing Up", value=True, key="pt_trailing_up")
        if enable_trailing_up:
            if _pt_tr_pct_mode:
                st.markdown(_caption("Trailing Up Stop (% über Upper)"), unsafe_allow_html=True)
                _tu_pct = st.number_input("", min_value=0.0, max_value=200.0,
                                           value=10.0, step=1.0,
                                           key="pt_trailing_up_pct", label_visibility="collapsed")
                trailing_up_stop = round(upper_price * (1 + _tu_pct / 100), 4) if upper_price > 0 else None
                if trailing_up_stop:
                    st.caption(f"→ ${trailing_up_stop:,.2f} absolut")
            else:
                st.markdown(_caption("Trailing Up Stop-Preis ($)"), unsafe_allow_html=True)
                _tus = st.number_input("", min_value=0.0, value=0.0, step=100.0,
                                        key="pt_trailing_up_stop", label_visibility="collapsed")
                trailing_up_stop = _tus if _tus > 0 else None
                if trailing_up_stop and upper_price > 0:
                    _pct_up = (trailing_up_stop - upper_price) / upper_price * 100
                    st.caption(f"→ {_pct_up:+.1f}% über Upper-Grenze (${upper_price:,.2f})")
        enable_trailing_down = st.checkbox("Trailing Down", value=True, key="pt_trailing_down")
        if enable_trailing_down:
            if _pt_tr_pct_mode:
                st.markdown(_caption("Trailing Down Stop (% unter Lower)"), unsafe_allow_html=True)
                _td_pct = st.number_input("", min_value=0.0, max_value=99.0,
                                           value=10.0, step=1.0,
                                           key="pt_trailing_down_pct", label_visibility="collapsed")
                trailing_down_stop = round(lower_price * (1 - _td_pct / 100), 4) if lower_price > 0 else None
                if trailing_down_stop:
                    st.caption(f"→ ${trailing_down_stop:,.2f} absolut")
            else:
                st.markdown(_caption("Trailing Down Stop-Preis ($)"), unsafe_allow_html=True)
                _tds = st.number_input("", min_value=0.0, value=0.0, step=100.0,
                                        key="pt_trailing_down_stop", label_visibility="collapsed")
                trailing_down_stop = _tds if _tds > 0 else None
                if trailing_down_stop and lower_price > 0:
                    _pct_dn = (trailing_down_stop - lower_price) / lower_price * 100
                    st.caption(f"→ {_pct_dn:+.1f}% unter Lower-Grenze (${lower_price:,.2f})")

    # Parametrisierungsvorschlag
    st.markdown("<div style='margin-top:16px'></div>", unsafe_allow_html=True)
    st.divider()
    st.markdown("**💡 Parametrisierungsvorschlag**")
    col_opt1, col_opt2, col_opt3 = st.columns([2, 2, 1])
    with col_opt1:
        opt_objective = st.selectbox(
            "Optimierungsziel",
            ["maximize_sharpe", "maximize_roi", "maximize_calmar", "minimize_drawdown"],
            format_func=lambda x: {
                "maximize_sharpe":   "Bestes Risiko/Rendite (Sharpe)",
                "maximize_roi":      "Höchster ROI",
                "maximize_calmar":   "Calmar Ratio",
                "minimize_drawdown": "Geringstes Risiko",
            }.get(x, x),
            key="pt_opt_objective",
        )
    with col_opt2:
        opt_days = st.selectbox(
            "Historischer Zeitraum",
            [7, 14, 30],
            index=1,
            format_func=lambda x: f"Letzte {x} Tage",
            key="pt_opt_days",
        )
    with col_opt3:
        st.markdown("<div style='margin-top:28px'></div>", unsafe_allow_html=True)
        opt_btn = st.button("🔍 Vorschlag", use_container_width=True, key="pt_opt_btn")

    if opt_btn:
        with st.spinner(f"Analysiere {coin}/USDT der letzten {opt_days} Tage..."):
            try:
                from src.trading.optimizer import suggest_parameters
                s = suggest_parameters(
                    coin             = coin,
                    total_investment = total_investment,
                    lookback_days    = opt_days,
                    interval         = interval,
                    objective        = opt_objective,
                )
                regime_colors = {
                    "range":      "#34D399",
                    "trend_up":   "#FBBF24",
                    "trend_down": "#F87171",
                    "neutral":    "#94A3B8",
                }
                rc = regime_colors.get(s.regime, "#94A3B8")
                st.markdown(
                    f"<div style='padding:12px 16px; background:rgba(255,255,255,0.04); "
                    f"border-left:3px solid {rc}; border-radius:6px; margin-top:8px;'>"
                    f"<div style='color:{rc}; font-weight:700; margin-bottom:8px;'>"
                    f"Parametrisierungsvorschlag für {coin}/USDT</div>"
                    f"<div style='color:#E2E8F0; font-size:0.9rem; line-height:1.8;'>"
                    f"<b>Grid-Modus:</b> {'Arithmetisch' if s.grid_mode == 'arithmetic' else 'Geometrisch'}<br>"
                    f"<b>Anzahl Grids:</b> {s.num_grids}<br>"
                    f"<b>Untere Grenze:</b> ${s.lower_price:,.2f}<br>"
                    f"<b>Obere Grenze:</b> ${s.upper_price:,.2f}<br>"
                    f"<b>ROI (hist.):</b> {s.roi_pct:+.2f}% | "
                    f"<b>Sharpe:</b> {s.sharpe:.2f} | "
                    f"<b>Max DD:</b> {s.max_dd_pct:.2f}%"
                    f"</div>"
                    f"<div style='color:#94A3B8; font-size:0.8rem; margin-top:8px;'>"
                    f"{s.reasoning.split(chr(10))[0]}</div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )
                if s.warning:
                    st.warning(s.warning)
            except Exception as e:
                st.error(f"Fehler beim Erstellen des Vorschlags: {e}")

    st.divider()
    st.markdown("<div style='margin-top:16px'></div>", unsafe_allow_html=True)
    col_btn1, col_btn2 = st.columns([2, 1])
    with col_btn1:
        if st.button("▶ Bot starten", type="primary",
                      use_container_width=True, key="pt_create_bot"):
            if lower_price >= upper_price:
                st.error("Untere Grenze muss kleiner als obere Grenze sein!")
            elif not coin:
                st.error("Bitte einen Coin auswaehlen!")
            else:
                name = bot_name.strip() if bot_name.strip() else f"{coin}/USDT"
                bot_id, err = bot_store.create_bot(
                    mode               = "paper",
                    coin               = coin,
                    interval           = interval,
                    lower_price        = lower_price,
                    upper_price        = upper_price,
                    total_investment   = total_investment,
                    num_grids          = int(num_grids),
                    grid_mode          = grid_mode,
                    fee_rate           = fee_rate,
                    reserve_pct        = reserve_pct,
                    stop_loss_pct      = stop_loss_pct,
                    enable_dd_throttle  = enable_dd_throttle,
                    dd_threshold_1      = dd_threshold_1,
                    dd_threshold_2      = dd_threshold_2,
                    enable_variable_orders = enable_variable_orders,
                    weight_bottom          = weight_bottom,
                    weight_top             = weight_top,
                    enable_recentering     = enable_recentering,
                    recenter_threshold     = recenter_threshold,
                    enable_atr_adjust      = enable_atr_adjust,
                    atr_multiplier         = atr_multiplier,
                    enable_atr_dynamic     = enable_atr_dynamic,
                    atr_dynamic_threshold  = atr_dynamic_threshold,
                    enable_trailing_up     = enable_trailing_up,
                    enable_trailing_down   = enable_trailing_down,
                    trailing_up_stop       = trailing_up_stop,
                    trailing_down_stop     = trailing_down_stop,
                )
                if err:
                    st.error(err)
                else:
                    bot_store.update_bot(bot_id, {"name": name})
                    st.success(f"Bot gestartet: {name}  {coin}/USDT {interval}")
                    st.session_state.pt_show_new_bot  = False
                    st.session_state.pt_selected_bot  = bot_id
                    st.rerun()
    with col_btn2:
        if st.button("Abbrechen", use_container_width=True, key="pt_cancel_new"):
            st.session_state.pt_show_new_bot = False
            st.rerun()


# ---------------------------------------------------------------------------
# Übersicht aller Bots
# ---------------------------------------------------------------------------

def _show_bots_overview(bots: list):
    col_ov1, col_ov2 = st.columns([3, 1])
    with col_ov1:
        st.markdown("### Übersicht aktive Bots")
    with col_ov2:
        running = [b for b in bots if b.get("status") == "running"]
        if st.button(
            f"🔄 Alle aktualisieren ({len(running)})",
            use_container_width=True,
            disabled=len(running) == 0,
            key="pt_update_all"
        ):
            from src.trading.engine import BotRunner
            errors = []
            for bot in running:
                try:
                    runner = BotRunner(bot["bot_id"])
                    runner.run_update()
                except Exception as e:
                    errors.append(f"{bot['bot_id']}: {e}")
            if errors:
                st.error("Fehler: " + ", ".join(errors))
            else:
                st.success(f"✅ {len(running)} Bots aktualisiert")
            st.rerun()

    for bot in bots:
        cfg     = bot.get("config", {})
        metrics = bot.get("metrics", {})
        roi     = metrics.get("roi_pct", 0) or 0
        trades  = len(bot.get("trade_log", []))
        runtime = metrics.get("runtime", {})
        if not isinstance(runtime, dict) or not runtime.get("formatted"):
            from src.metrics import calculate_runtime
            runtime = calculate_runtime(bot.get("created_at", ""))
        rt_str = runtime.get("formatted", "–") if isinstance(runtime, dict) else "–"
        color   = "#34D399" if roi >= 0 else "#F87171"

        st.markdown(f"""
        <div style="background:rgba(255,255,255,0.03);
                    border:1px solid rgba(255,255,255,0.08);
                    border-left: 3px solid {color};
                    border-radius:8px; padding:14px 18px;
                    margin-bottom:4px;">
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <div>
                    <span style="font-weight:700; color:#E2E8F0; font-size:1rem;">
                        {bot.get('name', bot['coin']+'/USDT')}
                    </span>
                    <span style="color:#64748B; font-size:0.8rem; margin-left:12px;">
                        {bot['coin']}/USDT · {bot['interval']} · ID: {bot['bot_id']}
                    </span>
                </div>
                {_status_badge(bot["status"])}
            </div>
            <div style="display:flex; gap:24px; margin-top:8px;">
                <span style="color:#94A3B8; font-size:0.85rem;">ROI: <b style="color:{color};">{roi:+.2f}%</b></span>
                <span style="color:#94A3B8; font-size:0.85rem;">Trades: <b style="color:#E2E8F0;">{trades}</b></span>
                <span style="color:#94A3B8; font-size:0.85rem;">Kapital: <b style="color:#E2E8F0;">${cfg.get('total_investment',0):,.0f}</b></span>
                <span style="color:#94A3B8; font-size:0.85rem;">Grids: <b style="color:#E2E8F0;">{cfg.get('num_grids',0)}</b></span>
                <span style="color:#94A3B8; font-size:0.85rem;">Laufzeit: <b style="color:#E2E8F0;">{rt_str}</b></span>
                <span style="color:#94A3B8; font-size:0.85rem;">Einstand: <b style="color:#E2E8F0;">{_format_ts(bot.get('created_at',''))}</b></span>
            </div>
        </div>
        """, unsafe_allow_html=True)
        if st.button("Details anzeigen", key=f"pt_detail_{bot['bot_id']}", use_container_width=True):
            st.session_state.pt_selected_bot = bot["bot_id"]
            st.rerun()
        st.markdown("<div style='margin-bottom:8px'></div>", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Bot-Detailansicht
# ---------------------------------------------------------------------------

def _show_bot_detail(bot: dict):
    cfg       = bot.get("config", {})
    metrics   = bot.get("metrics", {})
    trade_log = bot.get("trade_log", [])
    roi       = metrics.get("roi_pct", 0) or 0
    color     = "#34D399" if roi >= 0 else "#F87171"

    name = bot.get("name", f"{bot['coin']}/USDT")
    st.markdown(
        f"<div style='margin-bottom:8px;'>"
        f"<span style='font-size:1.6rem; font-weight:700; color:#E2E8F0;'>{name}</span>"
        f"<span style='font-size:0.85rem; color:#64748B; margin-left:10px;'>"
        f"{bot['coin']}/USDT · {bot['interval']} · ID: {bot['bot_id']}</span>"
        f" &nbsp;&nbsp; {_status_badge(bot['status'])}"
        f"</div>",
        unsafe_allow_html=True
    )

    col_b1, col_b2, col_b3, col_back = st.columns([3, 2, 2, 2])
    with col_b1:
        if st.button("Preis aktualisieren", key="pt_det_update",
                      disabled=bot["status"] != "running",
                      use_container_width=True):
            from src.trading.engine import BotRunner
            with st.spinner("Verarbeite neue Kerzen..."):
                try:
                    runner = BotRunner(bot["bot_id"])
                    result = runner.run_update()
                    if result.get("error"):
                        st.error(f"Fehler: {result['error']}")
                    else:
                        n = len(result.get("new_trades", []))
                        c = result.get("candles_processed", 0)
                        p = result.get("current_price", 0)
                        st.success(f"Kurs: ${p:,.2f} · {c} Kerzen · {n} neue Trades")
                        try:
                            from src.analysis.regime import detect_regime
                            from src.data.cache_manager import get_price_data as _gp
                            df_r, _ = _gp(bot["coin"], days=7, interval=bot["interval"])
                            if df_r is not None and not df_r.empty:
                                rg = detect_regime(df_r, bot["interval"])
                                r_colors = {"range": "#34D399", "trend_up": "#F87171", "trend_down": "#F87171", "neutral": "#FBBF24"}
                                r_labels = {"range": "Range-Markt — Grid-Bot geeignet",
                                            "trend_up": "Trend aufwärts — Grid-Bot weniger geeignet",
                                            "trend_down": "Trend abwärts — Grid-Bot weniger geeignet",
                                            "neutral": "Unklare Marktlage"}
                                rc = r_colors.get(rg.regime, "#FBBF24")
                                rl = r_labels.get(rg.regime, rg.regime)
                                st.markdown(
                                    f"<div style='padding:6px 10px; border-left:3px solid {rc}; "
                                    f"background:rgba(255,255,255,0.03); border-radius:4px;'>"
                                    f"<span style='color:{rc}; font-weight:600;'>Regime:</span> "
                                    f"<span style='color:#E2E8F0; font-size:0.85rem;'>{rl}</span> "
                                    f"<span style='color:#64748B; font-size:0.75rem;'>(ADX14: {rg.adx14:.1f} · {rg.confidence:.0f}%)</span>"
                                    f"</div>",
                                    unsafe_allow_html=True
                                )
                        except Exception:
                            pass
                        import time; time.sleep(8)
                        st.rerun()
                except Exception as e:
                    st.error(f"Fehler: {e}")
    with col_b2:
        if st.button("Stoppen", key="pt_det_stop",
                      disabled=bot["status"] != "running",
                      use_container_width=True):
            bot_store.set_status(bot["bot_id"], "stopped")
            st.rerun()
    with col_b3:
        if st.button("Löschen", key="pt_det_del",
                      use_container_width=True):
            bot_store.delete_bot(bot["bot_id"])
            st.session_state.pt_selected_bot = None
            st.rerun()
    with col_back:
        if st.button("← Zurück", key="pt_det_back",
                      use_container_width=True):
            st.session_state.pt_selected_bot = None
            st.rerun()

    st.divider()

    from components.metrics_display import render_metrics_row
    upnl    = metrics.get("unrealized_pnl", {})
    runtime = metrics.get("runtime", {})
    if not isinstance(runtime, dict) or not runtime.get("formatted"):
        from src.metrics import calculate_runtime
        runtime = calculate_runtime(bot.get("created_at", ""))

    metrics_dict = {
        "roi_pct":              roi,
        "sharpe":               metrics.get("sharpe_ratio", 0),
        "max_dd_pct":           metrics.get("max_drawdown_pct", 0),
        "num_trades":           len(trade_log),
        "bh_roi_pct":           metrics.get("benchmark_roi_pct", 0),
        "outperformance":       metrics.get("outperformance_pct", 0),
        "cagr_pct":             metrics.get("cagr_pct", 0),
        "calmar":               metrics.get("calmar_ratio", 0),
        "win_rate":             metrics.get("win_rate_pct", 0),
        "profit_factor":        metrics.get("profit_factor", 0),
        "fees_paid":            sum(t.get("fee",0) for t in trade_log),
        "initial_investment":   cfg.get("total_investment", 0),
        "final_value":          metrics.get("final_value", cfg.get("total_investment", 0)),
        "grid_efficiency":      metrics.get("grid_efficiency"),
        "avg_profit_per_trade": metrics.get("avg_profit_per_trade"),
        "runtime":              runtime,
        "unrealized_pnl":       upnl,
        "_trade_log":           trade_log,
    }
    render_metrics_row(metrics_dict, mode="backtest")
    st.divider()

    tab1, tab2, tab3 = st.tabs(["📈 Chart", "📋 Trade-Log", "⚙️ Konfiguration"])

    with tab1:
        try:
            df_chart, _ = get_price_data(bot["coin"], days=7, interval=bot["interval"])
            if df_chart is not None and not df_chart.empty:
                df_display = convert_df_timestamps(df_chart)
                _state_grids = bot.get("state", {}).get("grids", {})
                if _state_grids:
                    _state_prices = sorted([float(k) for k in _state_grids.keys()])
                    gc = build_grid_config(
                        lower_price = _state_prices[0],
                        upper_price = _state_prices[-1],
                        num_grids   = cfg["num_grids"],
                        mode        = cfg["grid_mode"],
                        fee_rate    = cfg.get("fee_rate", DEFAULT_FEE_RATE),
                    )
                    gc.grid_lines = _state_prices
                else:
                    gc = build_grid_config(
                        lower_price = cfg["lower_price"],
                        upper_price = cfg["upper_price"],
                        num_grids   = cfg["num_grids"],
                        mode        = cfg["grid_mode"],
                        fee_rate    = cfg.get("fee_rate", DEFAULT_FEE_RATE),
                    )
                tl_display = []
                for t in trade_log:
                    t2 = dict(t)
                    try:
                        t2["timestamp"] = utc_to_zurich(t2["timestamp"])
                    except Exception:
                        pass
                    tl_display.append(t2)

                plot_grid_chart_v2(
                    df          = df_display,
                    grid_lines  = gc.grid_lines if gc else [],
                    trade_log   = tl_display,
                    interval    = bot["interval"],
                    coin        = bot["coin"],
                    show_volume = True,
                    upper_price = float(gc.grid_lines[-1]) if gc and gc.grid_lines else float(cfg["upper_price"]),
                    lower_price = float(gc.grid_lines[0])  if gc and gc.grid_lines else float(cfg["lower_price"]),
                )
            else:
                st.info("Keine Chart-Daten verfügbar.")
        except Exception as e:
            st.warning(f"Chart-Fehler: {e}")

    with tab2:
        if trade_log:
            rows = []
            for t in reversed(trade_log[-50:]):
                try:
                    ts_str = utc_to_zurich(t.get("timestamp","")).strftime("%Y-%m-%d %H:%M")
                except Exception:
                    ts_str = str(t.get("timestamp",""))[:16]
                profit = t.get("profit", 0) or 0
                rows.append({
                    "Zeit":    ts_str,
                    "Typ":     t.get("type",""),
                    "Preis":   f"${t.get('price',0):,.2f}",
                    "Menge":   f"{t.get('amount',0):.6f}",
                    "Gebühr":  f"${t.get('fee',0):.4f}",
                    "Profit":  f"{profit:+.4f}" if "SELL" in str(t.get("type","")).upper() else "–",
                })
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        else:
            st.info("Noch keine Trades — Bot wartet auf Grid-Auslösung.")

    with tab3:
        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown(f"- **Coin:** {bot['coin']}/USDT")
            st.markdown(f"- **Intervall:** {bot['interval']}")
            st.markdown(f"- **Startkapital:** ${cfg.get('total_investment',0):,.2f}")
            st.markdown(f"- **Kapitalreserve:** {cfg.get('reserve_pct',0)*100:.0f}%")
            st.markdown(f"- **Grid-Modus:** {cfg.get('grid_mode','–')}")
            st.markdown(f"- **Anzahl Grids:** {cfg.get('num_grids','–')}")
            st.markdown(f"- **Untere Grenze:** ${cfg.get('lower_price',0):,.2f}")
            st.markdown(f"- **Obere Grenze:** ${cfg.get('upper_price',0):,.2f}")
            st.markdown(f"- **Gebührenrate:** {cfg.get('fee_rate',0)*100:.3f}%")
            st.markdown(f"- **Erstellt:** {_format_ts(bot.get('created_at',''))}")
        with col_b:
            st.markdown("**Dynamische Mechanismen:**")
            if cfg.get("stop_loss_pct"):
                st.markdown(f"- **Stop-Loss:** Aktiv ({cfg['stop_loss_pct']*100:.0f}%)")
            else:
                st.markdown("- **Stop-Loss:** Inaktiv")
            if cfg.get("enable_dd_throttle"):
                st.markdown(f"- **DD-Drosselung:** Aktiv (Schwelle 1: {cfg.get('dd_threshold_1',0)*100:.0f}% / Schwelle 2: {cfg.get('dd_threshold_2',0)*100:.0f}%)")
            else:
                st.markdown("- **DD-Drosselung:** Inaktiv")
            if cfg.get("enable_variable_orders"):
                st.markdown(f"- **Variable Orders:** Aktiv (unten {cfg.get('weight_bottom',1)}× / oben {cfg.get('weight_top',1)}×)")
            else:
                st.markdown("- **Variable Orders:** Inaktiv")
            if cfg.get("enable_recentering"):
                st.markdown(f"- **Recentering:** Aktiv ({cfg.get('recenter_threshold',0)*100:.0f}%)")
            else:
                st.markdown("- **Recentering:** Inaktiv")
            if cfg.get("enable_atr_adjust"):
                st.markdown(f"- **ATR-Anpassung:** Aktiv (×{cfg.get('atr_multiplier',1.0)})")
            else:
                st.markdown("- **ATR-Anpassung:** Inaktiv")
            trailing_up   = cfg.get("enable_trailing_up",   False)
            trailing_down = cfg.get("enable_trailing_down",  False)
            if trailing_up or trailing_down:
                parts = []
                if trailing_up:   parts.append(f"Up (Stop: ${cfg.get('trailing_up_stop','–')})")
                if trailing_down: parts.append(f"Down (Stop: ${cfg.get('trailing_down_stop','–')})")
                st.markdown(f"- **Grid Trailing:** Aktiv ({', '.join(parts)})")
            else:
                st.markdown("- **Grid Trailing:** Inaktiv")


# ---------------------------------------------------------------------------
# Leerer Zustand
# ---------------------------------------------------------------------------

def _show_empty_state():
    st.markdown(
        "<div style='text-align:center; padding:60px; color:#64748B;'>"
        "<div style='font-size:3rem;'>📄</div>"
        "<div style='font-size:1.1rem; margin-top:12px; color:#94A3B8;'>"
        "Noch keine Paper-Trading Bots</div>"
        "<div style='font-size:0.85rem; margin-top:8px;'>"
        "Klicke <b>＋ Neuen Bot starten</b> in der Sidebar</div>"
        "</div>",
        unsafe_allow_html=True
    )
