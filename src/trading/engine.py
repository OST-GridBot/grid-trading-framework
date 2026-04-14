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

        # GridBot erstellen — direkt mit Parametern (kein grid_config Objekt)
        self._grid_bot = GridBot(
            total_investment   = cfg["total_investment"],
            lower_price        = cfg["lower_price"],
            upper_price        = cfg["upper_price"],
            num_grids          = cfg["num_grids"],
            grid_mode          = cfg["grid_mode"],
            fee_rate           = cfg.get("fee_rate", DEFAULT_FEE_RATE),
            reserve_pct        = cfg.get("reserve_pct", 0.03),
            stop_loss_pct      = cfg.get("stop_loss_pct"),
            enable_dd_throttle  = cfg.get("enable_dd_throttle", False),
            dd_threshold_1      = cfg.get("dd_threshold_1", 0.10),
            dd_threshold_2      = cfg.get("dd_threshold_2", 0.20),
            enable_variable_orders = cfg.get("enable_variable_orders", False),
            weight_bottom          = cfg.get("weight_bottom", 2.0),
            weight_top             = cfg.get("weight_top", 0.5),
            enable_trailing_up     = cfg.get("enable_trailing_up", False),
            enable_trailing_down   = cfg.get("enable_trailing_down", False),
            trailing_up_stop       = cfg.get("trailing_up_stop"),
            trailing_down_stop     = cfg.get("trailing_down_stop"),
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

        # Timestamps serialisierbar machen (pd.Timestamp → str)
        def _serialize(obj):
            if hasattr(obj, "isoformat"):
                return obj.isoformat()
            if isinstance(obj, dict):
                return {k: _serialize(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [_serialize(i) for i in obj]
            return obj

        trade_log_serialized = _serialize(trade_log)
        state_serialized     = _serialize(
            self._grid_bot.get_state() if hasattr(self._grid_bot, "get_state") else {}
        )

        self.store.update_bot(self.bot_id, {
            "state":     state_serialized,
            "trade_log": trade_log_serialized,
            "metrics":   metrics,
            "status":    "stopped" if self._grid_bot.stop_loss_hit else "running",
        })

    # ── Update: neue Kerzen verarbeiten ─────────────────────────────────────

    def run_update(self) -> dict:
        """
        Holt die neuesten Kerzen und verarbeitet sie.
        Wird vom "Preis aktualisieren" Button in der Page aufgerufen.

        Returns:
            dict mit: current_price, new_trades, error
        """
        self._bot = self.store.get_bot(self.bot_id)
        if self._bot is None:
            return {"error": "Bot nicht gefunden"}
        if self._bot.get("status") != "running":
            return {"error": "Bot ist gestoppt"}

        cfg      = self._bot["config"]
        coin     = self._bot["coin"]
        interval = self._bot["interval"]

        # Aktuelle Kerzen laden
        from src.data.cache_manager import get_price_data
        n_days = {"1m":1,"5m":1,"15m":1,"1h":2,"4h":5,"1d":14}.get(interval, 2)
        df, _ = get_price_data(coin, days=n_days, interval=interval)
        if df is None or df.empty:
            return {"error": f"Keine Preisdaten für {coin}"}

        # GridBot initialisieren falls nötig
        # initialize() lädt den State bereits intern
        if self._grid_bot is None:
            ok, err = self.initialize()
            if not ok:
                return {"error": err}

        # Letzten verarbeiteten Timestamp ermitteln
        # Minimum: Bot-Erstellungszeit → niemals Kerzen vor Bot-Start verarbeiten
        created_at = pd.to_datetime(self._bot.get("created_at", "")).tz_localize(None)             if pd.to_datetime(self._bot.get("created_at","")).tzinfo is not None             else pd.to_datetime(self._bot.get("created_at",""))
        try:
            created_at = pd.to_datetime(self._bot.get("created_at","")).replace(tzinfo=None)
        except Exception:
            created_at = None

        last_ts = created_at  # Standard: nichts vor Bot-Start verarbeiten

        # Wenn bereits Trades vorhanden: letzten Trade-Timestamp nutzen
        saved_trade_log = self._bot.get("trade_log", [])
        if saved_trade_log:
            try:
                last_trade_ts = pd.to_datetime(saved_trade_log[-1].get("timestamp"))
                if last_trade_ts.tzinfo is not None:
                    last_trade_ts = last_trade_ts.tz_localize(None)
                if last_ts is None or last_trade_ts > last_ts:
                    last_ts = last_trade_ts
            except Exception:
                pass

        # Wenn State vorhanden aber keine Trades: letzten bekannten Preis-Timestamp nutzen
        elif self._grid_bot.last_price is not None:
            matching = df[abs(df["close"] - self._grid_bot.last_price) < 0.01]
            if not matching.empty:
                match_ts = pd.to_datetime(matching["timestamp"].iloc[-1])
                if match_ts.tzinfo is not None:
                    match_ts = match_ts.tz_localize(None)
                if last_ts is None or match_ts > last_ts:
                    last_ts = match_ts

        # Nur neue Kerzen verarbeiten
        new_trades = []
        candles_processed = 0
        for _, row in df.iterrows():
            candle_ts = pd.to_datetime(row["timestamp"])
            if last_ts is not None and candle_ts <= last_ts:
                continue
            trades = self.step(row.to_dict())
            new_trades.extend(trades)
            candles_processed += 1

        # Wenn gar keine neuen Kerzen: letzte Kerze verarbeiten
        if candles_processed == 0 and not df.empty:
            trades = self.step(df.iloc[-1].to_dict())
            new_trades.extend(trades)
            candles_processed = 1

        current_price = float(df["close"].iloc[-1])
        return {
            "error":             None,
            "current_price":     current_price,
            "new_trades":        new_trades,
            "candles_processed": candles_processed,
        }

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
