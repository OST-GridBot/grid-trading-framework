"""
pages/page_live_trading.py
==========================
Live-Trading-Page nach Phase-3-Migration.

Schlanke Router-Page analog zu page_backtesting / page_paper_trading.
Alle UI-Bausteine kommen aus den in Phase 2 gebauten Komponenten:
    components/portfolio_view.py    Portfolio-Uebersicht
    components/bot_list.py          Bot-Karten-Liste
    components/bot_setup_form.py    Bot-Aufsetzen-Form
    components/bot_detail.py        Detail-Ansicht mit Tabs

LT-spezifisch zusaetzlich:
    Binance API-Verbindungs-Check (BINANCE_API_KEY/SECRET aus .env)
    Wallet-/Portfolio-Anzeige aus dem Binance-Account
    Diese leben weiter direkt in dieser Page, da PT/BT sie nicht
    benoetigen.

Autor: Enes Eryilmaz
Projekt: Grid-Trading-Framework (Bachelorarbeit OST)
"""

import streamlit as st

from src.trading.bot_store     import store as bot_store
from components.bot_view       import bot_view_from_bot_state
from components.portfolio_view import render_portfolio_view
from components.bot_list       import render_bot_list
from components.bot_detail     import render_bot_detail
from components.bot_setup_form import render_bot_setup_form
from components.ui_helpers     import label
from config.settings import (
    MAX_BOTS_PER_MODE,
    BINANCE_API_KEY, BINANCE_SECRET_KEY,
)


# ---------------------------------------------------------------------------
# Binance-API-Hilfsfunktionen (LT-spezifisch, ohne Komponenten-Aequivalent)
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
    """Prueft Binance API Verbindung."""
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


def _show_connection_status() -> None:
    """Zeigt Verbindungsstatus und vollstaendiges Binance-Portfolio."""
    connected, msg = _check_binance_connection()
    bal            = st.session_state.get("lt_balance")

    # ── Zeile 1: API-Status + Laden-Button ──────────────────────────────────
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
        st.markdown(
            "<style>div[data-testid='stButton'] button {white-space:nowrap;}</style>",
            unsafe_allow_html=True
        )
        if st.button("Portfolio aktualisieren", use_container_width=True, key="lt_refresh_bal"):
            st.session_state.lt_balance = _get_binance_balance()
            st.rerun()

    # ── Zeile 2: Portfolio-Tabelle ──────────────────────────────────────────
    if bal is None:
        st.caption("Klicke **Portfolio aktualisieren** um dein Binance-Portfolio zu laden.")
    elif "error" in bal:
        st.error(f"Wallet-Fehler: {bal['error']}")
    else:
        balances = bal.get("balances", {})
        if not balances:
            st.info("Keine Assets mit Guthaben > 0 gefunden.")
        else:
            symbols = list(balances.keys())
            prices  = _get_asset_prices(symbols)
            rows        = []
            total_usdt  = 0.0
            for asset, amount in balances.items():
                price      = prices.get(asset, 0)
                value_usdt = round(amount * price, 2)
                total_usdt += value_usdt
                rows.append({
                    "asset":      asset,
                    "amount":     amount,
                    "price":      price,
                    "value_usdt": value_usdt,
                })
            rows.sort(key=lambda x: x["value_usdt"], reverse=True)

            st.markdown(
                "<div style='font-size:0.7rem; color:#64748B; text-transform:uppercase; "
                "margin-bottom:12px; margin-top:12px;'>Portfolio</div>",
                unsafe_allow_html=True
            )
            cols = st.columns(min(len(rows), 4))
            for i, row in enumerate(rows):
                with cols[i % 4]:
                    color = "#34D399" if row["asset"] == "USDT" else "#60A5FA"
                    pct   = round(row["value_usdt"] / total_usdt * 100, 1) if total_usdt > 0 else 0
                    price_str = (f"${row['price']:,.4f}" if row["price"] < 10
                                 else f"${row['price']:,.2f}")
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

            color_total = ("#34D399" if total_usdt > 100
                           else "#FBBF24" if total_usdt > 10 else "#F87171")
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


# ---------------------------------------------------------------------------
# Navigations-Callbacks (an die neuen Komponenten uebergeben)
# ---------------------------------------------------------------------------

def _lt_back() -> None:
    st.session_state.lt_show_new_bot  = False
    st.session_state.lt_show_overview = False
    st.session_state.lt_selected_bot  = None
    st.rerun()


def _lt_show_new_bot() -> None:
    st.session_state.lt_show_new_bot  = True
    st.session_state.lt_show_overview = False
    st.session_state.lt_selected_bot  = None
    st.rerun()


def _lt_show_overview() -> None:
    st.session_state.lt_show_overview = True
    st.session_state.lt_show_new_bot  = False
    st.session_state.lt_selected_bot  = None
    st.rerun()


def _lt_select_bot(bot_id: str) -> None:
    st.session_state.lt_selected_bot  = bot_id
    st.session_state.lt_show_new_bot  = False
    st.session_state.lt_show_overview = False
    st.rerun()


def _lt_back_to_overview() -> None:
    """Aus Detail-View zurueck zur Bot-Uebersicht (statt Portfolio)."""
    st.session_state.lt_selected_bot   = None
    st.session_state.lt_show_overview  = True
    st.session_state.lt_show_new_bot   = False
    st.rerun()


def _lt_handle_submit(params: dict) -> None:
    """
    Wird von render_bot_setup_form aufgerufen, sobald der User auf
    "Bot starten" klickt. Erstellt einen Live-Trading-Bot und springt
    direkt in die Detail-View.

    Phase Live-1: Vor dem create_bot wird ein Probe-LiveBroker instanziiert.
    Dieser laedt /api/v3/time, /api/v3/exchangeInfo und /api/v3/account und
    prueft Permissions sowie die Konfiguration gegen die Binance-Filter
    (tickSize, minNotional, minQty). Bei Init-Fehler oder Konfig-Verstoss
    wird der Bot NICHT erstellt — User-Feedback per st.error / st.warning.
    """
    name = (params.get("name") or "").strip() or f"{params['coin']}/USDT"
    # create_bot kennt weder "name" noch "period" - rausfiltern
    sim_kwargs = {k: v for k, v in params.items()
                  if k not in ("name", "period")}

    # ── Phase Live-1: Probe-Validierung gegen Binance ───────────────────
    from src.trading.live_broker import LiveBroker
    probe = LiveBroker(
        api_key    = BINANCE_API_KEY,
        api_secret = BINANCE_SECRET_KEY,
        coin       = params["coin"],
        testnet    = False,
    )
    if not probe.init_ok:
        st.error(f"Live-Bot kann nicht erstellt werden: {probe.init_error}")
        return
    # init_warnings werden NICHT mehr per st.warning angezeigt (die wuerden
    # vom st.rerun() in 0.5s ueberschrieben). Stattdessen persistieren wir
    # sie unten in bot["init_warnings"] und rendern sie als gelbes Banner
    # in der Bot-Detail-View, bis User auf "Verstanden" klickt.

    ok, errs = probe.validate_config(
        lower_price      = params["lower_price"],
        upper_price      = params["upper_price"],
        num_grids        = params["num_grids"],
        total_investment = params["total_investment"],
    )
    if not ok:
        for err_msg in errs:
            st.error(f"Konfig-Fehler: {err_msg}")
        return

    bot_id, err = bot_store.create_bot(mode="live", **sim_kwargs)
    if err or bot_id is None:
        st.error(err or "Bot konnte nicht erstellt werden.")
        return
    # Name nachtragen + Init-Warnings persistieren (siehe Banner-Logik in
    # components/bot_detail.render_bot_detail).
    update = {"name": name}
    if probe.init_warnings:
        update["init_warnings"] = list(probe.init_warnings)
    bot_store.update_bot(bot_id, update)
    # W.1: Smart-Setup-Vorschlag aus der Sidebar zuruecksetzen
    from components.bot_setup_form import reset_smart_setup
    reset_smart_setup("live")
    st.session_state.lt_show_new_bot = False
    st.session_state.lt_selected_bot = bot_id
    st.rerun()


# ---------------------------------------------------------------------------
# Haupteinstieg
# ---------------------------------------------------------------------------

def show_live_trading():
    # ── Session-State-Initialisierung ────────────────────────────────────────
    st.session_state.setdefault("lt_selected_bot",  None)
    st.session_state.setdefault("lt_show_new_bot",  False)
    st.session_state.setdefault("lt_show_overview", False)
    st.session_state.setdefault("lt_balance",       None)

    has_api_keys = bool(BINANCE_API_KEY and BINANCE_SECRET_KEY)

    # ── Konfigurations-Mode: Sidebar wird komplett von der Setup-Form
    #    uebernommen. Ansicht-Buttons und Page-Header bleiben unsichtbar.
    #    API-Key-Check kommt davor, damit Setup-Form gar nicht erst geoeffnet
    #    werden kann ohne konfigurierte Keys.
    if st.session_state.lt_show_new_bot:
        if not has_api_keys:
            st.error(
                "⚠️ **Binance API-Key nicht konfiguriert.** "
                "Bitte BINANCE_API_KEY und BINANCE_SECRET_KEY in der .env Datei hinterlegen."
            )
            return
        render_bot_setup_form(
            mode      = "live",
            on_submit = _lt_handle_submit,
            on_back   = _lt_back,
        )
        return

    # ── Bots laden + zu BotViews konvertieren ────────────────────────────────
    bots       = sorted(
        bot_store.get_all_bots(mode="live"),
        key=lambda b: b.get("created_at", ""),
        reverse=True,
    )
    views      = [bot_view_from_bot_state(b) for b in bots]
    bot_count  = len(bots)
    can_create = bot_count < MAX_BOTS_PER_MODE

    # ── Sidebar: Ansicht-Buttons ─────────────────────────────────────────────
    st.sidebar.markdown(label("Ansicht"), unsafe_allow_html=True)
    if st.sidebar.button("📊 Portfolio", use_container_width=True,
                          key="lt_btn_portfolio"):
        _lt_back()
    if st.sidebar.button("＋ Neuen Bot starten", use_container_width=True,
                          disabled=not can_create, key="lt_btn_new"):
        _lt_show_new_bot()
    if not can_create:
        st.sidebar.caption(f"Maximum {MAX_BOTS_PER_MODE} Bots erreicht.")
    if st.sidebar.button(f"Übersicht aktive Bots ({bot_count})",
                          use_container_width=True, key="lt_btn_overview"):
        _lt_show_overview()

    # ── Header ───────────────────────────────────────────────────────────────
    col_titel, col_info = st.columns([8, 1])
    with col_titel:
        st.markdown("# 🔴 Live Trading")
        st.caption(f"{bot_count}/{MAX_BOTS_PER_MODE} Bots aktiv")
    with col_info:
        st.markdown(
            "<div style='margin-top:22px; text-align:right;'>"
            "<span style='color:#64748B; font-size:0.85rem; cursor:default;' "
            "title='Live Trading verwendet echtes Kapital auf Binance. "
            "Orders werden direkt ausgeführt.'>ℹ️ Info</span>"
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

    # ── Router (Detail / Overview / Default) ────────────────────────────────
    if st.session_state.lt_selected_bot:
        bot = bot_store.get_bot(st.session_state.lt_selected_bot)
        if bot:
            view = bot_view_from_bot_state(bot)
            render_bot_detail(view, on_back=_lt_back_to_overview)
            return
        # Bot wurde geloescht oder ID ungueltig
        st.session_state.lt_selected_bot = None

    if st.session_state.lt_show_overview:
        render_bot_list(
            views         = views,
            mode          = "live",
            on_back       = _lt_back,
            on_select_bot = _lt_select_bot,
        )
        return

    # ── Default-View: Connection-Status + Portfolio-Komponente ──────────────
    # Binance-USDT-Guthaben wird via _show_connection_status() / Wallet-Block
    # angezeigt — nicht mehr als Portfolio-Karte.
    _show_connection_status()
    st.markdown("<div style='margin-top:8px'></div>", unsafe_allow_html=True)
    render_portfolio_view(
        views             = views,
        mode              = "live",
        on_new_bot        = _lt_show_new_bot,
        on_show_overview  = _lt_show_overview,
    )
