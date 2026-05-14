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
from typing import Optional

from config.settings import DEFAULT_FEE_RATE
from src.strategy.grid_bot import GridBot
from src.trading.bot_store import BotStore, store as default_store
from src.analysis.metrics import calculate_all_metrics


# Lookback in Tagen pro Intervall — gross genug fuer ADX30 (~60 Kerzen).
# Wird sowohl beim initialen Abruf in initialize() als auch bei run_update()
# verwendet, damit beide Pfade konsistent sind.
_INTERVAL_DAYS = {
    "1m":  1,    # 1440 Kerzen
    "5m":  1,    # 288 Kerzen
    "15m": 2,    # 192 Kerzen
    "1h":  7,    # 168 Kerzen
    "4h":  10,   # 60 Kerzen — knapp fuer ADX30
    "1d":  40,   # 40 Kerzen — ADX30 stabil
}


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
        n_days   = _INTERVAL_DAYS.get(interval, 7)

        # Preisdaten laden
        from src.data.cache_manager import get_price_data
        df, _ = get_price_data(coin, days=n_days, interval=interval)
        if df is None or df.empty:
            return False, f"Keine Preisdaten für {coin} verfügbar"

        # Aktuellen Preis als initial_price für GridBot bestimmen
        initial_price = float(df["close"].iloc[-1]) if df is not None and not df.empty else None

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
            take_profit_pct    = cfg.get("take_profit_pct"),
            enable_dd_throttle  = cfg.get("enable_dd_throttle", False),
            dd_threshold_1      = cfg.get("dd_threshold_1", 0.10),
            dd_threshold_2      = cfg.get("dd_threshold_2", 0.20),
            enable_atr_adjust      = cfg.get("enable_atr_adjust", False),
            atr_multiplier         = cfg.get("atr_multiplier", 1.0),
            enable_atr_dynamic     = cfg.get("enable_atr_dynamic", False),
            atr_dynamic_threshold  = cfg.get("atr_dynamic_threshold", 0.15),
            enable_trailing_up     = cfg.get("enable_trailing_up", False),
            enable_trailing_down   = cfg.get("enable_trailing_down", False),
            trailing_up_stop       = cfg.get("trailing_up_stop"),
            trailing_down_stop     = cfg.get("trailing_down_stop"),
            enable_recentering_up   = cfg.get("enable_recentering_up",
                                              cfg.get("enable_recentering", False)),
            enable_recentering_down = cfg.get("enable_recentering_down",
                                              cfg.get("enable_recentering", False)),
            recenter_threshold     = cfg.get("recenter_threshold", 0.05),
            df                     = df,
            initial_price          = initial_price,
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

    def _save_state(self, current_price: float, df: Optional[pd.DataFrame] = None) -> None:
        """
        Speichert aktuellen Bot-State und Metriken in den BotStore.

        Args:
            current_price: Aktueller Marktpreis
            df           : Optional. Wenn gegeben, werden Indikatoren
                           (ADX/ATR/Vola, Markt-Stats, Returns) berechnet
                           und ins metrics-Dict gepackt. Nur am Ende eines
                           Updates uebergeben (run_update), nicht pro Kerze.
        """
        if self._grid_bot is None:
            return

        trade_log = self._grid_bot.trade_log
        cfg       = self._bot["config"]

        # Metriken berechnen
        daily_values = self._grid_bot.daily_values or {}
        initial_val  = cfg["total_investment"]
        final_val    = self._grid_bot.get_portfolio_value(current_price)

        # Offene Positionen direkt aus dem FIFO-Inventar (statt Trade-Log mit
        # nicht-gesetztem matched-Flag zu filtern, was vorher alle BUYs als
        # "offen" markiert hat).
        open_buys = [
            {"price": float(p), "amount": float(a), "fee": 0.0}
            for (a, p, _ts) in self._grid_bot.coin_inventory
        ]

        # Echte Laufzeit in Tagen (statt grobe Approximation ueber daily_values)
        try:
            created_at = pd.to_datetime(self._bot["created_at"])
            now_utc    = pd.Timestamp.now(tz="UTC")
            if created_at.tzinfo is None:
                created_at = created_at.tz_localize("UTC")
            num_days = max(0.0, (now_utc - created_at).total_seconds() / 86400.0)
        except Exception:
            num_days = max(1.0, len(daily_values))

        has_dynamic_capital = cfg.get("enable_dd_throttle", False)

        metrics = {}
        try:
            metrics = calculate_all_metrics(
                trade_log           = trade_log,
                daily_values        = daily_values,
                initial_value       = initial_val,
                final_value         = final_val,
                initial_price       = self._grid_bot.initial_price or current_price,
                final_price         = current_price,
                fees_paid           = sum(t.get("fee", 0) for t in trade_log),
                num_days            = num_days,
                num_grids           = cfg["num_grids"],
                current_price       = current_price,
                open_buys           = open_buys,
                start_time          = self._bot["created_at"],
                fee_rate            = cfg.get("fee_rate", 0.001),
                has_dynamic_capital = has_dynamic_capital,
            )
        except Exception as e:
            print(f"BotRunner: Metrik-Fehler: {e}")

        # Slippage-Hook: aktuell None, weil PaperBroker/LiveBroker nicht im
        # aktiven Code-Pfad sind. TODO: sobald BotRunner einen Broker nutzt,
        # hier broker.state.total_slippage und avg slippage_pct lesen.
        metrics.setdefault("slippage_usdt",    None)
        metrics.setdefault("slippage_avg_pct", None)

        # Mechanismus-Aktivierung (fuer Tab "Mechanisms" — counts kommen aus
        # bot.state, hier nur die "ist aktiviert"-Flags aus der Config)
        metrics["mechanism_active"] = {
            "recentering": cfg.get("enable_recentering_up",
                                   cfg.get("enable_recentering", False))
                           or cfg.get("enable_recentering_down",
                                      cfg.get("enable_recentering", False)),
            "trailing":    cfg.get("enable_trailing_up", False)
                           or cfg.get("enable_trailing_down", False),
            "stop_loss":   cfg.get("stop_loss_pct")   is not None,
            "take_profit": cfg.get("take_profit_pct") is not None,
        }
        # Stop-Loss / Take-Profit Trigger-Status aus bot
        metrics["stop_loss_triggered"]   = self._grid_bot.stop_loss_hit
        metrics["take_profit_triggered"] = self._grid_bot.take_profit_hit
        # Counter aus Bot-State
        metrics["recentering_count"] = self._grid_bot.recentering_count
        metrics["trailing_count"]    = self._grid_bot.trailing_count

        # Indikatoren / Marktdaten — nur wenn df gegeben (am Ende von run_update)
        if df is not None and not df.empty:
            try:
                from src.analysis.indicators import (
                    get_atr_stats, get_adx_value, calculate_volatility,
                    calculate_return_stats, get_price_extremes,
                )
                atr_usdt, atr_pct = get_atr_stats(df)
                vola_m, vola_y    = calculate_volatility(df, self._bot["interval"])
                metrics["atr_usdt"]         = atr_usdt
                metrics["atr_pct"]          = atr_pct
                metrics["adx14"]            = get_adx_value(df, period=14)
                metrics["adx30"]            = get_adx_value(df, period=30)
                metrics["vola_monthly_pct"] = vola_m
                metrics["vola_yearly_pct"]  = vola_y
                metrics["return_stats"]     = calculate_return_stats(df)
                metrics["price_extremes"]   = get_price_extremes(df)
            except Exception as e:
                print(f"BotRunner: Indikator-Fehler: {e}")

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

        trailing_events_serialized = _serialize(
            getattr(self._grid_bot, "trailing_events", []) or []
        )

        self.store.update_bot(self.bot_id, {
            "state":           state_serialized,
            "trade_log":       trade_log_serialized,
            "trailing_events": trailing_events_serialized,
            "metrics":         metrics,
            "status":          "stopped" if (self._grid_bot.stop_loss_hit or self._grid_bot.take_profit_hit) else "running",
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
        n_days = _INTERVAL_DAYS.get(interval, 7)
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

        # Indikatoren-Update am Ende: einmaliger Save mit df, damit ADX/ATR/
        # Vola/Returns/Marktdaten-Extremes ins metrics-Dict landen
        if not df.empty:
            self._save_state(current_price, df=df)

        # Marktregime fuer die Page (wird neben dem Bot-Update angezeigt).
        regime = None
        if not df.empty:
            try:
                from src.analysis.regime import detect_regime
                regime = detect_regime(df, self._bot["interval"])
            except Exception as e:
                print(f"BotRunner: Regime-Fehler: {e}")

        return {
            "error":             None,
            "current_price":     current_price,
            "new_trades":        new_trades,
            "candles_processed": candles_processed,
            "regime":            regime,
        }


