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

from config.settings import CACHE_DIR, MAX_BOTS_PER_MODE

BOTS_DIR = Path(CACHE_DIR) / "bots"
BOTS_DIR.mkdir(parents=True, exist_ok=True)

# Gültige Modi
VALID_MODES = ("paper", "live")


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

    def bot_exists(self, bot_id: str) -> bool:
        """Prüft ob ein Bot existiert."""
        return _bot_path(bot_id).exists()

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
        count = self.count_bots(mode)
        if count >= MAX_BOTS_PER_MODE:
            return False, (
                f"Maximum von {MAX_BOTS_PER_MODE} Bots im {mode.upper()}-Modus "
                f"erreicht. Bitte einen laufenden Bot stoppen."
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
        stop_loss_pct:      Optional[float] = None,
        enable_dd_throttle:  bool  = False,
        dd_threshold_1:      float = 0.10,
        dd_threshold_2:      float = 0.20,
        enable_variable_orders: bool  = False,
        weight_bottom:          float = 2.0,
        weight_top:             float = 0.5,
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
                "enable_dd_throttle":  enable_dd_throttle,
                "dd_threshold_1":      dd_threshold_1,
                "dd_threshold_2":      dd_threshold_2,
                "enable_variable_orders": enable_variable_orders,
                "weight_bottom":          weight_bottom,
                "weight_top":             weight_top,
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

    def save_trade_log(self, bot_id: str, trade_log: list) -> bool:
        """Speichert den Trade-Log eines Bots."""
        return self.update_bot(bot_id, {"trade_log": trade_log})

    def save_metrics(self, bot_id: str, metrics: dict) -> bool:
        """Speichert die Metriken eines Bots."""
        return self.update_bot(bot_id, {"metrics": metrics})

    def save_state(self, bot_id: str, state: dict) -> bool:
        """Speichert den internen Bot-State (GridBot State)."""
        return self.update_bot(bot_id, {"state": state})


# ---------------------------------------------------------------------------
# Singleton-Instanz
# ---------------------------------------------------------------------------

# Globale Instanz — wird von allen Pages verwendet
store = BotStore()
