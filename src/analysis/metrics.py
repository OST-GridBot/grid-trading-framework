"""
src/analysis/metrics.py
=======================
Zentrale Kennzahlen-Bibliothek fuer das Grid-Trading-Framework.

Wird von allen Betriebsmodi verwendet:
    - Backtesting  : src/backtesting/engine.py
    - Paper Trading: src/trading/engine.py
    - Live Trading : src/trading/engine.py (geplant)

Kennzahlen:
    ROI, CAGR, Sharpe Ratio, Sortino Ratio, Calmar Ratio,
    Profit-Faktor, Win-Rate, Max Drawdown, Fee-Impact,
    Buy-and-Hold Benchmark

Autor: Enes Eryilmaz
Projekt: Grid-Trading-Framework (Bachelorarbeit OST)
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional


# ---------------------------------------------------------------------------
# Trade-Log Helfer
# ---------------------------------------------------------------------------

def _profit_gross(t: dict) -> float:
    """
    Liefert den Brutto-Profit eines Trades (Preisdifferenz × Menge, vor Fee).

    Neue Trade-Logs (ab Brutto-Refactor) haben den Schluessel "profit_gross"
    direkt. Alte Logs haben nur "profit" (netto, nach Sell-Fee). Fallback:
    profit + fee rekonstruiert den Brutto-Wert exakt, weil bei SELLs nur die
    Sell-Fee von profit abgezogen wurde und t["fee"] genau diese Sell-Fee ist.
    """
    if "profit_gross" in t:
        return t["profit_gross"]
    return t.get("profit", 0) + t.get("fee", 0)


# ---------------------------------------------------------------------------
# Drawdown
# ---------------------------------------------------------------------------

@dataclass
class DrawdownResult:
    max_drawdown_pct:     float
    max_drawdown_usdt:    float
    current_drawdown_pct: float


def calculate_drawdown(daily_values: dict) -> DrawdownResult:
    """Max Drawdown aus täglichen Portfolio-Werten."""
    if not daily_values or len(daily_values) < 2:
        return DrawdownResult(0.0, 0.0, 0.0)
    # Chronologisch sortieren (Bot-State aus JSON ist nicht garantiert geordnet)
    values = pd.Series(daily_values).sort_index().tolist()
    peak = values[0]
    max_dd_pct = 0.0
    max_dd_usdt = 0.0
    for v in values:
        peak = max(peak, v)
        dd_pct  = (peak - v) / peak * 100 if peak > 0 else 0
        dd_usdt = peak - v
        if dd_pct > max_dd_pct:
            max_dd_pct  = dd_pct
            max_dd_usdt = dd_usdt
    current_dd = (peak - values[-1]) / peak * 100 if peak > 0 else 0
    return DrawdownResult(
        max_drawdown_pct     = round(max_dd_pct,  4),
        max_drawdown_usdt    = round(max_dd_usdt, 2),
        current_drawdown_pct = round(current_dd,  4),
    )


# ---------------------------------------------------------------------------
# Rendite
# ---------------------------------------------------------------------------

def calculate_roi(initial: float, final: float) -> float:
    """ROI = (final - initial) / initial * 100"""
    if initial <= 0:
        return 0.0
    return round((final - initial) / initial * 100, 4)


def calculate_cagr(
    initial:  float,
    final:    float,
    num_days: float,
) -> Optional[float]:
    """CAGR = (final/initial)^(365/days) - 1"""
    if num_days < 1 or initial <= 0 or final <= 0:
        return None
    try:
        return round(((final / initial) ** (365 / num_days) - 1) * 100, 4)
    except Exception:
        return None


def calculate_calmar_ratio(
    cagr_pct:         Optional[float],
    max_drawdown_pct: float,
) -> Optional[float]:
    """Calmar = CAGR / Max Drawdown. Gut >= 1.0"""
    if cagr_pct is None or max_drawdown_pct <= 0:
        return None
    return round(cagr_pct / max_drawdown_pct, 4)


def calculate_gross_pl(
    initial_value: float,
    final_value:   float,
    fees_paid:     float,
) -> dict:
    """
    Brutto-P/L vor Gebuehren.

    USDT: profit_usdt + fees_paid (Gebuehren rueckgaengig machen)
    Pct : (final + fees) / initial - 1, in %
    """
    if initial_value <= 0:
        return {"usdt": 0.0, "pct": 0.0}
    gross_usdt = (final_value - initial_value) + fees_paid
    gross_pct  = ((final_value + fees_paid) / initial_value - 1) * 100
    return {
        "usdt": round(gross_usdt, 4),
        "pct":  round(gross_pct,  4),
    }


# ---------------------------------------------------------------------------
# Risiko-adjustierte Rendite
# ---------------------------------------------------------------------------

def calculate_sharpe_ratio(
    daily_values:   dict,
    risk_free_rate: float = 0.04,
) -> Optional[float]:
    """Sharpe = (mean_excess_return / std) * sqrt(365). Gut >= 1.0"""
    if len(daily_values) < 2:
        return None
    series  = pd.Series(daily_values).sort_index()
    returns = series.pct_change().dropna()
    if returns.std() == 0:
        return None
    daily_rf = risk_free_rate / 365
    excess   = returns - daily_rf
    sharpe   = (excess.mean() / returns.std()) * np.sqrt(365)
    return round(float(sharpe), 4)


# ---------------------------------------------------------------------------
# Trade-Statistiken
# ---------------------------------------------------------------------------

def calculate_profit_factor(trade_log: list) -> Optional[float]:
    """Profit-Faktor = Bruttogewinn / Bruttoverlust (auf Brutto-Basis). Gut >= 1.5"""
    sells        = [t for t in trade_log if t.get("type") == "SELL"]
    gross_profit = sum(_profit_gross(t) for t in sells if _profit_gross(t) > 0)
    gross_loss   = abs(sum(_profit_gross(t) for t in sells if _profit_gross(t) < 0))
    if gross_loss <= 0:
        return None
    return round(gross_profit / gross_loss, 4)


def calculate_fee_impact(fees_paid: float, gross_pl_usdt: float) -> Optional[float]:
    """
    Fee Impact = Trading Fees / Total Gross P/L * 100.

    Gibt den Anteil der Gebuehren am Brutto-Gewinn (vor Fees) in % an.
    Werte > 100% sind moeglich und korrekt (Fees haben mehr gefressen als
    Brutto-Gewinn war). Bei Brutto-Verlust (gross_pl_usdt <= 0) ist die
    Kennzahl nicht definiert → None.
    """
    if gross_pl_usdt <= 0:
        return None
    return round(fees_paid / gross_pl_usdt * 100, 2)


def calculate_benchmark_roi(
    initial_price: float,
    final_price:   float,
) -> Optional[float]:
    """Buy & Hold ROI = (final - initial) / initial * 100"""
    if initial_price <= 0:
        return None
    return round((final_price - initial_price) / initial_price * 100, 4)


def calculate_benchmark_roi_usdt(
    initial_value: float,
    initial_price: float,
    final_price:   float,
) -> Optional[float]:
    """Buy & Hold absoluter Gewinn in USDT.

    Annahme: Beim Start wird das gesamte initial_value in den Coin investiert.
    Endwert = (initial_value / initial_price) * final_price. PnL = Endwert -
    initial_value.
    """
    if initial_price <= 0 or initial_value <= 0:
        return None
    coin_amount = initial_value / initial_price
    final_val   = coin_amount * final_price
    return round(final_val - initial_value, 4)


# ---------------------------------------------------------------------------
# Komplett-Berechnung
# ---------------------------------------------------------------------------

def calculate_all_metrics(
    trade_log:        list,
    daily_values:     dict,
    initial_value:    float,
    final_value:      float,
    initial_price:    float,
    final_price:      float,
    fees_paid:        float,
    num_days:         float,
    num_grids:        Optional[int]   = None,
    current_price:    Optional[float] = None,
    open_buys:        Optional[list]  = None,
    start_time                         = None,
    fee_rate:         float           = 0.001,
    has_dynamic_capital: bool          = False,
) -> dict:
    """
    Berechnet alle Kennzahlen auf einmal.
    Einheitlicher Einstiegspunkt fuer alle Betriebsmodi.

    Pflicht-Felder (immer im Resultat):
        roi_pct, cagr_pct, calmar_ratio, sharpe_ratio, profit_factor,
        max_drawdown_pct, max_drawdown_usdt, current_drawdown_pct,
        fee_impact_pct, benchmark_roi_pct, benchmark_roi_usdt,
        outperformance_pct,
        avg_profit_per_trade, num_trades, fees_paid, initial_investment,
        final_value, gross_pl_usdt, gross_pl_pct, grid_profit_total_usdt,
        grid_profit_total_pct

    Optional-Felder (nur wenn entsprechender Parameter uebergeben):
        grid_efficiency, active_levels      : wenn num_grids gesetzt
        capital_per_grid                    : wenn num_grids gesetzt
                                              (None bei dynamischem Kapital)
        avg_profit_per_trade_pct            : wenn capital_per_grid bekannt
        current_price                       : wenn current_price gesetzt
        unrealized_pnl                      : wenn open_buys + current_price gesetzt
        runtime                             : wenn start_time gesetzt

    Args:
        has_dynamic_capital: True wenn variable Ordergroessen oder Drawdown-
            Drosselung aktiv sind — dann ist capital_per_grid kein konstanter
            Wert und wird als None geliefert.
    """
    roi    = calculate_roi(initial_value, final_value)
    cagr   = calculate_cagr(initial_value, final_value, num_days)
    dd     = calculate_drawdown(daily_values)
    calmar = calculate_calmar_ratio(cagr, dd.max_drawdown_pct)
    sharpe = calculate_sharpe_ratio(daily_values)
    pf     = calculate_profit_factor(trade_log)
    bh_roi = calculate_benchmark_roi(initial_price, final_price)
    bh_usdt= calculate_benchmark_roi_usdt(initial_value, initial_price, final_price)
    avg_p  = calculate_avg_profit_per_trade(trade_log)
    gross  = calculate_gross_pl(initial_value, final_value, fees_paid)
    gprof  = calculate_grid_profit_total(trade_log, initial_value)
    fee_imp= calculate_fee_impact(fees_paid, gross["usdt"])

    result = {
        "roi_pct":                roi,
        "cagr_pct":               cagr,
        "calmar_ratio":           calmar,
        "sharpe_ratio":           sharpe,
        "profit_factor":          pf,
        "max_drawdown_pct":       dd.max_drawdown_pct,
        "max_drawdown_usdt":      dd.max_drawdown_usdt,
        "current_drawdown_pct":   dd.current_drawdown_pct,
        "fee_impact_pct":         fee_imp,
        "benchmark_roi_pct":      bh_roi,
        "benchmark_roi_usdt":     bh_usdt,
        "outperformance_pct":     round(roi - bh_roi, 4) if bh_roi is not None else None,
        "avg_profit_per_trade":   avg_p,
        "num_trades":             len(trade_log),
        "fees_paid":              round(float(fees_paid), 4),
        "initial_investment":     float(initial_value),
        "final_value":            float(final_value),
        "gross_pl_usdt":          gross["usdt"],
        "gross_pl_pct":           gross["pct"],
        "grid_profit_total_usdt": gprof["usdt"],
        "grid_profit_total_pct":  gprof["pct"],
    }

    if num_grids is not None:
        result["grid_efficiency"]  = calculate_grid_efficiency(trade_log, num_grids)
        result["active_levels"]    = calculate_active_levels_ratio(trade_log, num_grids)
        cap_per_grid               = calculate_capital_per_grid(
            initial_value, num_grids, has_dynamic_capital
        )
        result["capital_per_grid"] = cap_per_grid
        result["avg_profit_per_trade_pct"] = calculate_avg_profit_per_trade_pct(
            avg_p, cap_per_grid
        )

    if current_price is not None:
        result["current_price"] = float(current_price)

    if open_buys is not None and current_price is not None:
        result["unrealized_pnl"] = calculate_unrealized_pnl(
            open_buys, current_price, fee_rate
        )

    if start_time is not None:
        result["runtime"] = calculate_runtime(start_time)

    return result


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def get_num_days(df, interval: str) -> float:
    """Berechnet Anzahl Tage im DataFrame basierend auf Intervall."""
    mins = {"1m":1,"5m":5,"15m":15,"1h":60,"4h":240,"1d":1440}.get(interval, 60)
    return (len(df) * mins) / (60 * 24)


# ---------------------------------------------------------------------------
# Zusätzliche Grid-Bot Metriken
# ---------------------------------------------------------------------------

def calculate_grid_efficiency(trade_log: list, num_grids: int) -> Optional[float]:
    """
    Grid Efficiency = Anzahl aktiv gekreuzter Grid-Levels / Total Grid-Levels * 100
    Zeigt ob die Grid-Grenzen gut gesetzt sind. Gut >= 50%
    """
    if num_grids <= 0:
        return None
    sells = [t for t in trade_log if t.get("type") == "SELL"]
    if not sells:
        return None
    # Einzigartige Preise der Trades = aktive Grid-Levels.
    # Vergleich ueber 6 signifikante Stellen statt 2 Dezimalstellen, sonst
    # kollabieren niedrigpreisige Coins (SHIB ~0.000023) auf einen Wert.
    unique_prices = set(
        f"{t.get('price', 0):.6g}"
        for t in trade_log if t.get("price", 0) > 0
    )
    active_levels = len(unique_prices)
    efficiency = min(active_levels / num_grids * 100, 100.0)
    return round(efficiency, 2)


def calculate_avg_profit_per_trade(trade_log: list) -> Optional[float]:
    """
    Durchschnittlicher Brutto-Gewinn pro abgeschlossenem SELL-Trade in USDT.
    = Grid Profit Total (gross) / Anzahl SELLs. Konsistent mit der Brutto-Linie.
    """
    sells = [t for t in trade_log if t.get("type") == "SELL"]
    if not sells:
        return None
    total_profit_gross = sum(_profit_gross(t) for t in sells)
    return round(total_profit_gross / len(sells), 4)


def calculate_avg_profit_per_trade_pct(
    avg_profit_usdt:  Optional[float],
    capital_per_grid: Optional[float],
) -> Optional[float]:
    """Avg Profit pro Trade in % vom Kapital pro Grid-Linie."""
    if avg_profit_usdt is None or capital_per_grid is None or capital_per_grid <= 0:
        return None
    return round(avg_profit_usdt / capital_per_grid * 100, 4)


def calculate_capital_per_grid(
    total_investment:    float,
    num_grids:           int,
    has_dynamic_capital: bool,
) -> Optional[float]:
    """
    Investierter Betrag pro Grid-Linie.

    None wenn dynamisches Kapital aktiv (variable Ordergroessen oder
    Drawdown-Drosselung) — dann ist der Wert nicht konstant.
    """
    if has_dynamic_capital or num_grids <= 0:
        return None
    return round(total_investment / num_grids, 4)


def calculate_active_levels_ratio(
    trade_log: list,
    num_grids: int,
) -> dict:
    """Anzahl aktiv gehandelter Grid-Levels vs. Total."""
    if num_grids <= 0:
        return {"active": 0, "total": 0}
    unique_prices = set(
        f"{t.get('price', 0):.6g}"
        for t in trade_log if t.get("price", 0) > 0
    )
    return {
        "active": min(len(unique_prices), num_grids),
        "total":  num_grids,
    }


def calculate_grid_profit_total(
    trade_log:     list,
    initial_value: float,
) -> dict:
    """Realisierter Brutto-Gesamtgewinn aus geschlossenen Grid-Trades.

    Summe aller SELL.profit_gross (Preisdifferenz × Menge, vor Fee).
    Pct = total / initial * 100. Brutto-Linie: Fees werden zentral ueber
    Trading Fees abgezogen, nicht hier doppelt.
    """
    total = sum(_profit_gross(t) for t in trade_log if t.get("type") == "SELL")
    pct   = (total / initial_value * 100) if initial_value > 0 else 0.0
    return {
        "usdt": round(total, 4),
        "pct":  round(pct,   4),
    }


def calculate_runtime(start_time) -> dict:
    """
    Berechnet Laufzeit des Bots seit Start.
    
    Args:
        start_time: datetime oder ISO-String des Bot-Starts
    
    Returns:
        dict mit hours, days, formatted string
    """
    try:
        if isinstance(start_time, str):
            start_dt = pd.to_datetime(start_time).to_pydatetime()
        else:
            start_dt = start_time
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=timezone.utc)
        now = datetime.now(tz=timezone.utc)
        delta = now - start_dt
        total_hours = delta.total_seconds() / 3600
        days  = int(total_hours // 24)
        hours = int(total_hours % 24)
        mins  = int((delta.total_seconds() % 3600) / 60)
        if days > 0:
            formatted = f"{days}d {hours}h {mins}m"
        elif hours > 0:
            formatted = f"{hours}h {mins}m"
        else:
            formatted = f"{mins}m"
        return {
            "total_hours": round(total_hours, 2),
            "days":        days,
            "hours":       hours,
            "minutes":     mins,
            "formatted":   formatted,
        }
    except Exception:
        return {"total_hours": 0, "days": 0, "hours": 0, "minutes": 0, "formatted": "–"}


def calculate_unrealized_pnl(
    open_buys:     list,
    current_price: float,
    fee_rate:      float = 0.001,
) -> dict:
    """
    Unrealisierter Brutto-Gewinn/Verlust der offenen BUY-Positionen.

    Brutto-Linie: Bewertung des Coin-Bestands zum Marktpreis vs. dem reinen
    Buy-Preis × Menge — ohne hypothetische Sell-Fee, ohne Buy-Fee. Fees
    werden zentral ueber Trading Fees abgezogen, nicht hier doppelt.

    Args:
        open_buys     : Liste offener BUY-Trades [{"price": x, "amount": y, "fee": z}]
        current_price : Aktueller Marktpreis
        fee_rate      : Erhalten fuer Rueckwaertskompatibilitaet, wird nicht
                        mehr verwendet (Brutto-Berechnung).

    Returns:
        dict mit usdt, pct, num_positions
    """
    if not open_buys or current_price <= 0:
        return {"usdt": 0.0, "pct": 0.0, "num_positions": 0}

    total_cost   = 0.0
    total_value  = 0.0

    for buy in open_buys:
        buy_price = buy.get("price", 0)
        amount    = buy.get("amount", 0)
        if buy_price <= 0 or amount <= 0:
            continue
        cost         = buy_price * amount       # brutto, ohne Buy-Fee
        sell_value   = current_price * amount   # brutto, ohne Sell-Fee
        total_cost  += cost
        total_value += sell_value

    if total_cost <= 0:
        return {"usdt": 0.0, "pct": 0.0, "num_positions": 0}

    pnl_usdt = total_value - total_cost
    pnl_pct  = pnl_usdt / total_cost * 100

    return {
        "usdt":          round(pnl_usdt, 4),
        "pct":           round(pnl_pct,  4),
        "num_positions": len(open_buys),
    }

