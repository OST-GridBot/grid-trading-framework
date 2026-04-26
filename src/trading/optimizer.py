"""
src/trading/optimizer.py
========================
Parametrisierungsvorschlag fuer Paper-Trading und Live-Trading.

Analysiert historische Marktdaten und schlaegt optimale Grid-Parameter vor.
Anders als der Backtesting-Optimizer ist dieser auf Echtzeit-Handel ausgerichtet:
- Berechnet ATR und Volatilitaet der letzten X Tage
- Erkennt aktuelles Marktregime (Range vs. Trend)
- Schlaegt optimale Preisrange, Grid-Anzahl und Modus vor
- Gibt Empfehlung als lesbaren Text zurueck (kein automatischer Eingriff)

Autor: Enes Eryilmaz
Projekt: Grid-Trading-Framework (Bachelorarbeit OST)
"""

import pandas as pd
from dataclasses import dataclass
from typing import Optional

from src.data.cache_manager import get_price_data
from src.analysis.indicators import get_atr_stats
from src.analysis.regime import detect_regime
from src.strategy.grid_bot import simulate_grid_bot
from src.metrics import calculate_sharpe_ratio, calculate_drawdown, calculate_cagr, get_num_days
from config.settings import DEFAULT_FEE_RATE, DEFAULT_RESERVE_PCT


# ---------------------------------------------------------------------------
# Datenklasse
# ---------------------------------------------------------------------------

@dataclass
class ParameterSuggestion:
    """
    Parametrisierungsvorschlag fuer einen Grid-Bot.

    Attributes:
        coin           : Kryptowährung
        interval       : Empfohlenes Intervall
        lower_price    : Empfohlene untere Grenze
        upper_price    : Empfohlene obere Grenze
        num_grids      : Empfohlene Anzahl Grids
        grid_mode      : Empfohlener Modus (arithmetic/geometric)
        regime         : Erkanntes Marktregime
        confidence     : Konfidenz der Regime-Erkennung
        atr_usdt       : ATR in USDT
        atr_pct        : ATR in %
        reasoning      : Begruendung der Empfehlung
        objective      : Optimierungsziel
        score          : Erreichter Score
        roi_pct        : Erwarteter ROI (auf historischen Daten)
        sharpe         : Erwartete Sharpe Ratio
        max_dd_pct     : Erwarteter Max Drawdown
        warning        : Warnung falls Markt ungeeignet
    """
    coin:        str
    interval:    str
    lower_price: float
    upper_price: float
    num_grids:   int
    grid_mode:   str
    regime:      str
    confidence:  float
    atr_usdt:    float
    atr_pct:     float
    reasoning:   str
    objective:   str
    score:       float
    roi_pct:     float
    sharpe:      float
    max_dd_pct:  float
    warning:     Optional[str] = None


# ---------------------------------------------------------------------------
# Hauptfunktion
# ---------------------------------------------------------------------------

def suggest_parameters(
    coin:             str,
    total_investment: float = 10_000.0,
    fee_rate:         float = DEFAULT_FEE_RATE,
    lookback_days:    int   = 14,
    interval:         str   = "1h",
    objective:        str   = "maximize_sharpe",
) -> ParameterSuggestion:
    """
    Analysiert historische Daten und schlaegt optimale Grid-Parameter vor.

    Vorgehen:
        1. Historische Daten laden (lookback_days)
        2. ATR berechnen → Range-Groesse bestimmen
        3. Marktregime erkennen → Parameter anpassen
        4. Grid-Search ueber plausible Kombinationen
        5. Besten Vorschlag als ParameterSuggestion zurueckgeben

    Args:
        coin             : Kryptowährung (z.B. "BTC")
        total_investment : Startkapital in USDT
        fee_rate         : Gebuehrenrate
        lookback_days    : Anzahl historischer Tage fuer Analyse
        interval         : Kerzen-Intervall
        objective        : Optimierungsziel

    Returns:
        ParameterSuggestion mit allen Empfehlungen und Begruendungen
    """
    # 1. Daten laden
    df, _ = get_price_data(coin, days=lookback_days, interval=interval)
    if df is None or df.empty:
        raise ValueError(f"Keine Daten für {coin} verfügbar.")

    current_price = float(df["close"].iloc[-1])

    # 2. ATR berechnen
    atr_usdt, atr_pct = get_atr_stats(df)

    # 3. Marktregime erkennen
    regime_result = detect_regime(df, interval)
    regime        = regime_result.regime
    confidence    = regime_result.confidence

    # 4. Parameter-Kandidaten je nach Regime
    if regime == "range":
        grid_counts = [15, 20, 25, 30]
        range_pcts  = [0.10, 0.15, 0.20]
        modes       = ["arithmetic", "geometric"]
        reasoning_base = (
            f"Range-Markt erkannt (ADX14: {regime_result.adx14:.1f}, "
            f"Konfidenz: {confidence:.0f}%). "
            f"Grid-Bots sind in Seitwärtsmärkten besonders effektiv. "
            f"Engere Range und mehr Grids empfohlen für häufigere Trades."
        )
        warning = None

    elif regime == "trend_up":
        grid_counts = [10, 15, 20]
        range_pcts  = [0.20, 0.30, 0.40]
        modes       = ["arithmetic", "geometric"]
        reasoning_base = (
            f"Aufwärtstrend erkannt (ADX14: {regime_result.adx14:.1f}, "
            f"Konfidenz: {confidence:.0f}%). "
            f"Weiterer Grid-Bereich nach oben empfohlen. "
            f"Weniger Grids um Gebühren zu minimieren."
        )
        warning = (
            "⚠️ Trendmarkt: Grid-Bots sind in Trendmärkten weniger geeignet. "
            "Stop-Loss aktivieren und enges Risikomanagement empfohlen."
        )

    elif regime == "trend_down":
        grid_counts = [10, 15]
        range_pcts  = [0.15, 0.20, 0.25]
        modes       = ["arithmetic"]
        reasoning_base = (
            f"Abwärtstrend erkannt (ADX14: {regime_result.adx14:.1f}, "
            f"Konfidenz: {confidence:.0f}%). "
            f"Vorsicht geboten. Konservative Parameter empfohlen."
        )
        warning = (
            "⚠️ Abwärtstrend: Grid-Bots sind in fallenden Märkten mit erhöhtem "
            "Verlustrisiko verbunden. Stop-Loss dringend empfohlen."
        )

    else:  # neutral
        grid_counts = [15, 20, 25]
        range_pcts  = [0.15, 0.20, 0.25]
        modes       = ["arithmetic", "geometric"]
        reasoning_base = (
            f"Unklares Marktregime (ADX14: {regime_result.adx14:.1f}, "
            f"Konfidenz: {confidence:.0f}%). "
            f"Konservative Standardparameter empfohlen."
        )
        warning = "ℹ️ Marktlage unklar — Ergebnisse mit Vorsicht interpretieren."

    # 5. Grid-Search
    best_score  = -999
    best_params = None
    best_sim    = None
    num_days    = get_num_days(df, interval)

    for num_grids in grid_counts:
        for range_pct in range_pcts:
            for mode in modes:
                lower = current_price * (1 - range_pct)
                upper = current_price * (1 + range_pct)

                sim = simulate_grid_bot(
                    df=df,
                    total_investment=total_investment,
                    lower_price=lower,
                    upper_price=upper,
                    num_grids=num_grids,
                    grid_mode=mode,
                    fee_rate=fee_rate,
                )
                if sim.get("error") or not sim.get("daily_values"):
                    continue

                # Score berechnen
                score = _score(sim, total_investment, num_days, objective)
                if score is None:
                    continue

                if score > best_score:
                    best_score  = score
                    best_params = (num_grids, range_pct, mode, lower, upper)
                    best_sim    = sim

    if best_params is None or best_sim is None:
        raise ValueError("Keine gültige Parameterkombination gefunden.")

    num_grids, range_pct, mode, lower, upper = best_params

    # 6. Kennzahlen aus bestem Backtest
    dd     = calculate_drawdown(best_sim["daily_values"])
    sharpe = calculate_sharpe_ratio(best_sim["daily_values"])
    roi    = best_sim["profit_pct"]

    # 7. Reasoning zusammenstellen
    mode_label = "Arithmetisch" if mode == "arithmetic" else "Geometrisch"
    reasoning  = (
        f"{reasoning_base}\n\n"
        f"ATR ({lookback_days}d): {atr_usdt:,.2f} USDT ({atr_pct:.2f}%) — "
        f"{'hohe' if atr_pct > 3 else 'moderate' if atr_pct > 1.5 else 'tiefe'} Volatilität.\n\n"
        f"Optimierungsziel: {_objective_label(objective)}\n"
        f"Getestete Kombinationen: {len(grid_counts) * len(range_pcts) * len(modes)}\n\n"
        f"Beste Kombination auf historischen Daten ({lookback_days}d):\n"
        f"• Modus: {mode_label}\n"
        f"• Anzahl Grids: {num_grids}\n"
        f"• Range: ±{range_pct*100:.0f}% → ${lower:,.2f} – ${upper:,.2f}\n"
        f"• ROI: {roi:+.2f}% | Sharpe: {sharpe:.2f} | Max DD: {dd.max_drawdown_pct:.2f}%\n\n"
        f"⚠️ Hinweis: Historische Ergebnisse sind kein Indikator für zukünftige Performance."
    )

    return ParameterSuggestion(
        coin        = coin,
        interval    = interval,
        lower_price = round(lower, 2),
        upper_price = round(upper, 2),
        num_grids   = num_grids,
        grid_mode   = mode,
        regime      = regime,
        confidence  = confidence,
        atr_usdt    = round(atr_usdt, 2),
        atr_pct     = round(atr_pct, 2),
        reasoning   = reasoning,
        objective   = objective,
        score       = round(best_score, 4),
        roi_pct     = round(roi, 2),
        sharpe      = round(sharpe, 2),
        max_dd_pct  = round(dd.max_drawdown_pct, 2),
        warning     = warning,
    )


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def _score(
    sim:              dict,
    total_investment: float,
    num_days:         float,
    objective:        str,
) -> Optional[float]:
    """Berechnet Score fuer Optimierungsziel."""
    dv = sim.get("daily_values", {})
    fv = sim.get("final_value", total_investment)

    if objective == "maximize_roi":
        return sim.get("profit_pct")
    elif objective == "maximize_sharpe":
        return calculate_sharpe_ratio(dv)
    elif objective == "maximize_calmar":
        cagr = calculate_cagr(total_investment, fv, num_days)
        dd   = calculate_drawdown(dv)
        return calculate_calmar_ratio(cagr, dd.max_drawdown_pct)
    elif objective == "minimize_drawdown":
        dd = calculate_drawdown(dv)
        return -dd.max_drawdown_pct
    return sim.get("profit_pct")


def _objective_label(objective: str) -> str:
    return {
        "maximize_roi":      "Höchster ROI",
        "maximize_sharpe":   "Bestes Risiko/Rendite (Sharpe)",
        "maximize_calmar":   "Beste Rendite pro Drawdown (Calmar)",
        "minimize_drawdown": "Geringstes Risiko (Min. Drawdown)",
    }.get(objective, objective)


def calculate_calmar_ratio(cagr: float, max_dd: float) -> float:
    if max_dd == 0:
        return 0.0
    return round(cagr / max_dd, 4)
