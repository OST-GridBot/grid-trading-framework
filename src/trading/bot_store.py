"""
src/trading/bot_store.py
========================
Zentraler Bot-Speicher fuer Paper- und Live-Trading.

Verwaltet alle laufenden Bots als JSON-Dateien:
    data/cache/bots/bot_{id}_{coin}_{mode}.json

Regeln:
    - Max 10 Bots pro Modus (paper / live)
    - Jeder Bot hat eine eindeutige ID (8-stellig hex)
    - Beide Modi (paper/live) teilen dieselbe Infrastruktur

Autor: Enes Eryilmaz
Projekt: Grid-Trading-Framework (Bachelorarbeit OST)
"""

import json
import uuid
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

from config.settings import CACHE_DIR, MAX_BOTS_PER_MODE, MAX_BACKTESTS

BOTS_DIR = Path(CACHE_DIR) / "bots"
BOTS_DIR.mkdir(parents=True, exist_ok=True)

# Gültige Modi
VALID_MODES = ("paper", "live", "backtest")


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def _bot_path(bot_id: str) -> Path:
    """Gibt den Pfad zur JSON-Datei eines Bots zurück."""
    matches = list(BOTS_DIR.glob(f"bot_{bot_id}_*.json"))
    if matches:
        return matches[0]
    return BOTS_DIR / f"bot_{bot_id}_unknown.json"


def _new_bot_id() -> str:
    """Generiert eine eindeutige 8-stellige Bot-ID."""
    return uuid.uuid4().hex[:8]


def _now_iso() -> str:
    """Gibt aktuelle UTC-Zeit als ISO-String zurück."""
    return datetime.now(tz=timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# BotStore
# ---------------------------------------------------------------------------

class BotStore:
    """
    Zentraler Speicher für alle Paper- und Live-Trading Bots.
    
    Jeder Bot wird als einzelne JSON-Datei gespeichert:
        data/cache/bots/bot_{id}_{COIN}_{mode}.json
    """

    # ── Lesen ────────────────────────────────────────────────────────────────

    def get_all_bots(self, mode: Optional[str] = None) -> list[dict]:
        """
        Gibt alle gespeicherten Bots zurück.
        
        Args:
            mode: "paper", "live" oder None (alle)
        """
        bots = []
        for f in sorted(BOTS_DIR.glob("bot_*.json")):
            try:
                bot = json.loads(f.read_text())
                if mode is None or bot.get("mode") == mode:
                    bots.append(bot)
            except Exception as e:
                print(f"BotStore: Lesefehler {f.name}: {e}")
        return bots

    def get_bot(self, bot_id: str) -> Optional[dict]:
        """Gibt einen einzelnen Bot zurück oder None."""
        path = _bot_path(bot_id)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except Exception as e:
            print(f"BotStore: Lesefehler {bot_id}: {e}")
            return None

    def count_bots(self, mode: str) -> int:
        """Gibt die Anzahl der Bots eines Modus zurück."""
        return len(self.get_all_bots(mode=mode))

    def can_create_bot(self, mode: str) -> tuple[bool, str]:
        """
        Prüft ob ein neuer Bot erstellt werden kann.
        
        Returns:
            (True, "") wenn möglich
            (False, Fehlermeldung) wenn nicht
        """
        if mode not in VALID_MODES:
            return False, f"Ungültiger Modus: {mode}"
        # Backtest hat eigenes (hoeheres) Limit; PT/LT teilen sich das alte
        limit = MAX_BACKTESTS if mode == "backtest" else MAX_BOTS_PER_MODE
        count = self.count_bots(mode)
        if count >= limit:
            return False, (
                f"Maximum von {limit} Bots im {mode.upper()}-Modus "
                f"erreicht."
            )
        return True, ""

    # ── Schreiben ────────────────────────────────────────────────────────────

    def create_bot(
        self,
        mode:               str,
        coin:               str,
        interval:           str,
        lower_price:        float,
        upper_price:        float,
        total_investment:   float,
        num_grids:          int,
        grid_mode:          str   = "arithmetic",
        fee_rate:           float = 0.001,
        reserve_pct:        float = 0.03,
        stop_loss_pct:       Optional[float] = None,
        take_profit_pct:     Optional[float] = None,
        stop_loss_roi_pct:   Optional[float] = None,
        take_profit_roi_pct: Optional[float] = None,
        stop_loss_pl_usdt:   Optional[float] = None,
        take_profit_pl_usdt: Optional[float] = None,
        enable_dd_throttle:  bool  = False,
        dd_threshold_1:      float = 0.10,
        dd_threshold_2:      float = 0.20,
        enable_atr_adjust:      bool  = False,
        atr_multiplier:         float = 1.0,
        enable_atr_dynamic:     bool  = False,
        atr_dynamic_threshold:  float = 0.15,
        enable_trailing_up:     bool  = False,
        trailing_up_stop:       float = None,
        trail_stop_levels:      bool  = False,
        enable_recentering_up:   bool  = False,
        enable_recentering_down: bool  = False,
        recenter_threshold:     float = 0.05,
        grid_trigger_price:     Optional[float] = None,
        enable_initial_buy:     bool  = True,
        stop_bot_on_trigger:    bool  = False,
    ) -> tuple[Optional[str], str]:
        """
        Erstellt einen neuen Bot und speichert ihn.
        
        Returns:
            (bot_id, "") bei Erfolg
            (None, Fehlermeldung) bei Fehler
        """
        ok, err = self.can_create_bot(mode)
        if not ok:
            return None, err

        bot_id   = _new_bot_id()
        filename = f"bot_{bot_id}_{coin.upper()}USDT_{mode}.json"

        bot = {
            "bot_id":           bot_id,
            "mode":             mode,
            "coin":             coin.upper(),
            "interval":         interval,
            "status":           "running",
            "created_at":       _now_iso(),
            "last_update":      _now_iso(),
            "config": {
                "lower_price":      lower_price,
                "upper_price":      upper_price,
                "total_investment": total_investment,
                "num_grids":        num_grids,
                "grid_mode":        grid_mode,
                "fee_rate":         fee_rate,
                "reserve_pct":      reserve_pct,
                "stop_loss_pct":    stop_loss_pct,
                "take_profit_pct":  take_profit_pct,
                "stop_loss_roi_pct":   stop_loss_roi_pct,
                "take_profit_roi_pct": take_profit_roi_pct,
                "stop_loss_pl_usdt":   stop_loss_pl_usdt,
                "take_profit_pl_usdt": take_profit_pl_usdt,
                "enable_dd_throttle":  enable_dd_throttle,
                "dd_threshold_1":      dd_threshold_1,
                "dd_threshold_2":      dd_threshold_2,
                "enable_atr_adjust":      enable_atr_adjust,
                "atr_multiplier":         atr_multiplier,
                "enable_atr_dynamic":     enable_atr_dynamic,
                "atr_dynamic_threshold":  atr_dynamic_threshold,
                "enable_trailing_up":     enable_trailing_up,
                "trailing_up_stop":       trailing_up_stop,
                "trail_stop_levels":      trail_stop_levels,
                "enable_recentering_up":   enable_recentering_up,
                "enable_recentering_down": enable_recentering_down,
                "recenter_threshold":     recenter_threshold,
                # Grid Trigger (None = sofortiger Start)
                "grid_trigger_price":     grid_trigger_price,
                # Initial-Buy (True = Binance-Standard, False = rein USDT)
                "enable_initial_buy":     enable_initial_buy,
                # Bot beim TP/SL-Trigger stoppen (statt nur Force-Sell)
                "stop_bot_on_trigger":    stop_bot_on_trigger,
            },
            "state":     {},
            "trade_log": [],
            "metrics":   {},
        }

        try:
            (BOTS_DIR / filename).write_text(json.dumps(bot, indent=2))
            print(f"BotStore: Bot {bot_id} ({coin} {mode}) erstellt")
            return bot_id, ""
        except Exception as e:
            return None, f"Speicherfehler: {e}"

    def save_backtest(
        self,
        name:     str,
        coin:     str,
        interval: str,
        period:   dict,
        config:   dict,
        result:   dict,
    ) -> tuple[Optional[str], str]:
        """
        Speichert ein Backtest-Result als persistenten Bot-State.

        Anders als create_bot() ist dies KEIN laufender Bot, sondern ein
        Snapshot eines abgeschlossenen Backtests. Wird im selben Verzeichnis
        wie PT/LT-Bots abgelegt (mode="backtest").

        Args:
            name     : Anzeigename (vom User vergeben oder synthetisch generiert)
            coin     : "BTC", "ETH", ...
            interval : "1h", "4h", ...
            period   : {"start_date": str, "end_date": str, "days": int}
            config   : Alle Sim-Parameter (lower_price, upper_price, num_grids,
                       grid_mode, fee_rate, reserve_pct, stop_loss_pct,
                       take_profit_pct, enable_*, ..., total_investment)
            result   : run_backtest()-Result (Standard-Schema + BT-spezifisch)

        Returns:
            (bot_id, "")    bei Erfolg
            (None, errmsg)  bei Fehler
        """
        ok, err = self.can_create_bot("backtest")
        if not ok:
            return None, err

        bot_id   = _new_bot_id()
        filename = f"bot_{bot_id}_{coin.upper()}USDT_backtest.json"

        # Status anhand des Result-error-Felds
        status = "error" if result.get("error") else "completed"

        # Metriken (Standard-Schema) aus dem Result herausziehen.
        # Konsistent mit dem PT/LT-Schema, wo metrics ein eigener Block ist.
        METRIC_KEYS = {
            "roi_pct", "cagr_pct", "calmar_ratio", "sharpe_ratio",
            "profit_factor", "max_drawdown_pct", "max_drawdown_usdt",
            "current_drawdown_pct", "fee_impact_pct", "benchmark_roi_pct",
            "benchmark_roi_usdt", "outperformance_pct", "avg_profit_per_trade",
            "avg_profit_per_trade_pct", "num_trades", "fees_paid",
            "initial_investment", "final_value", "grid_efficiency",
            "unrealized_pnl", "slippage_usdt", "slippage_avg_pct",
            "mechanism_active", "gross_pl_usdt", "gross_pl_pct",
            "grid_profit_total_usdt", "grid_profit_total_pct",
            "capital_per_grid", "active_levels_ratio", "runtime",
            "recentering_count", "trailing_count",
            "stop_loss_triggered", "take_profit_triggered",
            "stop_loss_trigger_timestamp", "stop_loss_trigger_price",
            "take_profit_trigger_timestamp", "take_profit_trigger_price",
        }
        metrics = {k: v for k, v in result.items() if k in METRIC_KEYS}

        # Indikatoren-Block (BT-spezifisch)
        indicator_keys = (
            "atr_usdt", "atr_pct", "adx14", "adx30",
            "vola_monthly_pct", "vola_yearly_pct",
            "return_stats", "price_extremes",
        )
        indicators = {k: result.get(k) for k in indicator_keys if k in result}

        # RegimeResult-Dataclass -> dict (serialisierbar)
        regime_obj = result.get("regime")
        if regime_obj is not None and hasattr(regime_obj, "__dict__"):
            regime_dict = dict(regime_obj.__dict__)
        elif isinstance(regime_obj, dict):
            regime_dict = regime_obj
        else:
            regime_dict = None

        bot = {
            "bot_id":          bot_id,
            "mode":            "backtest",
            "name":            name,
            "coin":            coin.upper(),
            "interval":        interval,
            "status":          status,
            "created_at":      _now_iso(),
            "last_update":     None,
            "config":          dict(config),
            "period":          dict(period),
            "metrics":         metrics,
            "trade_log":       list(result.get("trade_log", [])),
            "trailing_events": list(result.get("trailing_events", [])),
            "recentering_events": list(result.get("recentering_events", [])),
            "state":           None,
            "regime":          regime_dict,
            "indicators":      indicators,
        }

        try:
            (BOTS_DIR / filename).write_text(json.dumps(bot, indent=2, default=str))
            print(f"BotStore: Backtest {bot_id} ({coin}) gespeichert")
            return bot_id, ""
        except Exception as e:
            return None, f"Speicherfehler: {e}"

    def update_bot(self, bot_id: str, updates: dict) -> bool:
        """
        Aktualisiert einen bestehenden Bot.
        
        Args:
            bot_id  : Bot-ID
            updates : Dict mit zu aktualisierenden Feldern
        """
        bot = self.get_bot(bot_id)
        if bot is None:
            print(f"BotStore: Bot {bot_id} nicht gefunden")
            return False
        bot.update(updates)
        bot["last_update"] = _now_iso()
        try:
            _bot_path(bot_id).write_text(json.dumps(bot, indent=2))
            return True
        except Exception as e:
            print(f"BotStore: Schreibfehler {bot_id}: {e}")
            return False

    def set_status(self, bot_id: str, status: str) -> bool:
        """Setzt den Status eines Bots (running / stopped / error)."""
        return self.update_bot(bot_id, {"status": status})

    def delete_bot(self, bot_id: str) -> bool:
        """Löscht einen Bot permanent."""
        path = _bot_path(bot_id)
        if not path.exists():
            return False
        try:
            path.unlink()
            print(f"BotStore: Bot {bot_id} gelöscht")
            return True
        except Exception as e:
            print(f"BotStore: Löschfehler {bot_id}: {e}")
            return False

# ---------------------------------------------------------------------------
# Singleton-Instanz
# ---------------------------------------------------------------------------

# Globale Instanz — wird von allen Pages verwendet
store = BotStore()
