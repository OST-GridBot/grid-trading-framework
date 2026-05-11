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
from components.tab_grid_levels    import render_tab_grid_levels
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

def _format_runtime(view: dict) -> str:
    """
    Formatierte Laufzeit fuer die Detail-View.

    Bei mode="backtest" wird die Sim-Periode aus view["period"]["days"]
    als "Xd" formatiert (es gibt keine sinnvolle Wall-Clock-Laufzeit
    fuer einen gespeicherten Backtest).

    Bei PT/LT wird metrics["runtime"]["formatted"] gelesen (Wall-Clock
    seit Bot-Start, befuellt durch src.analysis.metrics.calculate_runtime).
    """
    if view.get("mode") == "backtest":
        period = view.get("period") or {}
        days = int(period.get("days", 0) or 0)
        return f"{days}d" if days > 0 else "–"
    rt = (view.get("metrics") or {}).get("runtime")
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
    rt_str  = _format_runtime(view)

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
    # Indikatoren (BT-spezifisch in view["indicators"]) ins metrics-Dict mergen,
    # damit Tab "Market Data & Indicators" auch bei BT-Bots Werte zeigt.
    # setdefault statt update -> PT/LT-Werte in metrics bleiben unberuehrt.
    for k, v in (view.get("indicators") or {}).items():
        metrics.setdefault(k, v)
    render_metrics_tabs(metrics, trade_log=view.get("trade_log", []))

    st.divider()

    # ── Sub-Tabs ────────────────────────────────────────────────────────────
    tab1, tab2, tab3, tab4 = st.tabs(
        ["📈 Chart", "📋 Trade-Log", "⚙️ Configuration", "📐 Grid Levels"]
    )
    with tab1:
        render_tab_chart(view)
    with tab2:
        render_tab_trades(view)
    with tab3:
        render_tab_configuration(view)
    with tab4:
        render_tab_grid_levels(view)

    # ── Optimizer (nur Backtest) ───────────────────────────────────────────
    if view.get("mode") == "backtest":
        _render_optimizer_section(view)


# ---------------------------------------------------------------------------
# Optimizer-Block (nur fuer Backtests)
# ---------------------------------------------------------------------------

_OBJECTIVE_LABELS = {
    "maximize_roi":      "ROI",
    "maximize_sharpe":   "Sharpe",
    "maximize_calmar":   "Calmar",
    "minimize_drawdown": "Min. Drawdown",
}

_GRID_MODE_LABELS = {
    "arithmetic":        "Arithmetisch",
    "geometric":         "Geometrisch",
    "asymmetric_bottom": "Bottom Heavy",
    "asymmetric_top":    "Top Heavy",
}


def _recenter_label_from_flags(up: bool, down: bool) -> str:
    if up and down: return "Up + Down"
    if up:          return "Nur Up"
    if down:        return "Nur Down"
    return "Inaktiv"


def _render_optimizer_section(view: dict) -> None:
    """
    Optimizer-Block fuer gespeicherte Backtests. Nimmt Range / Kapital /
    Gebuehrenrate aus der Bot-Config und variiert systematisch
    num_grids, grid_mode und Recentering (Up+Down zusammen).
    """
    cfg      = view.get("config") or {}
    coin     = view.get("coin", "")
    interval = view.get("interval", "1h")
    period   = view.get("period") or {}
    days     = int(period.get("days", 30))
    bid      = view.get("id", "")

    st.divider()
    st.markdown("### Parameter optimieren")
    st.caption(
        "Findet die optimale Kombination aus Anzahl Grids, Grid-Modus und "
        "Recentering bei gleicher Range."
    )

    col_obj, col_run = st.columns([3, 1])
    with col_obj:
        objective = st.radio(
            "Optimierungsziel",
            list(_OBJECTIVE_LABELS.keys()),
            horizontal=True,
            format_func=lambda x: _OBJECTIVE_LABELS.get(x, x),
            key=f"bd_opt_obj_{bid}",
        )
    with col_run:
        opt_btn = st.button("Optimieren", use_container_width=True,
                              key=f"bd_opt_btn_{bid}")

    if not opt_btn:
        return

    # Lazy-Imports: nur wenn der Optimizer wirklich gestartet wird
    from src.data.cache_manager import get_price_data
    from src.backtesting.optimizer import optimize_full_grid_search

    with st.spinner("Optimiere Grid-Parameter (Anzahl, Modus, Recentering)..."):
        try:
            df, _ = get_price_data(coin, days=days, interval=interval)
        except Exception as e:
            st.error(f"Preisdaten konnten nicht geladen werden: {e}")
            return
        if df is None or df.empty:
            st.error("Keine Preisdaten verfügbar.")
            return
        opt = optimize_full_grid_search(
            df               = df,
            lower_price      = float(cfg.get("lower_price", 0)),
            upper_price      = float(cfg.get("upper_price", 0)),
            total_investment = float(cfg.get("total_investment", 10_000.0)),
            fee_rate         = float(cfg.get("fee_rate", 0.001)),
            grid_range       = range(5, 51, 5),
            test_recentering = True,
            objective        = objective,
            interval         = interval,
        )

    if opt.num_tested <= 0:
        st.warning("Optimierung lieferte keine Ergebnisse.")
        return

    best     = opt.best_params
    mode_lbl = _GRID_MODE_LABELS.get(best.get("grid_mode", ""), best.get("grid_mode", ""))
    rc_lbl   = _recenter_label_from_flags(
        bool(best.get("enable_recentering_up")),
        bool(best.get("enable_recentering_down")),
    )

    st.success(
        f"**Beste Parametrisierung gefunden:**\n"
        f"- Anzahl Grids: **{int(best.get('num_grids', 0))}**\n"
        f"- Grid-Modus: **{mode_lbl}**\n"
        f"- Recentering: **{rc_lbl}**\n"
        f"- Untere Grenze: **${best.get('lower_price', 0):,.2f}**\n"
        f"- Obere Grenze: **${best.get('upper_price', 0):,.2f}**\n\n"
        f"ROI: {best.get('roi_pct', 0):+.2f}% | "
        f"Calmar: {best.get('calmar', 0):.2f} | "
        f"Max DD: {best.get('max_dd_pct', 0):.2f}%"
    )

    # Ergebnis-DataFrame
    _df_show = opt.all_results.copy()
    _df_show["grid_mode"] = _df_show["grid_mode"].map({
        "arithmetic": "Arith.", "geometric": "Geom.",
        "asymmetric_bottom": "Bottom", "asymmetric_top": "Top",
    })
    # Optimizer testet Up+Down immer gemeinsam -> eine Spalte reicht.
    _df_show["recentering"] = _df_show["enable_recentering_up"].map({True: "An", False: "Aus"})
    st.dataframe(
        _df_show[["num_grids", "grid_mode", "recentering", "roi_pct",
                  "calmar", "max_dd_pct", "num_trades", "score"]
        ].rename(columns={
            "num_grids":  "Grids",
            "grid_mode":  "Modus",
            "recentering": "Recenter",
            "roi_pct":    "ROI %",
            "calmar":     "Calmar",
            "max_dd_pct": "Max DD %",
            "num_trades": "Trades",
            "score":      "Score",
        }),
        use_container_width=True, hide_index=True,
    )
