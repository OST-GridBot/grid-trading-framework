"""
src/trading/live_broker.py
==========================
Echter Order-Broker fuer Live-Trading via Binance API.

Ersetzt den PaperBroker beim Live-Trading.
Die TradingEngine bleibt unveraendert - nur der Broker wechselt.

Sicherheitshinweise:
    - API-Key und Secret niemals im Code hardcoden
    - Nur in config/settings.py oder .env Datei
    - Testnet zuerst empfohlen

Autor: Enes Eryilmaz
Projekt: Grid-Trading-Framework (Bachelorarbeit OST)
"""

import hmac
import time
import hashlib
import requests
import pandas as pd
from datetime import datetime
from typing import Optional

from config.settings import DEFAULT_FEE_RATE
from src.trading.paper_broker import Order, BrokerState


BINANCE_BASE_URL = "https://api.binance.com"
BINANCE_TEST_URL = "https://testnet.binance.vision"


class LiveBroker:
    """
    Echter Order-Broker fuer Live-Trading via Binance API.

    Identische Schnittstelle wie PaperBroker:
        execute_buy()         -> echte MARKET BUY Order
        execute_sell()        -> echte MARKET SELL Order
        get_portfolio_value() -> echten Kontostand abfragen
        get_summary()         -> Zusammenfassung

    Args:
        api_key    : Binance API-Key
        api_secret : Binance API-Secret
        coin       : Coin-Symbol (z.B. "BTC")
        testnet    : True = Testnet (empfohlen zum Testen)
        fee_rate   : Gebuehrenrate
    """

    def __init__(
        self,
        api_key:    str,
        api_secret: str,
        coin:       str   = "BTC",
        testnet:    bool  = True,
        fee_rate:   float = DEFAULT_FEE_RATE,
    ):
        self.api_key    = api_key
        self.api_secret = api_secret
        self.coin       = coin.upper()
        self.base_url   = BINANCE_TEST_URL if testnet else BINANCE_BASE_URL
        self.fee_rate   = fee_rate
        self.testnet    = testnet
        self.state      = BrokerState(balance_usdt=0.0, balance_coin=0.0)
        self._update_balances()

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
        Fuehrt eine echte MARKET BUY Order auf Binance aus.

        Args:
            grid_price  : Ausloese-Preis (fuer Log)
            amount_usdt : Zu investierender Betrag in USDT
            timestamp   : Zeitstempel
        """
        ts     = timestamp or datetime.now().isoformat()
        symbol = f"{self.coin}USDT"

        params = {
            "symbol":        symbol,
            "side":          "BUY",
            "type":          "MARKET",
            "quoteOrderQty": round(amount_usdt, 2),
        }
        response = self._signed_request("POST", "/api/v3/order", params)
        if "error" in response:
            return self._failed_order("BUY", grid_price, amount_usdt, ts, response["error"])

        exec_price = float(response.get("fills", [{}])[0].get("price", grid_price))
        exec_qty   = float(response.get("executedQty", 0))
        fee        = amount_usdt * self.fee_rate

        self.state.filled_orders += 1
        self.state.total_fees    += fee
        self._update_balances()

        order = Order(
            order_id     = str(response.get("orderId", "unknown")),
            order_type   = "BUY",
            grid_price   = round(grid_price,  4),
            exec_price   = round(exec_price,  4),
            amount_coin  = round(exec_qty,    8),
            amount_usdt  = round(amount_usdt, 4),
            fee          = round(fee,         4),
            status       = "filled",
            reason       = "",
            timestamp    = ts,
            slippage_pct = round(abs(exec_price - grid_price) / grid_price * 100, 4),
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
        Fuehrt eine echte MARKET SELL Order auf Binance aus.

        Args:
            grid_price  : Ausloese-Preis (fuer Log)
            amount_coin : Zu verkaufende Coin-Menge
            timestamp   : Zeitstempel
        """
        ts     = timestamp or datetime.now().isoformat()
        symbol = f"{self.coin}USDT"

        params = {
            "symbol":   symbol,
            "side":     "SELL",
            "type":     "MARKET",
            "quantity": f"{amount_coin:.8f}",
        }
        response = self._signed_request("POST", "/api/v3/order", params)
        if "error" in response:
            return self._failed_order("SELL", grid_price, 0, ts, response["error"])

        exec_price  = float(response.get("fills", [{}])[0].get("price", grid_price))
        exec_qty    = float(response.get("executedQty", 0))
        amount_usdt = exec_qty * exec_price
        fee         = amount_usdt * self.fee_rate

        self.state.filled_orders += 1
        self.state.total_fees    += fee
        self._update_balances()

        order = Order(
            order_id     = str(response.get("orderId", "unknown")),
            order_type   = "SELL",
            grid_price   = round(grid_price,  4),
            exec_price   = round(exec_price,  4),
            amount_coin  = round(exec_qty,    8),
            amount_usdt  = round(amount_usdt, 4),
            fee          = round(fee,         4),
            status       = "filled",
            reason       = "",
            timestamp    = ts,
            slippage_pct = round(abs(exec_price - grid_price) / grid_price * 100, 4),
        )
        self.state.order_log.append(order)
        return order

    # -----------------------------------------------------------------------
    # Kontostand
    # -----------------------------------------------------------------------

    def get_portfolio_value(self, current_price: float) -> float:
        """Laedt echten Kontostand von Binance und berechnet Portfolio-Wert."""
        self._update_balances()
        return round(
            self.state.balance_usdt + self.state.balance_coin * current_price, 2
        )

    def get_summary(self, current_price: float) -> dict:
        """Identische Schnittstelle wie PaperBroker."""
        self._update_balances()
        return {
            "balance_usdt":    round(self.state.balance_usdt,   2),
            "balance_coin":    round(self.state.balance_coin,   8),
            "portfolio_value": self.get_portfolio_value(current_price),
            "total_fees":      round(self.state.total_fees,     4),
            "total_slippage":  round(self.state.total_slippage, 4),
            "filled_orders":   self.state.filled_orders,
            "rejected_orders": self.state.rejected_orders,
            "order_log":       self.state.order_log,
            "testnet":         self.testnet,
        }

    def get_order_log_df(self) -> pd.DataFrame:
        """Gibt den Order-Log als DataFrame zurueck."""
        if not self.state.order_log:
            return pd.DataFrame()
        rows = [{
            "ID":         o.order_id,
            "Type":       o.order_type,
            "Grid-Preis": o.grid_price,
            "Exec-Preis": o.exec_price,
            "Coins":      o.amount_coin,
            "USDT":       o.amount_usdt,
            "Fee":        o.fee,
            "Slippage_%": o.slippage_pct,
            "Status":     o.status,
            "Zeit":       o.timestamp,
        } for o in self.state.order_log]
        return pd.DataFrame(rows)

    # -----------------------------------------------------------------------
    # Binance API Hilfsfunktionen
    # -----------------------------------------------------------------------

    def _signed_request(self, method: str, endpoint: str, params: dict) -> dict:
        """Sendet einen signierten Request an Binance."""
        try:
            params["timestamp"] = int(time.time() * 1000)
            query     = "&".join(f"{k}={v}" for k, v in params.items())
            signature = hmac.new(
                self.api_secret.encode(),
                query.encode(),
                hashlib.sha256,
            ).hexdigest()
            url     = f"{self.base_url}{endpoint}?{query}&signature={signature}"
            headers = {"X-MBX-APIKEY": self.api_key}
            if method == "POST":
                resp = requests.post(url, headers=headers, timeout=10)
            else:
                resp = requests.get(url, headers=headers, timeout=10)
            data = resp.json()
            if "code" in data and data["code"] != 200:
                return {"error": data.get("msg", "Unbekannter Fehler")}
            return data
        except Exception as e:
            return {"error": str(e)}

    def _update_balances(self) -> None:
        """Laedt aktuellen Kontostand von Binance."""
        try:
            data = self._signed_request("GET", "/api/v3/account", {})
            if "error" in data:
                return
            for asset in data.get("balances", []):
                if asset["asset"] == "USDT":
                    self.state.balance_usdt = float(asset["free"])
                if asset["asset"] == self.coin:
                    self.state.balance_coin = float(asset["free"])
        except Exception:
            pass

    def _failed_order(
        self, order_type: str, grid_price: float,
        amount_usdt: float, timestamp: str, reason: str,
    ) -> Order:
        """Erstellt eine fehlgeschlagene Order."""
        self.state.rejected_orders += 1
        order = Order(
            order_id     = "failed",
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