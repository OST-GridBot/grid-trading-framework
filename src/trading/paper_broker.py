"""
src/paper_trading/paper_broker.py
==================================
Simulated Order Broker fuer Paper-Trading.

Trennt die Ausfuehrungs-Logik von der Strategie-Logik.
Simuliert Binance-Order-Ausfuehrung mit:
    - Kapital-Validierung (genuegend USDT / Coins?)
    - Slippage-Simulation (realistische Preisabweichung)
    - Order-Log mit Status (filled / rejected)
    - Min-Order-Groesse (Binance Mindestbetrag 10 USDT)

Architektur (Bachelorarbeit):
    Engine  ->  entscheidet DASS gehandelt wird
    Broker  ->  entscheidet WIE die Order ausgefuehrt wird

Beim Uebergang zu Live-Trading wird nur der Broker
ausgetauscht – die Engine bleibt unveraendert.

Autor: Enes Eryilmaz
Projekt: Grid-Trading-Framework (Bachelorarbeit OST)
"""

import uuid
import numpy as np
import pandas as pd
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional

from config.settings import DEFAULT_FEE_RATE


# ---------------------------------------------------------------------------
# Datenklassen
# ---------------------------------------------------------------------------

@dataclass
class Order:
    """Repraesentiert eine einzelne Order."""
    order_id:    str
    order_type:  str    # BUY oder SELL
    grid_price:  float  # Ausloese-Preis (Grid-Level)
    exec_price:  float  # Tatsaechlicher Ausfuehrungspreis (mit Slippage)
    amount_coin: float  # Menge in Coins
    amount_usdt: float  # Menge in USDT
    fee:         float  # Gebuehr in USDT
    status:      str    # filled / rejected
    reason:      str    # Begruendung bei rejected
    timestamp:   str    # Ausfuehrungszeitpunkt
    slippage_pct: float # Slippage in %


@dataclass
class BrokerState:
    """Aktueller Zustand des Brokers."""
    balance_usdt:  float
    balance_coin:  float
    order_log:     list  = field(default_factory=list)
    total_fees:    float = 0.0
    total_slippage: float = 0.0
    filled_orders:  int  = 0
    rejected_orders: int = 0


# ---------------------------------------------------------------------------
# Paper Broker
# ---------------------------------------------------------------------------

class PaperBroker:
    """
    Simulierter Order-Broker fuer Paper-Trading.

    Nimmt Order-Anfragen entgegen, validiert sie und
    fuehrt sie mit realistischer Slippage aus.

    Args:
        initial_usdt   : Startkapital in USDT
        initial_coin   : Startbestand in Coins
        fee_rate       : Gebuehrenrate (Standard: 0.1%)
        slippage_pct   : Maximale Slippage in % (Standard: 0.05%)
        min_order_usdt : Mindest-Order-Groesse (Standard: 10 USDT)
    """

    def __init__(
        self,
        initial_usdt:    float,
        initial_coin:    float  = 0.0,
        fee_rate:        float  = DEFAULT_FEE_RATE,
        slippage_pct:    float  = 0.0005,
        min_order_usdt:  float  = 10.0,
    ):
        self.fee_rate       = fee_rate
        self.slippage_pct   = slippage_pct
        self.min_order_usdt = min_order_usdt
        self.state          = BrokerState(
            balance_usdt = initial_usdt,
            balance_coin = initial_coin,
        )

    # -----------------------------------------------------------------------
    # Order ausfuehren
    # -----------------------------------------------------------------------

    def execute_buy(
        self,
        grid_price:  float,
        amount_usdt: float,
        timestamp:   Optional[str] = None,
    ) -> Order:
        """
        Fuehrt eine BUY-Order aus.

        Ablauf:
            1. Kapital-Validierung (genuegend USDT?)
            2. Mindest-Order-Groesse pruefen
            3. Slippage berechnen (Preis etwas hoeher beim Kauf)
            4. Coins kaufen, USDT abziehen, Gebuehr abziehen
            5. Order-Log aktualisieren

        Args:
            grid_price  : Ausloese-Preis des Grid-Levels
            amount_usdt : Zu investierender Betrag in USDT
            timestamp   : Zeitstempel der Kerze

        Returns:
            Order mit Status filled oder rejected
        """
        ts = timestamp or datetime.now().isoformat()

        # Validierung
        if amount_usdt < self.min_order_usdt:
            return self._rejected_order(
                "BUY", grid_price, amount_usdt, ts,
                f"Betrag {amount_usdt:.2f} USDT unter Minimum {self.min_order_usdt} USDT"
            )
        if self.state.balance_usdt < amount_usdt:
            return self._rejected_order(
                "BUY", grid_price, amount_usdt, ts,
                f"Ungenuegendes Kapital: {self.state.balance_usdt:.2f} USDT verfuegbar"
            )

        # Slippage: Beim Kauf etwas teurer
        slippage   = self._random_slippage()
        exec_price = grid_price * (1 + slippage)

        # Gebuehr auf USDT-Betrag
        fee         = amount_usdt * self.fee_rate
        net_usdt    = amount_usdt - fee
        amount_coin = net_usdt / exec_price

        # Kontostand aktualisieren
        self.state.balance_usdt  -= amount_usdt
        self.state.balance_coin  += amount_coin
        self.state.total_fees    += fee
        self.state.total_slippage += abs(slippage) * amount_usdt
        self.state.filled_orders += 1

        order = Order(
            order_id     = str(uuid.uuid4())[:8],
            order_type   = "BUY",
            grid_price   = round(grid_price,  4),
            exec_price   = round(exec_price,  4),
            amount_coin  = round(amount_coin, 8),
            amount_usdt  = round(amount_usdt, 4),
            fee          = round(fee,         4),
            status       = "filled",
            reason       = "",
            timestamp    = ts,
            slippage_pct = round(slippage * 100, 4),
        )
        self.state.order_log.append(order)
        return order

    def execute_sell(
        self,
        grid_price:  float,
        amount_coin: float,
        timestamp:   Optional[str] = None,
    ) -> Order:
        """
        Fuehrt eine SELL-Order aus.

        Ablauf:
            1. Coin-Bestand pruefen
            2. Mindest-Order-Groesse pruefen
            3. Slippage berechnen (Preis etwas tiefer beim Verkauf)
            4. Coins verkaufen, USDT gutschreiben, Gebuehr abziehen

        Args:
            grid_price  : Ausloese-Preis des Grid-Levels
            amount_coin : Zu verkaufende Menge in Coins
            timestamp   : Zeitstempel der Kerze

        Returns:
            Order mit Status filled oder rejected
        """
        ts = timestamp or datetime.now().isoformat()

        # Slippage: Beim Verkauf etwas billiger
        slippage   = self._random_slippage()
        exec_price = grid_price * (1 - slippage)
        amount_usdt = amount_coin * exec_price

        # Validierung
        if amount_usdt < self.min_order_usdt:
            return self._rejected_order(
                "SELL", grid_price, amount_usdt, ts,
                f"Betrag {amount_usdt:.2f} USDT unter Minimum"
            )
        if self.state.balance_coin < amount_coin:
            return self._rejected_order(
                "SELL", grid_price, amount_usdt, ts,
                f"Ungenuegende Coins: {self.state.balance_coin:.8f} verfuegbar"
            )

        # Gebuehr auf USDT-Ertrag
        fee      = amount_usdt * self.fee_rate
        net_usdt = amount_usdt - fee

        # Kontostand aktualisieren
        self.state.balance_coin  -= amount_coin
        self.state.balance_usdt  += net_usdt
        self.state.total_fees    += fee
        self.state.total_slippage += abs(slippage) * amount_usdt
        self.state.filled_orders += 1

        order = Order(
            order_id     = str(uuid.uuid4())[:8],
            order_type   = "SELL",
            grid_price   = round(grid_price,  4),
            exec_price   = round(exec_price,  4),
            amount_coin  = round(amount_coin, 8),
            amount_usdt  = round(net_usdt,    4),
            fee          = round(fee,         4),
            status       = "filled",
            reason       = "",
            timestamp    = ts,
            slippage_pct = round(slippage * 100, 4),
        )
        self.state.order_log.append(order)
        return order

    # -----------------------------------------------------------------------
    # Kontostand & Kennzahlen
    # -----------------------------------------------------------------------

    def get_portfolio_value(self, current_price: float) -> float:
        """Berechnet den aktuellen Portfolio-Wert in USDT."""
        return round(
            self.state.balance_usdt + self.state.balance_coin * current_price, 2
        )

    def get_summary(self, current_price: float) -> dict:
        """Gibt eine Zusammenfassung des Broker-Zustands zurueck."""
        return {
            "balance_usdt":    round(self.state.balance_usdt,   2),
            "balance_coin":    round(self.state.balance_coin,   8),
            "portfolio_value": self.get_portfolio_value(current_price),
            "total_fees":      round(self.state.total_fees,     4),
            "total_slippage":  round(self.state.total_slippage, 4),
            "filled_orders":   self.state.filled_orders,
            "rejected_orders": self.state.rejected_orders,
            "order_log":       self.state.order_log,
        }

    def get_order_log_df(self) -> pd.DataFrame:
        """Gibt den Order-Log als DataFrame zurueck (fuer UI-Tabellen)."""
        if not self.state.order_log:
            return pd.DataFrame()
        rows = []
        for o in self.state.order_log:
            rows.append({
                "ID":          o.order_id,
                "Type":        o.order_type,
                "Grid-Preis":  o.grid_price,
                "Exec-Preis":  o.exec_price,
                "Coins":       o.amount_coin,
                "USDT":        o.amount_usdt,
                "Fee":         o.fee,
                "Slippage_%":  o.slippage_pct,
                "Status":      o.status,
                "Zeit":        o.timestamp,
            })
        return pd.DataFrame(rows)

    # -----------------------------------------------------------------------
    # Hilfsfunktionen
    # -----------------------------------------------------------------------

    def _random_slippage(self) -> float:
        """
        Generiert zufaellige Slippage zwischen 0 und slippage_pct.
        Simuliert realistische Marktabweichungen.
        """
        return float(np.random.uniform(0, self.slippage_pct))

    def _rejected_order(
        self,
        order_type:  str,
        grid_price:  float,
        amount_usdt: float,
        timestamp:   str,
        reason:      str,
    ) -> Order:
        """Erstellt eine abgelehnte Order und loggt sie."""
        self.state.rejected_orders += 1
        order = Order(
            order_id     = str(uuid.uuid4())[:8],
            order_type   = order_type,
            grid_price   = round(grid_price,  4),
            exec_price   = 0.0,
            amount_coin  = 0.0,
            amount_usdt  = round(amount_usdt, 4),
            fee          = 0.0,
            status       = "rejected",
            reason       = reason,
            timestamp    = timestamp,
            slippage_pct = 0.0,
        )
        self.state.order_log.append(order)
        return order