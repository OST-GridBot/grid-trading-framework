"""
components/metrics_display.py
==============================
Kennzahlen-Anzeige Komponenten fuer Streamlit.

Enthaelt:
    render_metrics_row() -> Kennzahlen-Karten in einer Reihe
    render_trade_log()   -> Trade-Log als formatierte Tabelle

Schicht 3 des Metriken-Refactors: liest ausschliesslich Standard-Schluessel
aus calculate_all_metrics (src/analysis/metrics.py). Keine eigene Berechnungslogik.

Autor: Enes Eryilmaz
Projekt: Grid-Trading-Framework (Bachelorarbeit OST)
"""

import streamlit as st
import pandas as pd
from typing import Optional


# ---------------------------------------------------------------------------
# Farben und Styles
# ---------------------------------------------------------------------------

def _color_roi(value: float) -> str:
    if value > 0:   return "#34D399"
    if value < 0:   return "#F87171"
    return "#94A3B8"

def _color_sharpe(value: float) -> str:
    if value >= 1:  return "#34D399"
    if value >= 0:  return "#FBBF24"
    return "#F87171"

def _arrow(value: float) -> str:
    if value > 0: return "▲"
    if value < 0: return "▼"
    return "–"


# ---------------------------------------------------------------------------
# Metric Card (einzelne Kachel)
# ---------------------------------------------------------------------------

def _metric_card(
    label:    str,
    value:    str,
    delta:    Optional[str] = None,
    color:    str           = "#E2E8F0",
    help_txt: Optional[str] = None,
) -> None:
    """Rendert eine einzelne Kennzahlen-Kachel."""
    delta_html = f'''
        <div style="font-size:0.75rem; color:{color}; margin-top:2px;">
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
        ">
            <div style="font-size:0.7rem; color:#64748B; text-transform:uppercase;
                        letter-spacing:0.08em; margin-bottom:4px;">{label}</div>
            <div style="font-size:1.35rem; font-weight:700; color:{color};
                        font-family:monospace;">{value}</div>
            {delta_html}
        </div>
    ''', unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Kennzahlen-Reihe
# ---------------------------------------------------------------------------

def render_metrics_row(
    metrics:   dict,
    mode:      str  = "backtest",
    trade_log: Optional[list] = None,
) -> None:
    """
    Rendert die wichtigsten Kennzahlen in einer Reihe von Kacheln.

    Liest ausschliesslich das Standard-Schluesselschema aus
    calculate_all_metrics (src/metrics.py).

    Args:
        metrics  : Dictionary mit Kennzahlen aus calculate_all_metrics
        mode     : "backtest" oder "live"
        trade_log: Optionale Trade-Liste fuer Buy/Sell-Counts in der
                   Trades-Kachel. Frueher unter dem Schluessel "_trade_log"
                   ins metrics-Dict geschmuggelt — jetzt sauber als Parameter.
    """
    roi        = metrics.get("roi_pct",            0) or 0
    sharpe     = metrics.get("sharpe_ratio",       None)
    max_dd     = metrics.get("max_drawdown_pct",   0) or 0
    num_trades = metrics.get("num_trades",         0) or 0
    bh_roi     = metrics.get("benchmark_roi_pct",  None)
    outperf    = metrics.get("outperformance_pct", None)
    cagr       = metrics.get("cagr_pct",           None)
    calmar     = metrics.get("calmar_ratio",       None)
    win_rate   = metrics.get("win_rate_pct",       None)
    pf         = metrics.get("profit_factor",      None)

    # Zeile 1: Haupt-Kennzahlen
    cols = st.columns(4)
    with cols[0]:
        _metric_card(
            "ROI",
            f"{roi:+.2f}%",
            delta = f"BnH: {bh_roi:+.2f}%" if bh_roi is not None else None,
            color = _color_roi(roi),
        )
    with cols[1]:
        _metric_card(
            "Sharpe Ratio",
            f"{sharpe:.2f}" if sharpe is not None else "–",
            delta = "gut ≥ 1.0",
            color = _color_sharpe(sharpe or 0),
        )
    with cols[2]:
        _metric_card(
            "Max Drawdown",
            f"{max_dd:.2f}%",
            color = "#F87171" if max_dd > 20 else "#FBBF24" if max_dd > 10 else "#34D399",
        )
    with cols[3]:
        if trade_log:
            buys  = sum(1 for t in trade_log if "BUY"  in str(t.get("type", "")).upper())
            sells = sum(1 for t in trade_log if "SELL" in str(t.get("type", "")).upper())
            buy_sell_str = f"B:{buys} / S:{sells}"
        else:
            buy_sell_str = None
        _metric_card(
            "Trades",
            str(num_trades),
            delta = buy_sell_str,
            color = "#E2E8F0",
        )

    # Zeile 2: Erweiterte Kennzahlen (nur Backtest)
    if mode == "backtest":
        st.markdown("<div style='margin-top:8px'></div>", unsafe_allow_html=True)
        cols2 = st.columns(4)
        with cols2[0]:
            _metric_card(
                "CAGR",
                f"{cagr:+.2f}%" if cagr is not None else "–",
                color = _color_roi(cagr or 0),
            )
        with cols2[1]:
            _metric_card(
                "Calmar Ratio",
                f"{calmar:.2f}" if calmar is not None else "–",
                delta = "gut ≥ 1.0",
                color = _color_sharpe(calmar or 0),
            )
        with cols2[2]:
            _metric_card(
                "Win-Rate",
                f"{win_rate:.1f}%" if win_rate is not None else "–",
                color = "#34D399" if (win_rate or 0) > 50 else "#FBBF24",
            )
        with cols2[3]:
            _metric_card(
                "Profit-Faktor",
                f"{pf:.2f}" if pf is not None else "∞",
                delta = "gut ≥ 1.5",
                color = "#34D399" if pf is None or (pf or 0) >= 1.5 else "#FBBF24" if (pf or 0) >= 1 else "#F87171",
            )

    # Zeile 3: Grid-/Live-Kennzahlen
    if mode == "backtest":
        st.markdown("<div style='margin-top:8px'></div>", unsafe_allow_html=True)
        cols_new = st.columns(4)
        grid_eff   = metrics.get("grid_efficiency",      None)
        avg_profit = metrics.get("avg_profit_per_trade", None)
        runtime    = metrics.get("runtime",              None)
        upnl       = metrics.get("unrealized_pnl",       None)
        with cols_new[0]:
            _metric_card(
                "Grid Efficiency",
                f"{grid_eff:.1f}%" if grid_eff is not None else "–",
                delta = "gut ≥ 50%",
                color = "#34D399" if (grid_eff or 0) >= 50 else "#FBBF24",
            )
        with cols_new[1]:
            _metric_card(
                "Ø Profit/Trade",
                f"${avg_profit:+.2f}" if avg_profit is not None else "–",
                color = _color_roi(avg_profit or 0),
            )
        with cols_new[2]:
            rt_str = runtime.get("formatted", "–") if isinstance(runtime, dict) else "–"
            _metric_card(
                "Laufzeit",
                rt_str,
                color = "#E2E8F0",
            )
        with cols_new[3]:
            if upnl is not None and isinstance(upnl, dict):
                _metric_card(
                    "Unrealisiert",
                    f"${upnl.get('usdt', 0):+.2f}",
                    delta = f"{upnl.get('pct', 0):+.2f}%",
                    color = _color_roi(upnl.get('usdt', 0)),
                )
            else:
                _metric_card("Unrealisiert", "–", color="#94A3B8")

    # Zeile 4: Kapital-Übersicht
    if mode == "backtest":
        st.markdown("<div style='margin-top:8px'></div>", unsafe_allow_html=True)
        cols3 = st.columns(4)
        initial = metrics.get("initial_investment", None)
        final   = metrics.get("final_value",        None)
        fees    = metrics.get("fees_paid",          0) or 0
        with cols3[0]:
            _metric_card(
                "Startkapital",
                f"${initial:,.2f}" if initial else "–",
                color="#E2E8F0",
            )
        with cols3[1]:
            _metric_card(
                "Endwert",
                f"${final:,.2f}" if final else "–",
                color=_color_roi(roi),
            )
        with cols3[2]:
            _metric_card(
                "Gezahlte Gebühren",
                f"${fees:,.2f}",
                color="#F87171" if fees > 0 else "#94A3B8",
            )
        with cols3[3]:
            _metric_card(
                "Gewinn / Verlust",
                f"${((final or 0) - (initial or 0)):+,.2f}" if initial and final else "–",
                color=_color_roi(roi),
            )

    # Outperformance Banner
    if outperf is not None:
        color = "#34D399" if outperf > 0 else "#F87171"
        arrow = _arrow(outperf)
        st.markdown(f'''
            <div style="
                margin-top: 10px;
                padding: 8px 14px;
                background: rgba(255,255,255,0.03);
                border-left: 3px solid {color};
                border-radius: 4px;
                font-size: 0.85rem;
                color: {color};
            ">
                {arrow} Grid Bot outperformt Buy &amp; Hold um
                <strong>{outperf:+.2f}%</strong>
            </div>
        ''', unsafe_allow_html=True)


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

    # Farben via Pandas Styler
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
