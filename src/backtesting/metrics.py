"""
src/backtesting/metrics.py
==========================
Backward-Compatibility Re-Export.
Alle Metriken sind jetzt zentral in src/metrics.py definiert.

Autor: Enes Eryilmaz
Projekt: Grid-Trading-Framework (Bachelorarbeit OST)
"""

# Re-Export aller Funktionen aus src.metrics
from src.metrics import (
    calculate_roi,
    calculate_cagr,
    calculate_calmar_ratio,
    calculate_sharpe_ratio,
    calculate_sortino_ratio,
    calculate_profit_factor,
    calculate_win_rate,
    calculate_fee_impact,
    calculate_avg_trade_duration,
    calculate_benchmark_roi,
    calculate_kelly_fraction,
    calculate_drawdown,
    calculate_all_metrics,
    get_num_days,
    calculate_benchmark,
    format_metrics_summary,
    DrawdownResult,
)
