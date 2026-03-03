"""
src/backtesting/metrics.py
==========================
Kennzahlen-Bibliothek fuer die Backtesting-Auswertung.

Kennzahlen (Bachelorarbeit Ziel 6):
    ROI, CAGR, Sharpe, Sortino, Calmar, Profit-Faktor,
    Win-Rate, Fee-Impact, Buy-and-Hold Benchmark

Autor: Enes Eryilmaz
Projekt: Grid-Trading-Framework (Bachelorarbeit OST)
"""

import numpy as np
import pandas as pd
from typing import Optional


def calculate_all_metrics(sim, df, total_investment, interval="1h"):
    """
    Berechnet alle Kennzahlen aus einem Simulationsergebnis.
    Gibt ein Dictionary mit saemtlichen Performance-Metriken zurueck.
    """
    trade_log    = sim.get("trade_log", [])
    daily_values = sim.get("daily_values", {})
    final_value  = sim.get("final_value", total_investment)
    fees_paid    = sim.get("fees_paid", 0.0)
    num_days     = _get_num_days(df, interval)

    roi     = calculate_roi(total_investment, final_value)
    cagr    = calculate_cagr(total_investment, final_value, num_days)
    sharpe  = calculate_sharpe_ratio(daily_values)
    sortino = calculate_sortino_ratio(daily_values)
    pf      = calculate_profit_factor(trade_log)
    wr      = calculate_win_rate(trade_log)
    avg_dur = calculate_avg_trade_duration(trade_log)
    fee_imp = calculate_fee_impact(trade_log, fees_paid)
    bench   = calculate_benchmark(sim, total_investment)

    from src.strategy.risk import calculate_drawdown
    dd     = calculate_drawdown(daily_values)
    calmar = calculate_calmar_ratio(cagr, dd.max_drawdown_pct)

    return {
        "roi_pct":              roi,
        "cagr_pct":             cagr,
        "sharpe_ratio":         sharpe,
        "sortino_ratio":        sortino,
        "calmar_ratio":         calmar,
        "profit_factor":        pf["profit_factor"],
        "gross_profit":         pf["gross_profit"],
        "gross_loss":           pf["gross_loss"],
        "win_rate_pct":         wr["win_rate"],
        "num_wins":             wr["num_wins"],
        "num_losses":           wr["num_losses"],
        "avg_win_usdt":         wr["avg_win"],
        "avg_loss_usdt":        wr["avg_loss"],
        "avg_trade_duration_h": avg_dur,
        "fee_impact_pct":       fee_imp,
        "benchmark_roi_pct":    bench["bh_roi"],
        "outperformance_pct":   bench["outperformance"],
        "max_drawdown_pct":     dd.max_drawdown_pct,
        "recovery_days":        dd.recovery_days,
    }


def calculate_roi(initial: float, final: float) -> float:
    """
    Berechnet den Return on Investment in %.
    Formel: ROI = (final - initial) / initial * 100
    """
    if initial <= 0:
        return 0.0
    return round((final - initial) / initial * 100, 4)


def calculate_cagr(initial, final, num_days) -> Optional[float]:
    """
    Berechnet CAGR (Compound Annual Growth Rate).
    Normiert Renditen auf ein Jahr fuer Vergleichbarkeit.
    Formel: CAGR = (final/initial)^(365/days) - 1
    """
    if num_days < 1 or initial <= 0 or final <= 0:
        return None
    try:
        return round(((final / initial) ** (365 / num_days) - 1) * 100, 4)
    except Exception:
        return None


def calculate_sharpe_ratio(daily_values, risk_free_rate=0.04) -> Optional[float]:
    """
    Berechnet die Sharpe Ratio.
    Misst risikoadjustierte Rendite (Rendite pro Gesamtrisiko-Einheit).
    Formel: Sharpe = (mean_excess_return / std_return) * sqrt(365)
    Interpretation: >1 gut, >2 sehr gut, <0 schlecht.
    """
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


def calculate_sortino_ratio(daily_values, risk_free_rate=0.04) -> Optional[float]:
    """
    Berechnet die Sortino Ratio.
    Wie Sharpe, aber nur Downside-Volatilitaet wird beruecksichtigt.
    Fairer fuer asymmetrische Strategien wie Grid-Bots.
    Interpretation: >1 gut, >2 sehr gut.
    """
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


def calculate_calmar_ratio(cagr_pct, max_drawdown_pct) -> Optional[float]:
    """
    Berechnet die Calmar Ratio (CAGR / Max Drawdown).
    Hohe Calmar = gute Rendite bei geringem Risiko.
    Interpretation: >1 gut, >3 sehr gut.
    """
    if cagr_pct is None or max_drawdown_pct <= 0:
        return None
    return round(cagr_pct / max_drawdown_pct, 4)


def calculate_profit_factor(trade_log: list) -> dict:
    """
    Berechnet Profit-Faktor = Bruttogewinn / Bruttoverlust.
    Interpretation: >1 profitabel, >2 sehr gut.
    """
    sells        = [t for t in trade_log if t.get("type") == "SELL"]
    gross_profit = sum(t["profit"] for t in sells if t["profit"] > 0)
    gross_loss   = abs(sum(t["profit"] for t in sells if t["profit"] <= 0))
    pf = round(gross_profit / gross_loss, 4) if gross_loss > 0 else None
    return {
        "profit_factor": pf,
        "gross_profit":  round(gross_profit, 4),
        "gross_loss":    round(gross_loss,   4),
    }


def calculate_win_rate(trade_log: list) -> dict:
    """Berechnet Win-Rate und durchschnittliche Gewinne/Verluste."""
    sells = [t for t in trade_log if t.get("type") == "SELL"]
    if not sells:
        return {"win_rate": None, "num_wins": 0, "num_losses": 0,
                "avg_win": 0.0, "avg_loss": 0.0}
    wins   = [t["profit"] for t in sells if t["profit"] > 0]
    losses = [t["profit"] for t in sells if t["profit"] <= 0]
    return {
        "win_rate":   round(len(wins) / len(sells) * 100, 2),
        "num_wins":   len(wins),
        "num_losses": len(losses),
        "avg_win":    round(np.mean(wins),   4) if wins   else 0.0,
        "avg_loss":   round(np.mean(losses), 4) if losses else 0.0,
    }


def calculate_avg_trade_duration(trade_log: list) -> Optional[float]:
    """
    Berechnet durchschnittliche Dauer eines Grid-Zyklus in Stunden.
    Ein Zyklus = Zeit zwischen BUY und naechstem SELL.
    """
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


def calculate_fee_impact(trade_log: list, fees_paid: float) -> Optional[float]:
    """
    Berechnet Gebuehrenanteil am Bruttogewinn in %.
    Hoher Fee-Impact deutet auf zu viele Grids oder zu enge Range hin.
    """
    sells        = [t for t in trade_log if t.get("type") == "SELL"]
    gross_profit = sum(t["profit"] + t.get("fee", 0) for t in sells if t["profit"] > 0)
    if gross_profit <= 0:
        return None
    return round(fees_paid / gross_profit * 100, 2)


def calculate_benchmark(sim: dict, total_investment: float) -> dict:
    """
    Vergleicht Grid-Bot mit Buy-and-Hold Strategie.
    Outperformance = Bot-ROI - Buy-and-Hold-ROI.
    """
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


def _get_num_days(df: pd.DataFrame, interval: str) -> float:
    """Berechnet Anzahl Tage im DataFrame basierend auf Intervall."""
    mins = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440}.get(interval, 60)
    return (len(df) * mins) / (60 * 24)


def format_metrics_summary(metrics: dict) -> str:
    """Formatiert alle Kennzahlen als lesbaren Text fuer Debugging."""
    sep = "=" * 45
    return "\n".join([
        sep,
        "  BACKTESTING KENNZAHLEN",
        sep,
        f"  ROI              : {metrics.get('roi_pct', 0):>10.2f} %",
        f"  CAGR             : {metrics.get('cagr_pct') or 0:>10.2f} %",
        f"  Sharpe Ratio     : {metrics.get('sharpe_ratio') or 0:>10.4f}",
        f"  Sortino Ratio    : {metrics.get('sortino_ratio') or 0:>10.4f}",
        f"  Calmar Ratio     : {metrics.get('calmar_ratio') or 0:>10.4f}",
        f"  Profit-Faktor    : {metrics.get('profit_factor') or 0:>10.4f}",
        f"  Win-Rate         : {metrics.get('win_rate_pct') or 0:>10.2f} %",
        f"  Max Drawdown     : {metrics.get('max_drawdown_pct', 0):>10.2f} %",
        f"  Fee Impact       : {metrics.get('fee_impact_pct') or 0:>10.2f} %",
        f"  BnH ROI          : {metrics.get('benchmark_roi_pct') or 0:>10.2f} %",
        f"  Outperformance   : {metrics.get('outperformance_pct') or 0:>10.2f} %",
        sep,
    ]
    )