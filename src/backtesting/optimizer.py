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
from src.analysis.metrics import calculate_drawdown
from src.analysis.metrics import (
    calculate_roi, calculate_cagr, calculate_sharpe_ratio,
    calculate_calmar_ratio, calculate_profit_factor,
    get_num_days,
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
# Multi-Parameter Optimierung (Anzahl Grids + Modus + Recentering)
# ---------------------------------------------------------------------------

def optimize_full_grid_search(
    df:               pd.DataFrame,
    lower_price:      float,
    upper_price:      float,
    total_investment: float = 10_000.0,
    fee_rate:         float = DEFAULT_FEE_RATE,
    grid_range:       range = range(5, 51, 5),
    modes:            list  = None,
    test_recentering: bool  = True,
    recenter_threshold: float = 0.05,
    objective:        str   = "maximize_roi",
    interval:         str   = "1h",
) -> OptimizationResult:
    """
    Vollständige Multi-Parameter-Suche.

    Variiert: num_grids, grid_mode (4 Optionen), Recentering (Up+Down an/aus)
    Range (lower/upper) bleibt fix wie vom User definiert.

    Args:
        df               : OHLCV-DataFrame
        lower_price      : Untere Grid-Grenze (fix)
        upper_price      : Obere Grid-Grenze (fix)
        total_investment : Startkapital
        fee_rate         : Gebuehrenrate
        grid_range       : Zu testende Grid-Anzahlen
        modes            : Liste Grid-Modi (default: alle 4)
        test_recentering : ob Recentering an/aus mitgetestet werden soll
        recenter_threshold: Recentering-Schwelle wenn aktiv (default 5%)
        objective        : Optimierungsziel

    Returns:
        OptimizationResult mit bester Kombination
    """
    if modes is None:
        modes = ["arithmetic", "geometric", "asymmetric_bottom", "asymmetric_top"]

    recenter_options = [False, True] if test_recentering else [False]

    results  = []
    num_days = get_num_days(df, interval)

    for num_grids in grid_range:
        for mode in modes:
            for use_rc in recenter_options:
                sim = simulate_grid_bot(
                    df=df, total_investment=total_investment,
                    lower_price=lower_price, upper_price=upper_price,
                    num_grids=num_grids, grid_mode=mode, fee_rate=fee_rate,
                    enable_recentering_up=use_rc,
                    enable_recentering_down=use_rc,
                    recenter_threshold=recenter_threshold if use_rc else 0.05,
                )
                if sim.get("error"):
                    continue

                score = _calculate_score(sim, df, total_investment, num_days, objective)
                if score is None:
                    continue

                dd = calculate_drawdown(sim["daily_values"])
                results.append({
                    "num_grids":          num_grids,
                    "grid_mode":          mode,
                    "enable_recentering_up":   use_rc,
                    "enable_recentering_down": use_rc,
                    "lower_price":        round(lower_price, 4),
                    "upper_price":        round(upper_price, 4),
                    "roi_pct":            round(sim["profit_pct"], 4),
                    "calmar":             calculate_calmar_ratio(calculate_cagr(total_investment, sim["final_value"], num_days), dd.max_drawdown_pct),
                    "max_dd_pct":         dd.max_drawdown_pct,
                    "num_trades":         sim["num_trades"],
                    "fees_paid":          round(sim["fees_paid"], 2),
                    "score":              score,
                })

    return _build_result(results, ["num_grids", "grid_mode", "enable_recentering_up", "enable_recentering_down", "lower_price", "upper_price"], objective)


# ---------------------------------------------------------------------------
# SmartGridSetup
# ---------------------------------------------------------------------------

@dataclass
class SmartSetupResult:
    """Ergebnis des SmartGridSetup."""
    lower_price:          float
    upper_price:          float
    num_grids:            int
    grid_mode:            str
    enable_recentering_up:   bool
    enable_recentering_down: bool
    enable_trailing_up:   bool
    enable_trailing_down: bool
    trailing_up_stop:     Optional[float]
    trailing_down_stop:   Optional[float]
    expected_roi_pct:     float
    num_tested:           int
    stop_loss_pct:           Optional[float] = None
    enable_dd_throttle:      bool = False
    enable_variable_orders:  bool = False


def smart_grid_setup(
    df:               pd.DataFrame,
    total_investment: float = 10_000.0,
    fee_rate:         float = DEFAULT_FEE_RATE,
    objective:        str   = "maximize_roi",
    interval:         str   = "1h",
):
    """
    SmartGridSetup: Findet die optimale Bot-Konfiguration je nach Optimierungsziel.

    Fundament (immer dabei):
        - Range (+/-5%, +/-10%, +/-15%, +/-20% um Median)
        - Anzahl Grids (5, 10, 15, 20, 25, 30)
        - Grid-Modus (4 Optionen)

    Pro Ziel zusaetzlich:
        - maximize_roi:        Recentering ⊕ Trailing
        - maximize_sharpe:     Recentering ⊕ Trailing + Variable Orders
        - maximize_calmar:     Recentering ⊕ Trailing + DD-Drosselung
        - minimize_drawdown:   Stop-Loss + DD-Drosselung (kein Recenter/Trailing)
    """
    if df is None or df.empty:
        return None

    median_price = float(df["close"].median())

    range_pcts  = [0.05, 0.10, 0.15, 0.20]
    grid_counts = [5, 10, 15, 20, 25, 30]
    modes       = ["arithmetic", "geometric", "asymmetric_bottom", "asymmetric_top"]

    # Mechanismus-Optionen je nach Ziel
    if objective == "minimize_drawdown":
        # Kein Recenter/Trailing — nur SL + DD
        mech_options = [0]  # immer ohne dynamische Mechanismen
        sl_options   = [None, 0.20]  # Stop-Loss aus / 20%
        dd_options   = [False, True]  # DD-Drosselung aus / an
        vo_options   = [False]
    elif objective == "maximize_calmar":
        mech_options = [0, 1, 2]
        sl_options   = [None]
        dd_options   = [False, True]
        vo_options   = [False]
    elif objective == "maximize_sharpe":
        mech_options = [0, 1, 2]
        sl_options   = [None]
        dd_options   = [False]
        vo_options   = [False, True]
    else:  # maximize_roi
        mech_options = [0, 1, 2]
        sl_options   = [None]
        dd_options   = [False]
        vo_options   = [False]

    num_days = get_num_days(df, interval)

    best_score = -float("inf")
    best_cfg   = None
    num_tested = 0

    for range_pct in range_pcts:
        lower = median_price * (1 - range_pct)
        upper = median_price * (1 + range_pct)

        for num_grids in grid_counts:
            for mode in modes:
                for mech in mech_options:
                    for sl in sl_options:
                        for dd_on in dd_options:
                            for vo_on in vo_options:
                                use_recenter = (mech == 1)
                                use_trailing = (mech == 2)
                                tr_up_stop = upper * 1.20 if use_trailing else None
                                tr_dn_stop = lower * 0.80 if use_trailing else None

                                sim = simulate_grid_bot(
                                    df=df, total_investment=total_investment,
                                    lower_price=lower, upper_price=upper,
                                    num_grids=num_grids, grid_mode=mode, fee_rate=fee_rate,
                                    enable_recentering_up=use_recenter,
                                    enable_recentering_down=use_recenter,
                                    recenter_threshold=0.05,
                                    enable_trailing_up=use_trailing,
                                    enable_trailing_down=use_trailing,
                                    trailing_up_stop=tr_up_stop,
                                    trailing_down_stop=tr_dn_stop,
                                    stop_loss_pct=sl,
                                    enable_dd_throttle=dd_on,
                                    dd_threshold_1=0.10,
                                    dd_threshold_2=0.20,
                                    enable_variable_orders=vo_on,
                                    weight_bottom=2.0 if vo_on else 1.0,
                                    weight_top=0.5 if vo_on else 1.0,
                                )
                                num_tested += 1
                                if sim.get("error"):
                                    continue

                                # Score je nach Ziel
                                score = _calculate_score(sim, df, total_investment, num_days, objective)
                                if score is None:
                                    continue

                                if score > best_score:
                                    best_score = score
                                    best_cfg = {
                                        "lower_price":          round(lower, 4),
                                        "upper_price":          round(upper, 4),
                                        "num_grids":            num_grids,
                                        "grid_mode":            mode,
                                        "enable_recentering_up":   use_recenter,
                                        "enable_recentering_down": use_recenter,
                                        "enable_trailing_up":   use_trailing,
                                        "enable_trailing_down": use_trailing,
                                        "trailing_up_stop":     tr_up_stop,
                                        "trailing_down_stop":   tr_dn_stop,
                                        "stop_loss_pct":        sl,
                                        "enable_dd_throttle":   dd_on,
                                        "enable_variable_orders": vo_on,
                                        "expected_roi_pct":     round(sim.get("profit_pct", 0), 4),
                                    }

    if best_cfg is None:
        return None

    return SmartSetupResult(
        lower_price          = best_cfg["lower_price"],
        upper_price          = best_cfg["upper_price"],
        num_grids            = best_cfg["num_grids"],
        grid_mode            = best_cfg["grid_mode"],
        enable_recentering_up   = best_cfg["enable_recentering_up"],
        enable_recentering_down = best_cfg["enable_recentering_down"],
        enable_trailing_up   = best_cfg["enable_trailing_up"],
        enable_trailing_down = best_cfg["enable_trailing_down"],
        trailing_up_stop     = best_cfg["trailing_up_stop"],
        trailing_down_stop   = best_cfg["trailing_down_stop"],
        expected_roi_pct     = best_cfg["expected_roi_pct"],
        num_tested           = num_tested,
        stop_loss_pct          = best_cfg.get("stop_loss_pct"),
        enable_dd_throttle     = best_cfg.get("enable_dd_throttle", False),
        enable_variable_orders = best_cfg.get("enable_variable_orders", False),
    )


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
    objective:        str    = "maximize_roi",
    max_combinations: int    = 100,
    interval:         str    = "1h",
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
    num_days = get_num_days(df, interval)

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
            "calmar":      calculate_calmar_ratio(calculate_cagr(total_investment, sim["final_value"], num_days), dd.max_drawdown_pct),
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
    objective:        str   = "maximize_roi",
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
        interval=interval,
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
    for col in ["roi_pct", "calmar", "max_dd_pct", "num_trades"]:
        if col in best_row:
            best_params[col] = best_row[col]

    return OptimizationResult(
        best_params  = best_params,
        best_score   = float(best_row["score"]),
        objective    = objective,
        all_results  = df_results.reset_index(drop=True),
        num_tested   = len(results),
    )