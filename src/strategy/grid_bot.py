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
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from config.settings import (
    DEFAULT_FEE_RATE,
    DEFAULT_GRID_MODE,
    DEFAULT_NUM_GRIDS,
    DEFAULT_RESERVE_PCT,
)
from src.strategy.grid_builder import calculate_grid_lines


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
        take_profit_pct : Take-Profit in % (z.B. 0.20 = 20% Gewinn, None = deaktiviert)
        enable_recentering_up:   True = Grid neu zentrieren wenn Preis nach oben ausbricht
        enable_recentering_down: True = Grid neu zentrieren wenn Preis nach unten ausbricht
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
        take_profit_pct:     Optional[float] = None,
        # TP/SL haben drei moegliche Trigger-Varianten (Backend ODER-verknuepft;
        # das UI erlaubt aber nur exklusiv genau einen Modus pro Bot):
        #   Price: stop_loss_pct/take_profit_pct (relativ zu Lower/Upper)
        #   %ROI : stop_loss_roi_pct/take_profit_roi_pct
        #   P/L  : stop_loss_pl_usdt/take_profit_pl_usdt (absoluter USDT)
        stop_loss_roi_pct:   Optional[float] = None,
        take_profit_roi_pct: Optional[float] = None,
        stop_loss_pl_usdt:   Optional[float] = None,
        take_profit_pl_usdt: Optional[float] = None,
        enable_recentering_up:   bool  = False,
        enable_recentering_down: bool  = False,
        recenter_threshold:  float = 0.05,
        # Drawdown-Drosselung
        enable_dd_throttle:  bool  = False,
        dd_threshold_1:      float = 0.10,   # -10% → 50% Ordergrösse
        dd_threshold_2:      float = 0.20,   # -20% → 25% Ordergrösse
        # Grid Trailing (nur Up-Variante, Binance-Standard)
        enable_trailing_up:     bool  = False,
        trailing_up_stop:       Optional[float] = None,
        # Wenn aktiv: preis-basierte TP/SL-Schwellen wandern bei jedem
        # Trailing-Up-Shift um genau einen Grid-Step nach oben mit.
        # ROI-basierte Schwellen sind preis-unabhaengig und bleiben.
        trail_stop_levels:      bool  = False,
        # Grid Trigger (optional): Bot wartet bis Marktpreis diesen Wert
        # beruehrt, bevor Initial-Setup ausgefuehrt wird.
        grid_trigger_price:     Optional[float] = None,
        # Initial-Buy aktivieren (Binance-Standard). False = Bot startet
        # rein mit USDT, ohne sofortige Marktkaeufe auf den Sell-Linien.
        enable_initial_buy:     bool  = True,
        # Wenn True: nach TP/SL-Force-Sell wird der Bot komplett gestoppt
        # (bot_status="stopped", keine weiteren Trades). Wenn False:
        # Force-Sell, danach laeuft der Bot weiter mit aktiven Buy-Limits.
        stop_bot_on_trigger:    bool  = False,
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
        self.stop_loss_pct       = stop_loss_pct
        self.take_profit_pct     = take_profit_pct
        # ROI-basierte und P/L-basierte TP/SL-Schwellen (ODER-Verknuepfung
        # mit der preis-basierten — siehe _check_stop_loss/_check_take_profit)
        self.stop_loss_roi_pct   = stop_loss_roi_pct
        self.take_profit_roi_pct = take_profit_roi_pct
        self.stop_loss_pl_usdt   = stop_loss_pl_usdt
        self.take_profit_pl_usdt = take_profit_pl_usdt
        # Preis-Schwellen einmalig beim Bot-Start berechnen (Industrie-Standard,
        # entspricht GoodCrypto/Binance-Spot-Grid-Bot-Verhalten):
        #   SL-Preis = lower_price * (1 - sl_pct)  -> unter der Lower-Grenze
        #   TP-Preis = upper_price * (1 + tp_pct)  -> ueber der Upper-Grenze
        # Bewusst FIX ab Bot-Start: wandert bei Trailing/Recentering NICHT mit.
        self.stop_loss_price = (
            lower_price * (1 - stop_loss_pct) if stop_loss_pct is not None else None
        )
        self.take_profit_price = (
            upper_price * (1 + take_profit_pct) if take_profit_pct is not None else None
        )
        self.enable_recentering_up   = enable_recentering_up
        self.enable_recentering_down = enable_recentering_down
        self.recenter_threshold = recenter_threshold
        self.enable_dd_throttle  = enable_dd_throttle
        # Schwellen sortieren: vertauschte User-Eingaben (t1 > t2) wuerden
        # sonst dazu fuehren, dass die strengere Schwelle nie greift.
        self.dd_threshold_1, self.dd_threshold_2 = sorted(
            [dd_threshold_1, dd_threshold_2]
        )
        self.dd_throttle_factor  = 1.0  # aktueller Drosselfaktor
        # Peak-Portfolio fuer Peak-to-Trough-Drosselung (steigt monoton).
        # Start = total_investment; ein frisch geladener Bot ohne
        # historischen Peak muss diesen Wert verwenden, sonst waere der
        # erste portfolio_value < total_investment faelschlich der "Peak".
        self._peak_portfolio    = total_investment
        # DD-Verlaufs-Tracking pro Kerze (fuer Drawdown-Tab).
        # Jeder Eintrag: {"timestamp": str, "dd_pct": float, "factor": float}.
        # Wird IMMER gefuellt (auch bei enable_dd_throttle=False), damit der
        # Tab den DD-Verlauf zeigen kann; factor bleibt dann konstant 1.0.
        self.dd_history: List[dict] = []
        self.enable_trailing_up      = enable_trailing_up
        self.trailing_up_stop        = trailing_up_stop
        self.trail_stop_levels       = trail_stop_levels
        self.trailing_count          = 0
        self._candle_lowest_buy: Optional[float] = None

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
        self.take_profit_triggered: bool = False
        # Trigger-Zeitpunkt + Preis (gesetzt beim Auslosen, fuer Chart-Marker).
        # Datentyp: pd.Timestamp | None; Preis = current_price der Ausloese-Kerze.
        self.stop_loss_trigger_timestamp = None
        self.stop_loss_trigger_price: Optional[float] = None
        self.take_profit_trigger_timestamp = None
        self.take_profit_trigger_price: Optional[float] = None
        # Event-Log fuer dynamische Marker im Chart. Pro Trailing-Trigger
        # ein Dict mit timestamp, new_lower, new_upper, direction.
        self.trailing_events: List[dict] = []
        # Analog fuer Recentering. Pro Recentering-Trigger ein Dict mit
        # timestamp, new_lower, new_upper, trigger_price, direction.
        self.recentering_events: List[dict] = []
        # Wird in process_candle gesetzt - damit _check_trailing den
        # aktuellen Kerzen-Zeitstempel ins Event schreiben kann.
        self._current_timestamp = None

        # Preise
        self.last_price        = initial_price
        self.last_traded_price = None

        # ── Bot-Status + Grid Trigger ───────────────────────────────────────
        # bot_status: innerer Zustand der Grid-Mechanik
        #   "waiting_for_trigger" - wartet auf Trigger-Beruehrung
        #   "active"              - normaler Betrieb
        #   "paused"              - Preis ausserhalb Range (rein UI-Hinweis,
        #                            kein Verhaltens-Effekt)
        #   "stopped"             - TP/SL geriggert oder explizit gestoppt
        # Getrennt vom bot_store.status (Lebenszyklus-Eigenschaft).
        self.grid_trigger_price: Optional[float] = grid_trigger_price
        # Initial-Buy aktivieren (Default = Binance-Standard).
        self.enable_initial_buy: bool = enable_initial_buy
        self.stop_bot_on_trigger: bool = stop_bot_on_trigger
        # Richtung des Triggers ("up" = warte auf Anstieg, "down" = auf
        # Rueckgang). Wird bei der ersten Kerze anhand des Close-Preises
        # bestimmt — in __init__ ist der Initial-Preis evtl. None.
        self._trigger_direction: Optional[str] = None
        if grid_trigger_price is not None:
            self.bot_status: str = "waiting_for_trigger"
        else:
            self.bot_status = "active"

        # Aggregat-Tracking fuer Initial-Buys (Binance-Standard):
        # Anzahl Coins, gezahlte Fee, USDT-Wert.
        self.initial_buy_coin_amount: float = 0.0
        self.initial_buy_fee:         float = 0.0
        self.initial_buy_value_usdt:  float = 0.0
        # Pufferzone-Linie (= kleinste Linie ueber initial_price beim Bot-Start).
        # Bleibt blocked, bis der erste reale Trade laeuft — danach wird sie
        # zu einer normalen Grid-Linie. Wird in _perform_initial_setup gesetzt,
        # in _execute_trade nach dem ersten Trade auf None gesetzt.
        self._buffer_zone_price: Optional[float] = None

        # Initialisierung. Im "waiting_for_trigger"-Modus wird das Grid
        # erst beim Trigger aufgebaut (siehe _perform_initial_setup).
        # Fallback-Timestamp fuer Initial-Buys, falls __init__ ausserhalb
        # eines Candle-Kontexts laeuft (PT/LT bei Bot-Erstellung). Wird im
        # BT-Pfad von simulate_grid_bot anschliessend auf first_ts gepatcht.
        if self._current_timestamp is None:
            # Bugfix TZ: pd.Timestamp.now() liefert naive lokale Zeit (Zurich)
            # -> spaetere Anzeige via utc_to_zurich verschiebt um +2h. Konvention:
            # alle internen State-Timestamps = naive UTC.
            from src.utils.timezone import naive_utc_now
            self._current_timestamp = pd.Timestamp(naive_utc_now())
        if self.bot_status == "active":
            self._perform_initial_setup(initial_price, total_investment)

    # -----------------------------------------------------------------------
    # Initialisierung
    # -----------------------------------------------------------------------

    def _build_grids(self, current_price: float) -> None:
        """
        Zentrale Methode zum Aufbau der Grid-States.
        Jede Grid-Linie erhaelt die gleiche base_amount_usdt-Allokation.
        Wird von _initialize_grids, _shift_grid und _recenter_grid verwendet.
        """
        self.grids = {}
        for price in self.grid_lines:
            coin_amount = self.base_amount_usdt / (price * (1 + self.fee_rate))
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

    def _perform_initial_setup(
        self,
        initial_price:    float,
        total_investment: float,
    ) -> None:
        """
        Fuehrt das Initial-Setup nach Binance-Industrie-Standard durch:

        1. Grid-Linien berechnen (inkl. ATR-Anpassung falls aktiv)
        2. Effektive Order-Groesse pro Grid bestimmen
        3. Grid-States aufbauen (Sides klassifizieren + Variable-Order-Gewichte)
        4. Pufferzone bestimmen: kleinste Linie ueber initial_price -> KEINE Order
        5. Initial-Buys ausfuehren auf allen Sell-Linien ausser Pufferzone
           (= Binance "buy orders above market get filled at market price")
        6. Buys unterhalb des Preises bleiben offene Limit-Orders
        7. bot_status auf "active" setzen

        Wird beim Bot-Start (ohne Trigger) bzw. beim Trigger-Touch aufgerufen.
        """
        # Effektives Kapital gleichmaessig auf alle Grids verteilen
        effective_investment  = total_investment * (1 - self.reserve_pct)
        self.base_amount_usdt = effective_investment / self.num_grids

        # Grid-States aufbauen
        self._build_grids(initial_price)

        # ── Pufferzone bestimmen ────────────────────────────────────────────
        # Pufferzone ist ein Binance-Initial-Buy-spezifisches Konzept: sie
        # verhindert, dass der Bot direkt ueber dem Startpreis Inventar zum
        # Marktpreis aufbaut, das beim ersten Mini-Anstieg gleich wieder
        # mit minimalem Profit verkauft wird. Ohne Initial-Buy gibt es kein
        # Inventar zu schuetzen -> keine Pufferzone.
        if self.enable_initial_buy:
            lines_above = sorted(p for p in self.grids.keys()
                                  if p > initial_price)
            buffer_price: Optional[float] = (lines_above[0]
                                              if lines_above else None)
        else:
            buffer_price = None
        # Persistent merken, damit _update_grid_sides sie nicht ueberschreibt.
        self._buffer_zone_price = buffer_price

        # ── Sides finalisieren + (optional) Initial-Buys ausfuehren ─────────
        for price, g in self.grids.items():
            if buffer_price is not None and np.isclose(price, buffer_price):
                g.side = "blocked"
                continue
            if np.isclose(price, initial_price):
                g.side = "blocked"
                continue
            if price < initial_price:
                g.side = "buy"
                continue

            # price > initial_price (und nicht Pufferzone): Sell-Linie.
            if not self.enable_initial_buy:
                # Kein Initial-Buy: Sell-Linie ohne Inventar. trade_amount
                # bleibt auf dem in _build_grids berechneten Wert (=
                # base_amount/(price*(1+fee))) — wird relevant wenn die
                # Linie spaeter durch Preis-Fall zur Buy-Linie wird
                # (via _update_grid_sides). Sell-Match-Algo nutzt sowieso
                # die Menge aus coin_inventory, nicht grid.trade_amount.
                g.side = "sell"
                continue

            # Binance-Standard: Initial-Buy zum Marktpreis ausfuehren
            amount       = g.trade_amount  # bereits variable-order-gewichtet
            cost_usdt    = amount * initial_price
            fee          = cost_usdt * self.fee_rate
            required     = cost_usdt + fee
            if self.position["usdt"] < required:
                # Nicht genug USDT — Order kann nicht initialisiert werden,
                # bleibt aber als "sell" registriert (faellt einfach im
                # Folge-Match aus, da kein Inventar dafuer existiert).
                g.side = "sell"
                continue

            self.position["usdt"] -= required
            self.position["coin"] += amount
            self.coin_inventory.append(
                (amount, initial_price, self._current_timestamp)
            )
            # Initial-Buy im trade_log loggen.
            #   price  = grid.price       (nominelle Sell-Linie, fuer Chart-
            #                              Marker und tab_grid_levels-Match)
            #   cprice = initial_price    (tatsaechlicher Marktpreis = der
            #                              echte Buy-Preis fuers Inventar)
            # Inventar (coin_inventory) bleibt mit buy_price=initial_price —
            # so ist die Profit-Berechnung beim spaeteren Sell auf diese
            # Linie weiterhin korrekt: (sell_price - initial_price).
            self.trade_log.append({
                "timestamp":    self._current_timestamp,
                "type":         "BUY",
                "cprice":       float(initial_price),
                "price":        float(price),
                "amount":       float(amount),
                "fee":          float(fee),
                "profit":       0.0,
                "profit_gross": 0.0,
                "initial":      True,
            })
            # Aggregat-Tracking
            self.initial_buy_coin_amount += amount
            self.initial_buy_fee         += fee
            self.initial_buy_value_usdt  += cost_usdt

            # Order steht jetzt als Sell-Limit auf grid.price
            g.side = "sell"

        # Bot ist jetzt aktiv
        self.bot_status = "active"

    # -----------------------------------------------------------------------
    # Grid-Zustände aktualisieren
    # -----------------------------------------------------------------------

    def _update_grid_sides(
        self,
        current_price:  float,
        blocked_price:  Optional[float] = None,
    ) -> None:
        """Aktualisiert Buy/Sell-Zustände aller Grids basierend auf aktuellem Preis.

        Pufferzone (self._buffer_zone_price) bleibt "blocked", bis sie
        durch den ersten Trade aufgehoben wird (siehe _execute_trade).
        """
        for price in self.grid_lines:
            if np.isclose(price, current_price):
                continue
            if price == blocked_price:
                self.grids[price].side = "blocked"
                continue
            # Pufferzone (Initial-Setup-Konzept) bleibt blocked
            if (self._buffer_zone_price is not None
                    and np.isclose(price, self._buffer_zone_price)):
                self.grids[price].side = "blocked"
                continue
            if price > current_price:
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
        # BUGFIX: vorher hat ein einmaliger SL/TP-Trigger den Bot in
        # jeder folgenden Kerze gestoppt — unabhaengig von
        # stop_bot_on_trigger. Jetzt nur stoppen wenn der Status
        # explizit auf "stopped" gesetzt wurde.
        if self.bot_status == "stopped":
            return

        try:
            current_price = float(candle["close"])
            timestamp     = candle["timestamp"]
            date_str      = pd.to_datetime(timestamp).strftime("%Y-%m-%d")
            # Fuer _check_trailing / Initial-Buys zugaenglich machen
            self._current_timestamp = timestamp

            # ── Grid Trigger: wartet auf Preis-Beruehrung ───────────────────
            if self.bot_status == "waiting_for_trigger":
                trigger = self.grid_trigger_price
                # Richtung beim ersten gesehenen Preis bestimmen:
                #   close < trigger -> "up"   (warte auf Anstieg)
                #   close > trigger -> "down" (warte auf Rueckgang)
                #   close == trigger -> sofort triggern
                if self._trigger_direction is None:
                    if current_price < trigger:
                        self._trigger_direction = "up"
                    elif current_price > trigger:
                        self._trigger_direction = "down"
                    else:
                        self._trigger_direction = "hit"  # sofort
                # Trigger-Pruefung (Kerzen-Range-basiert)
                try:
                    high = float(candle["high"])
                    low  = float(candle["low"])
                except Exception:
                    high = low = current_price
                triggered = False
                if self._trigger_direction == "up":
                    triggered = high >= trigger
                elif self._trigger_direction == "down":
                    triggered = low <= trigger
                else:  # "hit"
                    triggered = True
                if not triggered:
                    return
                # Trigger erreicht: Initial-Setup zum Trigger-Preis
                self._perform_initial_setup(trigger, self.total_investment)
                self.last_price = trigger
                # Anschliessend normaler Trade-Flow auf dieser Kerze

            # Portfolio-Wert tracken
            portfolio_value = (
                self.position["usdt"] + self.position["coin"] * current_price
            )
            self.daily_values[date_str] = portfolio_value

            # Peak monoton hochziehen (Basis fuer Peak-to-Trough-Drosselung)
            if portfolio_value > self._peak_portfolio:
                self._peak_portfolio = portfolio_value

            # Drosselung aktualisieren
            if self.enable_dd_throttle:
                self._update_dd_throttle(portfolio_value)

            # DD-Verlauf tracken (immer, auch ohne aktivierte Drosselung).
            # dd_pct = peak-relativer Drawdown in [0, 1].
            # pv = portfolio_value, damit calculate_drawdown den
            # max_drawdown_usdt aus dd_history rekonstruieren kann
            # (peak = pv / (1 - dd_pct)).
            if self._peak_portfolio > 0:
                _dd_pct = max(0.0,
                              (self._peak_portfolio - portfolio_value)
                                / self._peak_portfolio)
            else:
                _dd_pct = 0.0
            self.dd_history.append({
                "timestamp": str(self._current_timestamp),
                "dd_pct":    float(_dd_pct),
                "factor":    float(self.dd_throttle_factor),
                "pv":        float(portfolio_value),
            })

            # Stop-Loss pruefen (Preis- und/oder ROI-basiert, ODER-verknuepft)
            if self._check_stop_loss(current_price, portfolio_value):
                self.stop_loss_triggered = True
                self.stop_loss_trigger_timestamp = self._current_timestamp
                self.stop_loss_trigger_price    = float(current_price)
                # Force-Sell aller Positionen zum aktuellen Marktpreis
                self._force_sell_all_inventory(current_price, timestamp,
                                                trigger="stop_loss")
                if self.stop_bot_on_trigger:
                    self.bot_status = "stopped"
                    return
                # Sonst: Bot laeuft weiter (Buy-Limits aktiv, neue Trades
                # moeglich). Nichts mehr in dieser Kerze tun (keine
                # weitere Trade-Loop, Trailing/Recentering ueberspringen).
                return

            # Take-Profit pruefen (Preis- und/oder ROI-basiert, ODER-verknuepft)
            if self._check_take_profit(current_price, portfolio_value):
                self.take_profit_triggered = True
                self.take_profit_trigger_timestamp = self._current_timestamp
                self.take_profit_trigger_price    = float(current_price)
                self._force_sell_all_inventory(current_price, timestamp,
                                                trigger="take_profit")
                if self.stop_bot_on_trigger:
                    self.bot_status = "stopped"
                    return
                return

            # Reset des Intra-Candle BUY-Trackers
            self._candle_lowest_buy = None

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
            if self.enable_recentering_up or self.enable_recentering_down:
                self._check_recentering(current_price)

            # Grid Trailing pruefen (nur Up-Variante, Binance-Standard)
            if self.enable_trailing_up:
                self._check_trailing(current_price)

            # ── Range-Status (rein UI-Hinweis, kein Verhaltens-Effekt) ──────
            # "paused" wenn Preis ausserhalb der aktuellen Range, "active"
            # sobald wieder drin. TP/SL-Stops setzen ihren eigenen Status.
            if current_price > self.upper_price or current_price < self.lower_price:
                if self.bot_status == "active":
                    self.bot_status = "paused"
            else:
                if self.bot_status == "paused":
                    self.bot_status = "active"

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
        fee          = 0.0
        profit       = 0.0   # netto (nach Sell-Fee-Abzug)
        profit_gross = 0.0   # brutto (reine Preisdifferenz × Menge)
        timestamp    = candle["timestamp"]

        try:
            if grid.side == "sell":
                # Grid-spezifisches Matching:
                # SELL bei Grid X verkauft die Position die bei Grid X-1 (darunter) gekauft wurde.
                # Grund: Jedes Grid-Paar (Buy@X-1, Sell@X) bildet einen abgeschlossenen Trade.
                if not self.coin_inventory:
                    return  # Kein Inventar vorhanden

                # Naechst-tieferes Grid-Level finden (= korrekter Buy-Level)
                grid_lines_sorted = sorted(self.grids.keys())
                sell_idx = None
                for idx, gl in enumerate(grid_lines_sorted):
                    if abs(gl - grid.price) < 1e-8:
                        sell_idx = idx
                        break

                # Buy-Level = Grid direkt darunter
                if sell_idx is not None and sell_idx > 0:
                    expected_buy_price = grid_lines_sorted[sell_idx - 1]
                else:
                    expected_buy_price = None

                # Position suchen die am korrekten Buy-Level gekauft wurde
                matched_idx = None
                if expected_buy_price is not None:
                    for inv_idx, (amt, bp, ts) in enumerate(self.coin_inventory):
                        if abs(bp - expected_buy_price) < 1e-8:
                            matched_idx = inv_idx
                            break

                # Fallback: FIFO nur wenn älteste Position UNTER dem Verkaufspreis liegt
                if matched_idx is None:
                    if (self.coin_inventory and
                            self.coin_inventory[0][1] < grid.price - 1e-8):
                        matched_idx = 0
                    else:
                        return  # Kein sinnvoller Match → kein Sell (verhindert Verlust)

                actual_amt, buy_price, buy_time = self.coin_inventory[matched_idx]
                actual_sell_amt = actual_amt
                matched_buy_price = float(buy_price)

                # Genuegend Coins vorhanden?
                if self.position["coin"] < actual_sell_amt - 1e-10:
                    return

                profit_gross = (grid.price - buy_price) * actual_sell_amt
                fee          = actual_sell_amt * grid.price * self.fee_rate
                profit       = profit_gross - fee

                self.coin_inventory.pop(matched_idx)
                self.position["coin"] -= actual_sell_amt
                self.position["usdt"] += (actual_sell_amt * grid.price) - fee

                # Tatsaechlich gehandelte Menge fuer den Log. grid.trade_amount
                # bleibt UNVERAENDERT - sonst wuerde beim naechsten Trade auf
                # derselben Linie der gedrosselte/Sell-Wert als neue Basis
                # genutzt (kumulative Drosselung).
                traded_amount = actual_sell_amt

            else:  # buy
                matched_buy_price = None
                # Drawdown-Drosselung: Ordergrösse reduzieren.
                # grid.trade_amount = Original-Menge aus _build_grids;
                # niemals ueberschreiben.
                throttled_amount = grid.trade_amount * self.dd_throttle_factor
                # Defensive Guard: trade_amount=0 erzeugt Empty-Inventar-
                # Eintraege und verhindert spaetere Sells. Kann passieren
                # bei extremer DD-Drosselung oder fehlerhaften Configs.
                if throttled_amount <= 0:
                    return
                required_usdt = throttled_amount * grid.price * (1 + self.fee_rate)
                if self.position["usdt"] < required_usdt:
                    return  # Nicht genuegend USDT

                fee = throttled_amount * grid.price * self.fee_rate
                self.position["usdt"] -= required_usdt
                self.position["coin"] += throttled_amount
                self.coin_inventory.append(
                    (throttled_amount, grid.price, timestamp)
                )
                traded_amount = throttled_amount

            # Trade loggen
            entry = {
                "timestamp":    timestamp,
                "type":         grid.side.upper(),
                "cprice":       float(candle["close"]),
                "price":        float(grid.price),
                "amount":       float(traded_amount),
                "fee":          float(fee),
                "profit":       float(profit),        # netto (nach Sell-Fee)
                "profit_gross": float(profit_gross),  # brutto (Preisdifferenz × Menge)
            }
            # SELL: zugeordneter Buy-Preis fuer UI-Anzeige (Buy-Bezug-Spalte).
            if matched_buy_price is not None:
                entry["matched_buy_price"] = matched_buy_price
            self.trade_log.append(entry)

            # Pufferzone (Initial-Setup-Konzept) wird durch den ersten realen
            # Trade aufgehoben — danach ist die Linie ein normales Grid-Level.
            if self._buffer_zone_price is not None:
                self._buffer_zone_price = None

            # last_traded_price:
            # SELL → immer auf dieses Grid setzen
            # BUY  → tiefsten Grid dieser Kerze merken (per _candle_lowest_buy)
            #        damit alle BUY-Grids einer Kerze geblockt bleiben
            if grid.side == "sell":
                self.last_traded_price  = grid.price
                self._candle_lowest_buy = None  # nach Sell zurücksetzen
            else:
                if (self._candle_lowest_buy is None or
                        grid.price < self._candle_lowest_buy):
                    self._candle_lowest_buy = grid.price
                self.last_traded_price = self._candle_lowest_buy
            grid.trade_count += 1

        except Exception as e:
            raise RuntimeError(f"Trade-Fehler bei {grid.price}: {e}")

    # -----------------------------------------------------------------------
    # Force-Sell bei TP/SL-Trigger
    # -----------------------------------------------------------------------

    def _force_sell_all_inventory(self, current_price: float, timestamp,
                                   trigger: Optional[str] = None) -> None:
        """
        Verkauft das gesamte Coin-Inventar zum aktuellen Marktpreis in
        EINER konsolidierten Order. Wird bei TP/SL-Trigger aufgerufen —
        semantisch korrekt fuer klassisches "Stop-Loss"/"Take-Profit"
        im Spot-Trading.

        Konsolidierung: ein einziger SELL-Trade pro Trigger mit Summen
        ueber alle Inventory-Eintraege (Menge, Wert, Profit, Fee).
        Vermeidet N kleinteilige Trades mit jeweils eigener
        Gebuehren-Berechnung.

        - position["coin"] und coin_inventory werden geleert.
        - Trade-Eintrag bekommt "force_sell": True; bei gesetztem
          trigger zusaetzlich "force_sell_trigger" ("stop_loss" /
          "take_profit").
        """
        if not self.coin_inventory:
            return
        # Aggregat ueber alle Inventory-Eintraege
        total_amount = sum(amt for amt, _, _ in self.coin_inventory)
        total_buy_value = sum(amt * bp for amt, bp, _ in self.coin_inventory)
        # Safety: bei Inkonsistenz zwischen Inventar und position["coin"]
        # das Minimum nehmen.
        if self.position["coin"] < total_amount - 1e-10:
            total_amount = max(0.0, self.position["coin"])
        if total_amount <= 0:
            self.coin_inventory.clear()
            self.position["coin"] = 0.0
            return

        sell_value   = total_amount * current_price
        fee          = sell_value * self.fee_rate
        profit_gross = sell_value - total_buy_value
        profit       = profit_gross - fee

        self.position["coin"]  = 0.0
        self.position["usdt"] += sell_value - fee
        self.coin_inventory.clear()

        # Buy-Bezug: gewichteter Durchschnitt aller verkauften Inventar-Pakete.
        avg_buy_price = (total_buy_value / total_amount) if total_amount > 0 else None
        entry = {
            "timestamp":    timestamp,
            "type":         "SELL",
            "cprice":       float(current_price),
            "price":        float(current_price),
            "amount":       float(total_amount),
            "fee":          float(fee),
            "profit":       float(profit),
            "profit_gross": float(profit_gross),
            "force_sell":   True,
        }
        if avg_buy_price is not None:
            entry["matched_buy_price"] = float(avg_buy_price)
        if trigger:
            entry["force_sell_trigger"] = trigger
        self.trade_log.append(entry)

    # -----------------------------------------------------------------------
    # Stop-Loss
    # -----------------------------------------------------------------------

    def _check_stop_loss(self, current_price: float,
                          portfolio_value: float) -> bool:
        """
        Prueft ob der Stop-Loss ausgeloest wurde.

        ODER-Verknuepfung dreier Trigger-Varianten:

        1) Preis-basiert: current_price <= stop_loss_price
        2) ROI-basiert  : (pv - total) / total <= -stop_loss_roi_pct
        3) P/L-basiert  : (pv - total)         <= -stop_loss_pl_usdt

        UI exponiert die drei Modi exklusiv (pro Bot nur einer aktiv); im
        Backend bleibt die ODER-Logik trotzdem allgemein und schadet
        nichts, da inaktive Felder None sind.

        Args:
            current_price   : Aktueller Marktpreis
            portfolio_value : Aktueller Portfolio-Wert (usdt + coin*price)

        Returns:
            True wenn einer der aktiven Trigger ausgeloest hat.
        """
        # Einmalige Trigger-Semantik: nach erstem Trigger wird SL nicht
        # mehr feuern. Verhindert Force-Sell-Loop wenn der Bot mit
        # stop_bot_on_trigger=False weiterlaeuft und Buy-Limits den
        # Preis erneut unter die SL-Schwelle bringen.
        if self.stop_loss_triggered:
            return False
        # Preis-basiert
        if (self.stop_loss_price is not None
                and current_price <= self.stop_loss_price):
            return True
        # ROI-basiert
        if self.stop_loss_roi_pct is not None and self.total_investment > 0:
            roi = (portfolio_value - self.total_investment) / self.total_investment
            if roi <= -self.stop_loss_roi_pct:
                return True
        # P/L-basiert (absoluter USDT-Verlust)
        if self.stop_loss_pl_usdt is not None:
            pl = portfolio_value - self.total_investment
            if pl <= -self.stop_loss_pl_usdt:
                return True
        return False

    # -----------------------------------------------------------------------
    # Take-Profit
    # -----------------------------------------------------------------------

    def _check_take_profit(self, current_price: float,
                            portfolio_value: float) -> bool:
        """
        Prueft ob der Take-Profit ausgeloest wurde.

        ODER-Verknuepfung dreier Trigger-Varianten (analog Stop-Loss):

        1) Preis-basiert: current_price >= take_profit_price
        2) ROI-basiert  : (pv - total) / total >= take_profit_roi_pct
        3) P/L-basiert  : (pv - total)         >= take_profit_pl_usdt

        Args:
            current_price   : Aktueller Marktpreis
            portfolio_value : Aktueller Portfolio-Wert (usdt + coin*price)

        Returns:
            True wenn einer der aktiven Trigger ausgeloest hat.
        """
        # Einmalige Trigger-Semantik (analog _check_stop_loss).
        if self.take_profit_triggered:
            return False
        # Preis-basiert
        if (self.take_profit_price is not None
                and current_price >= self.take_profit_price):
            return True
        # ROI-basiert
        if self.take_profit_roi_pct is not None and self.total_investment > 0:
            roi = (portfolio_value - self.total_investment) / self.total_investment
            if roi >= self.take_profit_roi_pct:
                return True
        # P/L-basiert (absoluter USDT-Gewinn)
        if self.take_profit_pl_usdt is not None:
            pl = portfolio_value - self.total_investment
            if pl >= self.take_profit_pl_usdt:
                return True
        return False

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

        if (near_upper and self.enable_recentering_up) or \
           (near_lower and self.enable_recentering_down):
            self._recenter_grid(current_price)

    def _recenter_grid(self, current_price: float) -> None:
        """
        Zentriert das Grid um den aktuellen Preis neu.

        Berechnet neue lower/upper Grenzen basierend auf der
        urspruenglichen Grid-Breite, zentriert auf current_price.

        Args:
            current_price: Neues Grid-Zentrum
        """
        # Alte Grenzen merken — fuer Richtungs-Bestimmung beim Event-Log
        old_upper = self.upper_price
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

        # Event-Log fuer Chart-Visualisierung (analog Trailing-Events).
        # Pro Recentering-Trigger ein Dict mit timestamp + neue Grenzen
        # + trigger_price + direction.
        if self._current_timestamp is not None:
            self.recentering_events.append({
                "timestamp":     self._current_timestamp,
                "new_lower":     float(self.lower_price),
                "new_upper":     float(self.upper_price),
                "trigger_price": float(current_price),
                "direction":     "up" if current_price >= old_upper else "down",
            })

    # -----------------------------------------------------------------------
    # Validierung
    # -----------------------------------------------------------------------

    def _check_trailing(self, current_price: float) -> None:
        """
        Prueft ob das Grid nach oben verschoben werden soll (Binance-Standard).

        Trigger: current_price >= upper_price + grid_step
                 (Preis muss die obere Grenze um einen vollen Step VERLASSEN
                 haben, nicht nur beruehren).
        Aktion : Grid um einen grid_step nach oben (Lower und Upper synchron).
        Limit  : trailing_up_stop deckelt die maximale Upper-Grenze.

        Optional (trail_stop_levels=True): preis-basierte TP/SL-Schwellen
        wandern um denselben grid_step mit nach oben.

        Down-Trailing existiert nicht — Spot-Grid-Bots wandern nur aufwaerts
        (Industrie-Standard).
        """
        if not self.enable_trailing_up:
            return
        grid_step = (self.upper_price - self.lower_price) / self.num_grids
        if current_price < self.upper_price + grid_step:
            return
        new_upper = self.upper_price + grid_step
        new_lower = self.lower_price + grid_step
        # Stop-Preis deckelt
        if self.trailing_up_stop is not None and new_upper > self.trailing_up_stop:
            return
        self._shift_grid(new_lower, new_upper, current_price)
        self.trailing_count += 1

        # Optional: preis-basierte TP/SL-Schwellen mitwandern
        if self.trail_stop_levels:
            if self.stop_loss_price is not None:
                self.stop_loss_price += grid_step
            if self.take_profit_price is not None:
                self.take_profit_price += grid_step

        if self._current_timestamp is not None:
            self.trailing_events.append({
                "timestamp": self._current_timestamp,
                "new_lower": float(self.lower_price),
                "new_upper": float(self.upper_price),
                "direction": "up",
            })

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
        Aktualisiert den Drosselfaktor basierend auf dem Drawdown vom Peak.

        dd_pct = (peak − portfolio_value) / peak

        Schwelle 1 (default -10%): Ordergrösse auf 50%
        Schwelle 2 (default -20%): Ordergrösse auf 25%
        Kein Drawdown:             Ordergrösse 100%
        """
        # Guard gegen Null/negative Werte (theoretisch unkritisch durch UI,
        # aber defensive Programmierung)
        if self._peak_portfolio <= 0 or self.total_investment <= 0:
            return
        dd_pct = (self._peak_portfolio - portfolio_value) / self._peak_portfolio
        if dd_pct >= self.dd_threshold_2:
            self.dd_throttle_factor = 0.25
        elif dd_pct >= self.dd_threshold_1:
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
            "take_profit_triggered": self.take_profit_triggered,
            "stop_loss_trigger_timestamp":   (str(self.stop_loss_trigger_timestamp)
                                              if self.stop_loss_trigger_timestamp else None),
            "stop_loss_trigger_price":       self.stop_loss_trigger_price,
            "take_profit_trigger_timestamp": (str(self.take_profit_trigger_timestamp)
                                              if self.take_profit_trigger_timestamp else None),
            "take_profit_trigger_price":     self.take_profit_trigger_price,
            "stop_loss_price":     self.stop_loss_price,
            "take_profit_price":   self.take_profit_price,
            "stop_loss_roi_pct":   self.stop_loss_roi_pct,
            "take_profit_roi_pct": self.take_profit_roi_pct,
            "stop_loss_pl_usdt":   self.stop_loss_pl_usdt,
            "take_profit_pl_usdt": self.take_profit_pl_usdt,
            "dd_throttle_factor":  self.dd_throttle_factor,
            "_peak_portfolio":     self._peak_portfolio,
            "dd_history":          self.dd_history,
            "enable_trailing_up":  self.enable_trailing_up,
            "trailing_up_stop":    self.trailing_up_stop,
            "trail_stop_levels":   self.trail_stop_levels,
            "trailing_count":      self.trailing_count,
            "trailing_events":     self.trailing_events,
            "recentering_events":  self.recentering_events,
            # Bot-Status + Grid Trigger
            "bot_status":             self.bot_status,
            "grid_trigger_price":     self.grid_trigger_price,
            "_trigger_direction":     self._trigger_direction,
            "enable_initial_buy":     self.enable_initial_buy,
            "stop_bot_on_trigger":    self.stop_bot_on_trigger,
            # Initial-Buy-Aggregate (Binance-Standard)
            "initial_buy_coin_amount": self.initial_buy_coin_amount,
            "initial_buy_fee":         self.initial_buy_fee,
            "initial_buy_value_usdt":  self.initial_buy_value_usdt,
            "_buffer_zone_price":      self._buffer_zone_price,
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
            self.take_profit_triggered = state.get("take_profit_triggered", False)
            # Trigger-Daten (M.2). Backward-Compat: alte States ohne Felder -> None.
            _sl_ts = state.get("stop_loss_trigger_timestamp")
            _tp_ts = state.get("take_profit_trigger_timestamp")
            self.stop_loss_trigger_timestamp = (
                pd.Timestamp(_sl_ts) if _sl_ts else None
            )
            self.take_profit_trigger_timestamp = (
                pd.Timestamp(_tp_ts) if _tp_ts else None
            )
            self.stop_loss_trigger_price   = state.get("stop_loss_trigger_price")
            self.take_profit_trigger_price = state.get("take_profit_trigger_price")
            # Backward-Compat: alte Bot-States haben kein stop_loss_price-Feld.
            # Aus pct + lower_price (das gerade frisch aus __init__ kam)
            # rekonstruieren, falls vorhanden im State -> uebernehmen.
            self.stop_loss_price = state.get("stop_loss_price", self.stop_loss_price)
            self.take_profit_price = state.get("take_profit_price", self.take_profit_price)
            # ROI-/P/L-basierte Schwellen (Backward-Compat: alte States -> __init__)
            self.stop_loss_roi_pct   = state.get("stop_loss_roi_pct",
                                                  self.stop_loss_roi_pct)
            self.take_profit_roi_pct = state.get("take_profit_roi_pct",
                                                  self.take_profit_roi_pct)
            self.stop_loss_pl_usdt   = state.get("stop_loss_pl_usdt",
                                                  self.stop_loss_pl_usdt)
            self.take_profit_pl_usdt = state.get("take_profit_pl_usdt",
                                                  self.take_profit_pl_usdt)
            self.dd_throttle_factor   = state.get("dd_throttle_factor", 1.0)
            # Frisch geladener Bot ohne historischen Peak -> total_investment
            # als logischer Start (verhindert dass ein erster pv<total
            # faelschlich als Peak gespeichert wird).
            self._peak_portfolio      = state.get("_peak_portfolio",
                                                   self.total_investment)
            # DD-Verlauf (Backward-Compat: alte States ohne Feld -> [])
            self.dd_history           = list(state.get("dd_history", []))
            self.enable_trailing_up   = state.get("enable_trailing_up", False)
            self.trailing_up_stop     = state.get("trailing_up_stop", None)
            # Alte Felder enable_trailing_down/trailing_down_stop werden
            # beim Laden ignoriert (Down-Trailing existiert nicht mehr).
            self.trail_stop_levels    = state.get("trail_stop_levels", False)
            self.trailing_count       = state.get("trailing_count", 0)
            self.trailing_events      = state.get("trailing_events", [])
            self.recentering_events   = state.get("recentering_events", [])
            # Bot-Status + Grid Trigger (Backward-Compat: alte Bots = "active")
            self.bot_status         = state.get("bot_status", "active")
            self.grid_trigger_price = state.get("grid_trigger_price",
                                                self.grid_trigger_price)
            self._trigger_direction = state.get("_trigger_direction", None)
            self.enable_initial_buy = state.get("enable_initial_buy",
                                                self.enable_initial_buy)
            self.stop_bot_on_trigger = state.get("stop_bot_on_trigger",
                                                  self.stop_bot_on_trigger)
            # Initial-Buy-Aggregate
            self.initial_buy_coin_amount = state.get("initial_buy_coin_amount", 0.0)
            self.initial_buy_fee         = state.get("initial_buy_fee", 0.0)
            self.initial_buy_value_usdt  = state.get("initial_buy_value_usdt", 0.0)
            self._buffer_zone_price      = state.get("_buffer_zone_price", None)
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

    @property
    def take_profit_hit(self) -> bool:
        """Alias für take_profit_triggered."""
        return self.take_profit_triggered

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
    take_profit_pct:     Optional[float] = None,
    stop_loss_roi_pct:   Optional[float] = None,
    take_profit_roi_pct: Optional[float] = None,
    stop_loss_pl_usdt:   Optional[float] = None,
    take_profit_pl_usdt: Optional[float] = None,
    enable_recentering_up:   bool  = False,
    enable_recentering_down: bool  = False,
    recenter_threshold:  float = 0.05,
    enable_dd_throttle:  bool  = False,
    dd_threshold_1:      float = 0.10,
    dd_threshold_2:      float = 0.20,
    enable_trailing_up:     bool  = False,
    trailing_up_stop:       Optional[float] = None,
    trail_stop_levels:      bool  = False,
    grid_trigger_price:     Optional[float] = None,
    enable_initial_buy:     bool  = True,
    stop_bot_on_trigger:    bool  = False,
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
        enable_recentering_up:   Recentering nach oben aktivieren
        enable_recentering_down: Recentering nach unten aktivieren
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

        # Initial-Buy-Timestamps auf erste Kerze setzen. Im __init__ wurde
        # _current_timestamp via naive_utc_now() vorbelegt (Fallback fuer
        # PT/LT), daher haben Initial-Buy-Eintraege im BT-Pfad die Wall-
        # Clock-Zeit statt den Sim-Start. Patch nach initial=True statt
        # nach None-Timestamp, damit der Trade-Log korrekt im Sim-Zeitraum
        # liegt. Betrifft nur den "active"-Pfad — im Trigger-Modus setzt
        # process_candle den Timestamp ohnehin korrekt.
        first_ts = df.iloc[0]["timestamp"]
        for t in bot.trade_log:
            if t.get("initial") or t.get("timestamp") is None:
                t["timestamp"] = first_ts
        # Inventar-Timestamps analog: Initial-Buy-Inventar haengt am
        # _current_timestamp aus __init__ -> auf first_ts patchen.
        # Erkennung: ts ist None ODER ts liegt ausserhalb [first_ts, last_ts].
        last_ts = df.iloc[-1]["timestamp"]
        bot.coin_inventory = [
            (a, p, first_ts if (ts is None or ts < first_ts or ts > last_ts) else ts)
            for (a, p, ts) in bot.coin_inventory
        ]

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

        # Offene Positionen am Ende des Backtests im open_buys-Format
        # (Liste von Dicts), damit calculate_unrealized_pnl es direkt
        # konsumieren kann.
        # fee=0.0 weil coin_inventory die Original-Buy-Fee nicht speichert.
        # Floating Profit ist dadurch minimal optimistisch (≤0.1% pro Position).
        final_open_buys = [
            {"price": float(p), "amount": float(a), "fee": 0.0}
            for (a, p, _ts) in bot.coin_inventory
        ]

        return {
            "initial_investment":  total_investment,
            "final_value":         final_value,
            "profit_usdt":         total_profit,
            "profit_pct":          (total_profit / total_investment) * 100,
            "fees_paid":           total_fees,
            # Initial-Buys (Binance-Setup) zaehlen nicht als Grid-Trades.
            "num_trades":          sum(
                1 for t in bot.trade_log
                if not (t.get("type") == "BUY" and t.get("initial"))
            ),
            "trade_log":           bot.trade_log,
            "grid_lines":          bot.grid_lines,
            "final_position":      dict(bot.position),
            "final_open_buys":     final_open_buys,
            "initial_price":       initial_price,
            "final_price":         final_price,
            "price_change_pct":    ((final_price - initial_price) / initial_price) * 100,
            "daily_values":        filled_daily,
            "recentering_count":   bot.recentering_count,
            "recentering_events":  bot.recentering_events,
            "trailing_count":      bot.trailing_count,
            "trailing_events":     bot.trailing_events,
            # DD-Verlauf pro Kerze (fuer Drawdown-Tab)
            "dd_history":          bot.dd_history,
            "stop_loss_triggered": bot.stop_loss_triggered,
            "take_profit_triggered": bot.take_profit_triggered,
            # Trigger-Daten fuer Chart-Marker (M.2)
            "stop_loss_trigger_timestamp":   bot.stop_loss_trigger_timestamp,
            "stop_loss_trigger_price":       bot.stop_loss_trigger_price,
            "take_profit_trigger_timestamp": bot.take_profit_trigger_timestamp,
            "take_profit_trigger_price":     bot.take_profit_trigger_price,
            # Initial-Buy-Aggregate + Bot-Status + Grid Trigger
            "initial_buy_coin_amount": bot.initial_buy_coin_amount,
            "initial_buy_fee":         bot.initial_buy_fee,
            "initial_buy_value_usdt":  bot.initial_buy_value_usdt,
            "bot_status":              bot.bot_status,
            "grid_trigger_price":      bot.grid_trigger_price,
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
            "final_open_buys":     [],
            "initial_price":       0.0,
            "final_price":         0.0,
            "price_change_pct":    0.0,
            "daily_values":        {},
            "recentering_count":   0,
            "trailing_events":     [],
            "recentering_events":  [],
            "stop_loss_triggered": False,
            "take_profit_triggered": False,
            "stop_loss_trigger_timestamp":   None,
            "stop_loss_trigger_price":       None,
            "take_profit_trigger_timestamp": None,
            "take_profit_trigger_price":     None,
            "initial_buy_coin_amount": 0.0,
            "initial_buy_fee":         0.0,
            "initial_buy_value_usdt":  0.0,
            "bot_status":              "stopped",
            "grid_trigger_price":      grid_trigger_price,
            "bot_version":         BOT_VERSION,
            "error":               str(e),
        }