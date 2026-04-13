"""
src/trading/engine.py
=====================
BotRunner fuer einen einzelnen Paper- oder Live-Trading Bot.

Zusammenspiel:
    BotStore  → verwaltet alle Bots (Speicher)
    BotRunner → fuehrt einen einzelnen Bot aus (Logik)
    Broker    → fuehrt Orders aus (Paper oder Live)

Autor: Enes Eryilmaz
Projekt: Grid-Trading-Framework (Bachelorarbeit OST)
"""

import pandas as pd
from datetime import datetime, timezone
from typing import Optional

from config.settings import DEFAULT_FEE_RATE
from src.data.binance_api import fetch_klines_df
from src.strategy.grid_bot import GridBot
from src.strategy.grid_builder import build_grid_config
from src.trading.bot_store import BotStore, store as default_store
from src.metrics import (
    calculate_all_metrics, calculate_grid_efficiency,
    calculate_avg_profit_per_trade, calculate_runtime,
    calculate_unrealized_pnl,
)


# Kerzen pro Intervall fuer den initialen Abruf
_INTERVAL_CANDLES = {
    "1m": 60, "5m": 60, "15m": 60,
    "1h": 48, "4h": 24, "1d": 30,
}


def _now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)


class BotRunner:
    """
    Fuehrt einen einzelnen Bot aus.
    Laedt seinen Zustand aus dem BotStore und speichert ihn zurueck.
    """

    def __init__(self, bot_id: str, store: BotStore = None):
        self.bot_id = bot_id
        self.store  = store or default_store
        self._bot   = self.store.get_bot(bot_id)
        if self._bot is None:
            raise ValueError(f"Bot {bot_id} nicht gefunden")
        self._grid_bot: Optional[GridBot] = None

    # ── Bot initialisieren ───────────────────────────────────────────────────

    def initialize(self) -> tuple[bool, str]:
        """
        Initialisiert den GridBot mit historischen Daten.
        Wird beim ersten Start oder nach einem Neustart aufgerufen.
        
        Returns:
            (True, "") bei Erfolg
            (False, Fehlermeldung) bei Fehler
        """
        cfg      = self._bot["config"]
        coin     = self._bot["coin"]
        interval = self._bot["interval"]
        n_candles = _INTERVAL_CANDLES.get(interval, 48)

        # Preisdaten laden
        from src.data.cache_manager import get_price_data
        df, _ = get_price_data(coin, days=max(1, n_candles // 24 + 1), interval=interval)
        if df is None or df.empty:
            return False, f"Keine Preisdaten für {coin} verfügbar"

        # Grid konfigurieren
        grid_config = build_grid_config(
            lower_price = cfg["lower_price"],
            upper_price = cfg["upper_price"],
            num_grids   = cfg["num_grids"],
            mode        = cfg["grid_mode"],
            fee_rate    = cfg.get("fee_rate", DEFAULT_FEE_RATE),
        )

        # GridBot erstellen
        self._grid_bot = GridBot(
            grid_config       = grid_config,
            total_investment  = cfg["total_investment"],
            fee_rate          = cfg.get("fee_rate", DEFAULT_FEE_RATE),
            reserve_pct       = cfg.get("reserve_pct", 0.03),
            stop_loss_pct     = cfg.get("stop_loss_pct"),
        )

        # Bestehenden State laden falls vorhanden
        saved_state = self._bot.get("state", {})
        if saved_state:
            try:
                self._grid_bot.load_state(saved_state)
            except Exception:
                pass  # Frischer Start wenn State nicht kompatibel

        return True, ""

    # ── Eine Kerze verarbeiten ───────────────────────────────────────────────

    def step(self, candle: dict) -> list[dict]:
        """
        Verarbeitet eine einzelne Kerze.
        
        Args:
            candle: {"open": x, "high": x, "low": x, "close": x, "timestamp": x}
        
        Returns:
            Liste der neuen Trades in diesem Schritt
        """
        if self._grid_bot is None:
            return []

        row = pd.Series(candle)
        trades_before = len(self._grid_bot.trade_log)
        self._grid_bot.process_candle(row)
        trades_after  = len(self._grid_bot.trade_log)

        new_trades = self._grid_bot.trade_log[trades_before:trades_after]

        # State sofort speichern
        self._save_state(candle.get("close", 0))

        return new_trades

    # ── State speichern ──────────────────────────────────────────────────────

    def _save_state(self, current_price: float) -> None:
        """Speichert aktuellen Bot-State und Metriken in den BotStore."""
        if self._grid_bot is None:
            return

        trade_log = self._grid_bot.trade_log
        cfg       = self._bot["config"]

        # Metriken berechnen
        daily_values = self._grid_bot.daily_values or {}
        initial_val  = cfg["total_investment"]
        final_val    = self._grid_bot.get_portfolio_value(current_price)

        open_buys = [
            t for t in trade_log
            if t.get("type") == "BUY" and not t.get("matched", False)
        ]

        metrics = {}
        try:
            metrics = calculate_all_metrics(
                trade_log     = trade_log,
                daily_values  = daily_values,
                initial_value = initial_val,
                final_value   = final_val,
                initial_price = self._grid_bot.initial_price or current_price,
                final_price   = current_price,
                fees_paid     = sum(t.get("fee", 0) for t in trade_log),
                num_days      = max(1, len(daily_values)),
            )
            metrics["grid_efficiency"]      = calculate_grid_efficiency(trade_log, cfg["num_grids"])
            metrics["avg_profit_per_trade"] = calculate_avg_profit_per_trade(trade_log)
            metrics["runtime"]              = calculate_runtime(self._bot["created_at"])
            metrics["unrealized_pnl"]       = calculate_unrealized_pnl(open_buys, current_price)
            metrics["current_price"]        = current_price
            metrics["final_value"]          = final_val
        except Exception as e:
            print(f"BotRunner: Metrik-Fehler: {e}")

        self.store.update_bot(self.bot_id, {
            "state":     self._grid_bot.get_state() if hasattr(self._grid_bot, "get_state") else {},
            "trade_log": trade_log,
            "metrics":   metrics,
            "status":    "stopped" if self._grid_bot.stop_loss_hit else "running",
        })

    # ── Aktuellen Stand abrufen ──────────────────────────────────────────────

    def get_summary(self, current_price: float) -> dict:
        """Gibt eine Zusammenfassung des Bot-Zustands zurück."""
        bot = self.store.get_bot(self.bot_id)
        if bot is None:
            return {}
        metrics = bot.get("metrics", {})
        cfg     = bot["config"]
        return {
            "bot_id":           self.bot_id,
            "coin":             bot["coin"],
            "interval":         bot["interval"],
            "mode":             bot["mode"],
            "status":           bot["status"],
            "created_at":       bot["created_at"],
            "current_price":    current_price,
            "roi_pct":          metrics.get("roi_pct", 0),
            "num_trades":       len(bot.get("trade_log", [])),
            "runtime":          metrics.get("runtime", {}),
            "unrealized_pnl":   metrics.get("unrealized_pnl", {}),
            "lower_price":      cfg["lower_price"],
            "upper_price":      cfg["upper_price"],
            "num_grids":        cfg["num_grids"],
            "total_investment": cfg["total_investment"],
        }


# ---------------------------------------------------------------------------
# Backward-Compatibility: alte Funktionen die noch genutzt werden könnten
# ---------------------------------------------------------------------------

def load_existing_state() -> Optional[dict]:
    """Deprecated: Wird nicht mehr verwendet."""
    return None

def clear_state() -> None:
    """Deprecated: Wird nicht mehr verwendet."""
    pass
