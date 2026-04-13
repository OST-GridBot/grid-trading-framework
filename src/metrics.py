"""
src/metrics.py
==============
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
from typing import Optional


# ---------------------------------------------------------------------------
# Drawdown
# ---------------------------------------------------------------------------

@dataclass
class DrawdownResult:
    max_drawdown_pct:     float
    max_drawdown_usdt:    float
    current_drawdown_pct: float
    recovery_days:        int


def calculate_drawdown(daily_values: dict) -> DrawdownResult:
    """Max Drawdown aus täglichen Portfolio-Werten."""
    if not daily_values or len(daily_values) < 2:
        return DrawdownResult(0.0, 0.0, 0.0, 0)
    values = list(daily_values.values())
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
        recovery_days        = 0,
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


def calculate_sortino_ratio(
    daily_values:   dict,
    risk_free_rate: float = 0.04,
) -> Optional[float]:
    """Sortino = (mean_excess / downside_std) * sqrt(365). Gut >= 1.0"""
    if len(daily_values) < 2:
        return None
    series   = pd.Series(daily_values).sort_index()
    returns  = series.pct_change().dropna()
    daily_rf = risk_free_rate / 365
    excess   = returns - daily_rf
    downside = excess[excess < 0]
    if len(downside) == 0 or downside.std() == 0:
        return None
    sortino = (excess.mean() / downside.std()) * np.sqrt(365)
    return round(float(sortino), 4)


# ---------------------------------------------------------------------------
# Trade-Statistiken
# ---------------------------------------------------------------------------

def calculate_profit_factor(trade_log: list) -> Optional[float]:
    """Profit-Faktor = Bruttogewinn / Bruttoverlust. Gut >= 1.5"""
    sells        = [t for t in trade_log if t.get("type") == "SELL"]
    gross_profit = sum(t["profit"] for t in sells if t["profit"] > 0)
    gross_loss   = abs(sum(t["profit"] for t in sells if t["profit"] <= 0))
    if gross_loss <= 0:
        return None
    return round(gross_profit / gross_loss, 4)


def calculate_win_rate(trade_log: list) -> Optional[float]:
    """Win-Rate = Anzahl profitable SELLs / Anzahl alle SELLs * 100"""
    sells = [t for t in trade_log if t.get("type") == "SELL"]
    if not sells:
        return None
    wins = [t for t in sells if t["profit"] > 0]
    return round(len(wins) / len(sells) * 100, 2)


def calculate_fee_impact(trade_log: list, fees_paid: float) -> Optional[float]:
    """Fee-Impact = Gebühren / Bruttogewinn * 100"""
    sells        = [t for t in trade_log if t.get("type") == "SELL"]
    gross_profit = sum(t["profit"] + t.get("fee", 0) for t in sells if t["profit"] > 0)
    if gross_profit <= 0:
        return None
    return round(fees_paid / gross_profit * 100, 2)


def calculate_avg_trade_duration(trade_log: list) -> Optional[float]:
    """Durchschnittliche Trade-Dauer in Stunden (BUY → SELL)."""
    buys  = [t for t in trade_log if t.get("type") == "BUY"]
    sells = [t for t in trade_log if t.get("type") == "SELL"]
    pairs = min(len(buys), len(sells))
    if pairs == 0:
        return None
    durations = []
    for i in range(pairs):
        try:
            diff = (pd.to_datetime(sells[i]["timestamp"]) -
                    pd.to_datetime(buys[i]["timestamp"])).total_seconds() / 3600
            if diff >= 0:
                durations.append(diff)
        except Exception:
            continue
    return round(float(np.mean(durations)), 2) if durations else None


def calculate_benchmark_roi(
    initial_price: float,
    final_price:   float,
) -> Optional[float]:
    """Buy & Hold ROI = (final - initial) / initial * 100"""
    if initial_price <= 0:
        return None
    return round((final_price - initial_price) / initial_price * 100, 4)


def calculate_kelly_fraction(
    trade_log:        list,
    total_investment: float,
) -> Optional[float]:
    """Kelly-Kriterium fuer optimale Positionsgrösse."""
    sells = [t for t in trade_log if t.get("type") == "SELL"]
    if not sells:
        return None
    wins   = [t["profit"] for t in sells if t["profit"] > 0]
    losses = [abs(t["profit"]) for t in sells if t["profit"] < 0]
    if not wins or not losses:
        return None
    win_rate  = len(wins) / len(sells)
    avg_win   = np.mean(wins)
    avg_loss  = np.mean(losses)
    if avg_loss == 0:
        return None
    kelly = win_rate - (1 - win_rate) * (avg_win / avg_loss)
    return round(max(0, kelly), 4)


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
) -> dict:
    """
    Berechnet alle Kennzahlen auf einmal.
    Einheitlicher Einstiegspunkt fuer alle Betriebsmodi.
    """
    roi    = calculate_roi(initial_value, final_value)
    cagr   = calculate_cagr(initial_value, final_value, num_days)
    dd     = calculate_drawdown(daily_values)
    sharpe = calculate_sharpe_ratio(daily_values)
    sortino= calculate_sortino_ratio(daily_values)
    calmar = calculate_calmar_ratio(cagr, dd.max_drawdown_pct)
    pf     = calculate_profit_factor(trade_log)
    wr     = calculate_win_rate(trade_log)
    fee_imp= calculate_fee_impact(trade_log, fees_paid)
    bh_roi = calculate_benchmark_roi(initial_price, final_price)
    kelly  = calculate_kelly_fraction(trade_log, initial_value)
    dur    = calculate_avg_trade_duration(trade_log)

    return {
        "roi_pct":              roi,
        "cagr_pct":             cagr,
        "sharpe_ratio":         sharpe,
        "sortino_ratio":        sortino,
        "calmar_ratio":         calmar,
        "profit_factor":        pf,
        "win_rate_pct":         wr,
        "max_drawdown_pct":     dd.max_drawdown_pct,
        "max_drawdown_usdt":    dd.max_drawdown_usdt,
        "current_drawdown_pct": dd.current_drawdown_pct,
        "fee_impact_pct":       fee_imp,
        "benchmark_roi_pct":    bh_roi,
        "outperformance_pct":   round(roi - bh_roi, 4) if bh_roi is not None else None,
        "kelly_fraction":       kelly,
        "avg_trade_duration_h": dur,
    }


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def get_num_days(df, interval: str) -> float:
    """Berechnet Anzahl Tage im DataFrame basierend auf Intervall."""
    mins = {"1m":1,"5m":5,"15m":15,"1h":60,"4h":240,"1d":1440}.get(interval, 60)
    return (len(df) * mins) / (60 * 24)


def calculate_benchmark(sim: dict, total_investment: float) -> dict:
    """Vergleicht Grid-Bot mit Buy-and-Hold."""
    initial_price = sim.get("initial_price", 0)
    final_price   = sim.get("final_price",   0)
    bot_roi       = sim.get("profit_pct",    0)
    if initial_price <= 0:
        return {"bh_roi": None, "outperformance": None}
    bh_roi = round((final_price - initial_price) / initial_price * 100, 4)
    return {
        "bh_roi":         bh_roi,
        "outperformance": round(bot_roi - bh_roi, 4),
    }


def format_metrics_summary(metrics: dict) -> str:
    """Formatiert alle Kennzahlen als lesbaren Text."""
    sep = "=" * 45
    return "\n".join([
        sep, "  KENNZAHLEN", sep,
        f"  ROI              : {metrics.get('roi_pct', 0):>10.2f} %",
        f"  CAGR             : {metrics.get('cagr_pct') or 0:>10.2f} %",
        f"  Sharpe Ratio     : {metrics.get('sharpe_ratio') or 0:>10.4f}",
        f"  Calmar Ratio     : {metrics.get('calmar_ratio') or 0:>10.4f}",
        f"  Profit-Faktor    : {metrics.get('profit_factor') or 0:>10.4f}",
        f"  Win-Rate         : {metrics.get('win_rate_pct') or 0:>10.2f} %",
        f"  Max Drawdown     : {metrics.get('max_drawdown_pct', 0):>10.2f} %",
        sep,
    ])


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
    # Einzigartige Preise der Trades = aktive Grid-Levels
    unique_prices = set(round(t.get("price", 0), 2) for t in trade_log if t.get("price", 0) > 0)
    active_levels = len(unique_prices)
    efficiency = min(active_levels / num_grids * 100, 100.0)
    return round(efficiency, 2)


def calculate_avg_profit_per_trade(trade_log: list) -> Optional[float]:
    """
    Durchschnittlicher Gewinn pro abgeschlossenem SELL-Trade in USDT.
    Zeigt ob einzelne Trades lohnenswert sind.
    """
    sells = [t for t in trade_log if t.get("type") == "SELL"]
    if not sells:
        return None
    total_profit = sum(t.get("profit", 0) for t in sells)
    return round(total_profit / len(sells), 4)


def calculate_runtime(start_time) -> dict:
    """
    Berechnet Laufzeit des Bots seit Start.
    
    Args:
        start_time: datetime oder ISO-String des Bot-Starts
    
    Returns:
        dict mit hours, days, formatted string
    """
    import pandas as pd
    from datetime import datetime, timezone
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
    Unrealisierter Gewinn/Verlust der offenen BUY-Positionen.
    
    Args:
        open_buys     : Liste offener BUY-Trades [{"price": x, "amount": y, "fee": z}]
        current_price : Aktueller Marktpreis
        fee_rate      : Gebührenrate für hypothetischen Verkauf
    
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
        buy_fee   = buy.get("fee", 0)
        if buy_price <= 0 or amount <= 0:
            continue
        cost         = buy_price * amount + buy_fee
        sell_value   = current_price * amount * (1 - fee_rate)
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
