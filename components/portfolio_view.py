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

def _compute_summary_running(views: list, max_bots: int) -> dict:
    """
    Berechnet die fuenf Portfolio-Kennzahlen fuer PT/LT.

    Args:
        views    : Liste aller BotViews dieses Modus
        max_bots : Limit der gleichzeitig erlaubten Bots (MAX_BOTS_PER_MODE)

    Returns:
        Dict mit Schluesseln:
            active_count  (int)   Anzahl laufender Bots
            max_count     (int)
            total_invest  (float) Summe Kapital aller laufenden Bots
            weighted_roi  (float) kapitalgewichtetes ROI in %
            total_profit  (float) realisierter Profit ueber alle Bots
            total_trades  (int)   Trades-Summe ueber alle Bots
    """
    running = [v for v in views if v.get("status") == "running"]

    total_invest = sum(
        (v.get("config") or {}).get("total_investment", 0) or 0
        for v in running
    )

    weighted_sum = sum(
        ((v.get("metrics") or {}).get("roi_pct", 0) or 0)
        * ((v.get("config") or {}).get("total_investment", 0) or 0)
        for v in running
    )
    weighted_roi = (weighted_sum / total_invest) if total_invest > 0 else 0.0

    total_trades = sum(len(v.get("trade_log") or []) for v in views)

    # Realisierter Profit = Summe profit aller SELL-Trades
    total_profit = sum(
        sum(
            (t.get("profit") or 0)
            for t in (v.get("trade_log") or [])
            if str(t.get("type", "")).upper() == "SELL"
        )
        for v in views
    )

    return {
        "active_count": len(running),
        "max_count":    max_bots,
        "total_invest": total_invest,
        "weighted_roi": weighted_roi,
        "total_profit": total_profit,
        "total_trades": total_trades,
    }


def _compute_summary_backtest(views: list, max_backtests: int) -> dict:
    """
    Berechnet die fuenf Portfolio-Kennzahlen fuer BT.

    Args:
        views         : Liste aller Backtest-Views
        max_backtests : Limit der gespeicherten Backtests (MAX_BACKTESTS)

    Returns:
        Dict mit Schluesseln:
            count        (int)
            max_count    (int)
            best_roi     (float) % - 0 bei leerer Liste
            worst_roi    (float) %
            avg_roi      (float) %
            total_trades (int)
    """
    rois = [
        (v.get("metrics") or {}).get("roi_pct", 0) or 0
        for v in views
    ]
    total_trades = sum(len(v.get("trade_log") or []) for v in views)

    if rois:
        best  = max(rois)
        worst = min(rois)
        avg   = sum(rois) / len(rois)
    else:
        best = worst = avg = 0.0

    return {
        "count":        len(views),
        "max_count":    max_backtests,
        "best_roi":     best,
        "worst_roi":    worst,
        "avg_roi":      avg,
        "total_trades": total_trades,
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


def _render_metric_cards_running(summary: dict) -> None:
    """Fuenf Metrik-Karten fuer PT/LT."""
    c1, c2, c3, c4, c5 = st.columns(5)
    roi    = summary["weighted_roi"]
    profit = summary["total_profit"]
    roi_color    = "#34D399" if roi >= 0 else "#F87171"
    profit_color = "#34D399" if profit >= 0 else "#F87171"
    c1.markdown(_metric_card_html("Aktive Bots",         f"{summary['active_count']}/{summary['max_count']}"), unsafe_allow_html=True)
    c2.markdown(_metric_card_html("Gesamtinvest",        f"${summary['total_invest']:,.0f}"),                  unsafe_allow_html=True)
    c3.markdown(_metric_card_html("Ø ROI",               f"{roi:+.2f}%",      color=roi_color),                unsafe_allow_html=True)
    c4.markdown(_metric_card_html("Realisierter Profit", f"${profit:+.2f}",   color=profit_color),             unsafe_allow_html=True)
    c5.markdown(_metric_card_html("Trades gesamt",       str(summary["total_trades"])),                        unsafe_allow_html=True)


def _render_metric_cards_backtest(summary: dict) -> None:
    """Fuenf Metrik-Karten fuer BT."""
    c1, c2, c3, c4, c5 = st.columns(5)
    best, worst, avg = summary["best_roi"], summary["worst_roi"], summary["avg_roi"]
    best_color  = "#34D399" if best  >= 0 else "#F87171"
    worst_color = "#34D399" if worst >= 0 else "#F87171"
    avg_color   = "#34D399" if avg   >= 0 else "#F87171"
    c1.markdown(_metric_card_html("Gespeicherte Backtests", f"{summary['count']}/{summary['max_count']}"), unsafe_allow_html=True)
    c2.markdown(_metric_card_html("Bestes ROI",             f"{best:+.2f}%",    color=best_color),         unsafe_allow_html=True)
    c3.markdown(_metric_card_html("Ø ROI",                  f"{avg:+.2f}%",     color=avg_color),          unsafe_allow_html=True)
    c4.markdown(_metric_card_html("Schlechtestes ROI",      f"{worst:+.2f}%",   color=worst_color),        unsafe_allow_html=True)
    c5.markdown(_metric_card_html("Trades gesamt",          str(summary["total_trades"])),                 unsafe_allow_html=True)


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
    views:            list,
    mode:             str,
    on_new_bot:       Callable[[], None],
    on_show_overview: Callable[[], None],
) -> None:
    """
    Rendert die Portfolio-Uebersicht eines Modus.

    Args:
        views            : Alle BotViews dieses Modus (Page-seitig sortiert)
        mode             : "backtest" | "paper" | "live"
        on_new_bot       : Callback "+ Neuen Bot/Backtest starten"
        on_show_overview : Callback "Uebersicht ... (N)"
    """
    st.markdown("### 📊 Portfolio-Übersicht")

    if mode == "backtest":
        summary = _compute_summary_backtest(views, MAX_BACKTESTS)
        _render_metric_cards_backtest(summary)
    else:
        summary = _compute_summary_running(views, MAX_BOTS_PER_MODE)
        _render_metric_cards_running(summary)

    st.markdown("<div style='margin-top:16px'></div>", unsafe_allow_html=True)

    if mode == "backtest":
        _render_compact_list_backtest(views)
    else:
        _render_compact_list_running(views)

    st.markdown("<div style='margin-top:16px'></div>", unsafe_allow_html=True)
    _render_action_buttons(views, mode, on_new_bot, on_show_overview)
