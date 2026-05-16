"""
src/backtesting/engine.py
=========================
Backtesting-Engine fuer den Grid-Bot.

Verbindet alle Core-Module zu einem vollstaendigen Backtesting-Workflow:
    1. Preisdaten laden (cache_manager)
    2. Grid konfigurieren (grid_builder)
    3. Simulation ausfuehren (grid_bot)
    4. Kennzahlen berechnen (metrics)
    5. Risiko bewerten (risk)

Autor: Enes Eryilmaz
Projekt: Grid-Trading-Framework (Bachelorarbeit OST)
"""

import pandas as pd
from datetime import date
from typing import Optional

from config.settings import (
    DEFAULT_NUM_GRIDS, DEFAULT_GRID_MODE,
    DEFAULT_FEE_RATE, DEFAULT_RESERVE_PCT,
    DEFAULT_BACKTEST_DAYS, DEFAULT_INTERVAL,
)
from src.data.cache_manager import get_price_data
from src.strategy.grid_bot import simulate_grid_bot
from src.strategy.grid_builder import validate_grid_config
from src.analysis.metrics import (
    calculate_all_metrics,
    get_num_days,
)
from src.analysis.indicators import (
    get_atr_stats, get_adx_value, calculate_volatility,
    calculate_return_stats, get_price_extremes,
)
from src.analysis.regime import detect_regime


def run_backtest(
    coin:               str,
    lower_price:        float,
    upper_price:        float,
    total_investment:   float   = 10_000.0,
    num_grids:          int     = DEFAULT_NUM_GRIDS,
    grid_mode:          str     = DEFAULT_GRID_MODE,
    fee_rate:           float   = DEFAULT_FEE_RATE,
    reserve_pct:        float   = DEFAULT_RESERVE_PCT,
    interval:           str     = DEFAULT_INTERVAL,
    days:               int     = DEFAULT_BACKTEST_DAYS,
    start_date: Optional[date] = None,
    end_date:   Optional[date] = None,
    stop_loss_pct:      Optional[float] = None,
    take_profit_pct:    Optional[float] = None,
    stop_loss_roi_pct:  Optional[float] = None,
    take_profit_roi_pct: Optional[float] = None,
    stop_loss_pl_usdt:  Optional[float] = None,
    take_profit_pl_usdt: Optional[float] = None,
    enable_recentering_up:   bool    = False,
    enable_recentering_down: bool    = False,
    recenter_threshold: float   = 0.05,
    enable_dd_throttle:  bool   = False,
    dd_threshold_1:      float  = 0.10,
    dd_threshold_2:      float  = 0.20,
    enable_trailing_up:     bool  = False,
    trailing_up_stop:       Optional[float] = None,
    trail_stop_levels:      bool  = False,
    grid_trigger_price:     Optional[float] = None,
    enable_initial_buy:     bool  = True,
    stop_bot_on_trigger:    bool  = False,
    force_reload:           bool  = False,
) -> dict:
    """
    Fuehrt einen vollstaendigen Backtest durch.

    Workflow:
        1. Preisdaten laden
        2. Parameter validieren
        3. Grid-Bot simulieren
        4. Kennzahlen berechnen (ROI, CAGR, Sharpe, Drawdown, Profit-Faktor)
        5. Risiko bewerten (Kelly, Position-Sizing)
        6. Marktregime analysieren

    Args:
        coin               : Coin-Symbol (z.B. "BTC")
        lower_price        : Untere Grid-Grenze
        upper_price        : Obere Grid-Grenze
        total_investment   : Startkapital in USDT
        num_grids          : Anzahl Grids
        grid_mode          : "arithmetic" oder "geometric"
        fee_rate           : Gebuehrenrate pro Trade
        reserve_pct        : Kapitalreserve
        interval           : Kerzen-Intervall
        days               : Backtesting-Zeitraum in Tagen
        stop_loss_pct      : Stop-Loss Schwelle (None = deaktiviert)
        enable_recentering_up   : Recentering nach oben aktivieren
        enable_recentering_down : Recentering nach unten aktivieren
        recenter_threshold : Recentering-Schwellenwert
        force_reload       : Cache ignorieren

    Returns:
        Dictionary mit vollstaendigen Backtesting-Ergebnissen
    """
    # --- Preisdaten laden ---
    df, from_cache = get_price_data(coin, days=days, interval=interval, force=force_reload, start_date=start_date, end_date=end_date)
    if df is None or df.empty:
        return _error_result("Keine Preisdaten verfuegbar.")

    # --- Parameter validieren ---
    is_valid, warnings = validate_grid_config(
        lower_price, upper_price, num_grids, total_investment, fee_rate
    )
    if not is_valid:
        return _error_result(f"Ungueltige Parameter: {warnings}")

    # --- Simulation ---
    sim = simulate_grid_bot(
        df                 = df,
        total_investment   = total_investment,
        lower_price        = lower_price,
        upper_price        = upper_price,
        num_grids          = num_grids,
        grid_mode          = grid_mode,
        fee_rate           = fee_rate,
        reserve_pct        = reserve_pct,
        stop_loss_pct      = stop_loss_pct,
        take_profit_pct    = take_profit_pct,
        stop_loss_roi_pct   = stop_loss_roi_pct,
        take_profit_roi_pct = take_profit_roi_pct,
        stop_loss_pl_usdt   = stop_loss_pl_usdt,
        take_profit_pl_usdt = take_profit_pl_usdt,
        enable_recentering_up   = enable_recentering_up,
        enable_recentering_down = enable_recentering_down,
        recenter_threshold = recenter_threshold,
        enable_dd_throttle  = enable_dd_throttle,
        dd_threshold_1      = dd_threshold_1,
        dd_threshold_2      = dd_threshold_2,
        enable_trailing_up     = enable_trailing_up,
        trailing_up_stop       = trailing_up_stop,
        trail_stop_levels      = trail_stop_levels,
        grid_trigger_price     = grid_trigger_price,
        enable_initial_buy     = enable_initial_buy,
        stop_bot_on_trigger    = stop_bot_on_trigger,
    )

    if sim.get("error"):
        return _error_result(sim["error"])

    # --- Kennzahlen (Standard-Schema aus src/analysis/metrics.py) ---
    num_days_real = get_num_days(df, interval)
    has_dynamic_capital = enable_dd_throttle
    metrics = calculate_all_metrics(
        trade_log           = sim["trade_log"],
        daily_values        = sim["daily_values"],
        initial_value       = total_investment,
        final_value         = sim["final_value"],
        initial_price       = sim["initial_price"],
        final_price         = sim["final_price"],
        fees_paid           = sim["fees_paid"],
        num_days            = num_days_real,
        num_grids           = num_grids,
        current_price       = sim["final_price"],
        open_buys           = sim.get("final_open_buys", []),
        has_dynamic_capital = has_dynamic_capital,
        reserve_pct         = reserve_pct,
    )

    # --- Indikatoren (fuer Tabs "Marktdaten" + "Indikatoren") ---
    atr_usdt, atr_pct         = get_atr_stats(df)
    vola_monthly, vola_yearly = calculate_volatility(df, interval)
    return_stats   = calculate_return_stats(df)
    price_extremes = get_price_extremes(df)
    adx14 = get_adx_value(df, period=14)
    adx30 = get_adx_value(df, period=30)

    # --- Marktregime ---
    regime = detect_regime(df, interval)

    # --- Result-Dict ---
    # Standard-Schema (Schritt B des Metriken-Refactors)
    result = dict(metrics)

    # Backtest-spezifische Felder
    result.update({
        "coin":                coin.upper(),
        "interval":            interval,
        "days":                days,
        "trade_log":           sim["trade_log"],
        "grid_lines":          sim["grid_lines"],
        "initial_price":       sim["initial_price"],
        "final_price":         sim["final_price"],
        "daily_values":        sim["daily_values"],
        "recentering_count":   sim["recentering_count"],
        "trailing_count":      sim.get("trailing_count", 0),
        "trailing_events":     sim.get("trailing_events", []),
        "recentering_events":  sim.get("recentering_events", []),
        "stop_loss_triggered": sim["stop_loss_triggered"],
        "take_profit_triggered": sim.get("take_profit_triggered", False),
        # Trigger-Daten fuer Chart-Marker (M.2)
        "stop_loss_trigger_timestamp":   sim.get("stop_loss_trigger_timestamp"),
        "stop_loss_trigger_price":       sim.get("stop_loss_trigger_price"),
        "take_profit_trigger_timestamp": sim.get("take_profit_trigger_timestamp"),
        "take_profit_trigger_price":     sim.get("take_profit_trigger_price"),
        # Final position (Bug 7: damit UI Coin-Inventar bei BT lesen kann)
        "final_position":          sim.get("final_position",
                                            {"usdt": 0.0, "coin": 0.0}),
        # Initial-Buy-Aggregate + Bot-Status + Grid Trigger (Binance-Standard)
        "initial_buy_coin_amount": sim.get("initial_buy_coin_amount", 0.0),
        "initial_buy_fee":         sim.get("initial_buy_fee", 0.0),
        "initial_buy_value_usdt":  sim.get("initial_buy_value_usdt", 0.0),
        "bot_status":              sim.get("bot_status", "active"),
        "grid_trigger_price":      sim.get("grid_trigger_price", None),
        # Mechanismus-Aktivierung (fuer Tab "Mechanisms")
        "mechanism_active":    {
            "recentering": enable_recentering_up or enable_recentering_down,
            "trailing":    enable_trailing_up,
            "stop_loss":   (stop_loss_pct is not None
                            or stop_loss_roi_pct is not None
                            or stop_loss_pl_usdt is not None),
            "take_profit": (take_profit_pct is not None
                            or take_profit_roi_pct is not None
                            or take_profit_pl_usdt is not None),
        },
        # Slippage existiert in der Backtest-Simulation nicht (Trade laeuft am
        # exakten Grid-Preis). Sobald PaperBroker/LiveBroker aktiv ist, kommt
        # der Wert ueber den BotRunner, nicht ueber run_backtest.
        "slippage_usdt":       None,
        "slippage_avg_pct":    None,
        "regime":              regime,
        # Indikatoren / Marktdaten (Tabs "Marktdaten" und "Indikatoren")
        "atr_usdt":            atr_usdt,
        "atr_pct":             atr_pct,
        "adx14":               adx14,
        "adx30":               adx30,
        "vola_monthly_pct":    vola_monthly,
        "vola_yearly_pct":     vola_yearly,
        "return_stats":        return_stats,
        "price_extremes":      price_extremes,
        "error":               None,
    })

    return result


def _error_result(message: str) -> dict:
    """
    Gibt ein leeres Fehler-Ergebnis-Dictionary zurueck.
    Hat dasselbe Schluesselschema wie das Erfolgs-Result, damit Aufrufer
    keine fehlenden Schluessel behandeln muessen.
    """
    return {
        # Standard-Schema (calculate_all_metrics)
        "roi_pct":              0.0,
        "cagr_pct":             None,
        "calmar_ratio":         None,
        "sharpe_ratio":         None,
        "profit_factor":        None,
        "max_drawdown_pct":     0.0,
        "max_drawdown_usdt":    0.0,
        "current_drawdown_pct": 0.0,
        "fee_impact_pct":       None,
        "benchmark_roi_pct":    None,
        "outperformance_pct":   None,
        "avg_profit_per_trade": None,
        "num_trades":           0,
        "fees_paid":            0.0,
        "initial_investment":   0.0,
        "final_value":          0.0,
        "grid_efficiency":      None,
        "unrealized_pnl":       {"usdt": 0.0, "pct": 0.0, "num_positions": 0},
        "slippage_usdt":        None,
        "slippage_avg_pct":     None,
        # Backtest-spezifisch
        "coin":                 "",
        "interval":             "",
        "days":                 0,
        "trade_log":            [],
        "grid_lines":           [],
        "initial_price":        0.0,
        "final_price":          0.0,
        "daily_values":         {},
        "recentering_count":    0,
        "trailing_count":       0,
        "trailing_events":      [],
        "recentering_events":   [],
        "dd_history":           [],
        "stop_loss_triggered":  False,
        "take_profit_triggered": False,
        "initial_buy_coin_amount": 0.0,
        "initial_buy_fee":         0.0,
        "initial_buy_value_usdt":  0.0,
        "bot_status":              "stopped",
        "grid_trigger_price":      None,
        "mechanism_active":     {
            "recentering": False, "trailing": False,
            "stop_loss":   False, "take_profit": False,
        },
        "regime":               None,
        "atr_usdt":             0.0,
        "atr_pct":              0.0,
        "adx14":                0.0,
        "adx30":                0.0,
        "vola_monthly_pct":     None,
        "vola_yearly_pct":      None,
        "return_stats":         {"avg_pct": None, "std_pct": None},
        "price_extremes":       {"max_price": 0.0, "min_price": 0.0, "range_usdt": 0.0, "range_pct": 0.0},
        "error":                message,
    }