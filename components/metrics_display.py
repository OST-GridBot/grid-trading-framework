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
    Adaptive Kommastellen-Regel fuer Coin-Preise (Q.2):
      - Preis >= 100  ->  2 Nachkommastellen  (BTC, ETH, SOL)
      - Preis >=   1  ->  4 Nachkommastellen  (XRP, DOGE, ADA)
      - Preis <    1  ->  6 Nachkommastellen  (SHIB, PEPE, LUNC)

    Bei niedrigpreisigen Coins sind enge Grid-Linien sonst unterscheidbar
    nicht moeglich. Aggregierte USDT-Betraege (Initial Capital, Fees etc.)
    nutzen weiterhin den expliziten {:,.2f}-Format-String und sind NICHT
    von dieser Regel betroffen.

    Args:
        price     : Coin-Preis in USDT (kann None sein)
        with_unit : True → " USDT" anhaengen
    """
    if price is None:
        return "–"
    try:
        p = float(price)
    except (TypeError, ValueError):
        return "–"
    if p <= 0:
        return "–"
    if p >= 100:
        s = f"{p:,.2f}"
    elif p >= 1:
        s = f"{p:,.4f}"
    else:
        s = f"{p:.6f}"
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

def _sltp_condition_label(cfg: dict, side: str) -> str:
    """Trigger-Bedingung als Kurzlabel ('Preis 20%' / 'ROI 30%' / ...)."""
    prefix = "stop_loss_" if side == "sl" else "take_profit_"
    pct = cfg.get(prefix + "pct")
    if pct:
        return f"Preis {pct * 100:.0f}%"
    roi = cfg.get(prefix + "roi_pct")
    if roi:
        return f"ROI {roi * 100:.0f}%"
    pl = cfg.get(prefix + "pl_usdt")
    if pl:
        return f"P/L ${pl:,.0f}"
    return "–"


def _sltp_trigger_summary(metrics: dict, trade_log: list, side: str) -> Optional[dict]:
    """Bei ausgeloestem Trigger: dict mit verkauftem Wert (USDT) und
    Timestamp; sonst None.
    Konsolidierter Force-Sell: ein Trade pro Trigger -> amount × price."""
    trig_key = "stop_loss" if side == "sl" else "take_profit"
    triggered = metrics.get(f"{trig_key}_triggered")
    if not triggered:
        return None
    # Aus trade_log den Force-Sell-Trade mit passendem Trigger holen.
    fs = [t for t in (trade_log or [])
          if t.get("force_sell") and t.get("force_sell_trigger") == trig_key]
    if not fs:
        return None
    # Bei Konsolidierung gibts genau einen; bei alten Bots evtl. mehrere.
    sold_usdt = sum(float(t.get("amount", 0)) * float(t.get("price", 0)) for t in fs)
    # Timestamp aus erstem (= einzigem) Trade, oder aus metrics-Feld
    ts = fs[0].get("timestamp")
    try:
        from src.utils.timezone import utc_to_zurich
        ts_str = utc_to_zurich(ts).strftime("%d.%m.%Y %H:%M")
    except Exception:
        ts_str = str(ts)[:16]
    return {"sold_usdt": sold_usdt, "timestamp": ts_str}


def _fmt_or_dash(value, fmt: str = "{}") -> str:
    """Formatiert value mit fmt, oder '–' wenn None."""
    if value is None:
        return "–"
    try:
        return fmt.format(value)
    except Exception:
        return "–"


# Linien-Hierarchie im "All"-Tab (von stark nach schwach):
#   Theme-Header  -> 2px solid rgba(255,255,255,0.22)   (deutlich)
#   Section-Header-> 1px solid rgba(255,255,255,0.14)   (mittel)
#   Zeilen-Trenner-> 1px solid rgba(255,255,255,0.07)   (subtil)
_LINE_THEME   = "2px solid rgba(255,255,255,0.22)"
_LINE_SECTION = "1px solid rgba(255,255,255,0.14)"
_LINE_ROW     = "1px solid rgba(255,255,255,0.07)"


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
    # Section-Header mit eigener Unterstreichung (mittlere Linien-Stufe).
    html = (
        f"<div style='font-size:0.85rem; font-weight:600; color:#94A3B8; "
        f"text-transform:uppercase; letter-spacing:0.05em; "
        f"margin: 10px 0 0 0; padding-bottom:3px; "
        f"border-bottom:{_LINE_SECTION};'>{title}</div>"
    )
    html += (
        "<table style='width:100%; border-collapse:collapse; "
        "font-size:0.78rem; margin-top:2px;'>"
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
            f"<td style='padding:4px 8px; color:#94A3B8; "
            f"border-bottom:{_LINE_ROW}; width:55%;'>{label}</td>"
            f"<td style='text-align:right; padding:4px 8px; "
            f"border-bottom:{_LINE_ROW}; width:45%;'>{value_cell}</td>"
            "</tr>"
        )
    html += "</table>"
    st.markdown(html, unsafe_allow_html=True)


def _render_theme_header(title: str) -> None:
    """
    Render-Header fuer ein Tab-Thema (Top-Level-Stufe der Linien-Hierarchie).
    Dickste Unterstreichung in der "All"-Tab-Ansicht.
    """
    st.markdown(
        f"<div style='font-size:1.0rem; font-weight:700; color:#CBD5E1; "
        f"letter-spacing:0.03em; margin: 18px 0 4px 0; "
        f"border-bottom:{_LINE_THEME}; padding-bottom:6px;'>"
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
    upnl_num     = upnl.get("num_positions", 0) if isinstance(upnl, dict) else 0
    upnl_u       = upnl.get("usdt") if isinstance(upnl, dict) else None
    upnl_p       = upnl.get("pct")  if isinstance(upnl, dict) else None
    # F-2 (M.1-Audit): Floating Profit zeigt '–' wenn keine offenen
    # Positionen vorhanden, analog zu Tab 'Performance & Risk'.
    floating_main = (_fmt_or_dash(upnl_u, "{:+,.2f} USDT")
                     if upnl_num > 0 else "–")
    floating_sec  = (_fmt_or_dash(upnl_p, "{:+.2f}%")
                     if upnl_num > 0 else None)
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
            ("Floating Profit",     floating_main, floating_sec),
            ("CAGR",                _fmt_or_dash(cagr,       "{:+.2f}%"), None),
            ("Ø Profit / Trade",    _fmt_or_dash(avg_p_usdt, "{:+,.2f} USDT"),
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
        # P.2: Status-Bezeichnungen einheitlich englisch klein
        if not enabled:
            return (label, "–", "inactive")
        if count is not None:
            return (label, str(count) if count is not None else "–",
                    "triggered" if (count or 0) > 0 else "never triggered")
        if hit is not None:
            return (label,
                    "triggered" if hit else "not triggered",
                    None)
        return (label, "–", None)

    # Grid Trigger + Bot-Status
    bot_status = metrics.get("bot_status")
    grid_trigger = metrics.get("grid_trigger_price")
    # Q.2: Grid Trigger ist Coin-Preis -> adaptive Kommastellen
    trigger_label = _fmt_price(grid_trigger) if grid_trigger else "–"
    trigger_sec = "immediate start" if not grid_trigger else None

    num_t        = metrics.get("num_trades")
    grid_eff     = metrics.get("grid_efficiency")
    active_lv    = metrics.get("active_levels", {"active": 0, "total": 0})
    cap_per_grid = metrics.get("capital_per_grid")
    # Bug 3: Aufschlüsselung Initial-Buys / normale Buys / Sells.
    ib_count = metrics.get("num_initial_buys", 0) or 0
    nb_count = metrics.get("num_normal_buys",  0) or 0
    s_count  = metrics.get("num_sells",        0) or 0
    bs_str   = (f"IB:{ib_count} / B:{nb_count} / S:{s_count}"
                if trade_log else None)
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

    # Auftrag H: SL/TP zweizeilig — Status+Bedingung und Trigger-Details.
    # SL/TP-Bedingungs-Felder werden in bot_detail.py ins metrics-Dict
    # gemergt (stop_loss_pct, take_profit_roi_pct, ...).
    sl_cond = _sltp_condition_label(metrics, "sl")
    tp_cond = _sltp_condition_label(metrics, "tp")
    sl_summary = _sltp_trigger_summary(metrics, trade_log, "sl")
    tp_summary = _sltp_trigger_summary(metrics, trade_log, "tp")

    # _sltp_status / _sltp_detail entfernt - werden nach P.3 nicht mehr
    # genutzt (einzeilige Mechanismen-Darstellung via _sltp_compact inline).

    # Coin-Inventar fuer Kapital & Aktivitaet
    coin_amt   = metrics.get("coin_holdings") or 0
    coin_val   = metrics.get("coin_holdings_value_usdt") or 0
    coin_sym   = metrics.get("coin_symbol") or ""
    coin_inv_main = (f"{coin_amt:.6f} {coin_sym}" if coin_amt > 0 else "–")
    coin_inv_sec  = (f"≈ {coin_val:,.2f} USDT" if coin_amt > 0 else None)

    # P.3: DD-Drosselung einzeilig (Status + Faktor-Detail kombiniert)
    dd_on_all = active.get("dd_throttle", False) or bool(
        metrics.get("enable_dd_throttle", False)
    )
    dd_factor_all = float(metrics.get("dd_throttle_factor", 1.0) or 1.0)
    if not dd_on_all:
        dd_status = "inactive"
        dd_sec    = None
    else:
        dd_status = "active"
        pct = int(round(dd_factor_all * 100))
        if dd_factor_all >= 0.999:
            dd_sec = "factor 100% (no throttling)"
        elif dd_factor_all >= 0.40:
            dd_sec = f"factor {pct}% (threshold 1)"
        else:
            dd_sec = f"factor {pct}% (threshold 2)"

    # P.3: SL/TP einzeilig - Status + Bedingung ODER Trigger-Detail
    def _sltp_compact(enabled, hit, cond, summary):
        if not enabled:
            return ("inactive", None)
        if hit and summary:
            return ("triggered",
                    f"sold ${summary['sold_usdt']:,.0f} • {summary['timestamp']}")
        if hit:
            return ("triggered", None)
        return ("active", cond)

    sl_main, sl_sec = _sltp_compact(sl_on, sl_hit, sl_cond, sl_summary)
    tp_main, tp_sec = _sltp_compact(tp_on, tp_hit, tp_cond, tp_summary)

    # Zwei Spalten: Mechanismen | Kapital & Aktivitaet
    col_mech, col_cap = st.columns(2)
    # S.3: Bot-Status als Title-Case-Label (z.B. 'Waiting for Trigger'
    # statt 'waiting_for_trigger').
    from components.bot_detail import format_bot_status
    with col_mech:
        _render_section_table("Mechanismen", [
            ("Bot-Status",          format_bot_status(bot_status), None),
            ("Grid Trigger",        trigger_label, trigger_sec),
            _mech_row("Recentering Events", rc_on, rc_count, None),
            _mech_row("Trailing Events",    tr_on, tr_count, None),
            # P.3: DD/SL/TP jeweils einzeilig
            ("DD-Drosselung", dd_status, dd_sec),
            ("Stop-Loss",     sl_main,   sl_sec),
            ("Take-Profit",   tp_main,   tp_sec),
        ])
    # P.4: Initial Capital einzeilig - Reserve integriert in Hauptwert
    # (keine separate Sekundaer-Zeile mehr).
    _res_pct = float(metrics.get("reserve_pct", 0) or 0)
    if _res_pct > 0 and initial:
        _ic_main = (f"{initial:,.2f} USDT  "
                     f"(reserve {_res_pct*100:.0f}% / "
                     f"{initial * (1 - _res_pct):,.2f} effective)")
    else:
        _ic_main = _fmt_or_dash(initial, "{:,.2f} USDT")
    with col_cap:
        _render_section_table("Kapital & Aktivität", [
            ("Initial Capital",      _ic_main, None),
            ("Current Capital",      _fmt_or_dash(final,    "{:,.2f} USDT"), None),
            ("Coin-Inventar",        coin_inv_main, coin_inv_sec),
            ("Number of Trades",     _fmt_or_dash(num_t,    "{}"),           bs_str),
            ("Grid Efficiency",      _fmt_or_dash(grid_eff, "{:.1f}%"),      ratio),
            ("Invest / Grid",        _fmt_or_dash(cap_per_grid, "{:,.2f} USDT"), None),
            ("Initial-Buy Coins",    _fmt_or_dash(ib_coin_v,  "{:,.6f}"),    None),
            ("Initial-Buy Wert",     _fmt_or_dash(ib_value_v, "{:,.2f} USDT"),
                                      f"Fee {ib_fee_v:.4f} USDT" if ib_fee_v else None),
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
        # Q.2: Coin-Preise mit adaptiven Kommastellen via _fmt_price.
        _render_section_table("Market Data", [
            ("Current Price",  _fmt_price(cur_price), None),
            ("Max Price",      _fmt_price(max_p),     None),
            ("Min Price",      _fmt_price(min_p),     None),
            # P.1: USDT-Zahl entfernt - nur Prozent-Range anzeigen.
            ("Max-Min Range",  _fmt_or_dash(range_p, "{:.2f}%"), None),
        ])
    with col_rv:
        _render_section_table("Returns & Volatilität", [
            ("Ø % Return / Candle",  _fmt_or_dash(avg_r,  "{:+.2f}%"), None),
            ("Vola Return / Candle", _fmt_or_dash(std_r,  "{:.2f}%"),  None),
            ("Monthly Vola",         _fmt_or_dash(vola_m, "{:.2f}%"),  None),
            ("Yearly Vola",          _fmt_or_dash(vola_y, "{:.2f}%"),  None),
        ])
    with col_ind:
        _render_section_table("Indikatoren", [
            # Q.2: ATR ist Preis-Range -> adaptive Kommastellen
            ("Ø ATR (USDT)",   _fmt_price(atr_u), None),
            ("Ø ATR (%)",      _fmt_or_dash(atr_p, "{:.2f}%"), None),
            ("ADX 14",         _fmt_or_dash(adx14, "{:.1f}"),       None),
            ("ADX 30",         _fmt_or_dash(adx30, "{:.1f}"),       None),
        ])


# ---------------------------------------------------------------------------
# Tab 1: Performance & Risk
# ---------------------------------------------------------------------------

def _render_tab_performance(metrics: dict) -> None:
    # F-1 (M.1-Audit): Defaults None statt 0, damit fehlende Werte einheitlich
    # mit Tab 'All' als '–' angezeigt werden statt als '+0.00%'.
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
    calmar       = metrics.get("calmar_ratio")
    sharpe       = metrics.get("sharpe_ratio")
    max_dd_pct   = metrics.get("max_drawdown_pct")
    max_dd_usdt  = metrics.get("max_drawdown_usdt")

    pf           = metrics.get("profit_factor")

    avg_p_usdt   = metrics.get("avg_profit_per_trade")
    avg_p_pct    = metrics.get("avg_profit_per_trade_pct")
    g_total_u    = metrics.get("grid_profit_total_usdt")
    g_total_p    = metrics.get("grid_profit_total_pct")
    upnl         = metrics.get("unrealized_pnl",     {}) or {}
    upnl_num     = upnl.get("num_positions", 0) if isinstance(upnl, dict) else 0
    upnl_u       = upnl.get("usdt") if isinstance(upnl, dict) else None
    upnl_p       = upnl.get("pct")  if isinstance(upnl, dict) else None

    fees         = metrics.get("fees_paid")
    fee_imp      = metrics.get("fee_impact_pct")
    slip_usdt    = metrics.get("slippage_usdt")
    slip_pct     = metrics.get("slippage_avg_pct")

    # ── Reihe 1: P/L-Top (Gross zuerst, dann Net) ──────────────────────
    cols = st.columns(4)
    with cols[0]:
        _metric_card(
            "Total Gross P/L",
            f"{gross_pct:+.2f}%" if gross_pct is not None else "–",
            delta = f"{gross_usdt:+,.2f} USDT" if gross_usdt is not None else None,
            color = _color_roi(gross_pct),
        )
    with cols[1]:
        _metric_card(
            "Total Net P/L",
            f"{roi:+.2f}%" if roi is not None else "–",
            delta = f"{pl_usdt:+,.2f} USDT" if pl_usdt is not None else None,
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
            f"{g_total_u:+,.2f} USDT" if g_total_u is not None else "–",
            delta = f"{g_total_p:+.2f}%" if g_total_p is not None else None,
            color = _color_roi(g_total_u),
        )
    with cols[1]:
        if upnl_num > 0 and upnl_u is not None:
            _metric_card(
                "Floating Profit",
                f"{upnl_u:+,.2f} USDT",
                delta = f"{upnl_p:+.2f}%" if upnl_p is not None else None,
                color = _color_roi(upnl_u),
            )
        else:
            _metric_card("Floating Profit", "–", color="#94A3B8")
    with cols[2]:
        if fees is None:
            _metric_card("Trading Fees", "–", color="#94A3B8")
        else:
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
        # _color_dd ist nicht None-safe -> defensive Fallback 0 fuer Color
        _metric_card(
            "Max Drawdown",
            f"{max_dd_pct:.2f}%" if max_dd_pct is not None else "–",
            delta = f"{max_dd_usdt:,.2f} USDT" if max_dd_usdt is not None else None,
            color = _color_dd(max_dd_pct if max_dd_pct is not None else 0),
        )
    with cols[3]:
        _metric_card(
            "Sharpe Ratio",
            f"{sharpe:.2f}" if sharpe is not None else "–",
            delta = "good ≥ 1.0",
            color = _color_calmar(sharpe),
        )

    st.markdown("<div style='margin-top:8px'></div>", unsafe_allow_html=True)

    # ── Reihe 4: Ø Profit / Profit Factor / Slippage / leer ──────────
    cols = st.columns(4)
    with cols[0]:
        _metric_card(
            "Ø Profit / Trade",
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
    # F-3: Bot-Status + Grid Trigger als kompakter Header-Text
    # (zusaetzlich zu Tab 'All', wo sie als Tabellen-Zeilen erscheinen).
    bot_status   = metrics.get("bot_status")
    grid_trigger = metrics.get("grid_trigger_price")
    # S.3: Bot-Status als Title-Case-Label.
    from components.bot_detail import format_bot_status
    _bs_str = format_bot_status(bot_status)
    # Q.2: Grid Trigger ist Coin-Preis -> adaptive Kommastellen
    _gt_str = _fmt_price(grid_trigger) if grid_trigger else "immediate start"
    st.markdown(
        f"<div style='color:#94A3B8; font-size:0.85rem; "
        f"margin: -4px 0 12px 0;'>"
        f"Status: <span style='color:#E2E8F0;'>{_bs_str}</span>  |  "
        f"Grid Trigger: <span style='color:#E2E8F0;'>{_gt_str}</span>"
        f"</div>",
        unsafe_allow_html=True,
    )

    # ── Reihe 1: Mechanismen ───────────────────────────────────────────
    active = metrics.get("mechanism_active", {}) or {}
    rc_on  = active.get("recentering", False)
    tr_on  = active.get("trailing",    False)
    sl_on  = active.get("stop_loss",   False)
    tp_on  = active.get("take_profit", False)

    # rc_count / tr_count werden in den Kombi-Karten nicht verwendet
    # (anders als in Tab 'All' -> _mech_row), daher hier nicht ausgelesen.
    sl_hit   = metrics.get("stop_loss_triggered",   False)
    tp_hit   = metrics.get("take_profit_triggered", False)

    # Notiz 6.2: Reihe 1 neu strukturiert — Kombi-Karte
    # Recentering/Trailing + bestehende SL/TP + neue DD-Drossel.
    cols = st.columns(4)

    # ── Karte 1: Recentering / Trailing (exklusiv, UI-Verriegelung) ───
    with cols[0]:
        if not rc_on and not tr_on:
            # P.2: Status englisch klein
            _metric_card("Recentering / Trailing", "—",
                          delta="inactive", color="#64748B")
        elif rc_on:
            rc_thr = metrics.get("recenter_threshold")
            d = (f"Schwelle: {float(rc_thr) * 100:.0f}%"
                 if rc_thr is not None else None)
            _metric_card("Recentering / Trailing", "Recentering",
                          delta=d, color="#94A3B8")
        else:  # tr_on
            tr_stop = metrics.get("trailing_up_stop")
            d = (f"Stop: ${float(tr_stop):,.2f}"
                 if tr_stop else None)
            _metric_card("Recentering / Trailing", "Trailing",
                          delta=d, color="#94A3B8")

    # Auftrag H: delta-Text erweitert um Trigger-Bedingung bzw. bei
    # ausgeloestem Trigger verkauften Wert + Timestamp.
    sl_summary = _sltp_trigger_summary(metrics, trade_log, "sl")
    tp_summary = _sltp_trigger_summary(metrics, trade_log, "tp")
    sl_cond = _sltp_condition_label(metrics, "sl")
    tp_cond = _sltp_condition_label(metrics, "tp")

    # ── Karte 2: Stop-Loss ────────────────────────────────────────────
    with cols[1]:
        # P.2: Status englisch klein
        if not sl_on:
            _metric_card("Stop-Loss", "–", delta="inactive", color="#64748B")
        elif sl_hit:
            d = (f"${sl_summary['sold_usdt']:,.0f} • {sl_summary['timestamp']}"
                 if sl_summary else None)
            _metric_card("Stop-Loss", "triggered", delta=d, color="#F87171")
        else:
            _metric_card("Stop-Loss", "not triggered",
                          delta=sl_cond, color="#94A3B8")

    # ── Karte 3: Take-Profit ──────────────────────────────────────────
    with cols[2]:
        if not tp_on:
            _metric_card("Take-Profit", "–", delta="inactive", color="#64748B")
        elif tp_hit:
            d = (f"${tp_summary['sold_usdt']:,.0f} • {tp_summary['timestamp']}"
                 if tp_summary else None)
            _metric_card("Take-Profit", "triggered", delta=d, color="#34D399")
        else:
            _metric_card("Take-Profit", "not triggered",
                          delta=tp_cond, color="#94A3B8")

    # ── Karte 4: DD-Drossel (neu, Notiz 6.2) ──────────────────────────
    dd_on     = active.get("dd_throttle", False) or bool(
        metrics.get("enable_dd_throttle", False)
    )
    dd_factor = float(metrics.get("dd_throttle_factor", 1.0) or 1.0)
    with cols[3]:
        if not dd_on:
            # P.2: Status englisch klein
            _metric_card("DD-Drossel", "–", delta="inactive", color="#64748B")
        elif dd_factor >= 0.999:
            _metric_card("DD-Drossel", "100%",
                          delta="Keine Drosselung", color="#94A3B8")
        elif dd_factor >= 0.40:    # ~Schwelle 1 (0.5)
            _metric_card("DD-Drossel", f"{int(round(dd_factor*100))}%",
                          delta="Schwelle 1 aktiv", color="#FBBF24")
        else:                       # Schwelle 2 (0.25)
            _metric_card("DD-Drossel", f"{int(round(dd_factor*100))}%",
                          delta="Schwelle 2 aktiv", color="#F87171")

    st.markdown("<div style='margin-top:8px'></div>", unsafe_allow_html=True)

    # ── Reihe 2: Kapital + Aktivität ───────────────────────────────────
    # F-1 (M.1-Audit): Defaults None statt 0, damit fehlende Werte einheitlich
    # mit Tab 'All' als '–' angezeigt werden.
    initial   = metrics.get("initial_investment")
    final     = metrics.get("final_value")
    roi       = metrics.get("roi_pct")
    num_t     = metrics.get("num_trades")
    grid_eff  = metrics.get("grid_efficiency")
    active_lv = metrics.get("active_levels", {"active": 0, "total": 0})

    # P.4: Initial Capital einzeilig - Reserve integriert (Konsistenz Tab All)
    _res_pct = float(metrics.get("reserve_pct", 0) or 0)
    if _res_pct > 0 and initial:
        _ic_main = (f"{initial:,.2f} USDT  "
                     f"(reserve {_res_pct*100:.0f}% / "
                     f"{initial * (1 - _res_pct):,.2f} effective)")
    else:
        _ic_main = f"{initial:,.2f} USDT" if initial is not None else "–"
    # Bug 3: Aufschluesselung IB / B / S
    ib_count = metrics.get("num_initial_buys", 0) or 0
    nb_count = metrics.get("num_normal_buys",  0) or 0
    s_count  = metrics.get("num_sells",        0) or 0
    trades_delta = (f"IB:{ib_count} / B:{nb_count} / S:{s_count}"
                     if trade_log else None)

    cols = st.columns(4)
    with cols[0]:
        # P.4: Initial Capital einzeilig (Reserve in Hauptwert integriert).
        _metric_card("Initial Capital", _ic_main, color="#E2E8F0")
    with cols[1]:
        _metric_card(
            "Current Capital",
            f"{final:,.2f} USDT" if final is not None else "–",
            color=_color_roi(roi),
        )
    with cols[2]:
        _metric_card(
            "Number of Trades",
            str(num_t) if num_t is not None else "–",
            delta=trades_delta, color="#E2E8F0",
        )
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

    # ── Reihe 3: Coin-Inv / Invest-Grid / Initial-Buy Coins / Wert ─────
    cap_per_grid = metrics.get("capital_per_grid")
    coin_amt     = metrics.get("coin_holdings")
    coin_val     = metrics.get("coin_holdings_value_usdt")
    coin_sym     = metrics.get("coin_symbol", "")
    ib_coin      = metrics.get("initial_buy_coin_amount")
    ib_value     = metrics.get("initial_buy_value_usdt")
    ib_fee       = metrics.get("initial_buy_fee")

    cols = st.columns(4)
    with cols[0]:
        if coin_amt is not None and coin_amt > 0:
            _metric_card(
                "Coin-Inventar",
                f"{coin_amt:.6f} {coin_sym}",
                delta = (f"≈ {coin_val:,.2f} USDT"
                          if coin_val is not None else None),
                color = "#E2E8F0",
            )
        else:
            _metric_card("Coin-Inventar", "–", delta=None, color="#64748B")
    with cols[1]:
        _metric_card(
            "Invest / Grid",
            f"{cap_per_grid:,.2f} USDT" if cap_per_grid is not None else "–",
            color = "#E2E8F0",
        )
    with cols[2]:
        if ib_coin is not None and ib_coin > 0:
            _metric_card("Initial-Buy Coins", f"{ib_coin:,.6f}", color="#E2E8F0")
        else:
            _metric_card("Initial-Buy Coins", "–", color="#64748B")
    with cols[3]:
        if ib_value is not None and ib_value > 0:
            fee_delta = (f"Fee {ib_fee:.4f} USDT"
                          if ib_fee is not None and ib_fee else None)
            _metric_card("Initial-Buy Wert",
                          f"{ib_value:,.2f} USDT",
                          delta=fee_delta, color="#E2E8F0")
        else:
            _metric_card("Initial-Buy Wert", "–", color="#64748B")


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
        # P.1: USDT-Zahl entfernt - nur Prozent-Range anzeigen.
        _metric_card(
            "Max-Min Range",
            f"{range_p:.2f}%" if range_p is not None else "–",
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
            "Ø % Return / Candle",
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
        # Q.2: ATR ist Preis-Range -> adaptive Kommastellen
        _metric_card(
            "Ø ATR (USDT)",
            _fmt_price(atr_u),
            color = "#94A3B8",
        )
    with cols[1]:
        _metric_card(
            "Ø ATR (%)",
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

def _classify_trade_type(t: dict) -> str:
    """Mappt einen trade_log-Eintrag auf eine Label fuer die Typ-Spalte.

    G.2-Klassifikation:
      - Initial-Buy : BUY mit initial=True
      - Stop-Loss   : SELL mit force_sell + force_sell_trigger='stop_loss'
      - Take-Profit : SELL mit force_sell + force_sell_trigger='take_profit'
      - buy / sell  : normale Grid-Trades
    """
    raw = str(t.get("type", "")).upper()
    if raw == "BUY" and t.get("initial"):
        return "Initial-Buy"
    if raw == "SELL" and t.get("force_sell"):
        trig = t.get("force_sell_trigger")
        if trig == "stop_loss":
            return "Stop-Loss"
        if trig == "take_profit":
            return "Take-Profit"
    if raw == "BUY":
        return "buy"
    if raw == "SELL":
        return "sell"
    return raw.lower()


# G.2: Farben pro Trade-Typ (Hex). Kein Default → leerer style.
_TYPE_COLORS = {
    "buy":         "#34D399",  # gruen hell
    "sell":        "#F87171",  # rot hell
    "Initial-Buy": "#60A5FA",  # blau
    "Take-Profit": "#10B981",  # gruen dunkel
    "Stop-Loss":   "#DC2626",  # rot dunkel
}


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

    # G.1: Warnung wenn Tabelle abgeschnitten wird
    total = len(trade_log)
    if total > max_rows:
        st.warning(
            f"Trade-Log hat {total:,} Eintraege, gezeigt werden nur die "
            f"letzten {max_rows:,}."
        )

    from src.utils.timezone import utc_to_zurich

    # T.2: Coin-Inventar pro Trade cumulative aus VOLLSTAENDIGEM trade_log
    # berechnen (chronologisch, aelteste zuerst). Dann gleiches Slice wie
    # die gerenderten Trades nehmen, damit Truncation (max_rows) den Stand
    # ab Truncation-Punkt korrekt darstellt.
    #
    # Logik:
    #   BUY              -> running_coin += amount
    #   SELL force_sell  -> running_coin  = 0      (komplettes Inventar weg)
    #   SELL normal      -> running_coin -= amount
    inv_full = []
    running_coin = 0.0
    for t in trade_log:
        ttype = (t.get("type") or "").upper()
        amt   = float(t.get("amount", 0) or 0)
        if ttype == "BUY":
            running_coin += amt
        elif ttype == "SELL":
            if t.get("force_sell"):
                running_coin = 0.0
            else:
                running_coin -= amt
        inv_full.append(max(0.0, running_coin))

    trades_slice = trade_log[-max_rows:]
    inv_slice    = inv_full[-max_rows:]

    rows = []
    for t, inv in zip(trades_slice, inv_slice):
        type_label = _classify_trade_type(t)
        is_sell    = type_label in ("sell", "Stop-Loss", "Take-Profit")
        profit     = t.get("profit", 0) or 0
        amount     = float(t.get("amount", 0) or 0)
        price      = float(t.get("price", 0) or 0)
        fee        = float(t.get("fee", 0) or 0)
        # Bug 2: Kosten (Buy) = Preis × Menge + Fee (Cash-Abfluss, negatives
        # Vorzeichen). Einnahmen (Sell) = Preis × Menge − Fee (Cash-Zufluss,
        # positives Vorzeichen). Initial-Buys -> Buy-Logik, Force-Sell ->
        # Sell-Logik.
        cash_flow  = (price * amount - fee) if is_sell else -(price * amount + fee)
        cash_label = f"{cash_flow:+,.2f}" if cash_flow else "–"
        try:
            ts_str = utc_to_zurich(t.get("timestamp", "")).strftime("%Y-%m-%d %H:%M")
        except Exception:
            ts_str = str(t.get("timestamp", ""))[:16]
        # Punkt 2: Buy-Bezug fuer Sells (matched_buy_price aus trade_log).
        # N.3: Force-Sell mit n>1 Paketen -> 'Ø X.XX (n=N)' (gewichteter
        # Durchschnitt), sonst Single-Match -> '@ X.XX'. Backward-Compat
        # via Fallback 1 fuer alte Trade-Log-Eintraege ohne matched_buy_count.
        mbp = t.get("matched_buy_price")
        if is_sell and mbp:
            if t.get("force_sell"):
                n = int(t.get("matched_buy_count", 1) or 1)
                if n > 1:
                    buy_ref = f"Ø {float(mbp):,.2f} (n={n})"
                else:
                    buy_ref = f"@ {float(mbp):,.2f}"
            else:
                buy_ref = f"@ {float(mbp):,.2f}"
        else:
            buy_ref = "–"
        # T.1: Preis-Spalte mit adaptiver Stellen-Regel (Q.2). Ohne USDT-
        # Suffix in der Zelle - die Spalte selbst heisst "Preis".
        price_str = _fmt_price(price, with_unit=False) if price > 0 else "–"
        rows.append({
            "Zeit":                ts_str,
            "Typ":                 type_label,
            "Preis":               price_str,
            "Menge":               f"{amount:.6f}",
            # T.2: Coin-Inventar nach diesem Trade (gleiche Stellen-Konvention
            # wie Menge fuer Konsistenz).
            "Coin-Inventar":       f"{inv:.6f}",
            "Gebühr":              f"{fee:.4f}",
            "Einnahmen / Ausgaben": cash_label,
            "Profit":              f"{profit:+.4f}" if is_sell else "–",
            "Buy-Bezug":           buy_ref,
        })

    df = pd.DataFrame(rows[::-1])  # Neueste zuerst

    def color_type(val):
        c = _TYPE_COLORS.get(str(val))
        return f"color: {c}" if c else ""

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
    styled = styled.applymap(color_profit, subset=["Einnahmen / Ausgaben"])
    st.dataframe(styled, use_container_width=True, hide_index=True)
