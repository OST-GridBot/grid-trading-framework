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
import numpy as np
from datetime import datetime, timedelta, date
from typing import Optional

from config.settings import (
    DEFAULT_NUM_GRIDS, DEFAULT_GRID_MODE,
    DEFAULT_FEE_RATE, DEFAULT_RESERVE_PCT,
    DEFAULT_BACKTEST_DAYS, DEFAULT_INTERVAL,
)
from src.data.cache_manager import get_price_data
from src.strategy.grid_bot import simulate_grid_bot
from src.strategy.grid_builder import build_grid_config, suggest_grid_range, validate_grid_config
from src.strategy.risk import calculate_drawdown, calculate_kelly_fraction, calculate_position_size
from src.analysis.indicators import get_adx_value, get_atr_stats, calculate_volatility
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
    enable_recentering: bool    = False,
    recenter_threshold: float   = 0.05,
    force_reload:       bool    = False,
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
        enable_recentering : Recentering aktivieren
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
        enable_recentering = enable_recentering,
        recenter_threshold = recenter_threshold,
    )

    if sim.get("error"):
        return _error_result(sim["error"])

    # --- Kennzahlen berechnen ---
    metrics = calculate_metrics(sim, df, total_investment, interval)

    # --- Risiko bewerten ---
    dd     = calculate_drawdown(sim["daily_values"])
    kelly  = calculate_kelly_fraction(sim["trade_log"], total_investment)
    _, atr_pct = get_atr_stats(df)
    pos    = calculate_position_size(total_investment, atr_pct)

    # --- Marktregime ---
    regime = detect_regime(df, interval)

    # --- Grid-Konfiguration ---
    grid_cfg = build_grid_config(lower_price, upper_price, num_grids, grid_mode, fee_rate)

    return {
        # Simulation
        "coin":                coin.upper(),
        "interval":            interval,
        "days":                days,
        "from_cache":          from_cache,
        "initial_investment":  total_investment,
        "final_value":         sim["final_value"],
        "profit_usdt":         sim["profit_usdt"],
        "profit_pct":          sim["profit_pct"],
        "fees_paid":           sim["fees_paid"],
        "num_trades":          sim["num_trades"],
        "trade_log":           sim["trade_log"],
        "grid_lines":          sim["grid_lines"],
        "final_position":      sim["final_position"],
        "initial_price":       sim["initial_price"],
        "final_price":         sim["final_price"],
        "price_change_pct":    sim["price_change_pct"],
        "daily_values":        sim["daily_values"],
        "recentering_count":   sim["recentering_count"],
        "stop_loss_triggered": sim["stop_loss_triggered"],
        # Kennzahlen
        "cagr":                metrics["cagr"],
        "sharpe_ratio":        metrics["sharpe_ratio"],
        "profit_factor":       metrics["profit_factor"],
        "win_rate":            metrics["win_rate"],
        "avg_profit_per_trade":metrics["avg_profit_per_trade"],
        "calmar_ratio":        metrics["calmar_ratio"],
        # Risiko
        "max_drawdown_pct":    dd.max_drawdown_pct,
        "max_drawdown_usdt":   dd.max_drawdown_usdt,
        "current_drawdown":    dd.current_drawdown_pct,
        "recovery_days":       dd.recovery_days,
        "kelly":               kelly,
        "position_size":       pos,
        # Markt
        "regime":              regime,
        "atr_pct":             atr_pct,
        "grid_config":         grid_cfg,
        "warnings":            warnings,
        "df":                  df,
        "error":               None,
    }


def calculate_metrics(
    sim:              dict,
    df:               pd.DataFrame,
    total_investment: float,
    interval:         str,
) -> dict:
    """
    Berechnet alle Backtesting-Kennzahlen (Bachelorarbeit Ziel 6).

    Kennzahlen:
        CAGR         : Compound Annual Growth Rate (annualisierte Rendite)
        Sharpe Ratio : Risikoadjustierte Rendite (Rendite / Volatilitaet)
        Profit-Faktor: Bruttogewinn / Bruttoverlust
        Win-Rate     : Anteil profitabler Trades in %

    Args:
        sim             : Ergebnis von simulate_grid_bot()
        df              : OHLCV-DataFrame
        total_investment: Startkapital
        interval        : Kerzen-Intervall

    Returns:
        Dictionary mit allen Kennzahlen
    """
    trade_log    = sim.get("trade_log", [])
    daily_values = sim.get("daily_values", {})
    final_value  = sim.get("final_value", total_investment)

    # CAGR berechnen
    num_days = len(df)
    cagr     = _calculate_cagr(total_investment, final_value, num_days, interval)

    # Sharpe Ratio
    sharpe = _calculate_sharpe(daily_values)

    # Profit-Faktor
    sell_trades   = [t for t in trade_log if t.get("type") == "SELL"]
    gross_profit  = sum(t["profit"] for t in sell_trades if t["profit"] > 0)
    gross_loss    = abs(sum(t["profit"] for t in sell_trades if t["profit"] <= 0))
    profit_factor = round(gross_profit / gross_loss, 4) if gross_loss > 0 else None

    # Win-Rate
    wins     = [t for t in sell_trades if t["profit"] > 0]
    win_rate = round(len(wins) / len(sell_trades) * 100, 2) if sell_trades else None

    # Durchschnittlicher Gewinn pro Trade
    profits = [t["profit"] for t in sell_trades]
    avg_profit = round(np.mean(profits), 4) if profits else 0.0

    # Calmar Ratio: CAGR / Max Drawdown
    from src.strategy.risk import calculate_drawdown
    from src.backtesting.metrics import calculate_calmar_ratio
    dd     = calculate_drawdown(sim.get("daily_values", {}))
    calmar = calculate_calmar_ratio(cagr, dd.max_drawdown_pct)

    return {
        "cagr":                 cagr,
        "sharpe_ratio":         sharpe,
        "profit_factor":        profit_factor,
        "win_rate":             win_rate,
        "avg_profit_per_trade": avg_profit,
        "calmar_ratio":         calmar,
    }


def _calculate_cagr(
    initial:  float,
    final:    float,
    num_days: int,
    interval: str,
) -> Optional[float]:
    """
    Berechnet CAGR (Compound Annual Growth Rate).
    Formel: CAGR = (final/initial)^(365/days) - 1
    """
    from config.settings import BINANCE_INTERVAL_MAP
    interval_minutes = {
        "1m": 1, "5m": 5, "15m": 15,
        "1h": 60, "4h": 240, "1d": 1440,
    }
    mins     = interval_minutes.get(interval, 60)
    days     = (num_days * mins) / (60 * 24)
    if days < 1 or initial <= 0:
        return None
    try:
        cagr = (final / initial) ** (365 / days) - 1
        return round(cagr * 100, 2)
    except Exception:
        return None


def _calculate_sharpe(
    daily_values: dict,
    risk_free_rate: float = 0.04,
) -> Optional[float]:
    """
    Berechnet die Sharpe Ratio.
    Formel: Sharpe = (Rendite - risikofreier Zins) / Standardabweichung
    Risikofreier Zins: 4% p.a. (Standard US-Staatsanleihe)
    """
    if len(daily_values) < 2:
        return None
    series  = pd.Series(daily_values).sort_index()
    returns = series.pct_change().dropna()
    if returns.std() == 0:
        return None
    daily_rf    = risk_free_rate / 365
    excess      = returns - daily_rf
    sharpe      = (excess.mean() / returns.std()) * np.sqrt(365)
    return round(float(sharpe), 4)


def run_multi_coin_backtest(
    coins:            list,
    range_pct:        float = 0.20,
    total_investment: float = 10_000.0,
    num_grids:        int   = DEFAULT_NUM_GRIDS,
    grid_mode:        str   = DEFAULT_GRID_MODE,
    fee_rate:         float = DEFAULT_FEE_RATE,
    interval:         str   = DEFAULT_INTERVAL,
    days:             int   = DEFAULT_BACKTEST_DAYS,
) -> pd.DataFrame:
    """
    Fuehrt Backtests fuer mehrere Coins durch und vergleicht Ergebnisse.

    Args:
        coins            : Liste von Coin-Symbolen
        range_pct        : Grid-Range in % vom aktuellen Preis
        total_investment : Startkapital pro Coin
        num_grids        : Anzahl Grids
        grid_mode        : Grid-Modus
        fee_rate         : Gebuehrenrate
        interval         : Kerzen-Intervall
        days             : Backtesting-Zeitraum

    Returns:
        DataFrame mit Vergleichsresultaten aller Coins
    """
    results = []

    for coin in coins:
        try:
            df, _ = get_price_data(coin, days=days, interval=interval)
            if df is None or df.empty:
                continue

            price       = float(df["close"].iloc[-1])
            lower_price = price * (1 - range_pct)
            upper_price = price * (1 + range_pct)

            result = run_backtest(
                coin             = coin,
                lower_price      = lower_price,
                upper_price      = upper_price,
                total_investment = total_investment,
                num_grids        = num_grids,
                grid_mode        = grid_mode,
                fee_rate         = fee_rate,
                interval         = interval,
                days             = days,
            )

            if not result.get("error"):
                results.append({
                    "Coin":          coin.upper(),
                    "ROI_%":         round(result["profit_pct"], 2),
                    "CAGR_%":        result["cagr"],
                    "Sharpe":        result["sharpe_ratio"],
                    "Max_DD_%":      result["max_drawdown_pct"],
                    "Trades":        result["num_trades"],
                    "Profit_Factor": result["profit_factor"],
                    "Win_Rate_%":    result["win_rate"],
                    "Regime":        result["regime"].regime,
                })
        except Exception as e:
            print(f"Fehler bei {coin}: {e}")
            continue

    if not results:
        return pd.DataFrame()

    df_results = pd.DataFrame(results)
    return df_results.sort_values("ROI_%", ascending=False).reset_index(drop=True)


def _error_result(message: str) -> dict:
    """Gibt ein leeres Fehler-Ergebnis-Dictionary zurueck."""
    return {
        "coin": "", "interval": "", "days": 0,
        "initial_investment": 0.0, "final_value": 0.0,
        "profit_usdt": 0.0, "profit_pct": 0.0,
        "fees_paid": 0.0, "num_trades": 0,
        "trade_log": [], "grid_lines": [],
        "cagr": None, "sharpe_ratio": None,
        "profit_factor": None, "win_rate": None,
        "max_drawdown_pct": 0.0, "regime": None,
        "error": message,
    }