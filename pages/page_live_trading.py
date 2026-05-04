"""
pages/page_live_trading.py
============================
Multi-Bot Live Trading Page.

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
    MAX_BOTS_PER_MODE, BINANCE_API_KEY, BINANCE_SECRET_KEY,
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


# ---------------------------------------------------------------------------
# Binance API Hilfsfunktionen
# ---------------------------------------------------------------------------

def _get_binance_balance() -> dict:
    """Holt aktuelles Binance-Guthaben."""
    try:
        import hmac, time, hashlib, requests as req
        api_key    = BINANCE_API_KEY
        api_secret = BINANCE_SECRET_KEY
        if not api_key or not api_secret:
            return {"error": "API-Key nicht konfiguriert"}
        ts        = int(time.time() * 1000)
        query     = f"timestamp={ts}"
        signature = hmac.new(api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()
        url       = f"https://api.binance.com/api/v3/account?{query}&signature={signature}"
        headers   = {"X-MBX-APIKEY": api_key}
        resp      = req.get(url, headers=headers, timeout=8)
        data      = resp.json()
        if "code" in data:
            return {"error": data.get("msg", "Binance API Fehler")}
        balances = {}
        for asset in data.get("balances", []):
            free = float(asset["free"])
            if free > 0:
                balances[asset["asset"]] = round(free, 8)
        return {"balances": balances, "usdt": balances.get("USDT", 0.0)}
    except Exception as e:
        return {"error": str(e)}

def _check_binance_connection() -> tuple:
    """Prüft Binance API Verbindung."""
    try:
        import requests as req
        resp = req.get("https://api.binance.com/api/v3/ping", timeout=5)
        return (True, "Verbunden") if resp.status_code == 200 else (False, f"HTTP {resp.status_code}")
    except Exception as e:
        return False, str(e)

def _get_asset_prices(symbols: list) -> dict:
    """Holt aktuelle Preise fuer mehrere Assets von Binance."""
    prices = {}
    try:
        import requests as req
        resp = req.get("https://api.binance.com/api/v3/ticker/price", timeout=5)
        all_prices = {p["symbol"]: float(p["price"]) for p in resp.json()}
        for symbol in symbols:
            if symbol == "USDT":
                prices[symbol] = 1.0
            else:
                key = f"{symbol}USDT"
                if key in all_prices:
                    prices[symbol] = all_prices[key]
    except Exception:
        pass
    return prices


def _show_connection_status():
    """Zeigt Verbindungsstatus und vollstaendiges Binance-Portfolio."""
    connected, msg = _check_binance_connection()
    bal            = st.session_state.get("lt_balance")

    # ── Zeile 1: API-Status + Laden-Button ───────────────────────────────────
    col_api, col_spacer, col_btn = st.columns([3, 2, 2])

    with col_api:
        color_api = "#34D399" if connected else "#F87171"
        icon      = "●" if connected else "✗"
        st.markdown(
            "<div style='padding:10px 14px; background:rgba(255,255,255,0.03); "
            "border:1px solid rgba(255,255,255,0.08); border-radius:8px; display:inline-block;'>"
            "<span style='font-size:0.7rem; color:#64748B; text-transform:uppercase; "
            "letter-spacing:0.05em; margin-right:8px;'>Binance API</span>"
            "<span style='color:" + color_api + "; font-weight:700;'>" + icon + " " + msg + "</span>"
            "</div>",
            unsafe_allow_html=True
        )

    with col_btn:
        st.markdown("<style>div[data-testid='stButton'] button {white-space:nowrap;}</style>", unsafe_allow_html=True)
        if st.button("Portfolio aktualisieren", use_container_width=True, key="lt_refresh_bal"):
            st.session_state.lt_balance = _get_binance_balance()
            st.rerun()

    # ── Zeile 2: Portfolio-Tabelle ────────────────────────────────────────────
    if bal is None:
        st.caption("Klicke **Portfolio aktualisieren** um dein Binance-Portfolio zu laden.")

    elif "error" in bal:
        st.error(f"Wallet-Fehler: {bal['error']}")

    else:
        balances = bal.get("balances", {})
        usdt_val = bal.get("usdt", 0)

        if not balances:
            st.info("Keine Assets mit Guthaben > 0 gefunden.")
        else:
            # Preise laden
            symbols = list(balances.keys())
            prices  = _get_asset_prices(symbols)

            # Portfolio berechnen
            rows        = []
            total_usdt  = 0.0
            for asset, amount in balances.items():
                price      = prices.get(asset, 0)
                value_usdt = round(amount * price, 2)
                total_usdt += value_usdt
                rows.append({
                    "asset":       asset,
                    "amount":      amount,
                    "price":       price,
                    "value_usdt":  value_usdt,
                })
            rows.sort(key=lambda x: x["value_usdt"], reverse=True)

            # Portfolio-Karten
            st.markdown(
                "<div style='font-size:0.7rem; color:#64748B; text-transform:uppercase; "
                "margin-bottom:12px; margin-top:12px;'>Portfolio</div>",
                unsafe_allow_html=True
            )

            cols = st.columns(min(len(rows), 4))
            for i, row in enumerate(rows):
                col_idx = i % 4
                with cols[col_idx]:
                    color = "#34D399" if row["asset"] == "USDT" else "#60A5FA"
                    pct   = round(row["value_usdt"] / total_usdt * 100, 1) if total_usdt > 0 else 0
                    price_str = f"${row['price']:,.4f}" if row['price'] < 10 else f"${row['price']:,.2f}"
                    st.markdown(
                        "<div style='padding:10px 12px; background:rgba(255,255,255,0.03); "
                        "border:1px solid rgba(255,255,255,0.08); border-radius:8px; margin-bottom:8px;'>"
                        "<div style='font-size:0.7rem; color:#64748B; margin-bottom:4px;'>"
                        + row["asset"] +
                        "<span style='color:#374151; margin-left:6px;'>" + str(pct) + "%</span></div>"
                        "<div style='color:" + color + "; font-weight:700; font-size:1rem;'>"
                        "$" + f"{row['value_usdt']:,.2f}" + "</div>"
                        "<div style='color:#64748B; font-size:0.72rem; margin-top:2px;'>"
                        + f"{row['amount']:.6f}".rstrip("0").rstrip(".") + " · " + price_str +
                        "</div></div>",
                        unsafe_allow_html=True
                    )

            # Gesamtwert
            color_total = "#34D399" if total_usdt > 100 else "#FBBF24" if total_usdt > 10 else "#F87171"
            st.markdown(
                "<div style='padding:10px 14px; background:rgba(255,255,255,0.03); "
                "border:1px solid rgba(255,255,255,0.08); border-radius:8px; "
                "display:flex; justify-content:space-between; align-items:center;'>"
                "<span style='color:#94A3B8; font-size:0.85rem;'>Gesamtportfolio</span>"
                "<span style='color:" + color_total + "; font-weight:700; font-size:1.1rem;'>"
                "$" + f"{total_usdt:,.2f}" + " USDT</span>"
                "</div>",
                unsafe_allow_html=True
            )



    st.divider()


def show_live_trading():

    # ── Session State ────────────────────────────────────────────────────────
    if "lt_selected_bot" not in st.session_state:
        st.session_state.lt_selected_bot = None
    if "lt_show_new_bot" not in st.session_state:
        st.session_state.lt_show_new_bot = False
    if "lt_show_overview" not in st.session_state:
        st.session_state.lt_show_overview = False
    if "lt_confirmed" not in st.session_state:
        st.session_state.lt_confirmed = False
    if "lt_balance" not in st.session_state:
        st.session_state.lt_balance = None

    has_api_keys = bool(BINANCE_API_KEY and BINANCE_SECRET_KEY)

    bots        = sorted(bot_store.get_all_bots(mode="live"), key=lambda b: b.get("created_at",""), reverse=True)
    bot_count   = len(bots)
    can_create  = bot_count < MAX_BOTS_PER_MODE

    running_bots = [b for b in bots if b.get("status") == "running"]

    # ── Sidebar ──────────────────────────────────────────────────────────────
    st.sidebar.markdown(_label("Ansicht"), unsafe_allow_html=True)
    if st.sidebar.button("📊 Portfolio",
                          use_container_width=True,
                          key="lt_btn_portfolio"):
        st.session_state.lt_show_new_bot  = False
        st.session_state.lt_selected_bot  = None
        st.session_state.lt_show_overview = False
        st.rerun()

    if st.sidebar.button("＋ Neuen Bot starten",
                          use_container_width=True,
                          disabled=not can_create,
                          key="lt_btn_new"):
        st.session_state.lt_show_new_bot  = True
        st.session_state.lt_selected_bot  = None
        st.session_state.lt_show_overview = False
        st.session_state.lt_confirmed     = False

    if not can_create:
        st.sidebar.caption(f"Maximum {MAX_BOTS_PER_MODE} Bots erreicht.")

    

    running_count = sum(1 for b in bots if b["status"] == "running")
    if st.sidebar.button(
        f"Übersicht aktive Bots ({bot_count})",
        use_container_width=True,
        key="lt_btn_overview"
    ):
        st.session_state.lt_show_overview = True
        st.session_state.lt_show_new_bot  = False
        st.session_state.lt_selected_bot  = None

    # ── Header ───────────────────────────────────────────────────────────────
    col_titel, col_info = st.columns([8, 1])
    with col_titel:
        st.markdown("# 🔴 Live Trading")
        st.caption(f"{bot_count}/{MAX_BOTS_PER_MODE} Bots aktiv")
    with col_info:
        st.markdown(
            "<div style='margin-top:22px; text-align:right;'>"
            "<span style='color:#64748B; font-size:0.85rem; cursor:default;' "
            "title='Live Trading verwendet echtes Kapital auf Binance. Orders werden direkt ausgeführt.'>ℹ️ Info</span>"
            "</div>",
            unsafe_allow_html=True
        )
    st.divider()

    if not has_api_keys:
        st.error(
            "⚠️ **Binance API-Key nicht konfiguriert.** "
            "Bitte BINANCE_API_KEY und BINANCE_SECRET_KEY in der .env Datei hinterlegen."
        )
        return

    # ── Ansicht: Bot-Detailansicht ───────────────────────────────────────────
    if st.session_state.lt_selected_bot:
        bot = bot_store.get_bot(st.session_state.lt_selected_bot)
        if bot:
            _show_bot_detail(bot)
            return
        else:
            st.session_state.lt_selected_bot = None

    # ── Ansicht: Neuen Bot konfigurieren ─────────────────────────────────────
    if st.session_state.lt_show_new_bot:
        _show_new_bot_form()
        return

    # ── Ansicht: Bot-Übersicht ────────────────────────────────────────────────
    if st.session_state.lt_show_overview:
        _show_bots_overview(bots)
        return

    # ── Standard-Ansicht: Portfolio + zwei Aktions-Buttons ───────────────────
    _show_connection_status()

    st.markdown("<div style='margin-top:8px'></div>", unsafe_allow_html=True)
    col_act1, col_act2 = st.columns(2)
    with col_act1:
        if st.button("＋ Neuen Bot starten",
                      use_container_width=True,
                      disabled=not can_create,
                      type="primary",
                      key="lt_main_new"):
            st.session_state.lt_show_new_bot = True
            st.rerun()
        if not can_create:
            st.caption(f"Maximum {MAX_BOTS_PER_MODE} Bots erreicht.")
    with col_act2:
        if st.button(f"Übersicht aktive Bots ({bot_count})",
                      use_container_width=True,
                      key="lt_main_overview"):
            st.session_state.lt_show_overview = True
            st.rerun()


# ---------------------------------------------------------------------------
# Neuen Bot erstellen
# ---------------------------------------------------------------------------

def _show_form_chart(coin: str = "BTC", interval: str = "1h"):
    """Zeigt Chart des gewählten Coins mit gewähltem Intervall."""
    days_map = {"1m": 1, "5m": 1, "15m": 2, "1h": 7, "4h": 14}
    days  = days_map.get(interval, 7)
    force = interval in ("1m", "5m")  # kurze Intervalle immer frisch laden
    try:
        df_chart, _ = get_price_data(coin, days=days, interval=interval, force=force)
        if df_chart is not None and not df_chart.empty:
            df_display = convert_df_timestamps(df_chart)
            plot_grid_chart_v2(
                df           = df_display,
                grid_lines   = [],
                trade_log    = [],
                coin         = coin,
                interval     = interval,
                show_volume  = True,
            )
    except Exception as e:
        st.caption(f"Chart nicht verfügbar: {e}")


def _show_new_bot_form():
    st.markdown("### Neuen Live-Bot konfigurieren")
    st.markdown("<div style='margin-bottom:16px'></div>", unsafe_allow_html=True)

    st.markdown(_label("Bot-Name"), unsafe_allow_html=True)
    bot_name = st.text_input(
        "", placeholder="z.B. BTC Range Bot, ETH Swing...",
        label_visibility="collapsed", key="lt_new_name"
    )
    st.markdown("<div style='margin-top:12px'></div>", unsafe_allow_html=True)

    st.markdown(_label("Coin"), unsafe_allow_html=True)
    coin_mode = st.radio("", ["Aus Liste", "Eigene Eingabe"],
                          horizontal=True, key="lt_new_coin_mode",
                          label_visibility="collapsed")
    if coin_mode == "Aus Liste":
        coin = st.selectbox("", COINS, label_visibility="collapsed", key="lt_new_coin")
    else:
        coin = st.text_input("", value="BTC", label_visibility="collapsed",
                              key="lt_new_coin_input").upper().strip()


    st.markdown("<hr style='border:none; border-top:1px solid rgba(255,255,255,0.08); margin:8px 0;'>", unsafe_allow_html=True)
    st.markdown("<div style='margin-top:12px'></div>", unsafe_allow_html=True)

    st.markdown(_label("Intervall"), unsafe_allow_html=True)
    interval = st.radio("", ["1m","5m","15m","1h","4h"],
                         index=3, horizontal=True, key="lt_new_interval",
                         label_visibility="collapsed")

    # Chart nach Coin + Intervall-Auswahl
    _show_form_chart(coin, interval)

    st.markdown("<div style='margin-top:12px'></div>", unsafe_allow_html=True)

    st.markdown(_label("Startkapital"), unsafe_allow_html=True)
    total_investment = st.number_input(
        "", min_value=100.0, max_value=1_000_000.0,
        value=10000.0, step=500.0,
        label_visibility="collapsed", key="lt_new_capital"
    )
    st.markdown("<div style='margin-top:12px'></div>", unsafe_allow_html=True)
    st.markdown("<hr style='border:none; border-top:1px solid rgba(255,255,255,0.08); margin:8px 0;'>", unsafe_allow_html=True)

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

    st.markdown(
        "<div style='font-size:1.1rem; font-weight:600; color:#94A3B8; "
        "letter-spacing:0.04em; margin-top:6px; margin-bottom:2px;'>Grid-Grenzen</div>",
        unsafe_allow_html=True
    )
    st.markdown(
        f"<div style='font-size:0.75rem; color:#94A3B8; margin-bottom:4px;'>"
        f"Aktueller Preis: <b style='color:#E2E8F0;'>{current_price:,.2f} USDT</b><br>"
        f"Vorschlag: {lower_s:,.2f} (\u221210%) \u2013 {upper_s:,.2f} (+10%)</div>",
        unsafe_allow_html=True
    )

    pct_mode = st.checkbox("Preisgrenzen prozentual setzen", value=False, key="lt_new_pct_mode")
    if pct_mode:
        col_p1, col_p2 = st.columns(2)
        with col_p1:
            st.markdown(_caption("Untere Grenze (%)"), unsafe_allow_html=True)
            pct_lv = st.number_input("", 1.0, 50.0, 10.0, 1.0,
                                      key="lt_new_pct_lower", label_visibility="collapsed")
        with col_p2:
            st.markdown(_caption("Obere Grenze (%)"), unsafe_allow_html=True)
            pct_uv = st.number_input("", 1.0, 50.0, 10.0, 1.0,
                                      key="lt_new_pct_upper", label_visibility="collapsed")
        lower_price = round(current_price * (1 - pct_lv / 100), 2)
        upper_price = round(current_price * (1 + pct_uv / 100), 2)
        st.caption(f"\u2192 {lower_price:,.2f} \u2013 {upper_price:,.2f} USDT")
    else:
        col_g1, col_g2 = st.columns(2)
        with col_g1:
            st.markdown(_caption("Untere Grenze ($)"), unsafe_allow_html=True)
            lower_price = st.number_input("", min_value=0.001,
                                           value=float(lower_s),
                                           step=step_val, key="lt_new_lower",
                                           label_visibility="collapsed")
        with col_g2:
            st.markdown(_caption("Obere Grenze ($)"), unsafe_allow_html=True)
            upper_price = st.number_input("", min_value=0.001,
                                           value=float(upper_s),
                                           step=step_val, key="lt_new_upper",
                                           label_visibility="collapsed")

    st.markdown("<hr style='border:none; border-top:1px solid rgba(255,255,255,0.08); margin:8px 0;'>", unsafe_allow_html=True)

    st.markdown(
        "<div style='font-size:1.1rem; font-weight:600; color:#94A3B8; "
        "letter-spacing:0.04em; margin-top:6px; margin-bottom:2px;'>Anzahl Grids</div>",
        unsafe_allow_html=True
    )
    num_grids = st.number_input(
        "", min_value=2, max_value=100,
        value=st.session_state.get("lt_new_grids", DEFAULT_NUM_GRIDS),
        step=1, key="lt_new_grids", label_visibility="collapsed"
    )

    _fee_preview = st.session_state.get("lt_new_fee", DEFAULT_FEE_RATE * 100) / 100
    try:
        _gstep   = (upper_price - lower_price) / num_grids
        _gprofit = _gstep / upper_price - 2 * _fee_preview
        _gcolor  = "#34D399" if _gprofit > 0 else "#F87171"
        st.markdown(
            f"<div style='margin-top:4px; margin-bottom:4px; padding:6px 10px; "
            f"background:rgba(52,211,153,0.07); border-left:3px solid {_gcolor}; "
            f"border-radius:4px; font-size:0.78rem;'>"
            f"<span style='color:{_gcolor}; font-weight:600;'>Gewinn pro Grid (nach Fees):</span>"
            f"<span style='color:{_gcolor};'> {_gprofit*100:.3f}%</span></div>",
            unsafe_allow_html=True
        )
    except Exception:
        pass

    try:
        if df_tmp_atr is not None:
            from src.analysis.indicators import get_atr_stats
            _atr, _ = get_atr_stats(df_tmp_atr)
            _rng = upper_price - lower_price
            _s05 = max(2, round(_rng / (_atr * 0.5)))
            _s10 = max(2, round(_rng / (_atr * 1.0)))
            _s15 = max(2, round(_rng / (_atr * 1.5)))
            with st.expander("Volatilität\u00e4tsbasierte Vorschl\u00e4ge"):
                st.markdown(
                    f"<div style='font-size:0.75rem; color:#94A3B8;'>"
                    f"<div style='color:#64748B; margin-bottom:6px;'>ATR (14 Kerzen) = "
                    f"<b style='color:#94A3B8;'>{_atr:,.2f} USDT</b></div>"
                    f"<div style='margin-bottom:5px;'><span style='color:#34D399; font-weight:500;'>\u00d7 0.5 \u2192 {_s05} Grids</span><br>"
                    f"<span style='color:#64748B;'>Enger, mehr Trades</span></div>"
                    f"<div style='margin-bottom:5px;'><span style='color:#60A5FA; font-weight:500;'>\u00d7 1.0 \u2192 {_s10} Grids</span><br>"
                    f"<span style='color:#64748B;'>Neutral, empfohlen</span></div>"
                    f"<div><span style='color:#FBBF24; font-weight:500;'>\u00d7 1.5 \u2192 {_s15} Grids</span><br>"
                    f"<span style='color:#64748B;'>Weiter, weniger Trades</span></div>"
                    f"</div>",
                    unsafe_allow_html=True
                )
    except Exception:
        pass

    st.markdown("<hr style='border:none; border-top:1px solid rgba(255,255,255,0.08); margin:8px 0;'>", unsafe_allow_html=True)

    st.markdown(
        "<div style='display:flex;align-items:center;gap:5px;margin-bottom:2px;'>"
        "<span style='font-size:1.1rem;font-weight:600;color:#94A3B8;letter-spacing:0.04em;'>Grid-Modus</span>"
        "<span title='Arithmetisch: gleiche Abst\u00e4nde\nGeometrisch: gleiche % Abst\u00e4nde\nBottom heavy: enger unten\nTop heavy: enger oben' style='cursor:help;color:#94A3B8;'>&#9432;</span></div>",
        unsafe_allow_html=True
    )
    _pt_gm_active = st.radio("", ["Symmetrisch", "Asymmetrisch"], horizontal=True, key="lt_gm_active", label_visibility="collapsed")
    st.markdown(_caption("Symmetrisch"), unsafe_allow_html=True)
    _pt_gm_sym = st.radio("", ["Arithmetisch", "Geometrisch"], horizontal=True, key="lt_gm_sym", disabled=(_pt_gm_active != "Symmetrisch"), label_visibility="collapsed")
    st.markdown(_caption("Asymmetrisch"), unsafe_allow_html=True)
    _pt_gm_asym = st.radio("", ["Bottom heavy", "Top heavy"], horizontal=True, key="lt_gm_asym", disabled=(_pt_gm_active != "Asymmetrisch"), label_visibility="collapsed")
    if _pt_gm_active == "Symmetrisch":
        grid_mode = "arithmetic" if _pt_gm_sym == "Arithmetisch" else "geometric"
    else:
        grid_mode = "asymmetric_bottom" if _pt_gm_asym == "Bottom heavy" else "asymmetric_top"

    st.markdown("<hr style='border:none; border-top:1px solid rgba(255,255,255,0.08); margin:8px 0;'>", unsafe_allow_html=True)

    st.markdown(_label("Risiko & Kapital"), unsafe_allow_html=True)
    st.markdown(_caption("Geb\u00fchrenrate (%)"), unsafe_allow_html=True)
    fee_rate = st.number_input(
        "", 0.0, 1.0, DEFAULT_FEE_RATE * 100, 0.01,
        format="%.3f", key="lt_new_fee", label_visibility="collapsed"
    ) / 100
    st.markdown(_caption("Kapitalreserve (%)"), unsafe_allow_html=True)

    st.markdown(_caption("Kapitalreserve (%)"), unsafe_allow_html=True)
    reserve_pct = st.slider("", 0.0, 20.0, DEFAULT_RESERVE_PCT * 100, 1.0,
                             key="lt_new_reserve", label_visibility="collapsed") / 100
    vo_enabled_pt = st.checkbox("Variable Ordergrössen aktivieren", key="lt_vo")
    enable_variable_orders = vo_enabled_pt
    weight_bottom = 2.0
    weight_top    = 0.5
    if vo_enabled_pt:
        st.markdown(_caption("Gewichtung unten (x)"), unsafe_allow_html=True)
        weight_bottom = st.slider("", 1.0, 5.0, 2.0, 0.1,
                                   key="lt_vo_bottom", label_visibility="collapsed")
        st.markdown(_caption("Gewichtung oben (x)"), unsafe_allow_html=True)
        weight_top = st.slider("", 0.0, 1.0, 0.5, 0.1,
                                key="lt_vo_top", label_visibility="collapsed")
        st.caption(f"Unten: {weight_bottom}x · Oben: {weight_top}x")
    sl_enabled = st.checkbox("Stop-Loss aktivieren", key="lt_new_sl")
    stop_loss_pct = None
    if sl_enabled:
        st.markdown(_caption("Stop-Loss (%)"), unsafe_allow_html=True)
        stop_loss_pct = st.slider("", 5.0, 50.0, 20.0, 5.0,
                                   key="lt_new_sl_pct", label_visibility="collapsed") / 100
    dd_enabled = st.checkbox("Drawdown-Drosselung aktivieren", key="lt_new_dd")
    enable_dd_throttle = dd_enabled
    dd_threshold_1 = 0.10
    dd_threshold_2 = 0.20
    if dd_enabled:
        st.markdown(_caption("Schwelle 1 (%) → 50% Ordergrösse"), unsafe_allow_html=True)
        dd_threshold_1 = st.slider("", 5.0, 30.0, 10.0, 1.0,
                                    key="lt_new_dd_thr1", label_visibility="collapsed") / 100
        st.markdown(_caption("Schwelle 2 (%) → 25% Ordergrösse"), unsafe_allow_html=True)
        dd_threshold_2 = st.slider("", 10.0, 50.0, 20.0, 1.0,
                                    key="lt_new_dd_thr2", label_visibility="collapsed") / 100

    st.markdown("<hr style='border:none; border-top:1px solid rgba(255,255,255,0.08); margin:8px 0;'>", unsafe_allow_html=True)
    st.markdown(_label("Dynamische Grid-Mechanismen"), unsafe_allow_html=True)

    trailing_active_pt = st.session_state.get("lt_trailing", False)
    enable_recentering = st.checkbox(
        "Recentering aktivieren",
        key="lt_new_recenter",
        disabled=trailing_active_pt,
        help="Nicht kombinierbar mit Grid Trailing"
    )
    enable_recentering = enable_recentering and not trailing_active_pt
    recenter_threshold = 0.05
    if enable_recentering:
        st.markdown(_caption("Recentering-Schwelle (%)"), unsafe_allow_html=True)
        recenter_threshold = st.slider("", 1.0, 20.0, 5.0, 1.0,
                                        key="lt_recenter_thr",
                                        label_visibility="collapsed") / 100
    atr_enabled_pt = st.checkbox("Volatilitätätsbasierte Anpassung", key="lt_atr")
    enable_atr_adjust = atr_enabled_pt
    atr_multiplier    = 1.0
    enable_atr_dynamic    = False
    atr_dynamic_threshold = 0.15
    if atr_enabled_pt:
        st.markdown(_caption("ATR-Modus"), unsafe_allow_html=True)
        atr_mode = st.radio(
            "", ["Statisch (einmalig beim Start)", "Dynamisch (pro Kerze)"],
            horizontal=True, key="lt_atr_mode",
            label_visibility="collapsed"
        )
        enable_atr_dynamic = (atr_mode == "Dynamisch (pro Kerze)")
        if enable_atr_dynamic:
            st.markdown(_caption("Anpassungsschwelle (%)"), unsafe_allow_html=True)
            st.caption("Grid nur anpassen wenn ATR um mehr als X% abweicht")
            atr_dynamic_threshold = st.slider(
                "", 5.0, 30.0, 15.0, 1.0,
                key="lt_atr_threshold",
                label_visibility="collapsed"
            ) / 100
        st.markdown(_caption("ATR-Multiplikator"), unsafe_allow_html=True)
        st.caption("Grid-Abstand = ATR × Multiplikator")
        atr_multiplier = st.slider("", 0.5, 5.0, 1.0, 0.1,
                                    key="lt_atr_mult",
                                    label_visibility="collapsed")
    trailing_enabled_pt = st.checkbox("Grid Trailing aktivieren", key="lt_trailing")
    enable_trailing_up   = False
    enable_trailing_down = False
    trailing_up_stop     = None
    trailing_down_stop   = None
    if trailing_enabled_pt:
        enable_trailing_up = st.checkbox("Trailing Up", value=True, key="lt_trailing_up")
        if enable_trailing_up:
            st.markdown(_caption("Trailing Up Stop-Preis ($)"), unsafe_allow_html=True)
            _tus = st.number_input("", min_value=0.0, value=0.0, step=100.0,
                                    key="lt_trailing_up_stop", label_visibility="collapsed")
            trailing_up_stop = _tus if _tus > 0 else None
        enable_trailing_down = st.checkbox("Trailing Down", value=True, key="lt_trailing_down")
        if enable_trailing_down:
            st.markdown(_caption("Trailing Down Stop-Preis ($)"), unsafe_allow_html=True)
            _tds = st.number_input("", min_value=0.0, value=0.0, step=100.0,
                                    key="lt_trailing_down_stop", label_visibility="collapsed")
            trailing_down_stop = _tds if _tds > 0 else None

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
            key="lt_opt_objective",
        )
    with col_opt2:
        opt_days = st.selectbox(
            "Historischer Zeitraum",
            [7, 14, 30],
            index=1,
            format_func=lambda x: f"Letzte {x} Tage",
            key="lt_opt_days",
        )
    with col_opt3:
        st.markdown("<div style='margin-top:28px'></div>", unsafe_allow_html=True)
        opt_btn = st.button("🔍 Vorschlag", use_container_width=True, key="lt_opt_btn")

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
                      use_container_width=True, key="lt_create_bot"):
            if lower_price >= upper_price:
                st.error("Untere Grenze muss kleiner als obere Grenze sein!")
            elif not coin:
                st.error("Bitte einen Coin auswaehlen!")
            else:
                name = bot_name.strip() if bot_name.strip() else f"{coin}/USDT"
                bot_id, err = bot_store.create_bot(
                    mode               = "live",
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
                    st.session_state.lt_show_new_bot  = False
                    st.session_state.lt_selected_bot  = bot_id
                    st.rerun()
    with col_btn2:
        if st.button("Abbrechen", use_container_width=True, key="lt_cancel_new"):
            st.session_state.lt_show_new_bot = False
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
            key="lt_update_all"
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

        # Klickbare Bot-Karte
        if roi < -10:
            st.warning(f"⚠️ Bot **{bot.get('name', bot['coin'])}**: ROI {roi:+.2f}% — starker Verlust!")

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
        if st.button("Details anzeigen", key=f"lt_detail_{bot['bot_id']}", use_container_width=True):
            st.session_state.lt_selected_bot = bot["bot_id"]
            st.rerun()
        st.markdown("<div style='margin-bottom:8px'></div>", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Bot-Detailansicht
# ---------------------------------------------------------------------------

def _show_bot_detail(bot: dict):
    cfg     = bot.get("config", {})
    metrics = bot.get("metrics", {})
    trade_log = bot.get("trade_log", [])
    roi     = metrics.get("roi_pct", 0) or 0
    color   = "#34D399" if roi >= 0 else "#F87171"


    # Header: Bot-Name + Status in einer Zeile, Buttons darunter
    name = bot.get("name", f"{bot['coin']}/USDT Live")
    if roi < -10:
        st.error(f"⚠️ **Starker Verlust:** ROI {roi:+.2f}% — Überprüfe die Marktlage und erwäge Stop-Loss.")
    st.markdown(
        f"<div style='margin-bottom:8px;'>"
        f"<span style='font-size:1.6rem; font-weight:700; color:#E2E8F0;'>{name}</span>"
        f"<span style='font-size:0.85rem; color:#64748B; margin-left:10px;'>"
        f"{bot['coin']}/USDT · {bot['interval']} · ID: {bot['bot_id']}</span>"
        f" &nbsp;&nbsp; {_status_badge(bot['status'])}"
        f"</div>",
        unsafe_allow_html=True
    )

    # Buttons: 3 links + Zurück rechts
    col_b1, col_b2, col_b3, col_back = st.columns([3, 2, 2, 2])
    with col_b1:
        if st.button("Preis aktualisieren", key="lt_det_update",
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
                        # Regime-Warnung
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
        if st.button("Stoppen", key="lt_det_stop",
                      disabled=bot["status"] != "running",
                      use_container_width=True):
            bot_store.set_status(bot["bot_id"], "stopped")
            st.rerun()
    with col_b3:
        if st.button("Löschen", key="lt_det_del",
                      use_container_width=True):
            bot_store.delete_bot(bot["bot_id"])
            st.session_state.lt_selected_bot = None
            st.rerun()
    with col_back:
        if st.button("← Zurück", key="lt_det_back",
                      use_container_width=True):
            st.session_state.lt_selected_bot = None
            st.rerun()


    st.divider()

    # Metriken — gleich wie Backtesting via render_metrics_row
    from components.metrics_display import render_metrics_row
    upnl = metrics.get("unrealized_pnl", {})
    upnl_usdt = upnl.get("usdt", 0) if isinstance(upnl, dict) else 0
    upnl_pct  = upnl.get("pct",  0) if isinstance(upnl, dict) else 0
    runtime   = metrics.get("runtime", {})
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

                plot_grid_chart_v2(
                    df          = df_display,
                    grid_lines  = gc.grid_lines if gc else [],
                    trade_log   = tl_display,
                    coin        = bot["coin"],
                    interval    = bot["interval"],
                    show_volume = True,
                    upper_price = float(gc.grid_lines[-1]) if gc and gc.grid_lines else float(bot["config"]["upper_price"]),
                    lower_price = float(gc.grid_lines[0])  if gc and gc.grid_lines else float(bot["config"]["lower_price"]),
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
            st.markdown(f"- **Grid-Modus:** {cfg.get('grid_mode','–')}")
            st.markdown(f"- **Stop-Loss:** {'Aktiv' if cfg.get('stop_loss_pct') else 'Inaktiv'}")
        with col_b:
            st.markdown(f"- **Anzahl Grids:** {cfg.get('num_grids','–')}")
            st.markdown(f"- **Untere Grenze:** ${cfg.get('lower_price',0):,.2f}")
            st.markdown(f"- **Obere Grenze:** ${cfg.get('upper_price',0):,.2f}")
            st.markdown(f"- **Gebührenrate:** {cfg.get('fee_rate',0)*100:.3f}%")
            _created_mez = _format_ts(bot.get("created_at",""))
            st.markdown(f"- **Erstellt:** {_created_mez}")


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