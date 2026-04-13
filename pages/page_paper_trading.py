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

def _status_badge(status: str) -> str:
    colors = {"running": "#34D399", "stopped": "#F87171", "error": "#FBBF24"}
    labels = {"running": "● LÄUFT", "stopped": "■ GESTOPPT", "error": "⚠ FEHLER"}
    color = colors.get(status, "#94A3B8")
    label = labels.get(status, status.upper())
    return (f"<span style='color:{color}; font-weight:700; "
            f"font-size:0.8rem;'>{label}</span>")


def _format_ts(ts_str: str) -> str:
    """UTC-Timestamp nach MEZ (Europe/Zurich) formatieren."""
    try:
        from src.utils.timezone import utc_to_zurich
        import pandas as pd
        ts = utc_to_zurich(pd.Timestamp(ts_str))
        return ts.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(ts_str)[:16].replace("T", " ")


def show_paper_trading():

    # ── Session State ────────────────────────────────────────────────────────
    if "pt_selected_bot" not in st.session_state:
        st.session_state.pt_selected_bot = None
    if "pt_show_new_bot" not in st.session_state:
        st.session_state.pt_show_new_bot = False
    if "pt_show_overview" not in st.session_state:
        st.session_state.pt_show_overview = False

    bots        = sorted(bot_store.get_all_bots(mode="paper"), key=lambda b: b.get("created_at",""), reverse=True)
    bot_count   = len(bots)
    can_create  = bot_count < MAX_BOTS_PER_MODE

    # ── Sidebar ──────────────────────────────────────────────────────────────
    st.sidebar.markdown(_label("Ansicht"), unsafe_allow_html=True)
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

    # ── Header ───────────────────────────────────────────────────────────────
    st.markdown("# 📄 Paper Trading")
    st.caption(f"{bot_count}/{MAX_BOTS_PER_MODE} Bots aktiv")
    st.divider()

    # ── Neuen Bot konfigurieren ──────────────────────────────────────────────
    if st.session_state.pt_show_new_bot or (not bots and not st.session_state.pt_selected_bot):
        _show_new_bot_form()
        return

    # ── Bot-Detailansicht ────────────────────────────────────────────────────
    if st.session_state.pt_selected_bot:
        bot = bot_store.get_bot(st.session_state.pt_selected_bot)
        if bot:
            _show_bot_detail(bot)
            return
        else:
            st.session_state.pt_selected_bot = None

    # ── Übersicht aktive Bots ────────────────────────────────────────────────
    if st.session_state.pt_show_overview or bots:
        _show_bots_overview(bots)
    else:
        _show_empty_state()


# ---------------------------------------------------------------------------
# Neuen Bot erstellen
# ---------------------------------------------------------------------------

def _show_new_bot_form():
    st.markdown("### Neuen Bot konfigurieren")
    st.markdown("<div style='margin-bottom:16px'></div>", unsafe_allow_html=True)

    st.markdown(_label("Bot-Name"), unsafe_allow_html=True)
    bot_name = st.text_input(
        "", placeholder="z.B. BTC Range Bot, ETH Swing...",
        label_visibility="collapsed", key="pt_new_name"
    )
    st.markdown("<div style='margin-top:12px'></div>", unsafe_allow_html=True)

    st.markdown(_label("Coin"), unsafe_allow_html=True)
    coin_mode = st.radio("", ["Aus Liste", "Eigene Eingabe"],
                          horizontal=True, key="pt_new_coin_mode",
                          label_visibility="collapsed")
    if coin_mode == "Aus Liste":
        coin = st.selectbox("", COINS, label_visibility="collapsed", key="pt_new_coin")
    else:
        coin = st.text_input("", value="BTC", label_visibility="collapsed",
                              key="pt_new_coin_input").upper().strip()
    st.markdown("<div style='margin-top:12px'></div>", unsafe_allow_html=True)

    st.markdown(_label("Intervall"), unsafe_allow_html=True)
    interval = st.radio("", ["1m","5m","15m","1h","4h"],
                         index=3, horizontal=True, key="pt_new_interval",
                         label_visibility="collapsed")
    st.markdown("<div style='margin-top:12px'></div>", unsafe_allow_html=True)

    st.markdown(_label("Startkapital"), unsafe_allow_html=True)
    total_investment = st.number_input(
        "", min_value=100.0, max_value=1_000_000.0,
        value=10000.0, step=500.0,
        label_visibility="collapsed", key="pt_new_capital"
    )
    st.markdown("<div style='margin-top:12px'></div>", unsafe_allow_html=True)

    st.markdown(_label("Grid-Parameter"), unsafe_allow_html=True)
    current_price, lower_s, upper_s = None, None, None
    try:
        df_tmp, _ = get_price_data(coin, days=14, interval="1h")
        if df_tmp is not None and not df_tmp.empty:
            current_price = float(df_tmp["close"].iloc[-1])
            suggestion    = suggest_grid_range(df_tmp, current_price)
            lower_s       = suggestion.lower_price
            upper_s       = suggestion.upper_price
    except Exception:
        pass
    current_price = current_price or 68000.0
    lower_s       = lower_s  or current_price * 0.80
    upper_s       = upper_s  or current_price * 1.20
    step_val      = float(round(current_price * 0.01, 2))
    pct_ld = round((current_price - lower_s) / current_price * 100, 1)
    pct_ud = round((upper_s - current_price) / current_price * 100, 1)

    st.markdown(
        f"<div style='font-size:0.75rem; color:#94A3B8; margin-bottom:6px;'>"
        f"Aktueller Preis: <b style='color:#E2E8F0;'>{current_price:,.2f} USDT</b>"
        f" &nbsp;&middot;&nbsp; Vorschlag: {lower_s:,.2f} (&minus;{pct_ld:.0f}%)"
        f" &ndash; {upper_s:,.2f} (+{pct_ud:.0f}%)</div>",
        unsafe_allow_html=True
    )

    pct_mode = st.checkbox("Preisgrenzen prozentual setzen", value=False, key="pt_new_pct_mode")
    if pct_mode:
        col_p1, col_p2 = st.columns(2)
        with col_p1:
            st.markdown(_caption("Untere Grenze (%)"), unsafe_allow_html=True)
            pct_lv = st.number_input("", 1.0, 50.0, pct_ld, 1.0,
                                      key="pt_new_pct_lower", label_visibility="collapsed")
        with col_p2:
            st.markdown(_caption("Obere Grenze (%)"), unsafe_allow_html=True)
            pct_uv = st.number_input("", 1.0, 50.0, pct_ud, 1.0,
                                      key="pt_new_pct_upper", label_visibility="collapsed")
        lower_price = round(current_price * (1 - pct_lv / 100), 2)
        upper_price = round(current_price * (1 + pct_uv / 100), 2)
        st.caption(f"-> {lower_price:,.2f} - {upper_price:,.2f} USDT")
    else:
        col_g1, col_g2 = st.columns(2)
        with col_g1:
            st.markdown(_caption("Untere Grenze ($)"), unsafe_allow_html=True)
            lower_price = st.number_input("", min_value=0.001,
                                           value=float(round(lower_s, 2)),
                                           step=step_val, key="pt_new_lower",
                                           label_visibility="collapsed")
        with col_g2:
            st.markdown(_caption("Obere Grenze ($)"), unsafe_allow_html=True)
            upper_price = st.number_input("", min_value=0.001,
                                           value=float(round(upper_s, 2)),
                                           step=step_val, key="pt_new_upper",
                                           label_visibility="collapsed")

    col_gl, col_gv = st.columns([3, 1])
    with col_gl:
        st.markdown(_caption("Anzahl Grids"), unsafe_allow_html=True)
    with col_gv:
        ng_val = st.session_state.get("pt_new_grids", DEFAULT_NUM_GRIDS)
        st.markdown(
            f"<div style='text-align:right; color:#3B82F6; font-weight:600;'>{ng_val}</div>",
            unsafe_allow_html=True
        )
    num_grids = st.number_input(
        "", min_value=2, max_value=100,
        value=st.session_state.get("pt_new_grids", DEFAULT_NUM_GRIDS),
        step=1, key="pt_new_grids", label_visibility="collapsed"
    )

    st.markdown(_caption("Grid-Modus"), unsafe_allow_html=True)
    st.caption("Arithmetic: gleiche Abstaende | Geometric: gleiche % Abstaende")
    grid_mode = st.radio("", ["arithmetic","geometric"],
                          horizontal=True, key="pt_new_mode",
                          label_visibility="collapsed")

    st.markdown(_caption("Handelsgebuehr (%)"), unsafe_allow_html=True)
    fee_rate = st.number_input(
        "", 0.0, 1.0, DEFAULT_FEE_RATE * 100, 0.01,
        format="%.3f", key="pt_new_fee", label_visibility="collapsed"
    ) / 100

    try:
        if upper_price > lower_price and num_grids > 0:
            gstep = (upper_price - lower_price) / num_grids
            gprofit = gstep / upper_price - 2 * fee_rate
            gcolor = "#34D399" if gprofit > 0 else "#F87171"
            st.markdown(
                f"<div style='margin-top:6px; padding:8px 10px; "
                f"background:rgba(52,211,153,0.08); border-left:3px solid {gcolor}; "
                f"border-radius:4px; font-size:0.8rem;'>"
                f"<span style='color:{gcolor}; font-weight:600;'>Gewinn pro Grid (nach Fees):</span>"
                f"<span style='color:{gcolor};'> {gprofit*100:.3f}%</span></div>",
                unsafe_allow_html=True
            )
    except Exception:
        pass

    st.markdown("<div style='margin-top:12px'></div>", unsafe_allow_html=True)

    with st.expander("Erweiterte Einstellungen"):
        st.markdown(_caption("Kapitalreserve (%)"), unsafe_allow_html=True)
        reserve_pct = st.slider("", 0.0, 20.0, DEFAULT_RESERVE_PCT * 100, 1.0,
                                 key="pt_new_reserve", label_visibility="collapsed") / 100
        sl_enabled = st.checkbox("Stop-Loss aktivieren", key="pt_new_sl")
        stop_loss_pct = None
        if sl_enabled:
            st.markdown(_caption("Stop-Loss (%)"), unsafe_allow_html=True)
            stop_loss_pct = st.slider("", 5.0, 50.0, 20.0, 5.0,
                                       key="pt_new_sl_pct", label_visibility="collapsed") / 100

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
                    mode             = "paper",
                    coin             = coin,
                    interval         = interval,
                    lower_price      = lower_price,
                    upper_price      = upper_price,
                    total_investment = total_investment,
                    num_grids        = int(num_grids),
                    grid_mode        = grid_mode,
                    fee_rate         = fee_rate,
                    reserve_pct      = reserve_pct,
                    stop_loss_pct    = stop_loss_pct,
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
    st.markdown("### Übersicht aktive Bots")

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

        with st.container():
            st.markdown(f"""
            <div style="background:rgba(255,255,255,0.03);
                        border:1px solid rgba(255,255,255,0.08);
                        border-left: 3px solid {color};
                        border-radius:8px; padding:14px 18px;
                        margin-bottom:10px;">
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <div>
                        <span style="font-weight:700; color:#E2E8F0; font-size:1rem;">
                            {bot.get('name', bot['coin']+'/USDT')}
                        </span>
                        <span style="color:#64748B; font-size:0.8rem; margin-left:12px;">
                            {bot['coin']}/USDT · {bot['interval']} · ID: {bot['bot_id']}
                        </span>
                    </div>
                    {_status_badge(bot['status'])}
                </div>
                <div style="display:flex; gap:24px; margin-top:8px;">
                    <span style="color:#94A3B8; font-size:0.85rem;">
                        ROI: <b style="color:{color};">{roi:+.2f}%</b>
                    </span>
                    <span style="color:#94A3B8; font-size:0.85rem;">
                        Trades: <b style="color:#E2E8F0;">{trades}</b>
                    </span>
                    <span style="color:#94A3B8; font-size:0.85rem;">
                        Kapital: <b style="color:#E2E8F0;">${cfg.get('total_investment',0):,.0f}</b>
                    </span>
                    <span style="color:#94A3B8; font-size:0.85rem;">
                        Grids: <b style="color:#E2E8F0;">{cfg.get('num_grids',0)}</b>
                    </span>
                    <span style="color:#94A3B8; font-size:0.85rem;">
                        Laufzeit: <b style="color:#E2E8F0;">{rt_str}</b>
                    </span>
                    <span style="color:#94A3B8; font-size:0.85rem;">
                        Einstand: <b style="color:#E2E8F0;">{_format_ts(bot.get('created_at',''))}</b>
                    </span>
                </div>
            </div>
            """, unsafe_allow_html=True)

            col1, col2, col3 = st.columns([2, 1, 1])
            with col1:
                if st.button("🔍 Details anzeigen",
                              key=f"pt_detail_{bot['bot_id']}",
                              use_container_width=True):
                    st.session_state.pt_selected_bot = bot["bot_id"]
                    st.rerun()
            with col2:
                if st.button("⏹ Stoppen",
                              key=f"pt_stop_{bot['bot_id']}",
                              disabled=bot["status"] != "running",
                              use_container_width=True):
                    bot_store.set_status(bot["bot_id"], "stopped")
                    st.rerun()
            with col3:
                if st.button("🗑 Löschen",
                              key=f"pt_del_{bot['bot_id']}",
                              use_container_width=True):
                    bot_store.delete_bot(bot["bot_id"])
                    if st.session_state.pt_selected_bot == bot["bot_id"]:
                        st.session_state.pt_selected_bot = None
                    st.rerun()


# ---------------------------------------------------------------------------
# Bot-Detailansicht
# ---------------------------------------------------------------------------

def _show_bot_detail(bot: dict):
    cfg     = bot.get("config", {})
    metrics = bot.get("metrics", {})
    trade_log = bot.get("trade_log", [])
    roi     = metrics.get("roi_pct", 0) or 0
    color   = "#34D399" if roi >= 0 else "#F87171"

    # Header
    col_title, col_back = st.columns([4, 1])
    with col_title:
        st.markdown(
            f"### {bot['coin']}/USDT · {bot['interval']} "
            f"<span style='font-size:0.85rem; color:#64748B;'>ID: {bot['bot_id']}</span>",
            unsafe_allow_html=True
        )
    with col_back:
        if st.button("← Zurück", use_container_width=True, key="pt_back"):
            st.session_state.pt_selected_bot = None
            st.rerun()

    # Status + Aktionen
    col_s, col_upd, col_stop, col_del = st.columns([2, 2, 1, 1])
    with col_s:
        st.markdown(_status_badge(bot["status"]), unsafe_allow_html=True)
    with col_upd:
        if st.button("🔄 Preis aktualisieren", key="pt_det_update",
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
                        st.success(f"✅ Kurs: ${p:,.2f} · {c} Kerzen · {n} neue Trades")
                        st.rerun()
                except Exception as e:
                    st.error(f"Runner-Fehler: {e}")
    with col_stop:
        if st.button("⏹ Stoppen", key="pt_det_stop",
                      disabled=bot["status"] != "running",
                      use_container_width=True):
            bot_store.set_status(bot["bot_id"], "stopped")
            st.rerun()
    with col_del:
        if st.button("🗑 Löschen", key="pt_det_del",
                      use_container_width=True):
            bot_store.delete_bot(bot["bot_id"])
            st.session_state.pt_selected_bot = None
            st.rerun()

    st.divider()

    # Metriken
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("ROI", f"{roi:+.2f}%")
    col2.metric("Trades", len(trade_log))
    col3.metric("Startkapital", f"${cfg.get('total_investment',0):,.2f}")
    runtime = metrics.get("runtime", {})
    col4.metric("Laufzeit",
                runtime.get("formatted","–") if isinstance(runtime, dict) else "–")

    col5, col6, col7, col8 = st.columns(4)
    col5.metric("Win-Rate",
                f"{metrics.get('win_rate_pct',0) or 0:.1f}%")
    col6.metric("Profit-Faktor",
                f"{metrics.get('profit_factor',0) or 0:.2f}")
    col7.metric("Max Drawdown",
                f"{metrics.get('max_drawdown_pct',0) or 0:.2f}%")
    upnl = metrics.get("unrealized_pnl", {})
    upnl_usdt = upnl.get("usdt", 0) if isinstance(upnl, dict) else 0
    col8.metric("Unrealisiert", f"${upnl_usdt:+.2f}")

    st.divider()

    # Tabs
    tab1, tab2, tab3 = st.tabs(["📈 Chart", "📋 Trade-Log", "⚙️ Konfiguration"])

    with tab1:
        try:
            df_chart, _ = get_price_data(
                bot["coin"], days=7, interval=bot["interval"]
            )
            if df_chart is not None and not df_chart.empty:
                df_display = convert_df_timestamps(df_chart)
                gc = build_grid_config(
                    lower_price = cfg["lower_price"],
                    upper_price = cfg["upper_price"],
                    num_grids   = cfg["num_grids"],
                    mode        = cfg["grid_mode"],
                    fee_rate    = cfg.get("fee_rate", DEFAULT_FEE_RATE),
                )
                # Trade-Log Timestamps konvertieren
                tl_display = []
                for t in trade_log:
                    t2 = dict(t)
                    try:
                        t2["timestamp"] = utc_to_zurich(t2["timestamp"])
                    except Exception:
                        pass
                    tl_display.append(t2)

                fig = plot_grid_chart(
                    df           = df_display,
                    grid_lines   = gc.grid_lines if gc else [],
                    trade_log    = tl_display,
                    coin         = bot["coin"],
                    title        = f"{bot['coin']}/USDT · {bot['interval']} · Paper Trading",
                    show_volume  = True,
                    show_grid_bg = True,
                    chart_type   = "Candlestick",
                )
                st.plotly_chart(fig, use_container_width=True)
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
            st.markdown(f"- **Grid-Modus:** {cfg.get('grid_mode','–')}")
            st.markdown(f"- **Stop-Loss:** {'Aktiv' if cfg.get('stop_loss_pct') else 'Inaktiv'}")
        with col_b:
            st.markdown(f"- **Anzahl Grids:** {cfg.get('num_grids','–')}")
            st.markdown(f"- **Untere Grenze:** ${cfg.get('lower_price',0):,.2f}")
            st.markdown(f"- **Obere Grenze:** ${cfg.get('upper_price',0):,.2f}")
            st.markdown(f"- **Gebührenrate:** {cfg.get('fee_rate',0)*100:.3f}%")
            st.markdown(f"- **Erstellt:** {bot.get('created_at','')[:16].replace('T',' ')}")


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
