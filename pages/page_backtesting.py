"""
pages/page_backtesting.py
=========================
Backtesting-Page nach Phase-2-Umbau.

Struktur analog Paper-/Live-Trading: Portfolio-Uebersicht als Einstieg,
Liste gespeicherter Backtests, Bot-Aufsetzen auf eigener Page, Bot-Detail
mit den Tabs Chart / Trade-Log / Configuration.

Alle UI-Bausteine kommen aus den in Phase 2 gebauten Komponenten:
    components/portfolio_view.py    (Portfolio-Uebersicht)
    components/bot_list.py          (Bot-Karten-Liste)
    components/bot_setup_form.py    (Bot-Aufsetzen-Form)
    components/bot_detail.py        (Detail-Ansicht mit Tabs)

Die Page selbst macht nur:
    - Session-State-Initialisierung
    - Sidebar mit den drei Ansicht-Buttons
    - Router (welche Komponente fuer welchen View)
    - Submit-Callback (run_backtest + bot_store.save_backtest)

Autor: Enes Eryilmaz
Projekt: Grid-Trading-Framework (Bachelorarbeit OST)
"""

from datetime import date

import streamlit as st

from config.settings           import MAX_BACKTESTS
from src.trading.bot_store     import store as bot_store
from src.backtesting.engine    import run_backtest

from components.bot_view       import bot_view_from_bot_state
from components.portfolio_view import render_portfolio_view
from components.bot_list       import render_bot_list
from components.bot_detail     import render_bot_detail
from components.bot_setup_form import render_bot_setup_form


# ---------------------------------------------------------------------------
# Lokale UI-Helper (analog PT/LT)
# ---------------------------------------------------------------------------

def _label(text: str) -> str:
    return (f"<div style='font-size:1.1rem; font-weight:600; color:#94A3B8; "
            f"letter-spacing:0.04em; margin-top:6px; margin-bottom:2px;'>{text}</div>")


# ---------------------------------------------------------------------------
# Navigations-Callbacks
# ---------------------------------------------------------------------------

def _bt_back() -> None:
    """Zurueck zur Portfolio-Uebersicht (alle View-Flags ruecksetzen)."""
    st.session_state.bt_selected_bot  = None
    st.session_state.bt_show_new_bot  = False
    st.session_state.bt_show_overview = False
    st.rerun()


def _bt_show_new_bot() -> None:
    st.session_state.bt_show_new_bot  = True
    st.session_state.bt_selected_bot  = None
    st.session_state.bt_show_overview = False
    st.rerun()


def _bt_show_overview() -> None:
    st.session_state.bt_show_overview = True
    st.session_state.bt_show_new_bot  = False
    st.session_state.bt_selected_bot  = None
    st.rerun()


def _bt_select_bot(bot_id: str) -> None:
    st.session_state.bt_selected_bot  = bot_id
    st.session_state.bt_show_new_bot  = False
    st.session_state.bt_show_overview = False
    st.rerun()


# ---------------------------------------------------------------------------
# Submit-Callback: run_backtest -> save_backtest -> Detail-View
# ---------------------------------------------------------------------------

def _handle_bt_submit(params: dict) -> None:
    """
    Wird von render_bot_setup_form aufgerufen, sobald der User auf
    "Backtest starten" klickt. Fuehrt die Simulation aus, persistiert
    das Ergebnis und springt direkt in die Detail-View des neuen Bots.
    """
    period = params.get("period") or {}
    try:
        start = date.fromisoformat(period["start_date"])
        end   = date.fromisoformat(period["end_date"])
    except Exception:
        st.error("Zeitraum konnte nicht gelesen werden.")
        return

    coin     = params["coin"]
    interval = params["interval"]
    days     = int(period.get("days", 30))

    # Sim-Parameter zusammenstellen (alles ausser den aeusseren Form-Feldern)
    sim_kwargs = {
        k: v for k, v in params.items()
        if k not in ("name", "coin", "interval", "period")
    }

    with st.spinner(f"Simuliere {coin}/USDT {start} – {end}..."):
        result = run_backtest(
            coin       = coin,
            interval   = interval,
            days       = days,
            start_date = start,
            end_date   = end,
            **sim_kwargs,
        )

    if result.get("error"):
        st.error(f"Simulationsfehler: {result['error']}")
        return

    # Persistieren - config enthaelt auch coin/interval, analog PT/LT-Schema
    config = {k: v for k, v in params.items() if k not in ("name", "period")}
    bot_id, err = bot_store.save_backtest(
        name     = params["name"],
        coin     = coin,
        interval = interval,
        period   = params["period"],
        config   = config,
        result   = result,
    )
    if bot_id is None:
        st.error(f"Speicherfehler: {err}")
        return

    # Direkt in Detail-View des neuen Bots
    st.session_state.bt_selected_bot  = bot_id
    st.session_state.bt_show_new_bot  = False
    st.session_state.bt_show_overview = False
    st.rerun()


# ---------------------------------------------------------------------------
# Empty-State
# ---------------------------------------------------------------------------

def _show_empty_state() -> None:
    st.markdown(
        "<div style='text-align:center; padding:60px; color:#64748B;'>"
        "<div style='font-size:3rem;'>📊</div>"
        "<div style='font-size:1.1rem; margin-top:12px; color:#94A3B8;'>"
        "Noch keine Backtests gespeichert</div>"
        "<div style='font-size:0.85rem; margin-top:8px;'>"
        "Klicke <b>＋ Neuen Backtest</b> in der Sidebar</div>"
        "</div>",
        unsafe_allow_html=True
    )


# ---------------------------------------------------------------------------
# Haupteinstieg
# ---------------------------------------------------------------------------

def show_backtesting() -> None:
    # ── Session-State-Initialisierung ────────────────────────────────────────
    st.session_state.setdefault("bt_selected_bot",  None)
    st.session_state.setdefault("bt_show_new_bot",  False)
    st.session_state.setdefault("bt_show_overview", False)

    # ── Konfigurations-Mode: Sidebar wird komplett von der Setup-Form
    #    uebernommen. Ansicht-Buttons und Page-Header bleiben unsichtbar.
    if st.session_state.bt_show_new_bot:
        render_bot_setup_form(
            mode      = "backtest",
            on_submit = _handle_bt_submit,
            on_back   = _bt_back,
        )
        return

    # ── Bots laden + zu BotView konvertieren ─────────────────────────────────
    raw_bots = bot_store.get_all_bots(mode="backtest")
    views    = sorted(
        (bot_view_from_bot_state(b) for b in raw_bots),
        key=lambda v: v.get("created_at", ""),
        reverse=True,
    )
    bot_count  = len(views)
    can_create = bot_count < MAX_BACKTESTS

    # ── Sidebar: Ansicht-Buttons ─────────────────────────────────────────────
    st.sidebar.markdown(_label("Ansicht"), unsafe_allow_html=True)
    if st.sidebar.button("📊 Portfolio", use_container_width=True,
                          key="bt_btn_portfolio"):
        _bt_back()
    if st.sidebar.button("＋ Neuen Backtest", use_container_width=True,
                          disabled=not can_create, key="bt_btn_new"):
        _bt_show_new_bot()
    if not can_create:
        st.sidebar.caption(f"Maximum {MAX_BACKTESTS} Backtests erreicht.")
    if st.sidebar.button(f"Übersicht ({bot_count})", use_container_width=True,
                          key="bt_btn_overview"):
        _bt_show_overview()

    # ── Header ───────────────────────────────────────────────────────────────
    st.markdown("# 📊 Backtesting")
    st.caption(f"{bot_count}/{MAX_BACKTESTS} Backtests")
    st.divider()

    # ── Router (Detail / Overview / Empty / Portfolio) ──────────────────────
    if st.session_state.bt_selected_bot:
        raw = bot_store.get_bot(st.session_state.bt_selected_bot)
        if raw:
            view = bot_view_from_bot_state(raw)
            render_bot_detail(view, on_back=_bt_back)
            return
        # Bot wurde geloescht oder ID ungueltig
        st.session_state.bt_selected_bot = None

    if st.session_state.bt_show_overview:
        render_bot_list(
            views          = views,
            mode           = "backtest",
            on_back        = _bt_back,
            on_select_bot  = _bt_select_bot,
        )
        return

    if not views:
        _show_empty_state()
        return

    # Default: Portfolio-View
    render_portfolio_view(
        views            = views,
        mode             = "backtest",
        on_new_bot       = _bt_show_new_bot,
        on_show_overview = _bt_show_overview,
    )
