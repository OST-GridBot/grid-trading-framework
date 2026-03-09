"""
pages/page_scanner.py
Autor: Enes Eryilmaz – Grid-Trading-Framework (Bachelorarbeit OST)
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from src.scanner.coin_scanner import run_scanner, format_scan_summary
from src.data.cache_manager import get_last_scan_time

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

SCORE_COLORS = {
    4: ("#34D399", "#064E3B"),
    3: ("#34D399", "#064E3B"),
    2: ("#FBBF24", "#78350F"),
    1: ("#F87171", "#7F1D1D"),
    0: ("#F87171", "#7F1D1D"),
}

REGIME_LABELS = {
    "range":      ("✅ Seitwärts",     "#34D399"),
    "trend_up":   ("📈 Aufwärtstrend", "#FBBF24"),
    "trend_down": ("📉 Abwärtstrend",  "#F87171"),
    "unknown":    ("❓ Unbekannt",     "#94A3B8"),
}

# Navigation-Keys exakt wie in Home.py
NAV_KEYS = {
    "backtesting":   "📊  Backtesting",
    "paper_trading": "📄  Paper Trading",
    "live_trading":  "🔴  Live Trading",
}


def _navigate_with_coin(coin: str, page_key: str):
    st.session_state["bt_coin"]         = coin
    st.session_state["nav_redirect"]    = NAV_KEYS[page_key]
    st.rerun()


def show_scanner():
    """Rendert die Coin-Scanner-Seite."""

    if "scanner_results" not in st.session_state:
        st.session_state.scanner_results = None

    # -----------------------------------------------------------------------
    # Sidebar
    # -----------------------------------------------------------------------
    st.sidebar.markdown(_label("Scanner-Einstellungen"), unsafe_allow_html=True)

    st.sidebar.markdown(_caption("Mindest-Score (0–4)"), unsafe_allow_html=True)
    min_score = st.sidebar.slider("", 0, 4, 0, 1,
                                   key="sc_min_score", label_visibility="collapsed")

    st.sidebar.markdown(_caption("Intervall"), unsafe_allow_html=True)
    interval = st.sidebar.radio("", ["1h", "4h", "1d"],
                                 index=0, horizontal=True,
                                 key="sc_interval", label_visibility="collapsed")

    st.sidebar.markdown(_caption("Lookback (Tage)"), unsafe_allow_html=True)
    days = st.sidebar.slider("", 7, 30, 14, 1,
                              key="sc_days", label_visibility="collapsed")

    st.sidebar.divider()
    st.sidebar.markdown(_label("Coin-Liste"), unsafe_allow_html=True)
    coin_source = st.sidebar.radio(
        "", ["Top 100 (CMC)", "Eigene Liste"],
        key="sc_coin_source", label_visibility="collapsed"
    )

    custom_coins = []
    if coin_source == "Eigene Liste":
        st.sidebar.markdown(_caption("Coins (kommagetrennt)"), unsafe_allow_html=True)
        coins_input = st.sidebar.text_area(
            "", value="BTC,ETH,SOL,BNB,XRP",
            key="sc_custom_coins", label_visibility="collapsed"
        )
        custom_coins = [c.strip().upper() for c in coins_input.split(",") if c.strip()]

    force_reload = st.sidebar.checkbox("Cache ignorieren (neu laden)", value=False, key="sc_force")

    # -----------------------------------------------------------------------
    # Header
    # -----------------------------------------------------------------------
    st.markdown("# 🔍 Coin Scanner")

    with st.expander("ℹ️ Wie funktioniert der Scanner?"):
        st.markdown("""
        Der Scanner bewertet Coins anhand ihrer **Grid-Bot-Eignung** auf Basis technischer Indikatoren.

        **📊 Scoring (0–4 Punkte):**
        | Kriterium | Bedingung | Punkte |
        |---|---|---|
        | ADX(14) | < 25 (kein kurzfristiger Trend) | +1 |
        | ADX(30) | < 15 (kein langfristiger Trend) | +1 |
        | ATR (%) | 0.5% – 4.0% (geeignete Volatilität) | +1 |
        | Volumen | > 1 Mio. USDT (genug Liquidität) | +1 |

        **🎯 Interpretation:**
        - ✅ **Score 3–4:** Sehr gut geeignet – Seitwärtsmarkt mit Volumen
        - ⚠️ **Score 2:** Potenziell geeignet – weitere Analyse empfohlen
        - ❌ **Score 0–1:** Nicht geeignet – Trendphase oder zu illiquide
        """)

    try:
        last_scan = get_last_scan_time()
        if last_scan:
            st.caption(f"🕒 Letzter Scan: **{last_scan.strftime('%d.%m.%Y – %H:%M')}**")
    except Exception:
        pass

    st.divider()

    # -----------------------------------------------------------------------
    # Scan starten
    # -----------------------------------------------------------------------
    col_btn, col_info = st.columns([2, 5])
    with col_btn:
        run_btn = st.button("▶ Scan starten", type="primary", use_container_width=True)
    with col_info:
        coins_label = f"{len(custom_coins)} Coins" if custom_coins else "Top 100 Coins (CMC)"
        st.markdown(
            f"<div style='padding-top:8px; color:#94A3B8; font-size:0.9rem;'>"
            f"Scannt: <b style='color:#E2E8F0'>{coins_label}</b> · "
            f"Intervall: <b style='color:#E2E8F0'>{interval}</b> · "
            f"Lookback: <b style='color:#E2E8F0'>{days} Tage</b> · "
            f"Min. Score: <b style='color:#E2E8F0'>{min_score}</b>"
            f"</div>",
            unsafe_allow_html=True
        )

    if run_btn:
        coins_to_scan = custom_coins if custom_coins else None
        progress_bar  = st.progress(0)
        status_text   = st.empty()

        def progress_cb(current, total, coin):
            pct = int(current / total * 100)
            progress_bar.progress(pct)
            status_text.caption(f"Analysiere {coin} ({current}/{total})...")

        with st.spinner("Scanner läuft..."):
            results = run_scanner(
                coins             = coins_to_scan,
                interval          = interval,
                days              = days,
                min_score         = min_score,
                force_reload      = force_reload,
                progress_callback = progress_cb,
            )

        progress_bar.empty()
        status_text.empty()
        st.session_state.scanner_results = results

        if results.empty:
            st.warning("Keine Coins gefunden – versuche einen niedrigeren Mindest-Score.")
        else:
            st.success(f"✅ Scan abgeschlossen – {len(results)} Coins gefunden.")

    # -----------------------------------------------------------------------
    # Ergebnisse
    # -----------------------------------------------------------------------
    results = st.session_state.scanner_results

    if results is not None and not results.empty:

        # Zusammenfassung
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Analysiert",  len(results))
        col2.metric("Score 4 ⭐",  len(results[results["score"] == 4]))
        col3.metric("Score 3 ✅",  len(results[results["score"] == 3]))
        col4.metric("Score 2 ⚠️", len(results[results["score"] == 2]))

        st.divider()

        # Filter
        col_f1, col_f2 = st.columns([3, 2])
        with col_f1:
            filter_regime = st.multiselect(
                "Regime filtern",
                options=["range", "trend_up", "trend_down", "unknown"],
                default=st.session_state.get("sc_filter_regime", ["range", "trend_up", "trend_down", "unknown"]),
                format_func=lambda x: REGIME_LABELS.get(x, (x, ""))[0],
                key="sc_filter_regime"
            )
        with col_f2:
            filter_score = st.slider(
                "Mindest-Score anzeigen", 0, 4, min_score, key="sc_display_score"
            )

        df_filtered = results[
            (results["score"] >= filter_score) &
            (results["regime"].isin(filter_regime) if filter_regime else pd.Series([True] * len(results)))
        ].copy()

        if df_filtered.empty:
            st.info("Keine Coins entsprechen den Filterkriterien.")
        else:
            st.markdown(f"### 📋 Ergebnisse ({len(df_filtered)} Coins)")

            # Tabelle aufbereiten
            display_df = df_filtered[[
                "coin", "score", "regime", "adx14", "adx30",
                "atr_pct", "volume_usdt", "price", "recommendation"
            ]].copy()

            display_df["regime"] = display_df["regime"].map(
                {k: v[0] for k, v in REGIME_LABELS.items()}
            )
            display_df["score"] = display_df["score"].apply(
                lambda s: f"{s}/4 {'★'*int(s)}{'☆'*(4-int(s))}"
            )
            display_df["volume_usdt"] = display_df["volume_usdt"].apply(
                lambda v: f"{v/1e6:.1f}M" if v >= 1e6 else f"{v/1e3:.0f}K"
            )
            display_df["price"] = display_df["price"].apply(
                lambda p: f"{p:,.4f}" if p < 10 else f"{p:,.2f}"
            )
            display_df["recommendation"] = display_df["recommendation"].str.replace(
                "oe", "ö", regex=False
            ).str.replace("ae", "ä", regex=False).str.replace(
                "eingeschraenkt", "Eingeschränkt", regex=False
            )

            display_df.columns = [
                "Coin", "Score", "Regime", "ADX14", "ADX30",
                "ATR%", "Volumen", "Preis", "Empfehlung"
            ]

            st.dataframe(display_df, use_container_width=True, hide_index=True)

            # -----------------------------------------------------------
            # Charts
            # -----------------------------------------------------------
            tab1, tab2 = st.tabs(["📊 Score-Übersicht", "🔥 Heatmap"])

            with tab1:
                top15  = df_filtered.head(15)
                colors = [SCORE_COLORS[s][0] for s in top15["score"]]
                fig = go.Figure(go.Bar(
                    x=top15["coin"],
                    y=top15["score"],
                    marker_color=colors,
                    text=top15["score"],
                    textposition="outside",
                ))
                fig.update_layout(
                    title="Top Coins nach Score",
                    paper_bgcolor="#0F1117",
                    plot_bgcolor="#0F1117",
                    font=dict(color="#94A3B8"),
                    yaxis=dict(range=[0, 4.5], tickvals=[0, 1, 2, 3, 4]),
                    height=350,
                    margin=dict(l=10, r=10, t=40, b=10),
                )
                st.plotly_chart(fig, use_container_width=True)

            with tab2:
                fig2 = px.imshow(
                    [df_filtered["score"].values],
                    labels=dict(x="Coin", color="Score"),
                    x=df_filtered["coin"].tolist(),
                    aspect="auto",
                    color_continuous_scale="YlGnBu",
                    zmin=0, zmax=4,
                )
                fig2.update_layout(
                    title="Heatmap: Grid-Bot Scores",
                    paper_bgcolor="#0F1117",
                    font=dict(color="#94A3B8"),
                    height=220,
                    margin=dict(l=10, r=10, t=40, b=10),
                )
                st.plotly_chart(fig2, use_container_width=True)

            # -----------------------------------------------------------
            # Coin übernehmen – bester Coin als Default
            # -----------------------------------------------------------
            st.divider()
            st.markdown("### 🚀 Coin übernehmen")

            best_coin   = df_filtered.iloc[0]["coin"]
            all_coins   = df_filtered["coin"].tolist()

            selected_coin = st.selectbox(
                "Coin auswählen (vorausgewählt: bester Score)",
                options=all_coins,
                index=0,
                key="sc_select_coin"
            )

            col_bt, col_pt, col_lt = st.columns(3)

            with col_bt:
                if st.button(
                    "📊 Im Backtesting öffnen",
                    key="sc_to_backtest",
                    use_container_width=True,
                    type="primary",
                ):
                    _navigate_with_coin(selected_coin, "backtesting")

            with col_pt:
                if st.button(
                    "📄 Im Paper Trading öffnen",
                    key="sc_to_paper",
                    use_container_width=True,
                ):
                    _navigate_with_coin(selected_coin, "paper_trading")

            with col_lt:
                if st.button(
                    "🔴 Im Live Trading öffnen",
                    key="sc_to_live",
                    use_container_width=True,
                ):
                    _navigate_with_coin(selected_coin, "live_trading")

            st.caption(
                f"Der ausgewählte Coin **{selected_coin}** wird beim Öffnen "
                f"der Zielseite automatisch gesetzt."
            )

    elif results is not None and results.empty:
        st.info("Keine Ergebnisse – starte einen neuen Scan mit angepassten Einstellungen.")
    else:
        st.markdown(
            "<div style='text-align:center; padding:60px; color:#64748B;'>"
            "<div style='font-size:3rem;'>🔍</div>"
            "<div style='font-size:1.1rem; margin-top:12px;'>"
            "Starte einen Scan um Coins zu analysieren</div>"
            "</div>",
            unsafe_allow_html=True
        )