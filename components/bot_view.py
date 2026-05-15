"""
components/bot_view.py
======================
Einheitliches Daten-Modell ueber Backtests, Paper- und Live-Bots.

Die drei Modi (BT/PT/LT) liefern ihre Ergebnisse heute in unterschiedlichen
Strukturen:
    - BT (run_backtest):  flaches Result mit Top-Level-Feldern
    - PT/LT (bot_store):  verschachtelt mit config/state/metrics/trade_log

Die hier definierte BotView vereinheitlicht das, damit die UI-Komponenten
(portfolio_view, bot_list, bot_detail, tab_*) ein konsistentes Datenmodell
konsumieren - unabhaengig vom Modus.

BotView-Schema (als Dict, nicht TypedDict wegen Python 3.9-Kompatibilitaet):

    {
        "id":          str,
        "mode":        "backtest" | "paper" | "live",
        "name":        str,
        "coin":        str,
        "interval":    str,
        "status":      str,               # running/stopped (PT/LT) | completed/error (BT)
        "created_at":  str,               # ISO-Timestamp
        "last_update": Optional[str],     # nur PT/LT (Zeit der letzten Aktualisierung)
        "config":      dict,              # alle Sim-/Bot-Parameter
        "metrics":     dict,              # Standard-Schema aus calculate_all_metrics
        "trade_log":   list[dict],
        "state":       Optional[dict],    # nur PT/LT (GridBot-Snapshot)
        "regime":      Optional[dict],    # serialisierter RegimeResult (BT bzw. PT/LT)
        "indicators":  Optional[dict],    # nur BT: {atr_*, adx*, vola_*, return_stats, price_extremes}
        "period":      Optional[dict],    # nur BT: {start_date, end_date, days}
    }

Autor: Enes Eryilmaz
Projekt: Grid-Trading-Framework (Bachelorarbeit OST)
"""

from typing import Optional


# ---------------------------------------------------------------------------
# Adapter: PT/LT-Bot-State -> BotView
# ---------------------------------------------------------------------------

def bot_view_from_bot_state(bot: dict) -> dict:
    """
    Konvertiert einen PT/LT-Bot-State (aus bot_store.get_bot) in eine BotView.

    Mapping ist 1:1 - PT/LT speichern bereits im verschachtelten Schema. Hier
    nur Default-Fallbacks fuer fehlende Schluessel (z.B. alte Bots ohne
    "last_update" oder "regime").
    """
    state = bot.get("state") or {}
    return {
        "id":              bot.get("bot_id", ""),
        "mode":            bot.get("mode", "paper"),
        "name":            bot.get("name", bot.get("coin", "")),
        "coin":            bot.get("coin", ""),
        "interval":        bot.get("interval", ""),
        "status":          bot.get("status", ""),
        "created_at":      bot.get("created_at", ""),
        "last_update":     bot.get("last_update"),
        "config":          dict(bot.get("config", {})),
        "metrics":         dict(bot.get("metrics", {})),
        "trade_log":       list(bot.get("trade_log", [])),
        "trailing_events": list(bot.get("trailing_events", [])),
        "recentering_events": list(bot.get("recentering_events", [])),
        "state":           bot.get("state"),
        "regime":          _serialize_regime(bot.get("regime")),
        "indicators":      bot.get("indicators"),
        "period":          bot.get("period"),
        # Innerer Bot-Status (Grid-Mechanik). Default "active" fuer alte Bots.
        "bot_status":      state.get("bot_status", "active"),
        # Initial-Buy-Aggregate (Binance-Standard). 0.0 fuer alte Bots.
        "initial_buy_coin_amount": state.get("initial_buy_coin_amount", 0.0),
        "initial_buy_fee":         state.get("initial_buy_fee", 0.0),
        "initial_buy_value_usdt":  state.get("initial_buy_value_usdt", 0.0),
    }


# ---------------------------------------------------------------------------
# Adapter: run_backtest-Result -> BotView
# ---------------------------------------------------------------------------

# Standard-Schema-Schluessel aus calculate_all_metrics + run_backtest-Erweiterungen.
# Identisch zur Liste in bot_store.save_backtest - dort wird sie zum Filtern
# beim Persistieren genutzt, hier zum Aufbauen der BotView direkt aus dem
# Result-Dict (ohne Persistenz).
_METRIC_KEYS = frozenset({
    "roi_pct", "cagr_pct", "calmar_ratio", "sharpe_ratio",
    "profit_factor", "max_drawdown_pct", "max_drawdown_usdt",
    "current_drawdown_pct", "fee_impact_pct", "benchmark_roi_pct",
    "benchmark_roi_usdt", "outperformance_pct", "avg_profit_per_trade",
    "avg_profit_per_trade_pct", "num_trades",
    "num_initial_buys", "num_normal_buys", "num_sells",
    "fees_paid",
    "initial_investment", "final_value", "grid_efficiency",
    "unrealized_pnl", "slippage_usdt", "slippage_avg_pct",
    "mechanism_active", "gross_pl_usdt", "gross_pl_pct",
    "grid_profit_total_usdt", "grid_profit_total_pct",
    "capital_per_grid", "active_levels", "runtime",
    "recentering_count", "trailing_count",
    "stop_loss_triggered", "take_profit_triggered",
    "stop_loss_trigger_timestamp", "stop_loss_trigger_price",
    "take_profit_trigger_timestamp", "take_profit_trigger_price",
    "current_price", "dd_throttle_factor",
})

_INDICATOR_KEYS = (
    "atr_usdt", "atr_pct", "adx14", "adx30",
    "vola_monthly_pct", "vola_yearly_pct",
    "return_stats", "price_extremes",
)


def bot_view_from_backtest_result(
    result: dict,
    config: dict,
    name:   str,
    period: dict,
    bot_id: Optional[str] = None,
) -> dict:
    """
    Konvertiert ein run_backtest-Result (+ Sidebar-Parameter + Zeitraum) in
    eine BotView.

    Args:
        result : Komplettes run_backtest()-Result
        config : Sim-Parameter (lower_price, upper_price, num_grids,
                 grid_mode, fee_rate, reserve_pct, stop_loss_pct,
                 take_profit_pct, enable_*, ..., total_investment).
                 Wird nicht aus dem Result rekonstruiert, weil das Result
                 selbst diese Felder nicht enthaelt.
        name   : Anzeigename
        period : {"start_date": str, "end_date": str, "days": int}
        bot_id : Falls bereits persistiert, die zugehoerige bot_id.
                 Sonst leer (View existiert nur in session_state).

    Returns:
        BotView-Dict im Standard-Schema.
    """
    status = "error" if result.get("error") else "completed"

    metrics = {k: v for k, v in result.items() if k in _METRIC_KEYS}
    indicators = {k: result.get(k) for k in _INDICATOR_KEYS if k in result}

    return {
        "id":              bot_id or "",
        "mode":            "backtest",
        "name":            name,
        "coin":            result.get("coin", config.get("coin", "")),
        "interval":        result.get("interval", config.get("interval", "")),
        "status":          status,
        "created_at":      "",
        "last_update":     None,
        "config":          dict(config),
        "metrics":         metrics,
        "trade_log":       list(result.get("trade_log", [])),
        "trailing_events": list(result.get("trailing_events", [])),
        "recentering_events": list(result.get("recentering_events", [])),
        # Bug 7: BT-Pfad legt final_position als state.position ab, damit
        # UI (Coin-Inventar-Anzeige) auch bei BT-Bots Werte lesen kann.
        "state":           ({"position": dict(result.get("final_position"))}
                             if result.get("final_position") else None),
        "regime":          _serialize_regime(result.get("regime")),
        "indicators":      indicators,
        "period":          dict(period),
        # Innerer Bot-Status + Initial-Buy-Aggregate (aus Result, da kein State)
        "bot_status":              result.get("bot_status", "active"),
        "initial_buy_coin_amount": result.get("initial_buy_coin_amount", 0.0),
        "initial_buy_fee":         result.get("initial_buy_fee", 0.0),
        "initial_buy_value_usdt":  result.get("initial_buy_value_usdt", 0.0),
    }


# ---------------------------------------------------------------------------
# Hilfsfunktion: anzeige-relevante Felder ins metrics-Dict mergen
# ---------------------------------------------------------------------------

def enrich_metrics_for_display(view: dict) -> dict:
    """
    Liefert ein neues metrics-Dict mit allen anzeige-relevanten Feldern.
    Konsolidiert den Merge-Block fuer beide UI-Pfade
    (bot_detail.render_bot_detail + pages/page_backtesting.Simulationsergebnis),
    damit kein Drift zwischen den beiden Renderern entsteht.

    Bestehende Werte in view["metrics"] werden NICHT ueberschrieben
    (setdefault-Pattern).
    """
    metrics = dict(view.get("metrics", {}))
    cfg     = view.get("config", {}) or {}
    trade_log = view.get("trade_log", []) or []

    # Basis-Felder + Fee-Fallback
    metrics.setdefault("initial_investment", cfg.get("total_investment", 0))
    if "fees_paid" not in metrics:
        metrics["fees_paid"] = sum(t.get("fee", 0) for t in trade_log)

    # Indikatoren (BT-spezifisch) — damit Tab 'Market Data' bei BT-Bots
    # Werte zeigt. setdefault statt update -> PT/LT-Werte bleiben.
    for k, v in (view.get("indicators") or {}).items():
        metrics.setdefault(k, v)

    # Initial-Buy-Aggregate + Bot-Status + Grid Trigger
    metrics.setdefault("initial_buy_coin_amount",
                        view.get("initial_buy_coin_amount", 0.0))
    metrics.setdefault("initial_buy_fee",
                        view.get("initial_buy_fee", 0.0))
    metrics.setdefault("initial_buy_value_usdt",
                        view.get("initial_buy_value_usdt", 0.0))
    metrics.setdefault("bot_status",         view.get("bot_status", "active"))
    metrics.setdefault("grid_trigger_price", cfg.get("grid_trigger_price"))

    # Coin-Inventar (Bug 7): PT/LT aus state.position, BT nach Persistenz
    # auch state.position (save_backtest legt final_position dorthin ab).
    state    = view.get("state") or {}
    position = state.get("position") or {}
    coin_amt = float(position.get("coin", 0) or 0)
    metrics.setdefault("coin_holdings", coin_amt)
    metrics.setdefault("coin_holdings_value_usdt",
                        coin_amt * float(metrics.get("current_price", 0) or 0))
    metrics.setdefault("coin_symbol", view.get("coin", ""))

    # SL/TP-Bedingungs-Felder (Auftrag H): Bedingung als Label in
    # All-Tab + Bot-Details-Karten anzeigen.
    for k in ("stop_loss_pct", "take_profit_pct",
              "stop_loss_roi_pct", "take_profit_roi_pct",
              "stop_loss_pl_usdt", "take_profit_pl_usdt"):
        metrics.setdefault(k, cfg.get(k))

    # Reserve (Bug 6): Initial-Capital-delta in Karten + All-Tab.
    metrics.setdefault("reserve_pct", cfg.get("reserve_pct", 0.0))

    # Notiz 6.2: DD-Drosselfaktor aus state mergen + DD-Aktivierungs-Flag
    # aus cfg (sonst zeigt Karte 'Inaktiv' obwohl cfg.enable_dd_throttle=True).
    # Plus Recentering/Trailing-Detail-Werte fuer Kombi-Karte.
    metrics.setdefault("dd_throttle_factor",
                        state.get("dd_throttle_factor", 1.0))
    metrics.setdefault("enable_dd_throttle",
                        cfg.get("enable_dd_throttle", False))
    metrics.setdefault("recenter_threshold", cfg.get("recenter_threshold"))
    metrics.setdefault("trailing_up_stop",   cfg.get("trailing_up_stop"))

    return metrics


# ---------------------------------------------------------------------------
# Hilfsfunktion: RegimeResult -> dict (JSON-serialisierbar)
# ---------------------------------------------------------------------------

def _serialize_regime(regime_obj) -> Optional[dict]:
    """
    Konvertiert ein RegimeResult-Dataclass-Objekt in ein dict.

    Robust gegen drei Eingabe-Formen:
        - None
        - bereits ein dict (z.B. nach Roundtrip durch JSON)
        - eine Dataclass-Instanz mit __dict__
    """
    if regime_obj is None:
        return None
    if isinstance(regime_obj, dict):
        return regime_obj
    if hasattr(regime_obj, "__dict__"):
        return dict(regime_obj.__dict__)
    return None
