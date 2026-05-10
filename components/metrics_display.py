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
    """Platzhalter-Karte fuer leere Spalten."""
    st.markdown("&nbsp;", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Haupt-Render-Funktion: 3-Tab-Layout
# ---------------------------------------------------------------------------

def render_metrics_tabs(
    metrics:   dict,
    trade_log: Optional[list] = None,
) -> None:
    """
    Drei Tabs: Grid-Bot-Performance / Marktdaten / Indikatoren.

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

    tab_p, tab_m, tab_i = st.tabs(["Grid Bot Performance", "Market Data", "Indicators"])
    with tab_p:
        _render_tab_performance(metrics, trade_log or [])
    with tab_m:
        _render_tab_market(metrics)
    with tab_i:
        _render_tab_indicators(metrics)


# ---------------------------------------------------------------------------
# Tab 1: Grid-Bot-Performance
# ---------------------------------------------------------------------------

def _render_tab_performance(metrics: dict, trade_log: list) -> None:
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

    num_t        = metrics.get("num_trades",         0) or 0
    pf           = metrics.get("profit_factor")
    grid_eff     = metrics.get("grid_efficiency")
    active       = metrics.get("active_levels", {"active": 0, "total": 0})
    cap_per_grid = metrics.get("capital_per_grid")

    avg_p_usdt   = metrics.get("avg_profit_per_trade")
    avg_p_pct    = metrics.get("avg_profit_per_trade_pct")
    g_total_u    = metrics.get("grid_profit_total_usdt", 0) or 0
    g_total_p    = metrics.get("grid_profit_total_pct",  0) or 0
    upnl         = metrics.get("unrealized_pnl",     {})
    upnl_u       = upnl.get("usdt", 0) if isinstance(upnl, dict) else 0
    upnl_p       = upnl.get("pct",  0) if isinstance(upnl, dict) else 0

    fees         = metrics.get("fees_paid",          0) or 0
    fee_imp      = metrics.get("fee_impact_pct")
    runtime      = metrics.get("runtime", {})
    rt_str       = runtime.get("formatted", "–") if isinstance(runtime, dict) else "–"

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

    # ── Reihe 4: Grid + Trade-Stats ────────────────────────────────────
    cols = st.columns(4)
    with cols[0]:
        ratio = (
            f"{active['active']}/{active['total']}"
            if isinstance(active, dict) else "–"
        )
        _metric_card(
            "Grid Efficiency",
            f"{grid_eff:.1f}%" if grid_eff is not None else "–",
            delta = ratio,
            color = "#34D399" if (grid_eff or 0) >= 50 else "#FBBF24",
        )
    with cols[1]:
        _metric_card(
            "Invest / Grid",
            f"{cap_per_grid:,.2f} USDT" if cap_per_grid is not None else "–",
            color = "#E2E8F0",
        )
    with cols[2]:
        _metric_card(
            "Avg Profit / Trade",
            f"{avg_p_usdt:+,.2f} USDT" if avg_p_usdt is not None else "–",
            delta = f"{avg_p_pct:+.2f}%" if avg_p_pct is not None else None,
            color = _color_roi(avg_p_usdt),
        )
    with cols[3]:
        # Profit Factor: "–" statt "∞" wenn keine Verluste
        _metric_card(
            "Profit Factor",
            f"{pf:.2f}" if pf is not None else "–",
            delta = "good ≥ 1.5",
            color = "#34D399" if (pf or 0) >= 1.5
                    else "#FBBF24" if (pf or 0) >= 1
                    else "#F87171",
        )

    st.markdown("<div style='margin-top:8px'></div>", unsafe_allow_html=True)

    # ── Reihe 5: Meta ──────────────────────────────────────────────────
    cols = st.columns(4)
    with cols[0]:
        _metric_card("Initial Capital", f"{initial:,.2f} USDT", color="#E2E8F0")
    with cols[1]:
        _metric_card("Current Capital", f"{final:,.2f} USDT", color=_color_roi(roi))
    with cols[2]:
        _metric_card("Runtime", rt_str, color="#E2E8F0")
    with cols[3]:
        buys  = sum(1 for t in trade_log if "BUY"  in str(t.get("type", "")).upper())
        sells = sum(1 for t in trade_log if "SELL" in str(t.get("type", "")).upper())
        bs    = f"B:{buys} / S:{sells}" if trade_log else None
        _metric_card("Number of Trades", str(num_t), delta=bs, color="#E2E8F0")


# ---------------------------------------------------------------------------
# Tab 2: Marktdaten
# ---------------------------------------------------------------------------

def _render_tab_market(metrics: dict) -> None:
    cur_price = metrics.get("current_price")
    extr      = metrics.get("price_extremes", {}) or {}
    max_p     = extr.get("max_price",  0) or 0
    min_p     = extr.get("min_price",  0) or 0
    range_u   = extr.get("range_usdt", 0) or 0
    range_p   = extr.get("range_pct",  0) or 0

    cols = st.columns(4)
    with cols[0]:
        _metric_card(
            "Current Price",
            f"{cur_price:,.4f} USDT" if cur_price else "–",
            color = "#E2E8F0",
        )
    with cols[1]:
        _metric_card("Max Price", f"{max_p:,.4f} USDT", color="#34D399")
    with cols[2]:
        _metric_card("Min Price", f"{min_p:,.4f} USDT", color="#F87171")
    with cols[3]:
        _metric_card(
            "Max-Min Range",
            f"{range_u:,.4f} USDT",
            delta = f"{range_p:.2f}%",
            color = "#94A3B8",
        )


# ---------------------------------------------------------------------------
# Tab 3: Indikatoren
# ---------------------------------------------------------------------------

def _render_tab_indicators(metrics: dict) -> None:
    rs    = metrics.get("return_stats", {}) or {}
    avg_r = rs.get("avg_pct")
    std_r = rs.get("std_pct")
    vola_m = metrics.get("vola_monthly_pct")
    vola_y = metrics.get("vola_yearly_pct")
    atr_u  = metrics.get("atr_usdt")
    atr_p  = metrics.get("atr_pct")
    adx14  = metrics.get("adx14")
    adx30  = metrics.get("adx30")

    # ── Reihe 1: Returns pro Kerze + Vola ──────────────────────────────
    cols = st.columns(4)
    with cols[0]:
        _metric_card(
            "Avg % Return / Candle",
            f"{avg_r:+.4f}%" if avg_r is not None else "–",
            color = _color_roi(avg_r),
        )
    with cols[1]:
        _metric_card(
            "Vola % Return / Candle",
            f"{std_r:.4f}%" if std_r is not None else "–",
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

    # ── Reihe 2: ATR + ADX ─────────────────────────────────────────────
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
