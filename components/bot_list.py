"""
components/bot_list.py
======================
Render-Komponente fuer die Bot-Uebersicht (BT/PT/LT).

Zeigt eine Liste von Bot-Karten mit Kennzahlen (ROI, Trades, Kapital,
Grids, Laufzeit, Einstand) und einem mode-spezifischen Header. Bei PT/LT
zusaetzlich einen "Alle aktualisieren"-Button, der alle laufenden Bots
in einer Schleife ueber BotRunner.run_update aktualisiert.

Konsumiert BotView-Dicts (siehe components/bot_view.py). Die Page
filtert/sortiert vor und reicht die Liste durch.

Autor: Enes Eryilmaz
Projekt: Grid-Trading-Framework (Bachelorarbeit OST)
"""

from typing import Callable

import streamlit as st

from components.bot_detail import status_badge


# ---------------------------------------------------------------------------
# Hilfsfunktionen (pure)
# ---------------------------------------------------------------------------

def _format_ts(ts_str: str) -> str:
    """ISO-Timestamp -> "YYYY-MM-DD HH:MM" in Zurich-Zeit. Robust bei Fehler."""
    try:
        from src.utils.timezone import utc_to_zurich
        import pandas as pd
        ts = utc_to_zurich(pd.Timestamp(ts_str))
        return ts.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(ts_str)[:16].replace("T", " ")


def _format_runtime_short(metrics: dict) -> str:
    """Extrahiert metrics['runtime']['formatted'] mit Fallback '–'."""
    rt = metrics.get("runtime")
    if isinstance(rt, dict):
        return rt.get("formatted", "–")
    return "–"


def _card_data(view: dict) -> dict:
    """
    Extrahiert die Anzeigewerte einer Bot-Karte aus einer BotView.
    Reine Funktion - testbar ohne Streamlit-Runtime.

    Returns:
        Dict mit Schluesseln:
            roi_pct   (float)
            roi_color (str)   "#34D399" bei roi >= 0, sonst "#F87171"
            trades    (int)
            capital   (float)
            grids     (int)
            runtime   (str)   formatierte Laufzeit, "–" bei Fehler
            created   (str)   YYYY-MM-DD HH:MM (Zurich)
    """
    metrics = view.get("metrics", {})
    cfg     = view.get("config", {})
    roi     = metrics.get("roi_pct", 0) or 0
    return {
        "roi_pct":   roi,
        "roi_color": "#34D399" if roi >= 0 else "#F87171",
        "trades":    len(view.get("trade_log", [])),
        "capital":   cfg.get("total_investment", 0),
        "grids":     cfg.get("num_grids", 0),
        "runtime":   _format_runtime_short(metrics),
        "created":   _format_ts(view.get("created_at", "")),
    }


# ---------------------------------------------------------------------------
# Render-Bausteine
# ---------------------------------------------------------------------------

def _render_header_actions(mode: str, views: list, on_back: Callable[[], None]) -> None:
    """Header + Top-Row-Buttons. Mode-spezifisch."""
    # Whitespace im Button-Text vermeiden
    st.markdown(
        "<style>"
        "div[data-testid='stButton'] button p { white-space: nowrap !important; }"
        "</style>",
        unsafe_allow_html=True
    )

    title = ("Übersicht gespeicherte Backtests" if mode == "backtest"
             else "Übersicht aktive Bots")

    col_left, col_right = st.columns([3, 2])
    with col_left:
        st.markdown(f"### {title}")
    with col_right:
        if st.button("← Zurück zum Portfolio", key="bl_back", use_container_width=True):
            on_back()
        if mode in ("paper", "live"):
            running = [v for v in views if v.get("status") == "running"]
            if st.button(
                f"Alle aktualisieren ({len(running)})",
                use_container_width=True,
                disabled=len(running) == 0,
                key="bl_update_all",
            ):
                from src.trading.engine import BotRunner
                errors = []
                for v in running:
                    try:
                        BotRunner(v["id"]).run_update()
                    except Exception as e:
                        errors.append(f"{v['id']}: {e}")
                if errors:
                    st.error("Fehler: " + ", ".join(errors))
                else:
                    st.success(f"✅ {len(running)} Bots aktualisiert")
                st.rerun()


def _render_card(view: dict, on_select_bot: Callable[[str], None]) -> None:
    """Eine Bot-Karte mit Status, Kennzahlen und Details-Button."""
    bid   = view.get("id", "")
    name  = view.get("name") or f"{view.get('coin','')}/USDT"
    coin  = view.get("coin", "")
    iv    = view.get("interval", "")
    stat  = view.get("status", "")

    d = _card_data(view)

    st.markdown(f"""
    <div style="background:rgba(255,255,255,0.03);
                border:1px solid rgba(255,255,255,0.08);
                border-left: 3px solid {d['roi_color']};
                border-radius:8px; padding:14px 18px;
                margin-bottom:4px;">
        <div style="display:flex; justify-content:space-between; align-items:center;">
            <div>
                <span style="font-weight:700; color:#E2E8F0; font-size:1rem;">
                    {name}
                </span>
                <span style="color:#64748B; font-size:0.8rem; margin-left:12px;">
                    {coin}/USDT · {iv} · ID: {bid}
                </span>
            </div>
            {status_badge(stat)}
        </div>
        <div style="display:flex; gap:24px; margin-top:8px;">
            <span style="color:#94A3B8; font-size:0.85rem;">ROI: <b style="color:{d['roi_color']};">{d['roi_pct']:+.2f}%</b></span>
            <span style="color:#94A3B8; font-size:0.85rem;">Trades: <b style="color:#E2E8F0;">{d['trades']}</b></span>
            <span style="color:#94A3B8; font-size:0.85rem;">Kapital: <b style="color:#E2E8F0;">${d['capital']:,.0f}</b></span>
            <span style="color:#94A3B8; font-size:0.85rem;">Grids: <b style="color:#E2E8F0;">{d['grids']}</b></span>
            <span style="color:#94A3B8; font-size:0.85rem;">Laufzeit: <b style="color:#E2E8F0;">{d['runtime']}</b></span>
            <span style="color:#94A3B8; font-size:0.85rem;">Einstand: <b style="color:#E2E8F0;">{d['created']}</b></span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    if st.button("Details anzeigen", key=f"bl_detail_{bid}", use_container_width=True):
        on_select_bot(bid)

    st.markdown("<div style='margin-bottom:8px'></div>", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Hauptfunktion
# ---------------------------------------------------------------------------

def render_bot_list(
    views:         list,
    mode:          str,
    on_back:       Callable[[], None],
    on_select_bot: Callable[[str], None],
) -> None:
    """
    Rendert die Uebersicht aller Bots eines Modus.

    Args:
        views         : Liste von BotView-Dicts (Page filtert/sortiert vor)
        mode          : "backtest" | "paper" | "live"
        on_back       : Callback fuer "← Zurueck"
        on_select_bot : Callback nimmt bot_id, oeffnet Detail-View
    """
    _render_header_actions(mode, views, on_back)
    for view in views:
        _render_card(view, on_select_bot)
