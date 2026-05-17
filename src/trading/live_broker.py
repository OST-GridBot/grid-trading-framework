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
from src.utils.timezone import naive_utc_now
from typing import Optional

from config.settings import DEFAULT_FEE_RATE, BINANCE_RECV_WINDOW
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
        testnet:    bool  = False,    # Phase Live-1: Production-Default
        fee_rate:   float = DEFAULT_FEE_RATE,
    ):
        self.api_key    = api_key
        self.api_secret = api_secret
        self.coin       = coin.upper()
        self.symbol     = f"{self.coin}USDT"
        self.base_url   = BINANCE_TEST_URL if testnet else BINANCE_BASE_URL
        self.fee_rate   = fee_rate
        self.testnet    = testnet
        self.state      = BrokerState(balance_usdt=0.0, balance_coin=0.0)

        # Phase Live-1: Init-Status-Felder (L-1/L-3/L-11/L-14)
        self._time_offset_ms: int            = 0
        self.symbol_filters: dict            = {}
        self.account_info:   dict            = {}
        self.init_ok:        bool            = False
        self.init_error:     Optional[str]   = None
        self.init_warnings:  list            = []

        # Init-Sequenz: Reihenfolge wichtig!
        # 1. Server-Time (L-11) -> ohne korrektes Offset versagen signed Requests
        # 2. exchangeInfo (L-3) -> Filter fuer Order-Validierung cachen
        # 3. Permissions  (L-14) -> canTrade pruefen, Withdraw warnen
        # 4. Balances             -> aktueller Kontostand
        if not self._init_time_sync():
            return
        if not self._init_exchange_info():
            return
        if not self._init_permissions():
            return
        self._update_balances()
        self.init_ok = True

    # -----------------------------------------------------------------------
    # Order ausfuehren
    # -----------------------------------------------------------------------

    # -----------------------------------------------------------------------
    # Phase Live-1: Init-Helfer (Time-Sync, exchangeInfo, Permissions)
    # -----------------------------------------------------------------------

    def _init_time_sync(self) -> bool:
        """
        L-11: Laedt Binance-Server-Zeit und berechnet Drift zur lokalen Uhr.
        Wird als _time_offset_ms gespeichert und zu jedem signed-Request
        addiert. Damit funktionieren Requests auch bei kleinen Uhren-
        Abweichungen (Binance lehnt sonst ab).
        """
        try:
            url  = f"{self.base_url}/api/v3/time"
            resp = requests.get(url, timeout=10)
            data = resp.json()
            if "serverTime" not in data:
                self.init_error = f"Server-Time-Antwort ungültig: {data}"
                return False
            server_ms = int(data["serverTime"])
            local_ms  = int(time.time() * 1000)
            self._time_offset_ms = server_ms - local_ms
            return True
        except Exception as e:
            self.init_error = f"Server-Time nicht erreichbar: {e}"
            return False

    def _init_exchange_info(self) -> bool:
        """
        L-3: Laedt Symbol-Filter (LOT_SIZE, NOTIONAL, PRICE_FILTER) und
        cached sie in self.symbol_filters. Wird fuer validate_config()
        genutzt und (in Phase Live-2) fuer Order-Validierung.
        """
        try:
            url  = f"{self.base_url}/api/v3/exchangeInfo?symbol={self.symbol}"
            resp = requests.get(url, timeout=10)
            data = resp.json()
            symbols = data.get("symbols", [])
            if not symbols:
                self.init_error = f"Symbol {self.symbol} bei Binance nicht gefunden"
                return False
            info    = symbols[0]
            filters = {}
            for f in info.get("filters", []):
                ftype = f.get("filterType", "")
                if ftype == "LOT_SIZE":
                    filters["stepSize"] = float(f["stepSize"])
                    filters["minQty"]   = float(f["minQty"])
                    filters["maxQty"]   = float(f["maxQty"])
                elif ftype in ("NOTIONAL", "MIN_NOTIONAL"):
                    # Binance hat beide Namen je nach Symbol — letzter gewinnt
                    filters["minNotional"] = float(f.get("minNotional", 5.0))
                elif ftype == "PRICE_FILTER":
                    filters["tickSize"] = float(f["tickSize"])
                    filters["minPrice"] = float(f.get("minPrice", 0))
                    filters["maxPrice"] = float(f.get("maxPrice", 0))
            # Defaults, falls einzelne Filter fehlen
            filters.setdefault("stepSize",    1e-8)
            filters.setdefault("minQty",      0.0)
            filters.setdefault("maxQty",      9e18)
            filters.setdefault("minNotional", 5.0)
            filters.setdefault("tickSize",    0.01)
            self.symbol_filters = filters
            return True
        except Exception as e:
            self.init_error = f"exchangeInfo nicht erreichbar: {e}"
            return False

    def _init_permissions(self) -> bool:
        """
        L-14: Prueft die API-Key-Berechtigungen.
            - canTrade=True ist Voraussetzung (sonst Init-Fehler).
            - canWithdraw=True erzeugt eine Warnung (Sicherheitsrisiko,
              nicht erforderlich fuer Live-Trading).
        Account-Daten werden zusaetzlich in self.account_info gespeichert.
        """
        data = self._signed_request("GET", "/api/v3/account", {})
        if "error" in data:
            self.init_error = f"Account-Info nicht abrufbar: {data['error']}"
            return False
        self.account_info = data
        if not data.get("canTrade", False):
            self.init_error = (
                "API-Key hat keine canTrade-Berechtigung. "
                "Bitte in Binance unter API-Management Spot-Trading aktivieren."
            )
            return False
        if data.get("canWithdraw", False):
            self.init_warnings.append(
                "API-Key hat canWithdraw=True. Für Live-Trading nicht nötig "
                "und ein Sicherheitsrisiko — bitte in Binance deaktivieren."
            )
        return True

    def validate_config(
        self,
        lower_price:      float,
        upper_price:      float,
        num_grids:        int,
        total_investment: float,
    ) -> tuple:
        """
        L-3: Prueft Bot-Konfiguration gegen Binance-Filter (vor Bot-
        Erstellung im UI). Gibt (ok: bool, errors: list[str]) zurueck.

        Geprueft wird:
            - Grid-Distanz >= tickSize
            - USDT pro Order >= minNotional
            - Coin-Menge pro Order >= minQty (Worst-Case: upper_price)
        """
        errors = []
        if not self.symbol_filters:
            errors.append("Symbol-Filter nicht geladen (Init fehlgeschlagen).")
            return False, errors

        tick_size    = self.symbol_filters["tickSize"]
        min_notional = self.symbol_filters["minNotional"]
        min_qty      = self.symbol_filters["minQty"]

        # Basis-Sanity
        if lower_price <= 0 or upper_price <= 0:
            errors.append("Preise müssen > 0 sein.")
        if lower_price >= upper_price:
            errors.append(
                f"lower_price ({lower_price}) muss < upper_price "
                f"({upper_price}) sein."
            )
        if num_grids < 2:
            errors.append(f"num_grids ({num_grids}) muss >= 2 sein.")
        if total_investment <= 0:
            errors.append(
                f"total_investment ({total_investment}) muss > 0 sein."
            )

        # Filter-Checks nur sinnvoll, wenn Basis-Checks ok sind
        if not errors:
            grid_distance = (upper_price - lower_price) / num_grids
            if grid_distance < tick_size:
                errors.append(
                    f"Grid-Distanz ({grid_distance:.8f}) < Binance tickSize "
                    f"({tick_size:.8f}). Reduziere num_grids oder weite die "
                    f"Preisspanne."
                )
            per_order_usdt = total_investment / num_grids
            if per_order_usdt < min_notional:
                errors.append(
                    f"USDT pro Order ({per_order_usdt:.2f}) < Binance "
                    f"minNotional ({min_notional:.2f}). Erhöhe das "
                    f"Investment oder reduziere num_grids."
                )
            per_order_qty = per_order_usdt / upper_price
            if per_order_qty < min_qty:
                errors.append(
                    f"Coin-Menge pro Order ({per_order_qty:.8f}) < Binance "
                    f"minQty ({min_qty:.8f}). Erhöhe das Investment."
                )

        return len(errors) == 0, errors

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
        ts     = timestamp or naive_utc_now().isoformat()
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
        ts     = timestamp or naive_utc_now().isoformat()
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
        """
        Sendet einen signierten Request an Binance.

        Phase Live-1 (L-11): timestamp wird um _time_offset_ms korrigiert,
        damit lokale Uhren-Drift Binance-Requests nicht blockiert. Zusaetz-
        lich recvWindow gesetzt (5000 ms = Default).
        """
        try:
            params["timestamp"]  = int(time.time() * 1000) + self._time_offset_ms
            params["recvWindow"] = BINANCE_RECV_WINDOW
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