"""
src/backtesting/optimizer.py
============================
Parameter-Optimierung fuer den Grid-Bot.

Optimierungsarten:
    - Grid-Anzahl          : Beste Anzahl Grids finden
    - Range-Optimierung    : Optimale lower/upper Grenzen
    - Modus-Vergleich      : Arithmetic vs. Geometric
    - Grid-Search          : Alle Parameter kombiniert
    - Regime-basiert       : Parameter je nach Marktregime

Optimierungsziele (waehlbar):
    - maximize_roi         : Hoechster Gewinn
    - maximize_sharpe      : Bestes Risiko/Rendite-Verhaeltnis
    - maximize_calmar      : Beste Rendite pro Drawdown
    - minimize_drawdown    : Geringstes Risiko

Theoretischer Hintergrund (Bachelorarbeit Ziel 7):
    Systematische Parameteroptimierung durch Backtesting auf
    historischen Daten. Overfitting-Risiko beachten: Parameter
    die auf vergangenen Daten optimal sind, muessen es auf
    zukuenftigen Daten nicht sein.

Autor: Enes Eryilmaz
Projekt: Grid-Trading-Framework (Bachelorarbeit OST)
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass
from typing import Optional

from config.settings import (
    DEFAULT_FEE_RATE,
    DEFAULT_GRID_MODE,
    DEFAULT_RESERVE_PCT,
    MIN_NUM_GRIDS,
    MAX_NUM_GRIDS,
)
from src.data.cache_manager import get_price_data
from src.strategy.grid_bot import simulate_grid_bot
from src.metrics import calculate_drawdown
from src.metrics import (
    calculate_roi, calculate_cagr, calculate_sharpe_ratio,
    calculate_calmar_ratio, calculate_profit_factor,
    calculate_win_rate, get_num_days,
)
from src.analysis.regime import detect_regime


# ---------------------------------------------------------------------------
# Datenklassen
# ---------------------------------------------------------------------------

@dataclass
class OptimizationResult:
    """
    Ergebnis einer Parameteroptimierung.

    Attributes:
        best_params    : Beste gefundene Parameter
        best_score     : Bester Kennzahlenwert
        objective      : Optimierungsziel
        all_results    : DataFrame mit allen getesteten Kombinationen
        num_tested     : Anzahl getesteter Kombinationen
    """
    best_params:  dict
    best_score:   float
    objective:    str
    all_results:  pd.DataFrame
    num_tested:   int


# ---------------------------------------------------------------------------
# Grid-Anzahl Optimierung
# ---------------------------------------------------------------------------

def optimize_num_grids(
    df:               pd.DataFrame,
    lower_price:      float,
    upper_price:      float,
    total_investment: float  = 10_000.0,
    grid_mode:        str    = DEFAULT_GRID_MODE,
    fee_rate:         float  = DEFAULT_FEE_RATE,
    grid_range:       range  = range(5, 51, 5),
    objective:        str    = "maximize_roi",
) -> OptimizationResult:
    """
    Findet die optimale Grid-Anzahl.

    Testet alle Werte in grid_range und bewertet sie nach objective.

    Args:
        df               : OHLCV-DataFrame
        lower_price      : Untere Grid-Grenze
        upper_price      : Obere Grid-Grenze
        total_investment : Startkapital
        grid_mode        : "arithmetic" oder "geometric"
        fee_rate         : Gebuehrenrate
        grid_range       : Zu testende Grid-Anzahlen
        objective        : Optimierungsziel

    Returns:
        OptimizationResult mit bester Grid-Anzahl und allen Resultaten
    """
    results = []
    num_days = get_num_days(df, "1h")

    for num_grids in grid_range:
        sim = simulate_grid_bot(
            df=df, total_investment=total_investment,
            lower_price=lower_price, upper_price=upper_price,
            num_grids=num_grids, grid_mode=grid_mode, fee_rate=fee_rate,
        )
        if sim.get("error"):
            continue

        score = _calculate_score(sim, df, total_investment, num_days, objective)
        if score is None:
            continue

        dd = calculate_drawdown(sim["daily_values"])
        results.append({
            "num_grids":     num_grids,
            "roi_pct":       round(sim["profit_pct"], 4),
            "sharpe":        calculate_sharpe_ratio(sim["daily_values"]),
            "max_dd_pct":    dd.max_drawdown_pct,
            "num_trades":    sim["num_trades"],
            "fees_paid":     round(sim["fees_paid"], 2),
            "score":         score,
        })

    return _build_result(results, "num_grids", objective)


# ---------------------------------------------------------------------------
# Range-Optimierung
# ---------------------------------------------------------------------------

def optimize_grid_range(
    df:               pd.DataFrame,
    current_price:    float,
    total_investment: float  = 10_000.0,
    num_grids:        int    = 20,
    grid_mode:        str    = DEFAULT_GRID_MODE,
    fee_rate:         float  = DEFAULT_FEE_RATE,
    range_pcts:       list   = None,
    objective:        str    = "maximize_sharpe",
) -> OptimizationResult:
    """
    Findet die optimale Grid-Range.

    Testet verschiedene prozentuale Abstände vom aktuellen Preis.

    Args:
        df               : OHLCV-DataFrame
        current_price    : Aktueller Marktpreis
        total_investment : Startkapital
        num_grids        : Anzahl Grids (fixiert)
        grid_mode        : Grid-Modus
        fee_rate         : Gebuehrenrate
        range_pcts       : Liste zu testender Range-Prozente (z.B. [0.10, 0.15, 0.20])
        objective        : Optimierungsziel

    Returns:
        OptimizationResult mit optimaler Range
    """
    if range_pcts is None:
        range_pcts = [0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50]

    results  = []
    num_days = get_num_days(df, "1h")

    for pct in range_pcts:
        lower = current_price * (1 - pct)
        upper = current_price * (1 + pct)

        sim = simulate_grid_bot(
            df=df, total_investment=total_investment,
            lower_price=lower, upper_price=upper,
            num_grids=num_grids, grid_mode=grid_mode, fee_rate=fee_rate,
        )
        if sim.get("error"):
            continue

        score = _calculate_score(sim, df, total_investment, num_days, objective)
        if score is None:
            continue

        dd = calculate_drawdown(sim["daily_values"])
        results.append({
            "range_pct":     round(pct * 100, 1),
            "lower_price":   round(lower, 2),
            "upper_price":   round(upper, 2),
            "roi_pct":       round(sim["profit_pct"], 4),
            "sharpe":        calculate_sharpe_ratio(sim["daily_values"]),
            "max_dd_pct":    dd.max_drawdown_pct,
            "num_trades":    sim["num_trades"],
            "score":         score,
        })

    return _build_result(results, "range_pct", objective)


# ---------------------------------------------------------------------------
# Modus-Vergleich
# ---------------------------------------------------------------------------

def compare_grid_modes(
    df:               pd.DataFrame,
    lower_price:      float,
    upper_price:      float,
    total_investment: float = 10_000.0,
    num_grids:        int   = 20,
    fee_rate:         float = DEFAULT_FEE_RATE,
    objective:        str   = "maximize_sharpe",
) -> dict:
    """
    Vergleicht arithmetischen und geometrischen Grid-Modus.

    Args:
        df               : OHLCV-DataFrame
        lower_price      : Untere Grid-Grenze
        upper_price      : Obere Grid-Grenze
        total_investment : Startkapital
        num_grids        : Anzahl Grids
        fee_rate         : Gebuehrenrate
        objective        : Vergleichskriterium

    Returns:
        Dictionary mit Ergebnissen beider Modi und Empfehlung
    """
    num_days = get_num_days(df, "1h")
    results  = {}

    for mode in ["arithmetic", "geometric"]:
        sim = simulate_grid_bot(
            df=df, total_investment=total_investment,
            lower_price=lower_price, upper_price=upper_price,
            num_grids=num_grids, grid_mode=mode, fee_rate=fee_rate,
        )
        if sim.get("error"):
            results[mode] = {"error": sim["error"]}
            continue

        dd    = calculate_drawdown(sim["daily_values"])
        cagr  = calculate_cagr(total_investment, sim["final_value"], num_days)
        score = _calculate_score(sim, df, total_investment, num_days, objective)

        results[mode] = {
            "roi_pct":    round(sim["profit_pct"], 4),
            "cagr_pct":   cagr,
            "sharpe":     calculate_sharpe_ratio(sim["daily_values"]),
            "max_dd_pct": dd.max_drawdown_pct,
            "num_trades": sim["num_trades"],
            "fees_paid":  round(sim["fees_paid"], 2),
            "score":      score,
        }

    # Empfehlung
    arith_score = results.get("arithmetic", {}).get("score") or -999
    geo_score   = results.get("geometric",  {}).get("score") or -999
    recommended = "arithmetic" if arith_score >= geo_score else "geometric"

    return {
        "arithmetic":  results.get("arithmetic", {}),
        "geometric":   results.get("geometric",  {}),
        "recommended": recommended,
        "objective":   objective,
    }


# ---------------------------------------------------------------------------
# Grid-Search (Multi-Parameter)
# ---------------------------------------------------------------------------

def grid_search(
    df:               pd.DataFrame,
    current_price:    float,
    total_investment: float  = 10_000.0,
    fee_rate:         float  = DEFAULT_FEE_RATE,
    grid_counts:      list   = None,
    range_pcts:       list   = None,
    modes:            list   = None,
    objective:        str    = "maximize_sharpe",
    max_combinations: int    = 100,
) -> OptimizationResult:
    """
    Vollstaendige Grid-Search ueber alle Parameter.

    Testet alle Kombinationen aus grid_counts x range_pcts x modes.
    Begrenzt auf max_combinations um Laufzeit zu kontrollieren.

    Args:
        df               : OHLCV-DataFrame
        current_price    : Aktueller Marktpreis
        total_investment : Startkapital
        fee_rate         : Gebuehrenrate
        grid_counts      : Liste zu testender Grid-Anzahlen
        range_pcts       : Liste zu testender Range-Prozente
        modes            : Liste zu testender Modi
        objective        : Optimierungsziel
        max_combinations : Maximale Anzahl Kombinationen

    Returns:
        OptimizationResult mit bester Parameterkombination
    """
    if grid_counts is None: grid_counts = [10, 15, 20, 25, 30]
    if range_pcts  is None: range_pcts  = [0.10, 0.15, 0.20, 0.25, 0.30]
    if modes       is None: modes       = ["arithmetic", "geometric"]

    # Alle Kombinationen generieren
    combinations = [
        (g, p, m)
        for g in grid_counts
        for p in range_pcts
        for m in modes
    ][:max_combinations]

    results  = []
    num_days = get_num_days(df, "1h")

    print(f"Grid-Search: {len(combinations)} Kombinationen werden getestet...")

    for i, (num_grids, range_pct, mode) in enumerate(combinations):
        lower = current_price * (1 - range_pct)
        upper = current_price * (1 + range_pct)

        sim = simulate_grid_bot(
            df=df, total_investment=total_investment,
            lower_price=lower, upper_price=upper,
            num_grids=num_grids, grid_mode=mode, fee_rate=fee_rate,
        )
        if sim.get("error"):
            continue

        score = _calculate_score(sim, df, total_investment, num_days, objective)
        if score is None:
            continue

        dd = calculate_drawdown(sim["daily_values"])
        results.append({
            "num_grids":   num_grids,
            "range_pct":   round(range_pct * 100, 1),
            "mode":        mode,
            "lower_price": round(lower, 2),
            "upper_price": round(upper, 2),
            "roi_pct":     round(sim["profit_pct"], 4),
            "sharpe":      calculate_sharpe_ratio(sim["daily_values"]),
            "max_dd_pct":  dd.max_drawdown_pct,
            "num_trades":  sim["num_trades"],
            "fees_paid":   round(sim["fees_paid"], 2),
            "score":       score,
        })

        if (i + 1) % 10 == 0:
            print(f"  {i+1}/{len(combinations)} getestet...")

    return _build_result(results, ["num_grids", "range_pct", "mode"], objective)


# ---------------------------------------------------------------------------
# Regime-basierte Optimierung
# ---------------------------------------------------------------------------

def optimize_by_regime(
    df:               pd.DataFrame,
    current_price:    float,
    total_investment: float = 10_000.0,
    fee_rate:         float = DEFAULT_FEE_RATE,
    interval:         str   = "1h",
    objective:        str   = "maximize_sharpe",
) -> dict:
    """
    Gibt optimale Parameter basierend auf dem aktuellen Marktregime zurueck.

    Logik (Bachelorarbeit Ziel 8):
        Range-Markt  : Mehr Grids, engere Range (mehr Trades = mehr Gewinn)
        Trend-Markt  : Weniger Grids, weitere Range (Trend folgen)

    Args:
        df               : OHLCV-DataFrame
        current_price    : Aktueller Marktpreis
        total_investment : Startkapital
        fee_rate         : Gebuehrenrate
        interval         : Kerzen-Intervall
        objective        : Optimierungsziel

    Returns:
        Dictionary mit regime-spezifischen Parametern und Begruendung
    """
    regime_result = detect_regime(df, interval)
    regime        = regime_result.regime

    if regime == "range":
        grid_counts = [20, 25, 30, 35, 40]
        range_pcts  = [0.10, 0.15, 0.20]
        reasoning   = "Range-Markt: Mehr Grids, engere Range fuer haeufigere Trades."
    elif regime == "trend_up":
        grid_counts = [10, 15, 20]
        range_pcts  = [0.20, 0.30, 0.40]
        reasoning   = "Aufwaertstrend: Weiterer Range nach oben, weniger Grids."
    elif regime == "trend_down":
        grid_counts = [10, 15, 20]
        range_pcts  = [0.20, 0.25, 0.30]
        reasoning   = "Abwaertstrend: Vorsicht – Grid-Bot nur mit Stop-Loss empfohlen."
    else:
        grid_counts = [15, 20, 25]
        range_pcts  = [0.15, 0.20, 0.25]
        reasoning   = "Unklares Regime: Konservative Standardparameter."

    opt = grid_search(
        df=df, current_price=current_price,
        total_investment=total_investment, fee_rate=fee_rate,
        grid_counts=grid_counts, range_pcts=range_pcts,
        modes=["arithmetic", "geometric"],
        objective=objective, max_combinations=50,
    )

    return {
        "regime":       regime,
        "confidence":   regime_result.confidence,
        "reasoning":    reasoning,
        "best_params":  opt.best_params,
        "best_score":   opt.best_score,
        "objective":    objective,
        "all_results":  opt.all_results,
    }


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def _calculate_score(
    sim:              dict,
    df:               pd.DataFrame,
    total_investment: float,
    num_days:         float,
    objective:        str,
) -> Optional[float]:
    """Berechnet den Score fuer ein Optimierungsziel."""
    daily_values = sim.get("daily_values", {})
    final_value  = sim.get("final_value", total_investment)

    if objective == "maximize_roi":
        return sim.get("profit_pct")

    elif objective == "maximize_sharpe":
        return calculate_sharpe_ratio(daily_values)

    elif objective == "maximize_calmar":
        cagr = calculate_cagr(total_investment, final_value, num_days)
        dd   = calculate_drawdown(daily_values)
        return calculate_calmar_ratio(cagr, dd.max_drawdown_pct)

    elif objective == "minimize_drawdown":
        dd = calculate_drawdown(daily_values)
        return -dd.max_drawdown_pct  # Negativ weil wir minimieren wollen

    return sim.get("profit_pct")


def _build_result(
    results:     list,
    param_key,
    objective:   str,
) -> OptimizationResult:
    """Baut ein OptimizationResult aus einer Liste von Ergebnissen."""
    if not results:
        return OptimizationResult(
            best_params  = {},
            best_score   = 0.0,
            objective    = objective,
            all_results  = pd.DataFrame(),
            num_tested   = 0,
        )

    df_results  = pd.DataFrame(results).sort_values("score", ascending=False)
    best_row    = df_results.iloc[0]

    if isinstance(param_key, list):
        best_params = {k: best_row[k] for k in param_key}
    else:
        best_params = {param_key: best_row[param_key]}

    # Zusaetzliche Kennzahlen in best_params aufnehmen
    for col in ["roi_pct", "sharpe", "max_dd_pct", "num_trades"]:
        if col in best_row:
            best_params[col] = best_row[col]

    return OptimizationResult(
        best_params  = best_params,
        best_score   = float(best_row["score"]),
        objective    = objective,
        all_results  = df_results.reset_index(drop=True),
        num_tested   = len(results),
    )