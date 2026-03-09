"""
pages/page_paper_trading.py
Autor: Enes Eryilmaz – Grid-Trading-Framework (Bachelorarbeit OST)
"""

import streamlit as st
import pandas as pd
from datetime import datetime, timedelta

from src.trading.engine import (
    TradingEngine, TradingConfig, load_existing_state, clear_state
)
from src.trading.paper_broker import PaperBroker
from src.data.cache_manager import get_price_data
from src.strategy.grid_builder import suggest_grid_range, build_grid_config
from components.chart import plot_grid_chart

from config.settings import (
    DEFAULT_NUM_GRIDS, DEFAULT_GRID_MODE,
    DEFAULT_FEE_RATE, DEFAULT_RESERVE_PCT,
)

LABEL_STYLE = (
    "font-size:1.15rem; font-weight:600; color:#CBD5E1; "
    "font-family:Inter,-apple-system,sans-serif; text-transform:uppercase; "
    "letter-spacing:0.06em; margin-bottom:4px; margin-top:0px;"
)
CAPTION_STYLE = (
    "font-size:0.75rem; color:#94A3B8; "
    "font-family:Inter,-apple-system,sans-serif; margin-bottom:2px;"
)

COINS = ["BTC","ETH","BNB","SOL","XRP","ADA","DOGE","AVAX","DOT","MATIC",
         "LINK","UNI","ATOM","LTC","BCH","NEAR","APT","OP","ARB","FTM"]

def _label(text):
    return f"<div style='{LABEL_STYLE}'>{text}</div>"

def _caption(text):
    return f"<div style='{CAPTION_STYLE}'>{text}</div>"


def _get_engine_from_state(state: dict) -> TradingEngine:
    cfg = state.get("config", {})
    config = TradingConfig(
        coin               = cfg.get("coin", "BTC"),
        lower_price        = cfg.get("lower_price", 0),
        upper_price        = cfg.get("upper_price", 0),
        total_investment   = cfg.get("total_investment", 10000),
        num_grids          = cfg.get("num_grids", DEFAULT_NUM_GRIDS),
        grid_mode          = cfg.get("grid_mode", DEFAULT_GRID_MODE),
        fee_rate           = cfg.get("fee_rate", DEFAULT_FEE_RATE),
        reserve_pct        = cfg.get("reserve_pct", DEFAULT_RESERVE_PCT),
        stop_loss_pct      = cfg.get("stop_loss_pct"),
        enable_recentering = cfg.get("enable_recentering", False),
        interval           = cfg.get("interval", "1h"),
        mode               = "paper",
    )
    position = state.get("position", {"usdt": config.total_investment, "coin": 0.0})
    broker = PaperBroker(
        initial_usdt = position.get("usdt", config.total_investment),
        initial_coin = position.get("coin", 0.0),
        fee_rate     = config.fee_rate,
    )
    engine = TradingEngine(config, broker)
    engine._load_state()
    engine._running = state.get("is_running", False)
    return engine


def _process_candle(existing_state: dict):
    engine = _get_engine_from_state(existing_state)
    return engine.process_latest_candle()


def _interval_to_seconds(interval: str) -> int:
    mapping = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400}
    return mapping.get(interval, 3600)


def show_paper_trading():

    if "pt_last_process" not in st.session_state:
        st.session_state.pt_last_process = None

    existing_state = load_existing_state()
    is_running     = existing_state.get("is_running", False) if existing_state else False

    # Auto-Refresh
    if is_running:
        cfg_interval = existing_state.get("config", {}).get("interval", "1h") if existing_state else "1h"
        refresh_ms   = _interval_to_seconds(cfg_interval) * 1000
        try:
            from streamlit_autorefresh import st_autorefresh
            st_autorefresh(interval=refresh_ms, key="pt_autorefresh")
        except ImportError:
            pass

        # Auto-Verarbeitung
        last = st.session_state.pt_last_process
        now  = datetime.now()
        interval_sec = _interval_to_seconds(cfg_interval)
        if last is None or (now - last).seconds >= interval_sec:
            result = _process_candle(existing_state)
            if not result.get("error"):
                st.session_state.pt_last_process = now
                existing_state = load_existing_state()

    # -----------------------------------------------------------------------
    # Sidebar
    # -----------------------------------------------------------------------
    st.sidebar.markdown(_label("Coin"), unsafe_allow_html=True)
    coin_mode = st.sidebar.radio("", ["Aus Liste", "Eigene Eingabe"],
                                  horizontal=True, key="pt_coin_mode")
    if coin_mode == "Aus Liste":
        default_coin_idx = 0
        if "bt_coin" in st.session_state and st.session_state["bt_coin"] in COINS:
            default_coin_idx = COINS.index(st.session_state["bt_coin"])
        coin = st.sidebar.selectbox("", COINS, index=default_coin_idx,
                                     label_visibility="collapsed", key="pt_coin")
    else:
        coin = st.sidebar.text_input("", value="BTC", label_visibility="collapsed",
                                      key="pt_coin_input").upper().strip()

    st.sidebar.markdown("<div style='margin-top:12px'></div>", unsafe_allow_html=True)
    st.sidebar.markdown(_label("Intervall"), unsafe_allow_html=True)
    interval = st.sidebar.radio("", ["1m","5m","15m","1h","4h"],
                                  index=3, horizontal=True,
                                  key="pt_interval", label_visibility="collapsed")

    st.sidebar.markdown("<div style='margin-top:12px'></div>", unsafe_allow_html=True)
    st.sidebar.markdown(_label("Startkapital"), unsafe_allow_html=True)
    total_investment = float(st.sidebar.number_input(
        "", min_value=100.0, max_value=1_000_000.0, value=10_000.0, step=500.0,
        label_visibility="collapsed", key="pt_capital"
    ))

    st.sidebar.markdown("<div style='margin-top:12px'></div>", unsafe_allow_html=True)
    st.sidebar.markdown(_label("Grid-Parameter"), unsafe_allow_html=True)

    current_price, lower_s, upper_s = None, None, None
    try:
        df_tmp, _ = get_price_data(coin, days=14, interval="1h")
        if df_tmp is not None and not df_tmp.empty:
            current_price = float(df_tmp["close"].iloc[-1])
            lower_s, upper_s, _ = suggest_grid_range(df_tmp, current_price)
    except Exception:
        pass
    current_price = current_price or 68000.0
    lower_s  = lower_s  or current_price * 0.80
    upper_s  = upper_s  or current_price * 1.20
    step_val = float(round(current_price * 0.01, 2))

    pct_lower_default = round((current_price - lower_s) / current_price * 100, 1)
    pct_upper_default = round((upper_s - current_price) / current_price * 100, 1)

    st.sidebar.markdown(
        f"<div style='font-size:0.75rem; color:#94A3B8; margin-bottom:4px;'>"
        f"Aktueller Preis: <b style='color:#E2E8F0'>{current_price:,.2f} USDT</b><br>"
        f"Vorschlag: {lower_s:,.0f} (−{pct_lower_default:.0f}%) – "
        f"{upper_s:,.0f} (+{pct_upper_default:.0f}%)"
        f"</div>", unsafe_allow_html=True
    )

    pct_mode = st.sidebar.checkbox("Preisgrenzen prozentual", value=False, key="pt_pct_mode")
    if pct_mode:
        c1, c2 = st.sidebar.columns(2)
        with c1:
            st.markdown(_caption("Untere (%)"), unsafe_allow_html=True)
            pct_lower_val = st.number_input("", 1.0, 50.0, pct_lower_default, 1.0,
                                             key="pt_pct_lower", label_visibility="collapsed")
        with c2:
            st.markdown(_caption("Obere (%)"), unsafe_allow_html=True)
            pct_upper_val = st.number_input("", 1.0, 50.0, pct_upper_default, 1.0,
                                             key="pt_pct_upper", label_visibility="collapsed")
        lower_price = round(current_price * (1 - pct_lower_val / 100), 2)
        upper_price = round(current_price * (1 + pct_upper_val / 100), 2)
        st.sidebar.caption(f"→ {lower_price:,.2f} – {upper_price:,.2f} USDT")
    else:
        c1, c2 = st.sidebar.columns(2)
        with c1:
            st.markdown(_caption("Untere ($)"), unsafe_allow_html=True)
            lower_price = st.number_input("", min_value=0.001,
                                           value=float(round(lower_s, 2)),
                                           step=step_val, key="pt_lower",
                                           label_visibility="collapsed")
        with c2:
            st.markdown(_caption("Obere ($)"), unsafe_allow_html=True)
            upper_price = st.number_input("", min_value=0.001,
                                           value=float(round(upper_s, 2)),
                                           step=step_val, key="pt_upper",
                                           label_visibility="collapsed")

    col_gl, col_gv = st.sidebar.columns([3, 1])
    with col_gl:
        st.markdown(_caption("Anzahl Grids"), unsafe_allow_html=True)
    with col_gv:
        st.markdown(
            f"<div style='text-align:right; color:#3B82F6; font-weight:600;'>"
            f"{st.session_state.get('pt_grids', DEFAULT_NUM_GRIDS)}</div>",
            unsafe_allow_html=True
        )
    num_grids = st.sidebar.number_input(
        "", min_value=1, max_value=100,
        value=st.session_state.get("pt_grids", DEFAULT_NUM_GRIDS),
        step=1, key="pt_grids", label_visibility="collapsed"
    )

    st.sidebar.markdown(_caption("Grid-Modus"), unsafe_allow_html=True)
    st.sidebar.caption("Arithmetic: gleiche Abstände | Geometric: gleiche % Abstände")
    grid_mode = st.sidebar.radio("", ["arithmetic","geometric"],
                                  horizontal=True, key="pt_mode",
                                  label_visibility="collapsed")

    st.sidebar.markdown(_caption("Handelsgebühr (%)"), unsafe_allow_html=True)
    fee_rate = st.sidebar.number_input(
        "", 0.0, 1.0, DEFAULT_FEE_RATE * 100, 0.01,
        format="%.3f", key="pt_fee", label_visibility="collapsed"
    ) / 100

    st.sidebar.divider()
    st.sidebar.markdown(_label("Erweiterte Einstellungen"), unsafe_allow_html=True)
    st.sidebar.markdown(_caption("Kapitalreserve (%)"), unsafe_allow_html=True)
    reserve_pct = st.sidebar.slider("", 0.0, 20.0, DEFAULT_RESERVE_PCT * 100, 1.0,
                                     key="pt_reserve", label_visibility="collapsed") / 100
    sl_enabled = st.sidebar.checkbox("Stop-Loss aktivieren", value=False, key="pt_sl")
    stop_loss_pct = None
    if sl_enabled:
        st.sidebar.markdown(_caption("Stop-Loss (%)"), unsafe_allow_html=True)
        stop_loss_pct = st.sidebar.slider("", 5.0, 50.0, 20.0, 5.0,
                                           key="pt_sl_pct",
                                           label_visibility="collapsed") / 100
    enable_recentering = st.sidebar.checkbox("Recentering aktivieren",
                                              value=False, key="pt_recenter")

    # -----------------------------------------------------------------------
    # Header
    # -----------------------------------------------------------------------
    st.markdown("# 📄 Paper Trading")

    if is_running and existing_state:
        cfg   = existing_state.get("config", {})
        since = existing_state.get("start_time", "")[:16].replace("T", " ")
        iv    = cfg.get("interval", "1h")
        refresh_label = {"1m":"1 Minute","5m":"5 Minuten","15m":"15 Minuten",
                         "1h":"1 Stunde","4h":"4 Stunden"}.get(iv, iv)
        st.markdown(
            f"<div style='background:rgba(52,211,153,0.1); border-left:3px solid #34D399; "
            f"padding:10px 14px; border-radius:4px; margin-bottom:4px;'>"
            f"<span style='color:#34D399; font-weight:700;'>● AKTIV</span> "
            f"<span style='color:#94A3B8;'>{cfg.get('coin','')}/USDT · "
            f"{iv} · gestartet {since}</span>"
            f"</div>",
            unsafe_allow_html=True
        )
        st.caption(f"⏱️ Preis wird automatisch alle {refresh_label} aktualisiert.")
    else:
        st.markdown(
            "<div style='background:rgba(248,113,113,0.1); border-left:3px solid #F87171; "
            "padding:10px 14px; border-radius:4px; margin-bottom:12px;'>"
            "<span style='color:#F87171; font-weight:700;'>● INAKTIV</span> "
            "<span style='color:#94A3B8;'>Kein Bot läuft – konfiguriere und starte unten</span>"
            "</div>",
            unsafe_allow_html=True
        )

    st.divider()

    # -----------------------------------------------------------------------
    # Steuerung
    # -----------------------------------------------------------------------
    col_start, col_update, col_stop = st.columns([2, 2, 1])

    with col_start:
        if st.button("▶ Bot starten", type="primary",
                     use_container_width=True, disabled=is_running, key="pt_start"):
            if lower_price >= upper_price:
                st.error("Lower muss kleiner als Upper sein!")
            else:
                config = TradingConfig(
                    coin=coin, lower_price=lower_price, upper_price=upper_price,
                    total_investment=total_investment, num_grids=num_grids,
                    grid_mode=grid_mode, fee_rate=fee_rate, reserve_pct=reserve_pct,
                    stop_loss_pct=stop_loss_pct, enable_recentering=enable_recentering,
                    interval=interval, mode="paper",
                )
                broker = PaperBroker(initial_usdt=total_investment, fee_rate=fee_rate)
                engine = TradingEngine(config, broker)
                result = engine.start(resume=False)
                if result.get("error"):
                    st.error(f"Fehler: {result['error']}")
                else:
                    st.session_state.pt_last_process = datetime.now()
                    st.success(f"✅ Bot gestartet @ {result.get('initial_price',0):,.2f} USDT")
                    st.rerun()

    with col_update:
        if st.button("🔄 Preis aktualisieren", use_container_width=True,
                     disabled=not is_running, key="pt_update"):
            if existing_state:
                with st.spinner("Verarbeite letzte Kerze..."):
                    result = _process_candle(existing_state)
                if result.get("error"):
                    st.error(f"Fehler: {result['error']}")
                else:
                    st.session_state.pt_last_process = datetime.now()
                    st.success(
                        f"✅ Kurs: {result['current_price']:,.2f} · "
                        f"ROI: {result['roi_pct']:+.2f}% · "
                        f"Neue Trades: {len(result.get('new_trades',[]))}"
                    )
                    st.rerun()

    with col_stop:
        if st.button("⏹ Stop", use_container_width=True,
                     disabled=not is_running, key="pt_stop"):
            if existing_state:
                engine = _get_engine_from_state(existing_state)
                result = engine.stop()
                clear_state()
                st.session_state.pt_last_process = None
                st.warning(
                    f"Bot gestoppt · ROI: {result.get('roi_pct',0):+.2f}% · "
                    f"Trades: {result.get('num_trades',0)}"
                )
                st.rerun()

    # -----------------------------------------------------------------------
    # Live-Metriken
    # -----------------------------------------------------------------------
    if is_running and existing_state:
        st.markdown("<div style='margin-top:16px'></div>", unsafe_allow_html=True)

        cfg          = existing_state.get("config", {})
        position     = existing_state.get("position", {})
        daily_values = existing_state.get("daily_values", {})
        trade_log    = existing_state.get("trade_log", [])
        last_price   = existing_state.get("last_price", 0)
        last_update  = existing_state.get("last_update", "")[:16].replace("T", " ")
        num_candles  = existing_state.get("num_candles", 0)
        start_time   = existing_state.get("start_time", "")[:16].replace("T", " ")
        initial_price = existing_state.get("initial_price", last_price)

        usdt_bal      = position.get("usdt", 0)
        coin_bal      = position.get("coin", 0)
        portfolio_val = usdt_bal + coin_bal * last_price
        initial       = cfg.get("total_investment", 10000)
        roi_pct       = (portfolio_val - initial) / initial * 100 if initial > 0 else 0
        bh_roi        = ((last_price - initial_price) / initial_price * 100
                         if initial_price > 0 else 0)
        outperformance = roi_pct - bh_roi

        # Gewinn/Verlust absolut
        pnl_abs = portfolio_val - initial

        # Max Drawdown
        dd_pct = 0.0
        if daily_values:
            vals = list(daily_values.values())
            peak = vals[0]
            for v in vals:
                peak = max(peak, v)
                dd   = (peak - v) / peak * 100 if peak > 0 else 0
                dd_pct = max(dd_pct, dd)

        # Zeile 1: Hauptmetriken
        col1, col2, col3, col4, col5, col6 = st.columns(6)
        col1.metric("Portfolio-Wert",    f"${portfolio_val:,.2f}", f"{roi_pct:+.2f}%")
        col2.metric("Aktueller Kurs",    f"${last_price:,.2f}",
                    f"{((last_price-initial_price)/initial_price*100):+.2f}% seit Start")
        col3.metric("USDT Balance",      f"${usdt_bal:,.2f}")
        col4.metric("Coin Balance",
                    f"{coin_bal:.6f}",
                    f"≈ ${coin_bal*last_price:,.2f}")
        col5.metric("Trades gesamt",     len(trade_log))
        col6.metric("Kerzen",            num_candles)

        # Zeile 2: Erweiterte Kennzahlen
        st.markdown("<div style='margin-top:8px'></div>", unsafe_allow_html=True)
        col7, col8, col9, col10, col11, col12 = st.columns(6)
        col7.metric("G/V absolut",       f"${pnl_abs:+,.2f}")
        col8.metric("Grid-ROI",          f"{roi_pct:+.2f}%")
        col9.metric("Buy & Hold ROI",    f"{bh_roi:+.2f}%")
        col10.metric("Outperformance",   f"{outperformance:+.2f}%",
                     help="Grid-ROI minus Buy&Hold-ROI")
        col11.metric("Max. Drawdown",    f"{dd_pct:.2f}%")
        col12.metric("Startkapital",     f"${initial:,.0f}")

        st.caption(
            f"Gestartet: {start_time} · "
            f"Letzte Aktualisierung: {last_update} · "
            f"Startpreis: ${initial_price:,.2f} USDT"
        )

        st.divider()

        tab1, tab2, tab3 = st.tabs(["📈 Chart", "📋 Trade-Log", "⚙️ Konfiguration"])

        with tab1:
            try:
                # Nur 2 Tage laden für bessere Übersicht
                df_chart, _ = get_price_data(
                    cfg.get("coin", "BTC"),
                    interval=cfg.get("interval", "1h"),
                    days=2
                )
                if df_chart is not None and not df_chart.empty:
                    gc = build_grid_config(
                        lower_price = cfg.get("lower_price", 0),
                        upper_price = cfg.get("upper_price", 0),
                        num_grids   = cfg.get("num_grids", 20),
                        mode        = cfg.get("grid_mode", "arithmetic"),
                        fee_rate    = cfg.get("fee_rate", 0.001),
                    )
                    grid_lines = gc.grid_lines if gc else []

                    fig = plot_grid_chart(
                        df           = df_chart,
                        grid_lines   = grid_lines,
                        trade_log    = trade_log,
                        coin         = cfg.get("coin", "BTC"),
                        title        = f"{cfg.get('coin','BTC')}/USDT · Paper Trading",
                        show_volume  = True,
                        show_grid_bg = True,
                        chart_type   = "Candlestick",
                    )

                    # Zoom auf letzten Tag – x-Achse einschränken
                    if len(df_chart) > 0:
                        x_end   = df_chart["timestamp"].iloc[-1] + pd.Timedelta(hours=2)
                        x_start = df_chart["timestamp"].iloc[-1] - pd.Timedelta(hours=46)
                        fig.update_xaxes(range=[x_start, x_end])

                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.info("Keine Chart-Daten verfügbar.")
            except Exception as e:
                st.warning(f"Chart-Fehler: {e}")

        with tab2:
            if trade_log:
                df_trades = pd.DataFrame(trade_log)
                if "timestamp" in df_trades.columns:
                    df_trades["timestamp"] = pd.to_datetime(
                        df_trades["timestamp"], errors="coerce"
                    ).dt.strftime("%d.%m %H:%M")
                # Spalten umbenennen
                rename_map = {
                    "timestamp": "Zeit", "type": "Typ", "price": "Preis",
                    "cprice": "Kurs", "amount": "Menge", "fee": "Gebühr",
                    "profit": "Profit"
                }
                df_trades.rename(columns={k:v for k,v in rename_map.items()
                                          if k in df_trades.columns}, inplace=True)
                st.dataframe(df_trades, use_container_width=True, hide_index=True)
            else:
                st.info("Noch keine Trades – Bot wartet auf Grid-Auslöser.")

        with tab3:
            col_a, col_b = st.columns(2)
            with col_a:
                st.markdown(f"- **Coin:** {cfg.get('coin','–')}/USDT")
                st.markdown(f"- **Intervall:** {cfg.get('interval','–')}")
                st.markdown(f"- **Startkapital:** ${cfg.get('total_investment',0):,.2f}")
                st.markdown(f"- **Grid-Modus:** {cfg.get('grid_mode','–')}")
                st.markdown(f"- **Stop-Loss:** "
                            f"{'Aktiv' if cfg.get('stop_loss_pct') else 'Inaktiv'}")
            with col_b:
                st.markdown(f"- **Anzahl Grids:** {cfg.get('num_grids','–')}")
                st.markdown(f"- **Untere Grenze:** ${cfg.get('lower_price',0):,.2f}")
                st.markdown(f"- **Obere Grenze:** ${cfg.get('upper_price',0):,.2f}")
                st.markdown(f"- **Gebührenrate:** {cfg.get('fee_rate',0)*100:.3f}%")
                st.markdown(f"- **Recentering:** "
                            f"{'Aktiv' if cfg.get('enable_recentering') else 'Inaktiv'}")

    elif not is_running:
        st.markdown(
            "<div style='text-align:center; padding:60px; color:#64748B;'>"
            "<div style='font-size:3rem;'>📄</div>"
            "<div style='font-size:1.1rem; margin-top:12px;'>"
            "Konfiguriere den Bot in der Sidebar und klicke <b>▶ Bot starten</b></div>"
            "<div style='font-size:0.85rem; margin-top:8px; color:#475569;'>"
            "Der Bot aktualisiert sich automatisch je nach gewähltem Intervall</div>"
            "</div>",
            unsafe_allow_html=True
        )

    if is_running:
        st.sidebar.divider()
        st.sidebar.markdown(
            "<div style='font-size:0.75rem; color:#64748B;'>"
            "⏱️ Auto-Refresh aktiv<br>"
            "💾 State wird automatisch gespeichert"
            "</div>",
            unsafe_allow_html=True
        )