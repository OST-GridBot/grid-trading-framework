"""
components/portfolio_view.py
============================
Render-Komponente fuer die Portfolio-Uebersicht (BT/PT/LT).

Zeigt:
    1. Fuenf Metrik-Karten oben (mode-spezifisch)
    2. Eine kompakte Bot-Liste:
        - PT/LT: getrennt nach "Laufende Bots" + "Gestoppte Bots"
        - BT:    eine Liste nach created_at desc, bis 10 Eintraege
    3. Zwei Action-Buttons unten:
       "+ Neuen Bot/Backtest starten"  und  "Uebersicht ... (N)"

Konsumiert BotView-Dicts (siehe components/bot_view.py). Die Page macht
den Adapter-Aufruf vorher und reicht die Liste sortiert durch.

Autor: Enes Eryilmaz
Projekt: Grid-Trading-Framework (Bachelorarbeit OST)
"""

from typing import Callable

import streamlit as st

from config.settings import MAX_BOTS_PER_MODE, MAX_BACKTESTS


# Anzahl Eintraege in der kompakten BT-Liste in der Portfolio-Ansicht
_BT_LIST_LIMIT = 10


# ---------------------------------------------------------------------------
# Summary-Berechnungen (pure, testbar)
# ---------------------------------------------------------------------------

def _avg_outperformance(views: list) -> float:
    """Mittelwert der outperformance_pct ueber alle Views (None-Werte ignorieren)."""
    vals = [
        (v.get("metrics") or {}).get("outperformance_pct")
        for v in views
    ]
    vals = [x for x in vals if x is not None]
    return (sum(vals) / len(vals)) if vals else 0.0


def _compute_summary_running(views: list, max_bots: int) -> dict:
    """
    Berechnet die Portfolio-Kennzahlen fuer PT/LT.

    Args:
        views    : Liste aller BotViews dieses Modus
        max_bots : (heute nur fuers Sidebar-Limit, nicht in den Karten verwendet)

    Returns:
        Dict mit Schluesseln:
            active_count       (int)   Anzahl WIRKLICH aktiver Bots
                                       (status == "running" UND
                                        bot_status != "waiting_for_trigger")
            waiting_count      (int)   Anzahl Bots im Trigger-Warten-Status
                                       (status == "running" UND
                                        bot_status == "waiting_for_trigger")
            max_count          (int)
            best_roi           (float) % - Maximum roi_pct ueber ALLE Views
            worst_roi          (float) % - Minimum roi_pct ueber ALLE Views
            avg_roi            (float) % - Mittelwert roi_pct ueber ALLE Views
            avg_outperformance (float) % - Mittelwert outperformance_pct
                                          ueber ALLE Views

    ROI-Statistiken (best/worst/avg) gehen bewusst ueber alle Views inkl.
    gestoppte Bots — konsistent zu BT und zur bisherigen Outperformance-Logik.
    """
    running       = [v for v in views if v.get("status") == "running"]
    waiting_count = sum(
        1 for v in running if v.get("bot_status") == "waiting_for_trigger"
    )
    active_count  = len(running) - waiting_count

    rois = [
        (v.get("metrics") or {}).get("roi_pct", 0) or 0
        for v in views
    ]
    if rois:
        best  = max(rois)
        worst = min(rois)
        avg   = sum(rois) / len(rois)
    else:
        best = worst = avg = 0.0

    return {
        "active_count":       active_count,
        "waiting_count":      waiting_count,
        "max_count":          max_bots,
        "best_roi":           best,
        "worst_roi":          worst,
        "avg_roi":            avg,
        "avg_outperformance": _avg_outperformance(views),
    }


def _compute_summary_backtest(views: list, max_backtests: int) -> dict:
    """
    Berechnet die Portfolio-Kennzahlen fuer BT.

    Returns:
        Dict mit Schluesseln:
            count              (int)
            max_count          (int)
            best_roi           (float) % - 0 bei leerer Liste
            worst_roi          (float) %
            avg_roi            (float) %
            avg_outperformance (float) % - Mittel der outperformance_pct
    """
    rois = [
        (v.get("metrics") or {}).get("roi_pct", 0) or 0
        for v in views
    ]

    if rois:
        best  = max(rois)
        worst = min(rois)
        avg   = sum(rois) / len(rois)
    else:
        best = worst = avg = 0.0

    return {
        "count":              len(views),
        "max_count":          max_backtests,
        "best_roi":           best,
        "worst_roi":          worst,
        "avg_roi":            avg,
        "avg_outperformance": _avg_outperformance(views),
    }


# ---------------------------------------------------------------------------
# Render-Bausteine
# ---------------------------------------------------------------------------

def _metric_card_html(label: str, value: str, color: str = "#E2E8F0") -> str:
    """Eine Portfolio-Metrik-Karte als HTML (gleiche Optik wie heute in PT)."""
    return (
        f"<div style='background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.08); "
        f"border-radius:8px; padding:14px; text-align:center;'>"
        f"<div style='color:#64748B; font-size:0.75rem; margin-bottom:4px;'>{label}</div>"
        f"<div style='color:{color}; font-size:1.3rem; font-weight:700;'>{value}</div>"
        f"</div>"
    )


def _render_metric_cards_running(summary: dict, count_label: str) -> None:
    """
    Fuenf Metrik-Karten fuer PT/LT (identische Struktur, nur Karte-1-Label
    bleibt variabel falls spaeter doch nochmal unterschieden werden soll).

    Reihenfolge: Active Bots / Best ROI / Worst ROI / Ø ROI /
                 Ø Outperformance B&H.

    Wenn Bots im Trigger-Warte-Status sind, wird die Anzahl in orange als
    Suffix "(M warten)" hinter die Active-Bots-Zahl gehaengt.
    """
    c1, c2, c3, c4, c5 = st.columns(5)
    best, worst, avg = summary["best_roi"], summary["worst_roi"], summary["avg_roi"]
    outperf = summary["avg_outperformance"]
    best_color  = "#34D399" if best    >= 0 else "#F87171"
    worst_color = "#34D399" if worst   >= 0 else "#F87171"
    avg_color   = "#34D399" if avg     >= 0 else "#F87171"
    outp_color  = "#34D399" if outperf >= 0 else "#F87171"

    waiting = summary.get("waiting_count", 0)
    if waiting > 0:
        active_value = (
            f"{summary['active_count']}"
            f" <span style='font-size:0.7rem; color:#FB923C; font-weight:600;'>"
            f"({waiting} warten)</span>"
        )
    else:
        active_value = str(summary['active_count'])

    c1.markdown(_metric_card_html(count_label,              active_value),                                unsafe_allow_html=True)
    c2.markdown(_metric_card_html("Best ROI",               f"{best:+.2f}%",    color=best_color),        unsafe_allow_html=True)
    c3.markdown(_metric_card_html("Worst ROI",              f"{worst:+.2f}%",   color=worst_color),       unsafe_allow_html=True)
    c4.markdown(_metric_card_html("Ø ROI",               f"{avg:+.2f}%",     color=avg_color),         unsafe_allow_html=True)
    c5.markdown(_metric_card_html("Ø Outperformance B&H", f"{outperf:+.2f}%", color=outp_color),       unsafe_allow_html=True)


def _render_metric_cards_paper(summary: dict) -> None:
    """Fuenf Metrik-Karten fuer Paper-Trading."""
    _render_metric_cards_running(summary, count_label="Active Bots")


def _render_metric_cards_live(summary: dict) -> None:
    """
    Fuenf Metrik-Karten fuer Live-Trading. Identisch zu Paper.
    Binance-USDT-Guthaben wird woanders in der LT-Page angezeigt
    (Connection-Status / Wallet-Block), nicht mehr in den Portfolio-Karten.
    """
    _render_metric_cards_running(summary, count_label="Active Bots")


def _render_metric_cards_backtest(summary: dict) -> None:
    """
    Fuenf Metrik-Karten fuer BT.

    Reihenfolge: Historic Bots / Best ROI / Worst ROI / Ø ROI /
                 Ø Outperformance B&H.
    """
    c1, c2, c3, c4, c5 = st.columns(5)
    best, worst, avg = summary["best_roi"], summary["worst_roi"], summary["avg_roi"]
    outperf  = summary["avg_outperformance"]
    best_color  = "#34D399" if best    >= 0 else "#F87171"
    worst_color = "#34D399" if worst   >= 0 else "#F87171"
    avg_color   = "#34D399" if avg     >= 0 else "#F87171"
    outp_color  = "#34D399" if outperf >= 0 else "#F87171"
    c1.markdown(_metric_card_html("Historic Bots",           str(summary['count'])),                     unsafe_allow_html=True)
    c2.markdown(_metric_card_html("Best ROI",                f"{best:+.2f}%",    color=best_color),      unsafe_allow_html=True)
    c3.markdown(_metric_card_html("Worst ROI",               f"{worst:+.2f}%",   color=worst_color),     unsafe_allow_html=True)
    c4.markdown(_metric_card_html("Ø ROI",                f"{avg:+.2f}%",     color=avg_color),       unsafe_allow_html=True)
    c5.markdown(_metric_card_html("Ø Outperformance B&H", f"{outperf:+.2f}%", color=outp_color),      unsafe_allow_html=True)


def _render_compact_card_running(view: dict, dim: bool) -> None:
    """Eine kompakte Bot-Karte fuer PT/LT (laufend oder gestoppt)."""
    cfg   = view.get("config") or {}
    mets  = view.get("metrics") or {}
    roi   = mets.get("roi_pct", 0) or 0
    color = "#34D399" if roi >= 0 else "#F87171"
    if dim:
        # gestoppt: grauer Rand, geringere Opazitaet
        border, opacity = "#475569", "0.6"
    else:
        border, opacity = color, "1.0"

    name = view.get("name") or f"{view.get('coin','')}/USDT"
    coin = view.get("coin", "")
    iv   = view.get("interval", "")
    cap  = cfg.get("total_investment", 0)

    st.markdown(
        f"<div style='display:grid; grid-template-columns:1fr auto auto; gap:8px; align-items:center; "
        f"padding:8px 12px; background:rgba(255,255,255,0.02); border-left:3px solid {border}; "
        f"border-radius:4px; margin-bottom:4px; opacity:{opacity};'>"
        f"<span style='color:#E2E8F0; font-weight:500; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;'>{name}</span>"
        f"<span style='color:#64748B; font-size:0.78rem; white-space:nowrap;'>{coin} · {iv} · ${cap:,.0f}</span>"
        f"<span style='color:{color}; font-weight:600; white-space:nowrap; text-align:right;'>{roi:+.2f}%</span>"
        f"</div>",
        unsafe_allow_html=True
    )


def _render_compact_list_running(views: list) -> None:
    """PT/LT-Kompaktliste: getrennt nach Laufende und Gestoppte Bots."""
    running = [v for v in views if v.get("status") == "running"]
    stopped = [v for v in views if v.get("status") != "running"]
    if running:
        st.markdown("**Laufende Bots**")
        for v in running:
            _render_compact_card_running(v, dim=False)
    if stopped:
        st.markdown("**Gestoppte Bots**")
        for v in stopped:
            _render_compact_card_running(v, dim=True)


def _render_compact_list_backtest(views: list) -> None:
    """BT-Kompaktliste: bis _BT_LIST_LIMIT Eintraege, neueste zuerst."""
    if not views:
        return
    sorted_views = sorted(
        views,
        key=lambda v: v.get("created_at", ""),
        reverse=True,
    )[:_BT_LIST_LIMIT]
    st.markdown("**Letzte Backtests**")
    for v in sorted_views:
        _render_compact_card_running(v, dim=False)


def _render_action_buttons(
    views:            list,
    mode:             str,
    on_new_bot:       Callable[[], None],
    on_show_overview: Callable[[], None],
) -> None:
    """Zwei Action-Buttons unter der Mini-Liste."""
    new_label = ("＋ Neuen Backtest starten" if mode == "backtest"
                 else "＋ Neuen Bot starten")
    ov_label  = (f"Übersicht Backtests ({len(views)})" if mode == "backtest"
                 else f"Übersicht aktive Bots ({len(views)})")

    col_b1, col_b2 = st.columns(2)
    with col_b1:
        if st.button(new_label, use_container_width=True, type="primary",
                     key=f"pv_new_{mode}"):
            on_new_bot()
    with col_b2:
        if st.button(ov_label, use_container_width=True,
                     key=f"pv_overview_{mode}"):
            on_show_overview()


# ---------------------------------------------------------------------------
# Hauptfunktion
# ---------------------------------------------------------------------------

def render_portfolio_view(
    views:             list,
    mode:              str,
    on_new_bot:        Callable[[], None],
    on_show_overview:  Callable[[], None],
) -> None:
    """
    Rendert die Portfolio-Uebersicht eines Modus.

    Args:
        views             : Alle BotViews dieses Modus (Page-seitig sortiert)
        mode              : "backtest" | "paper" | "live"
        on_new_bot        : Callback "+ Neuen Bot/Backtest starten"
        on_show_overview  : Callback "Uebersicht ... (N)"
    """
    st.markdown("### 📊 Portfolio-Übersicht")

    if mode == "backtest":
        summary = _compute_summary_backtest(views, MAX_BACKTESTS)
        _render_metric_cards_backtest(summary)
    elif mode == "live":
        summary = _compute_summary_running(views, MAX_BOTS_PER_MODE)
        _render_metric_cards_live(summary)
    else:
        summary = _compute_summary_running(views, MAX_BOTS_PER_MODE)
        _render_metric_cards_paper(summary)

    st.markdown("<div style='margin-top:16px'></div>", unsafe_allow_html=True)

    if mode == "backtest":
        _render_compact_list_backtest(views)
    else:
        _render_compact_list_running(views)

    st.markdown("<div style='margin-top:16px'></div>", unsafe_allow_html=True)
    _render_action_buttons(views, mode, on_new_bot, on_show_overview)
