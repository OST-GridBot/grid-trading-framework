"""
pages/page_backtesting.py
=========================
Backtesting-Seite des Grid-Trading-Frameworks.

Autor: Enes Eryilmaz
Projekt: Grid-Trading-Framework (Bachelorarbeit OST)
"""

import streamlit as st
import pandas as pd
from datetime import date, timedelta

from components.chart import plot_grid_chart, plot_equity_curve, plot_drawdown_chart
from components.metrics_display import render_metrics_row, render_trade_log, render_regime_badge

from src.backtesting.engine import run_backtest
from src.backtesting.optimizer import optimize_num_grids
from src.data.cache_manager import get_price_data
from src.strategy.grid_builder import suggest_grid_range
from config.settings import DEFAULT_NUM_GRIDS, DEFAULT_GRID_MODE, DEFAULT_FEE_RATE, DEFAULT_RESERVE_PCT

COINS = ["BTC","ETH","BNB","SOL","XRP","ADA","DOGE","AVAX","DOT","MATIC",
         "LINK","UNI","ATOM","LTC","BCH","NEAR","APT","OP","ARB","FTM"]


def show_backtesting():
    """Rendert die komplette Backtesting-Seite."""

    # Session State
    if "bt_result" not in st.session_state:
        st.session_state.bt_result = None
    if "bt_df" not in st.session_state:
        st.session_state.bt_df = None

    # -----------------------------------------------------------------------
    # Sidebar
    # -----------------------------------------------------------------------
    st.sidebar.divider()

    # Coin
    st.sidebar.subheader("Coin")
    coin_mode = st.sidebar.radio("", ["Aus Liste","Eigene Eingabe"],
                                 horizontal=True, key="bt_coin_mode")
    if coin_mode == "Aus Liste":
        coin = st.sidebar.selectbox("", COINS, label_visibility="collapsed", key="bt_coin")
    else:
        coin = st.sidebar.text_input("", value="BTC", label_visibility="collapsed",
                                     key="bt_coin_input").upper().strip()

    # Intervall
    st.sidebar.subheader("Intervall")
    interval = st.sidebar.radio("", ["1m","5m","15m","1h","4h","1d"],
                                 index=3, horizontal=True, key="bt_interval",
                                 label_visibility="collapsed")

    # Zeitraum
    st.sidebar.subheader("Zeitraum")
    col_d1, col_d2 = st.sidebar.columns(2)
    with col_d1:
        start_date = st.date_input("Von", value=date.today() - timedelta(days=30), key="bt_start")
    with col_d2:
        end_date = st.date_input("Bis", value=date.today(), key="bt_end")
    if start_date >= end_date:
        st.sidebar.error("Startdatum muss vor Enddatum liegen!")
    days = max(1, (end_date - start_date).days)
    st.sidebar.caption(f"→ {days} Tage")

    # Startkapital
    st.sidebar.subheader("Startkapital")
    total_investment = float(st.sidebar.number_input(
        "", min_value=100.0, max_value=1_000_000.0,
        value=10_000.0, step=500.0, label_visibility="collapsed", key="bt_capital"
    ))

    # Grid-Parameter
    st.sidebar.subheader("Grid-Parameter")
    current_price, lower_s, upper_s = None, None, None
    try:
        df_tmp, _ = get_price_data(coin, days=14, interval="1h")
        if df_tmp is not None and not df_tmp.empty:
            current_price = float(df_tmp["close"].iloc[-1])
            lower_s, upper_s, _ = suggest_grid_range(df_tmp, current_price)
    except Exception:
        pass
    current_price = current_price or 68000.0
    lower_s  = lower_s  or current_price * 0.85
    upper_s  = upper_s  or current_price * 1.15
    step_val = float(round(current_price * 0.01, 2))
    st.sidebar.caption(f"Aktueller Preis: **{current_price:,.2f} USDT** | Vorschlag: {lower_s:,.0f} – {upper_s:,.0f}")

    c1, c2 = st.sidebar.columns(2)
    with c1:
        lower_price = st.number_input("Lower ($)", min_value=0.001,
                                      value=float(round(lower_s, 2)),
                                      step=step_val, key="bt_lower")
    with c2:
        upper_price = st.number_input("Upper ($)", min_value=0.001,
                                      value=float(round(upper_s, 2)),
                                      step=step_val, key="bt_upper")

    num_grids = st.sidebar.slider("Anzahl Grids", 5, 100, DEFAULT_NUM_GRIDS, 5, key="bt_grids")
    grid_mode = st.sidebar.radio("Grid-Modus", ["arithmetic","geometric"],
                                  horizontal=True, key="bt_mode")
    fee_rate  = st.sidebar.number_input("Gebührenrate (%)", 0.0, 1.0,
                                        DEFAULT_FEE_RATE * 100, 0.01,
                                        format="%.3f", key="bt_fee") / 100

    with st.sidebar.expander("Erweiterte Einstellungen"):
        reserve_pct = st.slider("Kapitalreserve (%)", 0.0, 20.0,
                                 DEFAULT_RESERVE_PCT * 100, 1.0, key="bt_reserve") / 100
        sl_enabled = st.checkbox("Stop-Loss aktivieren", value=False, key="bt_sl")
        stop_loss_pct = None
        if sl_enabled:
            stop_loss_pct = st.slider("Stop-Loss (%)", 5.0, 50.0, 20.0, 5.0, key="bt_sl_pct") / 100
        enable_recentering = st.checkbox("Recentering aktivieren", value=False, key="bt_recenter")
        recenter_threshold = 0.05
        if enable_recentering:
            recenter_threshold = st.slider("Recentering-Schwelle (%)", 1.0, 20.0, 5.0, 1.0,
                                            key="bt_recenter_thr") / 100

    # -----------------------------------------------------------------------
    # Header
    # -----------------------------------------------------------------------
    col_title, col_btn = st.columns([5, 1])
    with col_title:
        st.markdown("# 📊 backtesting")
        st.caption(f"{coin}/USDT · {interval} · {start_date} – {end_date} ({days}d) · {total_investment:,.0f} USDT")
    with col_btn:
        st.markdown("<div style='margin-top:20px'>", unsafe_allow_html=True)
        run_btn = st.button("▶ Simulation starten", type="primary", use_container_width=True)

    st.divider()

    # Preisdaten immer laden
    with st.spinner(f"Lade {coin}/USDT Preisdaten..."):
        df_chart, _ = get_price_data(coin, interval=interval,
                                     start_date=start_date, end_date=end_date)
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

    # -----------------------------------------------------------------------
    # Ergebnisse
    # -----------------------------------------------------------------------
    result = st.session_state.bt_result
    df     = st.session_state.bt_df

    if result and not result.get("error"):
        regime = result.get("regime")
        if regime and hasattr(regime, "regime"):
            render_regime_badge(regime.regime, getattr(regime, "confidence", 0))
            st.markdown("<div style='margin-bottom:12px'></div>", unsafe_allow_html=True)

        metrics_dict = {
            "roi_pct":        result.get("profit_pct", 0),
            "sharpe":         result.get("sharpe_ratio", 0),
            "max_dd_pct":     result.get("max_drawdown_pct", 0),
            "num_trades":     result.get("num_trades", 0),
            "bh_roi_pct":     result.get("price_change_pct", 0),
            "outperformance": (result.get("profit_pct") or 0) - (result.get("price_change_pct") or 0),
            "cagr_pct":       result.get("cagr", 0),
            "calmar":         result.get("calmar_ratio", 0),
            "win_rate":       result.get("win_rate", 0),
            "profit_factor":  result.get("profit_factor", 0),
            "fees_paid":      result.get("fees_paid", 0),
        }
        render_metrics_row(metrics_dict, mode="backtest")
        st.markdown("<div style='margin-top:16px'></div>", unsafe_allow_html=True)

    # Tabs
    tab1, tab2, tab3, tab4 = st.tabs(["📈 Chart", "💰 Equity", "📉 Drawdown", "📋 Trades"])
    trade_log    = result.get("trade_log",    []) if result else []
    grid_lines   = result.get("grid_lines",   []) if result else []
    daily_values = result.get("daily_values", {}) if result else {}

    with tab1:
        if df is not None and not df.empty:
            fig = plot_grid_chart(df=df, grid_lines=grid_lines, trade_log=trade_log,
                                  coin=coin, title=f"{coin}/USDT · {interval} · {start_date} – {end_date}")
            st.plotly_chart(fig, use_container_width=True)
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
        st.markdown("### 🔧 Grid-Anzahl optimieren")
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
                key="bt_objective",
            )
        with col_run:
            opt_btn = st.button("🔍 Optimieren", use_container_width=True, key="bt_opt_btn")

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