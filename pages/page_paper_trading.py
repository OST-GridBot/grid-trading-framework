"""
pages/page_paper_trading.py
============================
Paper-Trading-Page nach Phase-3-Migration.

Schlanke Router-Page analog zu page_backtesting / page_live_trading.
Alle UI-Bausteine kommen aus den in Phase 2 gebauten Komponenten:
    components/portfolio_view.py    Portfolio-Uebersicht
    components/bot_list.py          Bot-Karten-Liste
    components/bot_setup_form.py    Bot-Aufsetzen-Form
    components/bot_detail.py        Detail-Ansicht mit Tabs

Die Page selbst macht nur:
    - Session-State-Initialisierung
    - Sidebar mit den drei Ansicht-Buttons
    - Router (welche Komponente fuer welchen View)
    - Submit-Callback (bot_store.create_bot + Name-Update)

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
from config.settings           import MAX_BOTS_PER_MODE


# ---------------------------------------------------------------------------
# Navigations-Callbacks (an die neuen Komponenten uebergeben)
# ---------------------------------------------------------------------------

def _pt_back() -> None:
    st.session_state.pt_show_new_bot  = False
    st.session_state.pt_show_overview = False
    st.session_state.pt_selected_bot  = None
    st.rerun()


def _pt_show_new_bot() -> None:
    st.session_state.pt_show_new_bot  = True
    st.session_state.pt_show_overview = False
    st.session_state.pt_selected_bot  = None
    st.rerun()


def _pt_show_overview() -> None:
    st.session_state.pt_show_overview = True
    st.session_state.pt_show_new_bot  = False
    st.session_state.pt_selected_bot  = None
    st.rerun()


def _pt_select_bot(bot_id: str) -> None:
    st.session_state.pt_selected_bot  = bot_id
    st.session_state.pt_show_new_bot  = False
    st.session_state.pt_show_overview = False
    st.rerun()


def _pt_handle_submit(params: dict) -> None:
    """
    Wird von render_bot_setup_form aufgerufen, sobald der User auf
    "Bot starten" klickt. Erstellt einen Paper-Trading-Bot und springt
    direkt in die Detail-View.
    """
    name = (params.get("name") or "").strip() or f"{params['coin']}/USDT"
    # create_bot kennt weder "name" noch "period" - rausfiltern
    sim_kwargs = {k: v for k, v in params.items()
                  if k not in ("name", "period")}
    bot_id, err = bot_store.create_bot(mode="paper", **sim_kwargs)
    if err or bot_id is None:
        st.error(err or "Bot konnte nicht erstellt werden.")
        return
    # Name nachtragen (create_bot speichert keinen Namen)
    bot_store.update_bot(bot_id, {"name": name})
    st.session_state.pt_show_new_bot = False
    st.session_state.pt_selected_bot = bot_id
    st.rerun()


# ---------------------------------------------------------------------------
# Empty-State
# ---------------------------------------------------------------------------

def _show_empty_state() -> None:
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


# ---------------------------------------------------------------------------
# Haupteinstieg
# ---------------------------------------------------------------------------

def show_paper_trading():
    # ── Session-State-Initialisierung ────────────────────────────────────────
    st.session_state.setdefault("pt_selected_bot",  None)
    st.session_state.setdefault("pt_show_new_bot",  False)
    st.session_state.setdefault("pt_show_overview", False)

    # ── Konfigurations-Mode: Sidebar wird komplett von der Setup-Form
    #    uebernommen. Ansicht-Buttons und Page-Header bleiben unsichtbar.
    if st.session_state.pt_show_new_bot:
        render_bot_setup_form(
            mode      = "paper",
            on_submit = _pt_handle_submit,
            on_back   = _pt_back,
        )
        return

    # ── Bots laden + zu BotViews konvertieren ────────────────────────────────
    bots       = sorted(
        bot_store.get_all_bots(mode="paper"),
        key=lambda b: b.get("created_at", ""),
        reverse=True,
    )
    views      = [bot_view_from_bot_state(b) for b in bots]
    bot_count  = len(bots)
    can_create = bot_count < MAX_BOTS_PER_MODE

    # ── Sidebar: Ansicht-Buttons ─────────────────────────────────────────────
    st.sidebar.markdown(label("Ansicht"), unsafe_allow_html=True)
    if st.sidebar.button("📊 Portfolio", use_container_width=True,
                          key="pt_btn_portfolio"):
        _pt_back()
    if st.sidebar.button("＋ Neuen Bot starten", use_container_width=True,
                          disabled=not can_create, key="pt_btn_new"):
        _pt_show_new_bot()
    if not can_create:
        st.sidebar.caption(f"Maximum {MAX_BOTS_PER_MODE} Bots erreicht.")
    if st.sidebar.button(f"Übersicht aktive Bots ({bot_count})",
                          use_container_width=True, key="pt_btn_overview"):
        _pt_show_overview()

    # ── Header ───────────────────────────────────────────────────────────────
    st.markdown("# 📄 Paper Trading")
    st.caption(f"{bot_count}/{MAX_BOTS_PER_MODE} Bots aktiv")
    st.divider()

    # ── Router (Detail / Overview / Empty / Portfolio) ──────────────────────
    if st.session_state.pt_selected_bot:
        bot = bot_store.get_bot(st.session_state.pt_selected_bot)
        if bot:
            view = bot_view_from_bot_state(bot)
            render_bot_detail(view, on_back=_pt_back)
            return
        # Bot wurde geloescht oder ID ungueltig
        st.session_state.pt_selected_bot = None

    if st.session_state.pt_show_overview:
        render_bot_list(
            views         = views,
            mode          = "paper",
            on_back       = _pt_back,
            on_select_bot = _pt_select_bot,
        )
        return

    if not bots:
        _show_empty_state()
        return

    # Default: Portfolio-View
    render_portfolio_view(
        views            = views,
        mode             = "paper",
        on_new_bot       = _pt_show_new_bot,
        on_show_overview = _pt_show_overview,
    )
