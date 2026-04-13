"""
src/strategy/risk.py
====================
Risikoorientierte Kapitalsteuerung fuer den Grid-Bot.
(Bachelorarbeit Ziel 9)

Autor: Enes Eryilmaz
Projekt: Grid-Trading-Framework (Bachelorarbeit OST)
"""

# Backward-Compatibility: Re-Export aus src.metrics
from src.metrics import calculate_drawdown, calculate_kelly_fraction


import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import Optional


@dataclass
class DrawdownResult:
    max_drawdown_pct:     float
    max_drawdown_usdt:    float
    current_drawdown_pct: float
    peak_value:           float
    trough_value:         float
    recovery_days:        Optional[int]


@dataclass
class PositionSizeResult:
    recommended_investment: float
    max_investment:         float
    risk_level:             str
    reasoning:              str


def calculate_drawdown(daily_values: dict) -> DrawdownResult:
    """Berechnet maximalen und aktuellen Drawdown aus daily_values."""
    if not daily_values:
        return DrawdownResult(0.0, 0.0, 0.0, 0.0, 0.0, None)

    series = pd.Series(daily_values)
    series.index = pd.to_datetime(series.index)
    series = series.sort_index()

    running_max = series.cummax()
    dd_series   = (running_max - series) / running_max * 100

    max_dd_pct   = float(dd_series.max())
    max_dd_usdt  = float((running_max - series).max())
    peak_value   = float(running_max.max())
    trough_idx   = dd_series.idxmax()
    trough_value = float(series[trough_idx])
    current_dd   = float(dd_series.iloc[-1])

    if dd_series.max() == 0:
        recovery = 0
    else:
        after = series[trough_idx:]
        rec   = after[after >= float(series[:trough_idx].max())]
        recovery = None if rec.empty else int((rec.index[0] - trough_idx).days)

    return DrawdownResult(
        max_drawdown_pct     = round(max_dd_pct,   2),
        max_drawdown_usdt    = round(max_dd_usdt,  2),
        current_drawdown_pct = round(current_dd,   2),
        peak_value           = round(peak_value,   2),
        trough_value         = round(trough_value, 2),
        recovery_days        = recovery,
    )


def calculate_position_size(
    total_capital:  float,
    atr_pct:        float,
    max_risk_pct:   float = 0.02,
    atr_multiplier: float = 1.5,
) -> PositionSizeResult:
    """
    Berechnet empfohlene Positionsgroesse basierend auf ATR-Volatilitaet.
    Hoehere Volatilitaet = kleinere empfohlene Position.
    """
    if atr_pct <= 0:
        return PositionSizeResult(
            total_capital, total_capital, "unknown", "ATR nicht verfuegbar."
        )

    max_inv = min(
        total_capital,
        (total_capital * max_risk_pct) / (atr_pct / 100 * atr_multiplier),
    )
    rec = min(max_inv * 0.8, total_capital)

    if atr_pct < 1.0:
        lvl, reason = "low",    f"Niedrige Volatilitaet (ATR {atr_pct:.2f}%) – konservativ."
    elif atr_pct < 2.5:
        lvl, reason = "medium", f"Moderate Volatilitaet (ATR {atr_pct:.2f}%) – ausgewogen."
    else:
        lvl, reason = "high",   f"Hohe Volatilitaet (ATR {atr_pct:.2f}%) – reduziert."

    return PositionSizeResult(round(rec, 2), round(max_inv, 2), lvl, reason)


def calculate_kelly_fraction(trade_log: list, total_investment: float) -> dict:
    """
    Berechnet optimale Positionsgroesse nach Kelly-Kriterium (Kelly, 1956).
    Formel: f* = W - (1-W)/R  |  W=Gewinnrate, R=Gewinn/Verlust-Ratio
    Half-Kelly empfohlen fuer konservativeres Risikomanagement.
    """
    closed = [t for t in trade_log if t.get("type") == "SELL"]

    if len(closed) < 5:
        return {
            "kelly_fraction": None, "half_kelly": None,
            "win_rate": None, "win_loss_ratio": None,
            "recommended_capital": total_investment,
            "note": "Zu wenig Trades (mind. 5 SELL-Trades benoetigt).",
        }

    profits  = [t["profit"] for t in closed]
    wins     = [p for p in profits if p > 0]
    losses   = [p for p in profits if p <= 0]
    win_rate = len(wins) / len(profits)
    avg_win  = np.mean(wins)            if wins   else 0.0
    avg_loss = abs(np.mean(losses))     if losses else 1e-10
    wl_ratio = avg_win / avg_loss       if avg_loss > 0 else 0.0
    kelly    = max(0.0, min(win_rate - (1 - win_rate) / wl_ratio if wl_ratio > 0 else 0.0, 1.0))
    hk       = kelly / 2

    return {
        "kelly_fraction":      round(kelly,           4),
        "half_kelly":          round(hk,              4),
        "win_rate":            round(win_rate * 100,  2),
        "win_loss_ratio":      round(wl_ratio,        4),
        "recommended_capital": round(total_investment * hk, 2),
        "note": "Half-Kelly empfohlen fuer konservativeres Risikomanagement.",
    }


def calculate_ruin_probability(
    win_rate:       float,
    win_loss_ratio: float,
    num_trades:     int,
    ruin_threshold: float = 0.5,
) -> dict:
    """
    Schaetzt Ruin-Wahrscheinlichkeit via vereinfachter Gamblers-Ruin-Formel.
    """
    if win_rate <= 0 or win_rate >= 1:
        return {"ruin_probability": None, "assessment": "Ungueltige Gewinnrate."}

    ev = win_rate * win_loss_ratio - (1 - win_rate)

    if ev <= 0:
        ruin_prob  = 1.0
        assessment = "Negatives Erwartungswert – langfristig nicht profitabel."
    else:
        ruin_prob = min(1.0, ((1 - win_rate) / win_rate) ** int(num_trades * ruin_threshold))
        if ruin_prob < 0.05:   assessment = "Sehr geringes Ruinrisiko – robust."
        elif ruin_prob < 0.20: assessment = "Geringes Ruinrisiko – akzeptabel."
        elif ruin_prob < 0.50: assessment = "Moderates Ruinrisiko – Vorsicht."
        else:                  assessment = "Hohes Ruinrisiko – Parameter pruefen."

    return {
        "ruin_probability": round(ruin_prob * 100, 2),
        "expected_value":   round(ev, 4),
        "assessment":       assessment,
    }


def check_capital_protection(
    current_value:      float,
    initial_value:      float,
    current_drawdown:   float,
    max_drawdown_limit: float = 0.25,
    min_capital_pct:    float = 0.50,
) -> dict:
    """Prueft ob Kapitalschutz-Grenzen verletzt werden."""
    warnings, actions, is_safe = [], [], True

    if current_drawdown >= max_drawdown_limit * 100:
        warnings.append(
            f"Drawdown {current_drawdown:.1f}% ueberschreitet Limit {max_drawdown_limit*100:.0f}%"
        )
        actions.append("Grid-Bot pausieren und Parameter ueberpruefen.")
        is_safe = False

    cap_ratio = current_value / initial_value if initial_value > 0 else 1.0
    if cap_ratio < min_capital_pct:
        warnings.append(f"Kapital kritisch: {cap_ratio*100:.1f}%")
        actions.append("Grid-Bot stoppen – Kapital zu niedrig.")
        is_safe = False

    return {
        "is_safe":       is_safe,
        "warnings":      warnings,
        "actions":       actions,
        "capital_ratio": round(cap_ratio * 100, 2),
    }