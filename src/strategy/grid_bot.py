"""
src/strategy/grid_bot.py
========================
Kernlogik des Grid-Trading-Bots.

Klassen:
    GridState : Zustand eines einzelnen Grid-Levels
    GridBot   : Hauptklasse mit vollstaendiger Bot-Logik

Funktionen:
    simulate_grid_bot(): Fuehrt Backtesting ueber einen DataFrame aus

Verbesserungen gegenueber Prototyp (bot.py v27):
    - coin_reserved vollstaendig entfernt
    - Keine UI-Abhaengigkeit (kein streamlit import)
    - Recentering-Logik neu implementiert (Ziel 8)
    - Stop-Loss Parameter neu (Ziel 9)
    - Vollstaendige Typ-Hints und Dokumentation
    - Keine Debug-Prints im Produktionscode

Theoretischer Hintergrund (Bachelorarbeit):
    Grid-Bots platzieren Kauf- und Verkaufsorders in gleichmaessigen
    Abstaenden. Bei jedem Preisdurchgang eines Grid-Levels wird ein
    Trade ausgefuehrt. Gewinn entsteht durch die Preisdifferenz
    zwischen Kauf- und Verkaufslevel abzueglich Gebuehren.

Autor: Enes Eryilmaz
Projekt: Grid-Trading-Framework (Bachelorarbeit OST)
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from datetime import datetime

from config.settings import (
    DEFAULT_FEE_RATE,
    DEFAULT_GRID_MODE,
    DEFAULT_NUM_GRIDS,
    DEFAULT_RESERVE_PCT,
)
from src.strategy.grid_builder import calculate_grid_lines, build_grid_config


# ---------------------------------------------------------------------------
# Versionierung
# ---------------------------------------------------------------------------

BOT_VERSION = "grid_bot.py v1.0"


# ---------------------------------------------------------------------------
# Datenklassen
# ---------------------------------------------------------------------------

@dataclass
class GridState:
    """
    Zustand eines einzelnen Grid-Levels.

    Attributes:
        price       : Preis dieses Grid-Levels
        side        : Aktueller Zustand (buy / sell / blocked)
        trade_amount: Coin-Betrag pro Trade an diesem Level
        trade_count : Anzahl ausgefuehrter Trades an diesem Level
    """
    price:        float
    side:         str    # "buy", "sell", "blocked"
    trade_amount: float
    trade_count:  int = 0


@dataclass
class TradeRecord:
    """
    Eintrag im Trade-Log.

    Attributes:
        timestamp   : Zeitpunkt des Trades
        trade_type  : "Initial BUY", "BUY" oder "SELL"
        grid_price  : Grid-Level an dem der Trade ausgeloest wurde
        exec_price  : Tatsaechlicher Ausfuehrungspreis (Close der Kerze)
        amount      : Gehandelte Coin-Menge
        fee         : Bezahlte Gebuehr in USDT
        profit      : Realisierter Gewinn in USDT (nur bei SELL)
    """
    timestamp:  pd.Timestamp
    trade_type: str
    grid_price: float
    exec_price: float
    amount:     float
    fee:        float
    profit:     float


# ---------------------------------------------------------------------------
# GridBot Hauptklasse
# ---------------------------------------------------------------------------

class GridBot:
    """
    Grid-Trading-Bot fuer Spot-Maerkte.

    Implementiert eine vollstaendige Grid-Bot-Logik mit:
        - Arithmetischen und geometrischen Grids
        - FIFO-Inventarverwaltung fuer korrekte Gewinnberechnung
        - Dynamischem Recentering wenn Preis Grid verlaesst
        - Stop-Loss Mechanismus
        - Taeglichem Portfolio-Tracking fuer Kennzahlen

    Args:
        total_investment: Gesamtkapital in USDT
        lower_price     : Untere Grid-Grenze
        upper_price     : Obere Grid-Grenze
        num_grids       : Anzahl Grids
        grid_mode       : "arithmetic" oder "geometric"
        fee_rate        : Gebuehrenrate pro Trade (z.B. 0.001 = 0.1%)
        initial_price   : Startpreis (erste Kerze)
        reserve_pct     : Kapitalreserve fuer Gebuehren (z.B. 0.03 = 3%)
        stop_loss_pct   : Stop-Loss in % (z.B. 0.20 = 20% Verlust, None = deaktiviert)
        enable_recentering: True = Grid automatisch neu zentrieren
        recenter_threshold: Schwellenwert fuer Recentering in % (z.B. 0.05 = 5%)
    """

    def __init__(
        self,
        total_investment:    float,
        lower_price:         float,
        upper_price:         float,
        num_grids:           int   = DEFAULT_NUM_GRIDS,
        grid_mode:           str   = DEFAULT_GRID_MODE,
        fee_rate:            float = DEFAULT_FEE_RATE,
        initial_price:       Optional[float] = None,
        reserve_pct:         float = DEFAULT_RESERVE_PCT,
        stop_loss_pct:       Optional[float] = None,
        enable_recentering:  bool  = False,
        recenter_threshold:  float = 0.05,
        # Drawdown-Drosselung
        enable_dd_throttle:  bool  = False,
        dd_threshold_1:      float = 0.10,   # -10% → 50% Ordergrösse
        dd_threshold_2:      float = 0.20,   # -20% → 25% Ordergrösse
        # Variable Ordergrössen
        enable_variable_orders: bool  = False,
        weight_bottom:          float = 2.0,
        weight_top:             float = 0.5,
        # Grid Trailing
        enable_trailing_up:     bool  = False,
        enable_trailing_down:   bool  = False,
        trailing_up_stop:       Optional[float] = None,
        trailing_down_stop:     Optional[float] = None,
    ):
        self._validate_inputs(total_investment, lower_price, upper_price,
                              num_grids, fee_rate)

        # Grundparameter
        self.total_investment   = total_investment
        self.lower_price        = lower_price
        self.upper_price        = upper_price
        self.num_grids          = num_grids
        self.grid_mode          = grid_mode
        self.fee_rate           = fee_rate
        self.reserve_pct        = reserve_pct
        self.stop_loss_pct      = stop_loss_pct
        self.enable_recentering = enable_recentering
        self.recenter_threshold = recenter_threshold
        self.enable_dd_throttle  = enable_dd_throttle
        self.dd_threshold_1      = dd_threshold_1
        self.dd_threshold_2      = dd_threshold_2
        self.dd_throttle_factor  = 1.0  # aktueller Drosselfaktor
        self.enable_variable_orders = enable_variable_orders
        self.weight_bottom           = weight_bottom
        self.weight_top              = weight_top
        self.enable_trailing_up      = enable_trailing_up
        self.enable_trailing_down    = enable_trailing_down
        self.trailing_up_stop        = trailing_up_stop
        self.trailing_down_stop      = trailing_down_stop
        self.trailing_count          = 0

        # Grid-Linien berechnen
        self.grid_lines = calculate_grid_lines(
            lower_price, upper_price, num_grids, grid_mode
        )

        # Portfolio
        self.position: Dict[str, float] = {
            "usdt": float(total_investment),
            "coin": 0.0,
        }

        # FIFO-Inventar: Liste von (amount, buy_price, timestamp)
        self.coin_inventory: List[Tuple[float, float, pd.Timestamp]] = []

        # Tracking
        self.trade_log:    List[dict]        = []
        self.daily_values: Dict[str, float]  = {}
        self.grids:        Dict[float, GridState] = {}
        self.recentering_count: int = 0
        self.stop_loss_triggered: bool = False

        # Preise
        self.last_price        = initial_price
        self.last_traded_price = None

        # Initialisierung
        self._initialize_grids(total_investment, initial_price)

    # -----------------------------------------------------------------------
    # Initialisierung
    # -----------------------------------------------------------------------

    def _build_grids(self, current_price: float) -> None:
        """
        Zentrale Methode zum Aufbau der Grid-States.
        Beruecksichtigt grid_mode (asymmetrisch) und variable_order_size.
        Wird von _initialize_grids, _shift_grid und _recenter_grid verwendet.
        """
        n = len(self.grid_lines)

        # Variable Ordergrössen: Gewichte berechnen
        if self.enable_variable_orders and n > 1:
            weights = [
                self.weight_bottom + (self.weight_top - self.weight_bottom) * (i / (n - 1))
                for i in range(n)
            ]
        else:
            weights = [1.0] * n

        # Normalisieren
        weight_sum = sum(weights) or n
        weights = [w / weight_sum * n for w in weights]

        self.grids = {}
        for idx, price in enumerate(self.grid_lines):
            amount_usdt = self.base_amount_usdt * weights[idx]
            coin_amount = amount_usdt / (price * (1 + self.fee_rate))
            if price > current_price:
                side = "sell"
            elif price < current_price:
                side = "buy"
            else:
                side = "blocked"
            self.grids[price] = GridState(
                price=round(price, 8),
                side=side,
                trade_amount=coin_amount,
            )

    def _initialize_grids(
        self,
        total_investment: float,
        initial_price:    Optional[float],
    ) -> None:
        """
        Initialisiert alle Grid-Levels.

        Bot startet ausschliesslich mit USDT. Kein initialer Coin-Kauf.
        Grids unterhalb initial_price sind Buy-Grids.
        Grids oberhalb initial_price sind Sell-Grids.
        """
        if initial_price is None:
            initial_price = self.grid_lines[len(self.grid_lines) // 2]

        # Effektives Kapital gleichmaessig auf alle Grids verteilen
        effective_investment  = total_investment * (1 - self.reserve_pct)
        self.base_amount_usdt = effective_investment / self.num_grids

        # Grid-States aufbauen (inkl. asymm. + variable orders)
        self._build_grids(initial_price)

        # Grids unterhalb initial_price sind buy (nicht sell)
        for price, g in self.grids.items():
            if price < initial_price:
                g.side = "buy"
            elif price >= initial_price:
                g.side = "sell"

    # -----------------------------------------------------------------------
    # Grid-Zustände aktualisieren
    # -----------------------------------------------------------------------

    def _update_grid_sides(
        self,
        current_price:  float,
        blocked_price:  Optional[float] = None,
    ) -> None:
        """Aktualisiert Buy/Sell-Zustände aller Grids basierend auf aktuellem Preis."""
        for price in self.grid_lines:
            if np.isclose(price, current_price):
                continue
            if price == blocked_price:
                self.grids[price].side = "blocked"
            elif price > current_price:
                self.grids[price].side = "sell"
            else:
                self.grids[price].side = "buy"

    # -----------------------------------------------------------------------
    # Kerze verarbeiten
    # -----------------------------------------------------------------------

    def process_candle(self, candle: pd.Series) -> None:
        """
        Verarbeitet eine einzelne Kerze und fuehrt Trades aus.

        Ablauf:
            1. Stop-Loss pruefen
            2. Portfolio-Wert tracken
            3. Grid-Zustände aktualisieren
            4. Trades ausfuehren fuer alle durchkreuzten Levels
            5. Recentering pruefen

        Args:
            candle: pd.Series mit timestamp, open, high, low, close, volume
        """
        if self.stop_loss_triggered:
            return

        try:
            current_price = float(candle["close"])
            timestamp     = candle["timestamp"]
            date_str      = pd.to_datetime(timestamp).strftime("%Y-%m-%d")

            # Portfolio-Wert tracken
            portfolio_value = (
                self.position["usdt"] + self.position["coin"] * current_price
            )
            self.daily_values[date_str] = portfolio_value

            # Drawdown-Drosselung aktualisieren
            if self.enable_dd_throttle:
                self._update_dd_throttle(portfolio_value)

            # Stop-Loss pruefen
            if self._check_stop_loss(portfolio_value):
                self.stop_loss_triggered = True
                return

            prev_price         = self.last_price if self.last_price else float(candle["open"])
            last_traded_price  = self.last_traded_price or prev_price

            # Grid-Zustände aktualisieren
            self._update_grid_sides(prev_price, last_traded_price)

            # Trades ausfuehren
            for grid in self.grids.values():
                crossed_up   = prev_price < grid.price < current_price
                crossed_down = prev_price > grid.price > current_price

                if (crossed_up   and grid.side == "sell") or                    (crossed_down and grid.side == "buy"):
                    if grid.price != self.last_traded_price and                        not np.isclose(grid.price, current_price):
                        self._execute_trade(grid, candle)
                        grid.side = "blocked"

            self.last_price = current_price

            # Recentering pruefen
            if self.enable_recentering:
                self._check_recentering(current_price)

            # Grid Trailing pruefen
            if self.enable_trailing_up or self.enable_trailing_down:
                self._check_trailing(current_price)

        except Exception as e:
            raise RuntimeError(f"Fehler bei Kerzenverarbeitung: {e}")

    # -----------------------------------------------------------------------
    # Trade ausfuehren
    # -----------------------------------------------------------------------

    def _execute_trade(self, grid: GridState, candle: pd.Series) -> None:
        """
        Fuehrt einen Kauf oder Verkauf an einem Grid-Level aus.

        Verkauf (SELL):
            Coins werden per FIFO verkauft (aelteste zuerst).
            Gewinn = Differenz zwischen Kauf- und Verkaufspreis.

        Kauf (BUY):
            USDT wird in Coins umgetauscht.
            Coins werden ins FIFO-Inventar aufgenommen.

        Args:
            grid  : GridState des auszufuehrenden Levels
            candle: Aktuelle Kerze fuer Timestamp und Preis
        """
        fee    = 0.0
        profit = 0.0
        timestamp = candle["timestamp"]

        try:
            if grid.side == "sell":
                # Tatsaechlich verkaufte Menge aus FIFO ermitteln
                # (eine FIFO-Position = ein BUY, exakt diese Menge verkaufen)
                if not self.coin_inventory:
                    return  # Kein Inventar vorhanden

                # Genau eine FIFO-Position verkaufen (aelteste zuerst)
                oldest_amt, oldest_price, oldest_time = self.coin_inventory[0]
                actual_sell_amt = oldest_amt  # exakte Menge aus dem BUY

                # Genuegend Coins vorhanden?
                if self.position["coin"] < actual_sell_amt - 1e-10:
                    return

                profit = (grid.price - oldest_price) * actual_sell_amt
                fee    = actual_sell_amt * grid.price * self.fee_rate
                profit -= fee

                self.coin_inventory.pop(0)
                self.position["coin"] -= actual_sell_amt
                self.position["usdt"] += (actual_sell_amt * grid.price) - fee

                # trade_amount fuer den Log auf tatsaechliche Menge setzen
                grid.trade_amount = actual_sell_amt

            else:  # buy
                # Drawdown-Drosselung: Ordergrösse reduzieren
                throttled_amount = grid.trade_amount * self.dd_throttle_factor
                required_usdt = throttled_amount * grid.price * (1 + self.fee_rate)
                if self.position["usdt"] < required_usdt:
                    return  # Nicht genuegend USDT

                fee = throttled_amount * grid.price * self.fee_rate
                self.position["usdt"] -= required_usdt
                self.position["coin"] += throttled_amount
                self.coin_inventory.append(
                    (throttled_amount, grid.price, timestamp)
                )
                grid.trade_amount = throttled_amount

            # Trade loggen
            self.trade_log.append({
                "timestamp": timestamp,
                "type":      grid.side.upper(),
                "cprice":    float(candle["close"]),
                "price":     float(grid.price),
                "amount":    float(grid.trade_amount),
                "fee":       float(fee),
                "profit":    float(profit),
            })

            self.last_traded_price = grid.price
            grid.trade_count += 1

        except Exception as e:
            raise RuntimeError(f"Trade-Fehler bei {grid.price}: {e}")

    # -----------------------------------------------------------------------
    # Stop-Loss
    # -----------------------------------------------------------------------

    def _check_stop_loss(self, portfolio_value: float) -> bool:
        """
        Prueft ob der Stop-Loss ausgeloest wurde.

        Args:
            portfolio_value: Aktueller Portfolio-Wert in USDT

        Returns:
            True wenn Stop-Loss ausgeloest
        """
        if self.stop_loss_pct is None:
            return False

        loss_pct = (self.total_investment - portfolio_value) / self.total_investment
        return loss_pct >= self.stop_loss_pct

    # -----------------------------------------------------------------------
    # Recentering
    # -----------------------------------------------------------------------

    def _check_recentering(self, current_price: float) -> None:
        """
        Prueft ob das Grid neu zentriert werden soll.

        Recentering wird ausgeloest wenn der Preis ausserhalb des
        definierten Schwellenwerts vom Grid-Zentrum abweicht.

        Logik:
            Grid-Zentrum = Mittelpunkt zwischen lower und upper Price.
            Wenn Preis > upper * (1 - threshold) oder
                 Preis < lower * (1 + threshold)
            -> Grid neu zentrieren.

        Args:
            current_price: Aktueller Marktpreis
        """
        # Recentering wenn Preis AUSSERHALB der Grid-Grenzen (+ Schwellenwert)
        near_upper = current_price >= self.upper_price * (1 + self.recenter_threshold)
        near_lower = current_price <= self.lower_price * (1 - self.recenter_threshold)

        if near_upper or near_lower:
            self._recenter_grid(current_price)

    def _recenter_grid(self, current_price: float) -> None:
        """
        Zentriert das Grid um den aktuellen Preis neu.

        Berechnet neue lower/upper Grenzen basierend auf der
        urspruenglichen Grid-Breite, zentriert auf current_price.

        Args:
            current_price: Neues Grid-Zentrum
        """
        half_range = (self.upper_price - self.lower_price) / 2

        self.lower_price = max(current_price - half_range, current_price * 0.5)
        self.upper_price = current_price + half_range

        self.grid_lines = calculate_grid_lines(
            self.lower_price, self.upper_price,
            self.num_grids, self.grid_mode
        )

        # Grid-States neu aufbauen (inkl. asymm. + variable orders)
        self._build_grids(current_price)
        self.last_traded_price = None
        self.recentering_count += 1

    # -----------------------------------------------------------------------
    # Validierung
    # -----------------------------------------------------------------------

    def _check_trailing(self, current_price: float) -> None:
        """
        Prueft ob das Grid trailing ausgeloest werden soll.

        Trailing UP:  Preis >= upper_price → Grid 1 Schritt nach oben
        Trailing DOWN: Preis <= lower_price → Grid 1 Schritt nach unten

        Stop-Preise verhindern unkontrolliertes Verschieben.
        """
        grid_step = (self.upper_price - self.lower_price) / self.num_grids

        # Trailing UP
        if self.enable_trailing_up and current_price >= self.upper_price:
            new_upper = self.upper_price + grid_step
            new_lower = self.lower_price + grid_step
            # Stop-Preis pruefen
            if self.trailing_up_stop is not None and new_upper > self.trailing_up_stop:
                return
            self._shift_grid(new_lower, new_upper, current_price)
            self.trailing_count += 1

        # Trailing DOWN
        elif self.enable_trailing_down and current_price <= self.lower_price:
            new_lower = self.lower_price - grid_step
            new_upper = self.upper_price - grid_step
            # Stop-Preis pruefen
            if self.trailing_down_stop is not None and new_lower < self.trailing_down_stop:
                return
            self._shift_grid(new_lower, new_upper, current_price)
            self.trailing_count += 1

    def _shift_grid(self, new_lower: float, new_upper: float, current_price: float) -> None:
        """
        Verschiebt das Grid auf neue Grenzen.
        Erhält Grid-Breite und Anzahl Grids.
        """
        self.lower_price = max(new_lower, current_price * 0.01)
        self.upper_price = new_upper

        self.grid_lines = calculate_grid_lines(
            self.lower_price, self.upper_price,
            self.num_grids, self.grid_mode
        )

        # Grid-States neu aufbauen (inkl. asymm. + variable orders)
        self._build_grids(current_price)
        self.last_traded_price = None

    def _update_dd_throttle(self, portfolio_value: float) -> None:
        """
        Aktualisiert den Drawdown-Drosselfaktor basierend auf aktuellem Verlust.
        
        Schwelle 1 (default -10%): Ordergrösse auf 50%
        Schwelle 2 (default -20%): Ordergrösse auf 25%
        Kein Drawdown:             Ordergrösse 100%
        """
        loss_pct = (self.total_investment - portfolio_value) / self.total_investment
        if loss_pct >= self.dd_threshold_2:
            self.dd_throttle_factor = 0.25
        elif loss_pct >= self.dd_threshold_1:
            self.dd_throttle_factor = 0.50
        else:
            self.dd_throttle_factor = 1.0

    def get_state(self) -> dict:
        """Serialisiert den aktuellen Bot-State für Persistenz."""
        return {
            "position":            self.position,
            "coin_inventory":      [(a, p, str(ts)) for a, p, ts in self.coin_inventory],
            "trade_log":           self.trade_log,
            "daily_values":        self.daily_values,
            "last_price":          self.last_price,
            "last_traded_price":   self.last_traded_price,
            "recentering_count":   self.recentering_count,
            "stop_loss_triggered": self.stop_loss_triggered,
            "dd_throttle_factor":  self.dd_throttle_factor,
            "enable_trailing_up":  self.enable_trailing_up,
            "enable_trailing_down": self.enable_trailing_down,
            "trailing_up_stop":    self.trailing_up_stop,
            "trailing_down_stop":  self.trailing_down_stop,
            "trailing_count":      self.trailing_count,
            "enable_variable_orders": self.enable_variable_orders,
            "weight_bottom":          self.weight_bottom,
            "weight_top":             self.weight_top,
            "grids": {
                str(price): {
                    "price":        g.price,
                    "side":         g.side,
                    "trade_amount": g.trade_amount,
                    "trade_count":  g.trade_count,
                }
                for price, g in self.grids.items()
            },
        }

    def load_state(self, state: dict) -> None:
        """Lädt einen gespeicherten Bot-State."""
        if not state:
            return
        try:
            self.position          = state.get("position", self.position)
            self.daily_values      = state.get("daily_values", {})
            self.last_price        = state.get("last_price", self.last_price)
            self.last_traded_price = state.get("last_traded_price")
            self.recentering_count = state.get("recentering_count", 0)
            self.stop_loss_triggered = state.get("stop_loss_triggered", False)
            self.dd_throttle_factor   = state.get("dd_throttle_factor", 1.0)
            self.enable_trailing_up   = state.get("enable_trailing_up", False)
            self.enable_trailing_down = state.get("enable_trailing_down", False)
            self.trailing_up_stop     = state.get("trailing_up_stop", None)
            self.trailing_down_stop   = state.get("trailing_down_stop", None)
            self.trailing_count       = state.get("trailing_count", 0)
            self.enable_variable_orders = state.get("enable_variable_orders", False)
            self.weight_bottom           = state.get("weight_bottom", 2.0)
            self.weight_top              = state.get("weight_top", 0.5)
            self.trade_log         = state.get("trade_log", [])

            # FIFO-Inventar wiederherstellen
            inv = state.get("coin_inventory", [])
            self.coin_inventory = [
                (float(a), float(p), pd.Timestamp(ts))
                for a, p, ts in inv
            ]

            # Grid-States wiederherstellen
            grids_data = state.get("grids", {})
            for price_str, g in grids_data.items():
                price = float(price_str)
                if price in self.grids:
                    self.grids[price].side        = g.get("side", "buy")
                    self.grids[price].trade_count = g.get("trade_count", 0)
        except Exception as e:
            print(f"GridBot.load_state Fehler: {e}")

    @property
    def stop_loss_hit(self) -> bool:
        """Alias für stop_loss_triggered."""
        return self.stop_loss_triggered

    def get_portfolio_value(self, current_price: float) -> float:
        """Gibt aktuellen Portfolio-Wert zurück."""
        return self.position["usdt"] + self.position["coin"] * current_price

    @property
    def initial_price(self) -> Optional[float]:
        """Erster Preis aus Trade-Log oder last_price."""
        if self.trade_log:
            return self.trade_log[0].get("price", self.last_price)
        return self.last_price

    def _validate_inputs(
        self,
        total_investment: float,
        lower_price:      float,
        upper_price:      float,
        num_grids:        int,
        fee_rate:         float,
    ) -> None:
        """Validiert Eingabeparameter."""
        if total_investment <= 0:
            raise ValueError("Investition muss groesser als 0 sein.")
        if lower_price >= upper_price:
            raise ValueError("Obere Grenze muss groesser als untere sein.")
        if num_grids < 2:
            raise ValueError("Mindestens 2 Grids erforderlich.")
        if not 0 <= fee_rate < 0.1:
            raise ValueError("Gebuehrenrate muss zwischen 0% und 10% liegen.")


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------

def simulate_grid_bot(
    df:                  pd.DataFrame,
    total_investment:    float,
    lower_price:         float,
    upper_price:         float,
    num_grids:           int   = DEFAULT_NUM_GRIDS,
    grid_mode:           str   = DEFAULT_GRID_MODE,
    fee_rate:            float = DEFAULT_FEE_RATE,
    reserve_pct:         float = DEFAULT_RESERVE_PCT,
    stop_loss_pct:       Optional[float] = None,
    enable_recentering:  bool  = False,
    recenter_threshold:  float = 0.05,
    enable_dd_throttle:  bool  = False,
    dd_threshold_1:      float = 0.10,
    dd_threshold_2:      float = 0.20,
    enable_variable_orders: bool  = False,
    weight_bottom:          float = 2.0,
    weight_top:             float = 0.5,
    enable_trailing_up:     bool  = False,
    enable_trailing_down:   bool  = False,
    trailing_up_stop:       Optional[float] = None,
    trailing_down_stop:     Optional[float] = None,
) -> dict:
    """
    Simuliert den Grid-Bot ueber einen historischen Datensatz (Backtesting).

    Args:
        df               : OHLCV-DataFrame
        total_investment : Startkapital in USDT
        lower_price      : Untere Grid-Grenze
        upper_price      : Obere Grid-Grenze
        num_grids        : Anzahl Grids
        grid_mode        : "arithmetic" oder "geometric"
        fee_rate         : Gebuehrenrate pro Trade
        reserve_pct      : Kapitalreserve
        stop_loss_pct    : Stop-Loss Schwelle (None = deaktiviert)
        enable_recentering: Automatisches Recentering aktivieren
        recenter_threshold: Recentering-Schwellenwert

    Returns:
        Dictionary mit Simulationsergebnissen:
            initial_investment : Startkapital
            final_value        : Endwert des Portfolios
            profit_usdt        : Gewinn in USDT
            profit_pct         : Gewinn in %
            fees_paid          : Gesamtgebuehren
            num_trades         : Anzahl Trades
            trade_log          : Liste aller Trades
            grid_lines         : Verwendete Grid-Linien
            final_position     : Endposition {usdt, coin}
            initial_price      : Startpreis
            final_price        : Endpreis
            price_change_pct   : Kursveraenderung in %
            daily_values       : Taegliche Portfolio-Werte
            recentering_count  : Anzahl Recentering-Ereignisse
            stop_loss_triggered: True wenn Stop-Loss ausgeloest
            bot_version        : Versionsnummer
            error              : None bei Erfolg
    """
    try:
        initial_price = float(df.iloc[0]["close"])

        bot = GridBot(
            total_investment   = total_investment,
            lower_price        = lower_price,
            upper_price        = upper_price,
            num_grids          = num_grids,
            grid_mode          = grid_mode,
            fee_rate           = fee_rate,
            initial_price      = initial_price,
            reserve_pct        = reserve_pct,
            stop_loss_pct      = stop_loss_pct,
            enable_recentering = enable_recentering,
            recenter_threshold = recenter_threshold,
            enable_dd_throttle  = enable_dd_throttle,
            dd_threshold_1      = dd_threshold_1,
            dd_threshold_2      = dd_threshold_2,
            enable_variable_orders = enable_variable_orders,
            weight_bottom          = weight_bottom,
            weight_top             = weight_top,
            enable_trailing_up     = enable_trailing_up,
            enable_trailing_down   = enable_trailing_down,
            trailing_up_stop       = trailing_up_stop,
            trailing_down_stop     = trailing_down_stop,
        )

        # Timestamp fuer Initial-Trade setzen
        if bot.trade_log:
            bot.trade_log[0]["timestamp"] = df.iloc[0]["timestamp"]

        # Kerzen verarbeiten (erste Kerze = Initialisierung)
        for _, candle in df.iloc[1:].iterrows():
            bot.process_candle(candle)

        final_price = float(df.iloc[-1]["close"])
        final_value = bot.position["usdt"] + bot.position["coin"] * final_price
        total_profit = final_value - total_investment
        total_fees   = sum(t["fee"] for t in bot.trade_log)

        # Tageszeitreihe auffuellen
        daily_series = pd.Series(bot.daily_values)
        daily_series.index = pd.to_datetime(daily_series.index)
        start    = df["timestamp"].dt.date.min()
        end      = df["timestamp"].dt.date.max()
        all_days = pd.date_range(start=start, end=end, freq="D")
        filled   = daily_series.reindex(all_days).ffill()
        filled_daily = {
            d.strftime("%Y-%m-%d"): float(v)
            for d, v in filled.items()
            if not pd.isna(v)
        }

        return {
            "initial_investment":  total_investment,
            "final_value":         final_value,
            "profit_usdt":         total_profit,
            "profit_pct":          (total_profit / total_investment) * 100,
            "fees_paid":           total_fees,
            "num_trades":          len(bot.trade_log),
            "trade_log":           bot.trade_log,
            "grid_lines":          bot.grid_lines,
            "final_position":      dict(bot.position),
            "initial_price":       initial_price,
            "final_price":         final_price,
            "price_change_pct":    ((final_price - initial_price) / initial_price) * 100,
            "daily_values":        filled_daily,
            "recentering_count":   bot.recentering_count,
            "trailing_count":      bot.trailing_count,
            "stop_loss_triggered": bot.stop_loss_triggered,
            "bot_version":         BOT_VERSION,
            "error":               None,
        }

    except Exception as e:
        return {
            "initial_investment":  total_investment,
            "final_value":         total_investment,
            "profit_usdt":         0.0,
            "profit_pct":          0.0,
            "fees_paid":           0.0,
            "num_trades":          0,
            "trade_log":           [],
            "grid_lines":          [],
            "final_position":      {"usdt": total_investment, "coin": 0.0},
            "initial_price":       0.0,
            "final_price":         0.0,
            "price_change_pct":    0.0,
            "daily_values":        {},
            "recentering_count":   0,
            "stop_loss_triggered": False,
            "bot_version":         BOT_VERSION,
            "error":               str(e),
        }