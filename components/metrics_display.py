"""
components/metrics_display.py
==============================
Kennzahlen-Anzeige Komponenten fuer Streamlit (3-Tab-Layout).

Enthaelt:
    render_metrics_tabs() -> 3-Tab-Anzeige (Performance/Marktdaten/Indikatoren)
    render_trade_log()    -> Trade-Log als formatierte Tabelle

Schicht 3 des Metriken-Refactors: liest ausschliesslich Standard-Schluessel
aus calculate_all_metrics (src/analysis/metrics.py) plus die in der Engine
ergaenzten Indikator-/Marktdaten-Felder. Keine eigene Berechnungslogik.

Autor: Enes Eryilmaz
Projekt: Grid-Trading-Framework (Bachelorarbeit OST)
"""

import streamlit as st
import pandas as pd
from typing import Optional


# ---------------------------------------------------------------------------
# Farben und Hilfsfunktionen
# ---------------------------------------------------------------------------

def _color_roi(value) -> str:
    if value is None: return "#94A3B8"
    if value > 0:     return "#34D399"
    if value < 0:     return "#F87171"
    return "#94A3B8"

def _color_calmar(value) -> str:
    if value is None: return "#94A3B8"
    if value >= 1:    return "#34D399"
    if value >= 0:    return "#FBBF24"
    return "#F87171"

def _color_dd(value: float) -> str:
    if value > 20: return "#F87171"
    if value > 10: return "#FBBF24"
    return "#34D399"


def _fmt_price(price, with_unit: bool = True) -> str:
    """
    Formatiert einen Preis kompakt — 2 Nachkommastellen bei normalen Preisen,
    6 signifikante Stellen bei niedrigpreisigen Coins (SHIB ~0.000023, PEPE).

    Args:
        price     : Preis in USDT (kann None sein)
        with_unit : True → " USDT" anhaengen
    """
    if price is None or price <= 0:
        return "–"
    if price >= 1:
        s = f"{price:,.2f}"
    else:
        s = f"{price:.6g}"
    return f"{s} USDT" if with_unit else s


def _metric_card(
    label:   str,
    value:   str,
    delta:   Optional[str] = None,
    color:   str           = "#E2E8F0",
) -> None:
    """
    Eine einzelne Kennzahlen-Kachel. Schriftparameter sind ueber alle
    Karten in allen 3 Tabs identisch — Referenz-Karte: "Total Net P/L".

    Layout pro Karte (alle Werte explizit gesetzt, keine impliziten Defaults):
        Label : 0.7rem,  Inter,     uppercase, letter-spacing 0.08em, #64748B
        Value : 1.25rem, monospace, weight 700, line-height 1.2
        Delta : 0.75rem, Inter,     weight 400, line-height 1.2, margin-top 10px

    Lange Werte werden mit ellipsis abgeschnitten statt umzubrechen, damit
    die Karten-Hoehe konstant 95px bleibt.
    """
    delta_html = f'''
        <div style="font-family:Inter,-apple-system,sans-serif;
                    font-size:0.75rem; font-weight:400; line-height:1.2;
                    color:{color}; margin-top:10px;
                    white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">
            {delta}
        </div>
    ''' if delta else ""

    st.markdown(f'''
        <div style="
            background: rgba(255,255,255,0.04);
            border: 1px solid rgba(255,255,255,0.08);
            border-radius: 8px;
            padding: 12px 14px;
            height: 95px;
            overflow: hidden;
        ">
            <div style="font-family:Inter,-apple-system,sans-serif;
                        font-size:0.7rem; font-weight:500;
                        color:#64748B; text-transform:uppercase;
                        letter-spacing:0.08em; margin-bottom:4px;
                        white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">
                {label}
            </div>
            <div style="font-family:monospace;
                        font-size:1.25rem; font-weight:700; line-height:1.2;
                        color:{color};
                        white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">
                {value}
            </div>
            {delta_html}
        </div>
    ''', unsafe_allow_html=True)


def _empty_cell() -> None:
    """
    Platzhalter-Karte fuer leere Spalten — gleicher Box-Style wie
    _metric_card, aber ohne Inhalt. Haelt das Karten-Raster optisch
    geschlossen.
    """
    st.markdown(
        '<div style="'
        'background: rgba(255,255,255,0.04);'
        'border: 1px solid rgba(255,255,255,0.08);'
        'border-radius: 8px;'
        'padding: 12px 14px;'
        'height: 95px;'
        '">&nbsp;</div>',
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Haupt-Render-Funktion: 3-Tab-Layout
# ---------------------------------------------------------------------------

def render_metrics_tabs(
    metrics:   dict,
    trade_log: Optional[list] = None,
) -> None:
    """
    Drei Tabs: Performance & Risk / Bot Details / Market Data & Indicators.

    Liest ausschliesslich Standard-Schluessel aus dem Metrics-Dict.

    Args:
        metrics  : Dict aus run_backtest() oder bot["metrics"]
        trade_log: Optional. Fuer Buy/Sell-Counts in der Trades-Karte.
    """
    st.markdown(
        '<div style="font-size:1.15rem; font-weight:600; color:#CBD5E1; '
        'text-transform:uppercase; letter-spacing:0.06em; '
        'margin: 16px 0 8px 0;">Metrics</div>',
        unsafe_allow_html=True,
    )

    tab_all, tab_pr, tab_bd, tab_mi = st.tabs(
        ["All", "Performance & Risk", "Bot Details", "Market Data & Indicators"]
    )
    with tab_all:
        _render_tab_all(metrics, trade_log or [])
    with tab_pr:
        _render_tab_performance(metrics)
    with tab_bd:
        _render_tab_bot_details(metrics, trade_log or [])
    with tab_mi:
        _render_tab_market_indicators(metrics)


# ---------------------------------------------------------------------------
# Tab 0: All — kompakte Excel-aehnliche Uebersicht aller Metriken
# ---------------------------------------------------------------------------

def _fmt_or_dash(value, fmt: str = "{}") -> str:
    """Formatiert value mit fmt, oder '–' wenn None."""
    if value is None:
        return "–"
    try:
        return fmt.format(value)
    except Exception:
        return "–"


def _render_section_table(title: str, rows: list) -> None:
    """
    Rendert eine kompakte Section mit Sub-Header + 2-spaltiger Tabelle.

    Args:
        title: Section-Header (z.B. "Performance")
        rows : Liste von Tupeln (label, value_str, secondary_str_or_None).
               Falls value_str None -> "–". Sekundaerwert (sofern vorhanden)
               wird in derselben Wert-Spalte in Klammern + grau angehaengt.
               Beispiel-Output: "10% (100 USDT)"
    """
    html = (
        f"<div style='font-size:0.85rem; font-weight:600; color:#94A3B8; "
        f"text-transform:uppercase; letter-spacing:0.05em; "
        f"margin: 10px 0 4px 0;'>{title}</div>"
    )
    html += (
        "<table style='width:100%; border-collapse:collapse; font-size:0.78rem;'>"
    )
    for label, value, secondary in rows:
        val_str = value if value is not None else "–"
        if secondary is not None:
            value_cell = (
                f"<span style='color:#E2E8F0; font-weight:500;'>{val_str}</span> "
                f"<span style='color:#64748B;'>({secondary})</span>"
            )
        else:
            value_cell = f"<span style='color:#E2E8F0; font-weight:500;'>{val_str}</span>"
        html += (
            "<tr>"
            f"<td style='padding:3px 8px; color:#94A3B8; "
            f"border-bottom:1px solid rgba(255,255,255,0.04); width:55%;'>{label}</td>"
            f"<td style='text-align:right; padding:3px 8px; "
            f"border-bottom:1px solid rgba(255,255,255,0.04); width:45%;'>"
            f"{value_cell}</td>"
            "</tr>"
        )
    html += "</table>"
    st.markdown(html, unsafe_allow_html=True)


def _render_theme_header(title: str) -> None:
    """Render-Header fuer ein Tab-Thema (eine Stufe groesser als Section-Header)."""
    st.markdown(
        f"<div style='font-size:1.0rem; font-weight:700; color:#CBD5E1; "
        f"letter-spacing:0.03em; margin: 18px 0 4px 0; "
        f"border-bottom:1px solid rgba(255,255,255,0.10); padding-bottom:4px;'>"
        f"{title}</div>",
        unsafe_allow_html=True,
    )


def _render_tab_all(metrics: dict, trade_log: list) -> None:
    """
    "All"-Tab: kompakte tabellarische Uebersicht aller Metriken.

    Gliederung nach den drei thematischen Tabs, innerhalb dieser jeweils
    Sub-Sections. Initial-Buy-Felder + bot_status + grid_trigger_price
    werden ebenfalls angezeigt (sofern in metrics gemerged).
    """
    # ──────────────────────────────────────────────────────────────────────
    # PERFORMANCE & RISK
    # ──────────────────────────────────────────────────────────────────────
    _render_theme_header("Performance & Risk")

    initial      = metrics.get("initial_investment")
    final        = metrics.get("final_value")
    pl_usdt      = (final - initial) if (final is not None and initial is not None) else None
    roi          = metrics.get("roi_pct")
    bh_pct       = metrics.get("benchmark_roi_pct")
    bh_usdt      = metrics.get("benchmark_roi_usdt")
    gross_pct    = metrics.get("gross_pl_pct")
    gross_usdt   = metrics.get("gross_pl_usdt")
    outperf      = metrics.get("outperformance_pct")
    cagr         = metrics.get("cagr_pct")
    g_total_u    = metrics.get("grid_profit_total_usdt")
    g_total_p    = metrics.get("grid_profit_total_pct")
    upnl         = metrics.get("unrealized_pnl") or {}
    upnl_u       = upnl.get("usdt") if isinstance(upnl, dict) else None
    upnl_p       = upnl.get("pct")  if isinstance(upnl, dict) else None
    avg_p_usdt   = metrics.get("avg_profit_per_trade")
    avg_p_pct    = metrics.get("avg_profit_per_trade_pct")

    calmar       = metrics.get("calmar_ratio")
    sharpe       = metrics.get("sharpe_ratio")
    max_dd_pct   = metrics.get("max_drawdown_pct")
    max_dd_usdt  = metrics.get("max_drawdown_usdt")
    pf           = metrics.get("profit_factor")
    fees         = metrics.get("fees_paid")
    fee_imp      = metrics.get("fee_impact_pct")
    slip_usdt    = metrics.get("slippage_usdt")
    slip_pct     = metrics.get("slippage_avg_pct")

    # Zwei Spalten: Performance | Risk
    col_perf, col_risk = st.columns(2)
    with col_perf:
        _render_section_table("Performance", [
            ("Total Gross P/L",     _fmt_or_dash(gross_pct,  "{:+.2f}%"),
                                    _fmt_or_dash(gross_usdt, "{:+,.2f} USDT")),
            ("Total Net P/L",       _fmt_or_dash(roi,        "{:+.2f}%"),
                                    _fmt_or_dash(pl_usdt,    "{:+,.2f} USDT")),
            ("Buy & Hold",          _fmt_or_dash(bh_pct,     "{:+.2f}%"),
                                    _fmt_or_dash(bh_usdt,    "{:+,.2f} USDT")),
            ("Outperformance",      _fmt_or_dash(outperf,    "{:+.2f}%"),
                                    "vs. Buy & Hold" if outperf is not None else None),
            ("Grid Profit Total",   _fmt_or_dash(g_total_u,  "{:+,.2f} USDT"),
                                    _fmt_or_dash(g_total_p,  "{:+.2f}%")),
            ("Floating Profit",     _fmt_or_dash(upnl_u,     "{:+,.2f} USDT"),
                                    _fmt_or_dash(upnl_p,     "{:+.2f}%")),
            ("CAGR",                _fmt_or_dash(cagr,       "{:+.2f}%"), None),
            ("Avg Profit / Trade",  _fmt_or_dash(avg_p_usdt, "{:+,.2f} USDT"),
                                    _fmt_or_dash(avg_p_pct,  "{:+.2f}%")),
        ])
    with col_risk:
        _render_section_table("Risk", [
            ("Calmar Ratio",   _fmt_or_dash(calmar,      "{:.2f}"),     "good ≥ 1.0"),
            ("Sharpe Ratio",   _fmt_or_dash(sharpe,      "{:.2f}"),     "good ≥ 1.0"),
            ("Max Drawdown",   _fmt_or_dash(max_dd_pct,  "{:.2f}%"),
                               _fmt_or_dash(max_dd_usdt, "{:,.2f} USDT")),
            ("Profit Factor",  _fmt_or_dash(pf,          "{:.2f}"),     "good ≥ 1.5"),
            ("Trading Fees",   _fmt_or_dash(fees,        "{:,.2f} USDT"), None),
            ("Fee Impact",     _fmt_or_dash(fee_imp,     "{:.1f}%"),    None),
            ("Total Slippage", _fmt_or_dash(slip_usdt,   "{:,.4f} USDT"),
                               _fmt_or_dash(slip_pct,    "{:.4f}%")),
        ])

    # ──────────────────────────────────────────────────────────────────────
    # BOT DETAILS
    # ──────────────────────────────────────────────────────────────────────
    _render_theme_header("Bot Details")

    active = metrics.get("mechanism_active", {}) or {}
    rc_on  = active.get("recentering", False)
    tr_on  = active.get("trailing",    False)
    sl_on  = active.get("stop_loss",   False)
    tp_on  = active.get("take_profit", False)

    rc_count = metrics.get("recentering_count")
    tr_count = metrics.get("trailing_count")
    sl_hit   = metrics.get("stop_loss_triggered")
    tp_hit   = metrics.get("take_profit_triggered")

    def _mech_row(label: str, enabled: bool, count, hit) -> tuple:
        if not enabled:
            return (label, "–", "Inactive")
        if count is not None:
            return (label, str(count) if count is not None else "–",
                    "Triggered" if (count or 0) > 0 else "Never triggered")
        if hit is not None:
            return (label,
                    "Triggered" if hit else "Not triggered",
                    None)
        return (label, "–", None)

    # Grid Trigger + Bot-Status
    bot_status = metrics.get("bot_status")
    grid_trigger = metrics.get("grid_trigger_price")
    trigger_label = (
        _fmt_or_dash(grid_trigger, "{:,.2f} USDT") if grid_trigger else "–"
    )
    trigger_sec = "Sofortiger Start" if not grid_trigger else None

    num_t        = metrics.get("num_trades")
    grid_eff     = metrics.get("grid_efficiency")
    active_lv    = metrics.get("active_levels", {"active": 0, "total": 0})
    cap_per_grid = metrics.get("capital_per_grid")
    buys  = sum(1 for t in trade_log if "BUY"  in str(t.get("type", "")).upper())
    sells = sum(1 for t in trade_log if "SELL" in str(t.get("type", "")).upper())
    bs_str = f"B:{buys} / S:{sells}" if trade_log else None
    ratio = (
        f"{active_lv['active']}/{active_lv['total']}"
        if isinstance(active_lv, dict) and active_lv.get("total")
        else None
    )

    # Initial-Buy-Aggregate (Binance-Standard-Setup)
    ib_coin  = metrics.get("initial_buy_coin_amount")
    ib_fee   = metrics.get("initial_buy_fee")
    ib_value = metrics.get("initial_buy_value_usdt")
    # "–" auch bei 0.0 (kein Initial-Setup ausgefuehrt z.B. bei Trigger-Wartenden)
    ib_coin_v  = None if not ib_coin  else ib_coin
    ib_fee_v   = None if not ib_fee   else ib_fee
    ib_value_v = None if not ib_value else ib_value

    # Zwei Spalten: Mechanismen | Kapital & Aktivitaet
    col_mech, col_cap = st.columns(2)
    with col_mech:
        _render_section_table("Mechanismen", [
            ("Bot-Status",          bot_status if bot_status else "–", None),
            ("Grid Trigger",        trigger_label, trigger_sec),
            _mech_row("Recentering Events", rc_on, rc_count, None),
            _mech_row("Trailing Events",    tr_on, tr_count, None),
            _mech_row("Stop-Loss",          sl_on, None,     sl_hit),
            _mech_row("Take-Profit",        tp_on, None,     tp_hit),
        ])
    with col_cap:
        _render_section_table("Kapital & Aktivität", [
            ("Initial Capital",      _fmt_or_dash(initial,  "{:,.2f} USDT"), None),
            ("Current Capital",      _fmt_or_dash(final,    "{:,.2f} USDT"), None),
            ("Number of Trades",     _fmt_or_dash(num_t,    "{}"),           bs_str),
            ("Grid Efficiency",      _fmt_or_dash(grid_eff, "{:.1f}%"),      ratio),
            ("Invest / Grid",        _fmt_or_dash(cap_per_grid, "{:,.2f} USDT"), None),
            ("Initial-Buy Coins",    _fmt_or_dash(ib_coin_v,  "{:,.6f}"),    None),
            ("Initial-Buy Wert",     _fmt_or_dash(ib_value_v, "{:,.2f} USDT"), None),
            ("Initial-Buy Fee",      _fmt_or_dash(ib_fee_v,   "{:,.4f} USDT"), None),
        ])

    # ──────────────────────────────────────────────────────────────────────
    # MARKET DATA & INDICATORS
    # ──────────────────────────────────────────────────────────────────────
    _render_theme_header("Market Data & Indicators")

    cur_price = metrics.get("current_price")
    extr      = metrics.get("price_extremes", {}) or {}
    max_p     = extr.get("max_price")
    min_p     = extr.get("min_price")
    range_u   = extr.get("range_usdt")
    range_p   = extr.get("range_pct")

    rs     = metrics.get("return_stats", {}) or {}
    avg_r  = rs.get("avg_pct")
    std_r  = rs.get("std_pct")
    vola_m = metrics.get("vola_monthly_pct")
    vola_y = metrics.get("vola_yearly_pct")

    atr_u = metrics.get("atr_usdt")
    atr_p = metrics.get("atr_pct")
    adx14 = metrics.get("adx14")
    adx30 = metrics.get("adx30")

    # Drei Spalten: Market Data | Returns & Volatilitaet | Indikatoren
    col_md, col_rv, col_ind = st.columns(3)
    with col_md:
        _render_section_table("Market Data", [
            ("Current Price",  _fmt_or_dash(cur_price, "{:,.2f} USDT"), None),
            ("Max Price",      _fmt_or_dash(max_p,     "{:,.2f} USDT"), None),
            ("Min Price",      _fmt_or_dash(min_p,     "{:,.2f} USDT"), None),
            ("Max-Min Range",  _fmt_or_dash(range_u,   "{:,.2f} USDT"),
                               _fmt_or_dash(range_p,   "{:.2f}%")),
        ])
    with col_rv:
        _render_section_table("Returns & Volatilität", [
            ("Avg Return / Candle",  _fmt_or_dash(avg_r,  "{:+.2f}%"), None),
            ("Vola Return / Candle", _fmt_or_dash(std_r,  "{:.2f}%"),  None),
            ("Monthly Vola",         _fmt_or_dash(vola_m, "{:.2f}%"),  None),
            ("Yearly Vola",          _fmt_or_dash(vola_y, "{:.2f}%"),  None),
        ])
    with col_ind:
        _render_section_table("Indikatoren", [
            ("Avg ATR (USDT)", _fmt_or_dash(atr_u, "{:,.2f} USDT"), None),
            ("Avg ATR (%)",    _fmt_or_dash(atr_p, "{:.2f}%"),      None),
            ("ADX 14",         _fmt_or_dash(adx14, "{:.1f}"),       None),
            ("ADX 30",         _fmt_or_dash(adx30, "{:.1f}"),       None),
        ])


# ---------------------------------------------------------------------------
# Tab 1: Performance & Risk
# ---------------------------------------------------------------------------

def _render_tab_performance(metrics: dict) -> None:
    initial      = metrics.get("initial_investment", 0) or 0
    final        = metrics.get("final_value",        0) or 0
    pl_usdt      = final - initial

    roi          = metrics.get("roi_pct",            0) or 0
    bh_pct       = metrics.get("benchmark_roi_pct")
    bh_usdt      = metrics.get("benchmark_roi_usdt")
    gross_pct    = metrics.get("gross_pl_pct",       0) or 0
    gross_usdt   = metrics.get("gross_pl_usdt",      0) or 0
    outperf      = metrics.get("outperformance_pct")

    cagr         = metrics.get("cagr_pct")
    calmar       = metrics.get("calmar_ratio")
    sharpe       = metrics.get("sharpe_ratio")
    max_dd_pct   = metrics.get("max_drawdown_pct",   0) or 0
    max_dd_usdt  = metrics.get("max_drawdown_usdt",  0) or 0

    pf           = metrics.get("profit_factor")

    avg_p_usdt   = metrics.get("avg_profit_per_trade")
    avg_p_pct    = metrics.get("avg_profit_per_trade_pct")
    g_total_u    = metrics.get("grid_profit_total_usdt", 0) or 0
    g_total_p    = metrics.get("grid_profit_total_pct",  0) or 0
    upnl         = metrics.get("unrealized_pnl",     {})
    upnl_u       = upnl.get("usdt", 0) if isinstance(upnl, dict) else 0
    upnl_p       = upnl.get("pct",  0) if isinstance(upnl, dict) else 0

    fees         = metrics.get("fees_paid",          0) or 0
    fee_imp      = metrics.get("fee_impact_pct")
    slip_usdt    = metrics.get("slippage_usdt")
    slip_pct     = metrics.get("slippage_avg_pct")

    # ── Reihe 1: P/L-Top (Gross zuerst, dann Net) ──────────────────────
    cols = st.columns(4)
    with cols[0]:
        _metric_card(
            "Total Gross P/L",
            f"{gross_pct:+.2f}%",
            delta = f"{gross_usdt:+,.2f} USDT",
            color = _color_roi(gross_pct),
        )
    with cols[1]:
        _metric_card(
            "Total Net P/L",
            f"{roi:+.2f}%",
            delta = f"{pl_usdt:+,.2f} USDT",
            color = _color_roi(roi),
        )
    with cols[2]:
        _metric_card(
            "Buy & Hold",
            f"{bh_pct:+.2f}%" if bh_pct is not None else "–",
            delta = f"{bh_usdt:+,.2f} USDT" if bh_usdt is not None else None,
            color = _color_roi(bh_pct),
        )
    with cols[3]:
        _metric_card(
            "Outperformance",
            f"{outperf:+.2f}%" if outperf is not None else "–",
            delta = "vs. Buy & Hold" if outperf is not None else None,
            color = _color_roi(outperf),
        )

    st.markdown("<div style='margin-top:8px'></div>", unsafe_allow_html=True)

    # ── Reihe 2: Grid Profit + Floating + Fees ─────────────────────────
    cols = st.columns(4)
    with cols[0]:
        _metric_card(
            "Grid Profit Total",
            f"{g_total_u:+,.2f} USDT",
            delta = f"{g_total_p:+.2f}%",
            color = _color_roi(g_total_u),
        )
    with cols[1]:
        if isinstance(upnl, dict) and upnl.get("num_positions", 0) > 0:
            _metric_card(
                "Floating Profit",
                f"{upnl_u:+,.2f} USDT",
                delta = f"{upnl_p:+.2f}%",
                color = _color_roi(upnl_u),
            )
        else:
            _metric_card("Floating Profit", "–", color="#94A3B8")
    with cols[2]:
        _metric_card(
            "Trading Fees",
            f"{fees:,.2f} USDT",
            color = "#F87171" if fees > 0 else "#94A3B8",
        )
    with cols[3]:
        _metric_card(
            "Fee Impact",
            f"{fee_imp:.1f}%" if fee_imp is not None else "–",
            color = "#94A3B8",
        )

    st.markdown("<div style='margin-top:8px'></div>", unsafe_allow_html=True)

    # ── Reihe 3: Risiko/Rendite ────────────────────────────────────────
    cols = st.columns(4)
    with cols[0]:
        _metric_card(
            "CAGR",
            f"{cagr:+.2f}%" if cagr is not None else "–",
            color = _color_roi(cagr),
        )
    with cols[1]:
        _metric_card(
            "Calmar Ratio",
            f"{calmar:.2f}" if calmar is not None else "–",
            delta = "good ≥ 1.0",
            color = _color_calmar(calmar),
        )
    with cols[2]:
        _metric_card(
            "Max Drawdown",
            f"{max_dd_pct:.2f}%",
            delta = f"{max_dd_usdt:,.2f} USDT",
            color = _color_dd(max_dd_pct),
        )
    with cols[3]:
        _metric_card(
            "Sharpe Ratio",
            f"{sharpe:.2f}" if sharpe is not None else "–",
            delta = "good ≥ 1.0",
            color = _color_calmar(sharpe),
        )

    st.markdown("<div style='margin-top:8px'></div>", unsafe_allow_html=True)

    # ── Reihe 4: Avg Profit / Profit Factor / Slippage / leer ──────────
    cols = st.columns(4)
    with cols[0]:
        _metric_card(
            "Avg Profit / Trade",
            f"{avg_p_usdt:+,.2f} USDT" if avg_p_usdt is not None else "–",
            delta = f"{avg_p_pct:+.2f}%" if avg_p_pct is not None else None,
            color = _color_roi(avg_p_usdt),
        )
    with cols[1]:
        # Profit Factor: "–" statt "∞" wenn keine Verluste
        _metric_card(
            "Profit Factor",
            f"{pf:.2f}" if pf is not None else "–",
            delta = "good ≥ 1.5",
            color = "#34D399" if (pf or 0) >= 1.5
                    else "#FBBF24" if (pf or 0) >= 1
                    else "#F87171",
        )
    with cols[2]:
        # Slippage: aktuell "–" in allen Modi (Brokers nicht aktiv).
        # Sobald LiveBroker / PaperBroker aktiv ist, fliesst der Wert
        # automatisch ins Schema.
        slip_main  = _fmt_price(slip_usdt) if slip_usdt is not None else "–"
        slip_delta = f"{slip_pct:.4f}%"   if slip_pct  is not None else None
        _metric_card("Total Slippage", slip_main, delta=slip_delta, color="#94A3B8")
    with cols[3]:
        _empty_cell()


# ---------------------------------------------------------------------------
# Tab 2: Bot Details
# ---------------------------------------------------------------------------

def _render_tab_bot_details(metrics: dict, trade_log: list) -> None:
    """
    Bot Details: Mechanismen + Kapital/Aktivität + Konfiguration.
    """
    # ── Reihe 1: Mechanismen ───────────────────────────────────────────
    active = metrics.get("mechanism_active", {}) or {}
    rc_on  = active.get("recentering", False)
    tr_on  = active.get("trailing",    False)
    sl_on  = active.get("stop_loss",   False)
    tp_on  = active.get("take_profit", False)

    rc_count = metrics.get("recentering_count", 0) or 0
    tr_count = metrics.get("trailing_count",    0) or 0
    sl_hit   = metrics.get("stop_loss_triggered",   False)
    tp_hit   = metrics.get("take_profit_triggered", False)

    cols = st.columns(4)
    with cols[0]:
        if not rc_on:
            _metric_card("Recentering Events", "–", delta="Inactive", color="#64748B")
        elif rc_count == 0:
            _metric_card("Recentering Events", "0", delta="Never triggered", color="#94A3B8")
        else:
            _metric_card("Recentering Events", str(rc_count), delta="Triggered", color="#94A3B8")
    with cols[1]:
        if not tr_on:
            _metric_card("Trailing Events", "–", delta="Inactive", color="#64748B")
        elif tr_count == 0:
            _metric_card("Trailing Events", "0", delta="Never triggered", color="#94A3B8")
        else:
            _metric_card("Trailing Events", str(tr_count), delta="Triggered", color="#94A3B8")
    with cols[2]:
        if not sl_on:
            _metric_card("Stop-Loss", "–", delta="Inactive", color="#64748B")
        elif sl_hit:
            _metric_card("Stop-Loss", "Triggered", delta=None, color="#F87171")
        else:
            _metric_card("Stop-Loss", "Not triggered", delta=None, color="#94A3B8")
    with cols[3]:
        if not tp_on:
            _metric_card("Take-Profit", "–", delta="Inactive", color="#64748B")
        elif tp_hit:
            _metric_card("Take-Profit", "Triggered", delta=None, color="#34D399")
        else:
            _metric_card("Take-Profit", "Not triggered", delta=None, color="#94A3B8")

    st.markdown("<div style='margin-top:8px'></div>", unsafe_allow_html=True)

    # ── Reihe 2: Kapital + Aktivität ───────────────────────────────────
    initial   = metrics.get("initial_investment", 0) or 0
    final     = metrics.get("final_value",        0) or 0
    roi       = metrics.get("roi_pct",            0) or 0
    num_t     = metrics.get("num_trades",         0) or 0
    grid_eff  = metrics.get("grid_efficiency")
    active_lv = metrics.get("active_levels", {"active": 0, "total": 0})

    cols = st.columns(4)
    with cols[0]:
        _metric_card("Initial Capital", f"{initial:,.2f} USDT", color="#E2E8F0")
    with cols[1]:
        _metric_card("Current Capital", f"{final:,.2f} USDT", color=_color_roi(roi))
    with cols[2]:
        buys  = sum(1 for t in trade_log if "BUY"  in str(t.get("type", "")).upper())
        sells = sum(1 for t in trade_log if "SELL" in str(t.get("type", "")).upper())
        bs    = f"B:{buys} / S:{sells}" if trade_log else None
        _metric_card("Number of Trades", str(num_t), delta=bs, color="#E2E8F0")
    with cols[3]:
        ratio = (
            f"{active_lv['active']}/{active_lv['total']}"
            if isinstance(active_lv, dict) else "–"
        )
        _metric_card(
            "Grid Efficiency",
            f"{grid_eff:.1f}%" if grid_eff is not None else "–",
            delta = ratio,
            color = "#34D399" if (grid_eff or 0) >= 50 else "#FBBF24",
        )

    st.markdown("<div style='margin-top:8px'></div>", unsafe_allow_html=True)

    # ── Reihe 3: Konfiguration (Invest / Grid + leere Slots) ───────────
    cap_per_grid = metrics.get("capital_per_grid")

    cols = st.columns(4)
    with cols[0]:
        _metric_card(
            "Invest / Grid",
            f"{cap_per_grid:,.2f} USDT" if cap_per_grid is not None else "–",
            color = "#E2E8F0",
        )
    with cols[1]: _empty_cell()
    with cols[2]: _empty_cell()
    with cols[3]: _empty_cell()


# ---------------------------------------------------------------------------
# Tab 3: Market Data & Indicators (zusammengelegt)
# ---------------------------------------------------------------------------

def _render_tab_market_indicators(metrics: dict) -> None:
    """
    Market Data + technische Indikatoren in einem Tab.
    """
    # ── Reihe 1: Market Data ───────────────────────────────────────────
    cur_price = metrics.get("current_price")
    extr      = metrics.get("price_extremes", {}) or {}
    max_p     = extr.get("max_price",  0) or 0
    min_p     = extr.get("min_price",  0) or 0
    range_u   = extr.get("range_usdt", 0) or 0
    range_p   = extr.get("range_pct",  0) or 0

    cols = st.columns(4)
    with cols[0]:
        _metric_card("Current Price", _fmt_price(cur_price), color="#E2E8F0")
    with cols[1]:
        _metric_card("Max Price", _fmt_price(max_p), color="#34D399")
    with cols[2]:
        _metric_card("Min Price", _fmt_price(min_p), color="#F87171")
    with cols[3]:
        _metric_card(
            "Max-Min Range",
            _fmt_price(range_u),
            delta = f"{range_p:.2f}%",
            color = "#94A3B8",
        )

    st.markdown("<div style='margin-top:8px'></div>", unsafe_allow_html=True)

    # ── Reihe 2: Returns + Vola ────────────────────────────────────────
    # Hinweis: bei sehr kleinen Renditen kann die Anzeige auf +0.00% gerundet
    # werden — akzeptiert fuer kompakte UI, keine Sonder-Behandlung.
    rs     = metrics.get("return_stats", {}) or {}
    avg_r  = rs.get("avg_pct")
    std_r  = rs.get("std_pct")
    vola_m = metrics.get("vola_monthly_pct")
    vola_y = metrics.get("vola_yearly_pct")

    cols = st.columns(4)
    with cols[0]:
        _metric_card(
            "Avg % Return / Candle",
            f"{avg_r:+.2f}%" if avg_r is not None else "–",
            color = _color_roi(avg_r),
        )
    with cols[1]:
        _metric_card(
            "Vola % Return / Candle",
            f"{std_r:.2f}%" if std_r is not None else "–",
            color = "#94A3B8",
        )
    with cols[2]:
        _metric_card(
            "Monthly Vola",
            f"{vola_m:.2f}%" if vola_m is not None else "–",
            color = "#94A3B8",
        )
    with cols[3]:
        _metric_card(
            "Yearly Vola",
            f"{vola_y:.2f}%" if vola_y is not None else "–",
            color = "#94A3B8",
        )

    st.markdown("<div style='margin-top:8px'></div>", unsafe_allow_html=True)

    # ── Reihe 3: ATR + ADX ─────────────────────────────────────────────
    atr_u = metrics.get("atr_usdt")
    atr_p = metrics.get("atr_pct")
    adx14 = metrics.get("adx14")
    adx30 = metrics.get("adx30")

    cols = st.columns(4)
    with cols[0]:
        _metric_card(
            "Avg ATR (USDT)",
            f"{atr_u:,.2f} USDT" if atr_u is not None else "–",
            color = "#94A3B8",
        )
    with cols[1]:
        _metric_card(
            "Avg ATR (%)",
            f"{atr_p:.2f}%" if atr_p is not None else "–",
            color = "#94A3B8",
        )
    with cols[2]:
        _metric_card(
            "ADX 14",
            f"{adx14:.1f}" if adx14 is not None else "–",
            color = "#94A3B8",
        )
    with cols[3]:
        _metric_card(
            "ADX 30",
            f"{adx30:.1f}" if adx30 is not None else "–",
            color = "#94A3B8",
        )


# ---------------------------------------------------------------------------
# Trade-Log Tabelle
# ---------------------------------------------------------------------------

def render_trade_log(trade_log: list, max_rows: int = 100000) -> None:
    """
    Formatierter Trade-Log als Tabelle.

    Args:
        trade_log : Liste der Trades aus grid_bot
        max_rows  : Maximale Anzahl anzuzeigender Zeilen
    """
    if not trade_log:
        st.info("Noch keine Trades.")
        return

    from src.utils.timezone import utc_to_zurich

    rows = []
    for t in trade_log[-max_rows:]:
        trade_type = t.get("type", "")
        is_sell    = "SELL" in trade_type.upper()
        profit     = t.get("profit", 0) or 0
        try:
            ts_str = utc_to_zurich(t.get("timestamp", "")).strftime("%Y-%m-%d %H:%M")
        except Exception:
            ts_str = str(t.get("timestamp", ""))[:16]
        rows.append({
            "Zeit":    ts_str,
            "Typ":     trade_type,
            "Preis":   f"{t.get('price', 0):,.2f}",
            "Menge":   f"{t.get('amount', 0):.6f}",
            "Gebuehr": f"{t.get('fee', 0):.4f}",
            "Profit":  f"{profit:+.4f}" if is_sell else "–",
        })

    df = pd.DataFrame(rows[::-1])  # Neueste zuerst

    def color_type(val):
        if "SELL" in str(val).upper(): return "color: #F87171"
        if "BUY"  in str(val).upper(): return "color: #34D399"
        return ""

    def color_profit(val):
        try:
            v = float(str(val).replace("+", ""))
            if v > 0: return "color: #34D399"
            if v < 0: return "color: #F87171"
        except Exception:
            pass
        return "color: #94A3B8"

    styled = df.style.applymap(color_type, subset=["Typ"])
    styled = styled.applymap(color_profit, subset=["Profit"])
    st.dataframe(styled, use_container_width=True, hide_index=True)
