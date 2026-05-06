"""
src/trading/optimizer.py
========================
Live/Paper-Trading SmartGridSetup.

Saubere Trennung von Backtesting:
- Backtesting verwendet src/backtesting/optimizer.py
- Live/Paper Trading verwendet diese Datei

Konzeptioneller Unterschied zum Backtesting:
- Backtesting optimiert für VERGANGENEN Startpunkt (Range basierend auf Median)
- PT/LT optimiert Range basierend auf AKTUELLEM Preis (für Bot-Start heute)
- Backtests werden intern mit auf historisches Preisniveau skalierter Range
  ausgeführt (sonst würden sie keine Trades auslösen)

Autor: Enes Eryilmaz
Projekt: Grid-Trading-Framework (Bachelorarbeit OST)
"""

import pandas as pd
from dataclasses import dataclass
from typing import Optional

from config.settings import DEFAULT_FEE_RATE
from src.strategy.grid_bot import simulate_grid_bot
from src.metrics import (
    calculate_drawdown, calculate_sharpe_ratio,
    calculate_calmar_ratio, calculate_cagr, get_num_days,
)


@dataclass
class SmartSetupResult:
    """Ergebnis des SmartGridSetup für PT/LT.

    Range bezieht sich auf den AKTUELLEN Preis (heute) — nicht auf
    den Median des historischen Zeitraums.
    """
    lower_price:           float
    upper_price:           float
    num_grids:             int
    grid_mode:             str
    enable_recentering:    bool
    enable_trailing_up:    bool
    enable_trailing_down:  bool
    trailing_up_stop:      Optional[float]
    trailing_down_stop:    Optional[float]
    expected_roi_pct:      float
    num_tested:            int
    stop_loss_pct:         Optional[float] = None
    enable_dd_throttle:    bool = False
    enable_variable_orders: bool = False


def _calculate_score(sim, total_investment, num_days, objective):
    """Score-Berechnung je nach Optimierungsziel."""
    dv = sim.get("daily_values", {})
    fv = sim.get("final_value", total_investment)

    if objective == "maximize_roi":
        return sim.get("profit_pct")
    elif objective == "minimize_drawdown":
        dd  = calculate_drawdown(dv)
        roi = sim.get("profit_pct", 0)
        if roi <= 0:
            return -999
        return -dd.max_drawdown_pct + roi * 0.1
    return sim.get("profit_pct")


def smart_grid_setup(
    df:               pd.DataFrame,
    total_investment: float = 10_000.0,
    fee_rate:         float = DEFAULT_FEE_RATE,
    objective:        str   = "maximize_roi",
):
    """
    SmartGridSetup für Live/Paper Trading.

    WICHTIGER UNTERSCHIED zum Backtesting-Optimizer:
    - Range wird basierend auf dem AKTUELLEN Preis (df.close.iloc[-1]) berechnet
      → der Bot startet HEUTE mit dieser Range, sie muss um den heutigen Preis liegen
    - Für die internen Backtests wird die Range jedoch auf das damalige Preisniveau
      umgerechnet (Median des Zeitraums), damit die historischen Trades sinnvoll sind
    - Die anderen Parameter (Anzahl Grids, Modus, Mechanismen) werden auf den
      historischen Daten getestet und ihre Ergebnisse auf "heute" übertragen

    Variiert systematisch:
        - Range-% (5%, 10%, 15%, 20%) — um aktuellen Preis bzw. historischen Median
        - Anzahl Grids (5, 10, 15, 20, 25, 30)
        - Grid-Modus (4 Optionen)
        - Mechanismen je nach Optimierungsziel
    """
    if df is None or df.empty:
        return None

    current_price = float(df["close"].iloc[-1])
    median_price  = float(df["close"].median())

    range_pcts  = [0.05, 0.10, 0.15, 0.20]
    grid_counts = [5, 10, 15, 20, 25, 30]
    modes       = ["arithmetic", "geometric", "asymmetric_bottom", "asymmetric_top"]

    if objective == "minimize_drawdown":
        mech_options = [0]
        sl_options   = [None, 0.20]
        dd_options   = [False, True]
        vo_options   = [False]
    else:  # maximize_roi
        mech_options = [0, 1, 2]
        sl_options   = [None]
        dd_options   = [False]
        vo_options   = [False]

    num_days = get_num_days(df, "1h")

    best_score = -float("inf")
    best_cfg   = None
    num_tested = 0

    for range_pct in range_pcts:
        # Interne Backtest-Range (basiert auf Median des historischen Zeitraums)
        bt_lower = median_price * (1 - range_pct)
        bt_upper = median_price * (1 + range_pct)
        # Anzeige-Range für den User (basiert auf aktuellem Preis)
        display_lower = current_price * (1 - range_pct)
        display_upper = current_price * (1 + range_pct)

        for num_grids in grid_counts:
            for mode in modes:
                for mech in mech_options:
                    for sl in sl_options:
                        for dd_on in dd_options:
                            for vo_on in vo_options:
                                use_recenter = (mech == 1)
                                use_trailing = (mech == 2)
                                # Trailing-Stops immer relativ zur Backtest-Range
                                bt_tr_up = bt_upper * 1.20 if use_trailing else None
                                bt_tr_dn = bt_lower * 0.80 if use_trailing else None
                                # Anzeige-Trailing-Stops relativ zur Anzeige-Range
                                display_tr_up = display_upper * 1.20 if use_trailing else None
                                display_tr_dn = display_lower * 0.80 if use_trailing else None

                                sim = simulate_grid_bot(
                                    df=df, total_investment=total_investment,
                                    lower_price=bt_lower, upper_price=bt_upper,
                                    num_grids=num_grids, grid_mode=mode, fee_rate=fee_rate,
                                    enable_recentering=use_recenter,
                                    recenter_threshold=0.05,
                                    enable_trailing_up=use_trailing,
                                    enable_trailing_down=use_trailing,
                                    trailing_up_stop=bt_tr_up,
                                    trailing_down_stop=bt_tr_dn,
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

                                score = _calculate_score(sim, total_investment, num_days, objective)
                                if score is None:
                                    continue

                                if score > best_score:
                                    best_score = score
                                    best_cfg = {
                                        # Anzeige-Werte (User sieht die für heute)
                                        "lower_price":            round(display_lower, 4),
                                        "upper_price":            round(display_upper, 4),
                                        "num_grids":              num_grids,
                                        "grid_mode":              mode,
                                        "enable_recentering":     use_recenter,
                                        "enable_trailing_up":     use_trailing,
                                        "enable_trailing_down":   use_trailing,
                                        "trailing_up_stop":       display_tr_up,
                                        "trailing_down_stop":     display_tr_dn,
                                        "stop_loss_pct":          sl,
                                        "enable_dd_throttle":     dd_on,
                                        "enable_variable_orders": vo_on,
                                        "expected_roi_pct":       round(sim.get("profit_pct", 0), 4),
                                    }

    if best_cfg is None:
        return None

    return SmartSetupResult(
        lower_price            = best_cfg["lower_price"],
        upper_price            = best_cfg["upper_price"],
        num_grids              = best_cfg["num_grids"],
        grid_mode              = best_cfg["grid_mode"],
        enable_recentering     = best_cfg["enable_recentering"],
        enable_trailing_up     = best_cfg["enable_trailing_up"],
        enable_trailing_down   = best_cfg["enable_trailing_down"],
        trailing_up_stop       = best_cfg["trailing_up_stop"],
        trailing_down_stop     = best_cfg["trailing_down_stop"],
        expected_roi_pct       = best_cfg["expected_roi_pct"],
        num_tested             = num_tested,
        stop_loss_pct          = best_cfg["stop_loss_pct"],
        enable_dd_throttle     = best_cfg["enable_dd_throttle"],
        enable_variable_orders = best_cfg["enable_variable_orders"],
    )
