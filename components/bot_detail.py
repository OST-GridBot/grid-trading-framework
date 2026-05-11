"""
components/bot_detail.py
========================
Render-Komponente fuer die Bot-Detail-Ansicht (BT/PT/LT).

Konsumiert eine BotView (siehe components/bot_view.py) und rendert:
    1. Header (Name, Coin/Intervall/ID/Laufzeit, Status-Badge)
    2. Mode-spezifische Action-Buttons:
        - paper/live:  Preis aktualisieren · Stoppen/Fortfahren · Loeschen · Zurueck
        - backtest:    Loeschen · Zurueck  (Re-Run kommt in Sub 2.8)
    3. render_metrics_tabs (Standard-Metriken aus metrics_display)
    4. Drei Sub-Tabs: Chart · Trade-Log · Configuration  (aus Sub 2.2)

Page-spezifisch wird nur ein on_back-Callback uebergeben (zum Zuruecksetzen
des jeweiligen <mode>_selected_bot-Keys in st.session_state). Alle anderen
Aktionen handhabt die Komponente direkt ueber bot_store / BotRunner.

Autor: Enes Eryilmaz
Projekt: Grid-Trading-Framework (Bachelorarbeit OST)
"""

import time
from typing import Callable, Optional

import streamlit as st

from components.metrics_display    import render_metrics_tabs
from components.tab_chart          import render_tab_chart
from components.tab_trades         import render_tab_trades
from components.tab_configuration  import render_tab_configuration
from src.trading.bot_store         import store as bot_store


# ---------------------------------------------------------------------------
# Status-Badge (oeffentlich, wird auch von bot_list / portfolio_view genutzt)
# ---------------------------------------------------------------------------

_BADGE_COLORS = {
    "running":   "#34D399",
    "stopped":   "#F87171",
    "completed": "#34D399",
    "error":     "#FBBF24",
}
_BADGE_LABELS = {
    "running":   "● LÄUFT",
    "stopped":   "■ GESTOPPT",
    "completed": "✓ ABGESCHLOSSEN",
    "error":     "⚠ FEHLER",
}


def status_badge(status: str) -> str:
    """Status-Pill als HTML-Snippet. Kennt running/stopped/completed/error."""
    color = _BADGE_COLORS.get(status, "#94A3B8")
    label = _BADGE_LABELS.get(status, str(status).upper())
    return (f"<span style='color:{color}; font-weight:700; "
            f"font-size:0.8rem;'>{label}</span>")


# ---------------------------------------------------------------------------
# Hilfsfunktionen (pure)
# ---------------------------------------------------------------------------

def _format_runtime(metrics: dict) -> str:
    """
    Extrahiert die formatierte Laufzeit aus metrics. Defensiv: wenn das
    runtime-Feld kein Dict ist, gibt "–" zurueck.
    """
    rt = metrics.get("runtime")
    if isinstance(rt, dict):
        return rt.get("formatted", "–")
    return "–"


def _regime_attr(regime, key: str, default=None):
    """
    Robustes Auslesen aus einem RegimeResult-Objekt ODER einem dict (nach
    Roundtrip durch JSON / save_backtest).
    """
    if regime is None:
        return default
    if isinstance(regime, dict):
        return regime.get(key, default)
    return getattr(regime, key, default)


# ---------------------------------------------------------------------------
# Modal-Dialog (modulweit definiert, damit Streamlit ihn erkennt)
# ---------------------------------------------------------------------------

@st.dialog("Bot löschen")
def _confirm_delete_dialog(bot_id: str, bot_name: str, on_deleted: Callable[[], None]) -> None:
    """Bestaetigungs-Modal zum Loeschen eines Bots."""
    st.markdown(
        f"<div style='font-size:0.95rem; color:#E2E8F0; margin-bottom:16px;'>"
        f"Soll der Bot <b>{bot_name}</b> wirklich gelöscht werden?<br>"
        f"<span style='color:#94A3B8; font-size:0.85rem;'>"
        f"Diese Aktion kann nicht rückgängig gemacht werden.</span>"
        f"</div>",
        unsafe_allow_html=True
    )
    # Roter Ja-Button via CSS-Override
    st.markdown("""
        <style>
        div[data-testid="stDialog"] div[data-testid="column"]:first-child button {
            background-color: #DC2626 !important;
            border-color: #DC2626 !important;
            color: white !important;
        }
        </style>
    """, unsafe_allow_html=True)
    col_yes, col_no = st.columns(2)
    with col_yes:
        if st.button("Ja, löschen", key=f"bd_del_yes_{bot_id}", use_container_width=True):
            bot_store.delete_bot(bot_id)
            on_deleted()
    with col_no:
        if st.button("Nein", key=f"bd_del_no_{bot_id}", use_container_width=True):
            st.rerun()


# ---------------------------------------------------------------------------
# Render-Bausteine
# ---------------------------------------------------------------------------

def _render_header(view: dict) -> None:
    """Bot-Name + Coin/Intervall/ID/Laufzeit + Status-Badge."""
    name    = view.get("name") or f"{view.get('coin','')}/USDT"
    coin    = view.get("coin", "")
    iv      = view.get("interval", "")
    bid     = view.get("id", "")
    status  = view.get("status", "")
    rt_str  = _format_runtime(view.get("metrics", {}))

    st.markdown(
        f"<div style='margin-bottom:8px;'>"
        f"<span style='font-size:1.6rem; font-weight:700; color:#E2E8F0;'>{name}</span>"
        f"<span style='font-size:0.85rem; color:#64748B; margin-left:10px;'>"
        f"{coin}/USDT · {iv} · ID: {bid} · Laufzeit {rt_str}</span>"
        f" &nbsp;&nbsp; {status_badge(status)}"
        f"</div>",
        unsafe_allow_html=True
    )


def _render_regime_hint(regime) -> None:
    """Kleine farbige Box mit der aktuellen Regime-Klassifikation."""
    name = _regime_attr(regime, "regime")
    if not name:
        return
    colors = {"range": "#34D399", "trend_up": "#F87171",
              "trend_down": "#F87171", "neutral": "#FBBF24"}
    labels = {"range":      "Range-Markt — Grid-Bot geeignet",
              "trend_up":   "Trend aufwärts — Grid-Bot weniger geeignet",
              "trend_down": "Trend abwärts — Grid-Bot weniger geeignet",
              "neutral":    "Unklare Marktlage"}
    rc   = colors.get(name, "#FBBF24")
    rl   = labels.get(name, str(name))
    adx  = _regime_attr(regime, "adx14", 0.0) or 0.0
    conf = _regime_attr(regime, "confidence", 0.0) or 0.0
    st.markdown(
        f"<div style='padding:6px 10px; border-left:3px solid {rc}; "
        f"background:rgba(255,255,255,0.03); border-radius:4px;'>"
        f"<span style='color:{rc}; font-weight:600;'>Regime:</span> "
        f"<span style='color:#E2E8F0; font-size:0.85rem;'>{rl}</span> "
        f"<span style='color:#64748B; font-size:0.75rem;'>"
        f"(ADX14: {adx:.1f} · {conf:.0f}%)</span>"
        f"</div>",
        unsafe_allow_html=True
    )


def _render_actions_running_bot(view: dict, on_back: Callable[[], None]) -> None:
    """Action-Buttons fuer PT/LT-Bots: Update · Stop/Resume · Delete · Back."""
    bid    = view["id"]
    name   = view.get("name") or view.get("coin", "")
    status = view.get("status", "")
    is_running = (status == "running")

    col_upd, col_stop, col_del, col_back = st.columns([3, 2, 2, 2])
    with col_upd:
        if st.button("Preis aktualisieren", key=f"bd_update_{bid}",
                     disabled=not is_running, use_container_width=True):
            from src.trading.engine import BotRunner
            with st.spinner("Verarbeite neue Kerzen..."):
                try:
                    result = BotRunner(bid).run_update()
                    if result.get("error"):
                        st.error(f"Fehler: {result['error']}")
                    else:
                        n = len(result.get("new_trades", []))
                        c = result.get("candles_processed", 0)
                        p = result.get("current_price", 0)
                        st.success(f"Kurs: ${p:,.2f} · {c} Kerzen · {n} neue Trades")
                        _render_regime_hint(result.get("regime"))
                        time.sleep(8)
                        st.rerun()
                except Exception as e:
                    st.error(f"Fehler: {e}")
    with col_stop:
        label = "Stoppen" if is_running else "Fortfahren"
        if st.button(label, key=f"bd_stop_{bid}", use_container_width=True):
            bot_store.set_status(bid, "stopped" if is_running else "running")
            st.rerun()
    with col_del:
        if st.button("Löschen", key=f"bd_del_{bid}", use_container_width=True):
            _confirm_delete_dialog(bid, name, on_back)
    with col_back:
        if st.button("← Zurück", key=f"bd_back_{bid}", use_container_width=True):
            on_back()


def _render_actions_backtest(view: dict, on_back: Callable[[], None]) -> None:
    """Action-Buttons fuer Backtest-Snapshots: Delete · Back. (Re-Run kommt in Sub 2.8.)"""
    bid  = view["id"]
    name = view.get("name") or view.get("coin", "")

    col_del, col_back = st.columns(2)
    with col_del:
        if st.button("Löschen", key=f"bd_del_{bid}", use_container_width=True):
            _confirm_delete_dialog(bid, name, on_back)
    with col_back:
        if st.button("← Zurück", key=f"bd_back_{bid}", use_container_width=True):
            on_back()


# ---------------------------------------------------------------------------
# Hauptfunktion
# ---------------------------------------------------------------------------

def render_bot_detail(view: dict, on_back: Callable[[], None]) -> None:
    """
    Rendert die komplette Bot-Detail-Ansicht.

    Args:
        view    : BotView-Dict (siehe components/bot_view.py)
        on_back : Page-spezifischer Callback. Wird gerufen bei
                  "← Zurueck" sowie nach erfolgreichem Loeschen.
                  Soll den selected_bot-Key in st.session_state
                  zuruecksetzen und st.rerun() ausloesen.
    """
    _render_header(view)

    mode = view.get("mode", "")
    if mode == "backtest":
        _render_actions_backtest(view, on_back)
    else:
        _render_actions_running_bot(view, on_back)

    st.divider()

    # ── Standard-Metriken-Tabs (Performance / Bot Details / Market Data) ────
    # Schicht 2 hat das Standard-Schema bereits in view["metrics"] abgelegt.
    # Fallbacks fuer Felder, die nicht aus calculate_all_metrics kommen:
    metrics = dict(view.get("metrics", {}))
    cfg     = view.get("config", {})
    metrics.setdefault("initial_investment", cfg.get("total_investment", 0))
    if "fees_paid" not in metrics:
        metrics["fees_paid"] = sum(t.get("fee", 0) for t in view.get("trade_log", []))
    render_metrics_tabs(metrics, trade_log=view.get("trade_log", []))

    st.divider()

    # ── Sub-Tabs ────────────────────────────────────────────────────────────
    tab1, tab2, tab3 = st.tabs(["📈 Chart", "📋 Trade-Log", "⚙️ Configuration"])
    with tab1:
        render_tab_chart(view)
    with tab2:
        render_tab_trades(view)
    with tab3:
        render_tab_configuration(view)
