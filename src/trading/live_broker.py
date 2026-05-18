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
import math
import time
import uuid
import hashlib
import requests
import pandas as pd
from datetime import datetime
from decimal import Decimal, ROUND_DOWN
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

        Account-Daten werden zusaetzlich in self.account_info gespeichert.

        Hinweis: Die frueher geplante canWithdraw-Warnung wurde entfernt.
        canWithdraw aus /api/v3/account ist Account-Status, nicht die
        API-Key-Permission. Im nicht-kommerziellen Single-User-Setup
        bleibt die Withdraw-Permission auf API-Key-Ebene ohnehin immer
        deaktiviert — der Check ist daher entbehrlich.
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
            elif method == "DELETE":
                resp = requests.delete(url, headers=headers, timeout=10)
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

    # =======================================================================
    # Phase Live-2.1: Order-Primitives fuer LIMIT-Orders + clientOrderId +
    # Partial-Fill-Aggregation. Wird vom LiveRunner ab Phase Live-2.2 genutzt.
    # =======================================================================

    @staticmethod
    def _make_client_order_id(prefix: str = "gbf") -> str:
        """
        L-2: Idempotenz-Schluessel fuer Orders. UUID-basiert, Format:
            <prefix>_<16 hex chars>
        Binance erlaubt bis 36 Zeichen. Prefix "gbf" = Grid-Bot-Framework.
        """
        return f"{prefix}_{uuid.uuid4().hex[:16]}"

    @staticmethod
    def _decimals_from_step(step: float) -> int:
        """
        Robuste Decimal-Stellen-Ableitung aus tickSize/stepSize.
        Loest F2 aus Live-2.1-Audit: log10(0.5)=-0.301 wurde frueher
        gerundet zu 0 -> falsche Decimal-Stellen. String-Parsing umgeht
        das.
        """
        s = f"{step:.10f}".rstrip("0").rstrip(".")
        return len(s.split(".")[1]) if "." in s else 0

    def _format_price(self, price: float) -> str:
        """
        Rundet auf das naechste Vielfache von tickSize ab (Binance-konform).
        Decimal-basiert um Float-Drift zu vermeiden (Live-2.1b-Fix fuer
        F1: tickSize=0.0001, F2: tickSize=0.5).

        Beispiel: tickSize=0.01,    price=70123.456    -> "70123.45"
                  tickSize=0.5,     price=70123.7      -> "70123.5"
                  tickSize=0.0001,  price=70123.4567   -> "70123.4567"
                  tickSize=1.0,     price=70123.456    -> "70123"
        """
        tick = self.symbol_filters.get("tickSize", 0.01)
        if tick <= 0:
            tick = 0.01
        d_tick    = Decimal(str(tick))
        d_price   = Decimal(str(price))
        # ROUND_DOWN: niemals ueber den Soll-Tick — Binance lehnt sonst ab.
        n_ticks   = (d_price / d_tick).quantize(Decimal("1"),
                                                rounding=ROUND_DOWN)
        d_rounded = n_ticks * d_tick
        decimals  = self._decimals_from_step(tick)
        return f"{float(d_rounded):.{decimals}f}"

    def _format_quantity(self, qty: float) -> str:
        """
        Rundet auf stepSize ab, prueft minQty/maxQty. Decimal-basiert
        (Live-2.1b-Fix fuer F3: qty exakt maxQty wegen Float-Drift).

        Bei qty < minQty wird ValueError geworfen.
        Bei qty > maxQty wird auf maxQty gekappt.

        Beispiel: stepSize=0.00001, qty=0.000123456 -> "0.00012"
        """
        step    = self.symbol_filters.get("stepSize", 1e-8)
        min_qty = self.symbol_filters.get("minQty",   0.0)
        max_qty = self.symbol_filters.get("maxQty",   9e18)
        if step <= 0:
            step = 1e-8
        d_step    = Decimal(str(step))
        d_qty     = Decimal(str(qty))
        n_steps   = (d_qty / d_step).quantize(Decimal("1"),
                                              rounding=ROUND_DOWN)
        d_rounded = n_steps * d_step
        f_rounded = float(d_rounded)
        if f_rounded < min_qty:
            raise ValueError(
                f"Quantity {f_rounded:.10f} < minQty {min_qty:.10f}"
            )
        if f_rounded > max_qty:
            d_max     = Decimal(str(max_qty))
            n_cap     = (d_max / d_step).quantize(Decimal("1"),
                                                  rounding=ROUND_DOWN)
            d_rounded = n_cap * d_step
        decimals  = self._decimals_from_step(step)
        return f"{float(d_rounded):.{decimals}f}"

    def _aggregate_fills(self, fills_list: list) -> dict:
        """
        L-6: Aggregiert Binance-fills[]-Liste zu gewichtetem Average-Price,
        Summe der Quantities und Summe der Commissions. Erkennt gemischte
        commissionAssets (BNB-Discount + USDT-Fees).

        Args:
            fills_list: Liste von Dicts {price, qty, commission, commissionAsset}

        Returns:
            {
                "avg_price":        gewichteter avg-price (0 bei leer),
                "total_qty":        Summe qty,
                "total_commission": Summe commission,
                "commission_asset": Asset-Symbol oder "mixed" oder None,
            }
        """
        if not fills_list:
            return {
                "avg_price":        0.0,
                "total_qty":        0.0,
                "total_commission": 0.0,
                "commission_asset": None,
            }
        total_qty        = 0.0
        total_quote      = 0.0
        total_commission = 0.0
        assets           = set()
        for f in fills_list:
            qty        = float(f.get("qty", 0))
            price      = float(f.get("price", 0))
            commission = float(f.get("commission", 0))
            total_qty        += qty
            total_quote      += qty * price
            total_commission += commission
            asset = f.get("commissionAsset")
            if asset:
                assets.add(asset)
        avg_price = (total_quote / total_qty) if total_qty > 0 else 0.0
        if len(assets) == 0:
            commission_asset = None
        elif len(assets) == 1:
            commission_asset = next(iter(assets))
        else:
            commission_asset = "mixed"
        return {
            "avg_price":        avg_price,
            "total_qty":        total_qty,
            "total_commission": total_commission,
            "commission_asset": commission_asset,
        }

    def place_limit_order(
        self,
        side:             str,
        price:            float,
        quantity:         float,
        client_order_id:  Optional[str] = None,
    ) -> dict:
        """
        L-13 + L-2: Platziert eine LIMIT-Order (timeInForce=GTC) mit
        clientOrderId fuer Idempotenz. Returns ein Dict (kein Order-
        Dataclass, weil LIMIT noch nicht gefuellt ist).

        Args:
            side            : "BUY" oder "SELL"
            price           : Limit-Preis (wird via _format_price gerundet)
            quantity        : Coin-Menge (wird via _format_quantity gerundet)
            client_order_id : Optional. Wird generiert wenn None.

        Returns dict:
            {
                "client_order_id":   gbf_<hex> (immer gesetzt),
                "binance_order_id":  str (orderId von Binance) oder "",
                "symbol":            "BTCUSDT" etc.,
                "side":              "BUY"/"SELL",
                "price":             float (gerundet auf tickSize),
                "quantity":          float (gerundet auf stepSize),
                "status":            "NEW" / "PARTIALLY_FILLED" / "FILLED",
                "timestamp":         ISO-String,
                "error":             str | None,
            }
        """
        ts = naive_utc_now().isoformat()
        if client_order_id is None:
            client_order_id = self._make_client_order_id()

        # Format-Validierung
        try:
            price_str = self._format_price(price)
            qty_str   = self._format_quantity(quantity)
        except ValueError as e:
            return {
                "client_order_id":  client_order_id,
                "binance_order_id": "",
                "symbol":           self.symbol,
                "side":             side,
                "price":            float(price),
                "quantity":         float(quantity),
                "status":           "rejected",
                "timestamp":        ts,
                "error":            str(e),
            }

        params = {
            "symbol":           self.symbol,
            "side":             side,
            "type":             "LIMIT",
            "timeInForce":      "GTC",
            "price":            price_str,
            "quantity":         qty_str,
            "newClientOrderId": client_order_id,
        }
        response = self._signed_request("POST", "/api/v3/order", params)
        if "error" in response:
            return {
                "client_order_id":  client_order_id,
                "binance_order_id": "",
                "symbol":           self.symbol,
                "side":             side,
                "price":            float(price_str),
                "quantity":         float(qty_str),
                "status":           "rejected",
                "timestamp":        ts,
                "error":            response["error"],
            }
        return {
            "client_order_id":  client_order_id,
            "binance_order_id": str(response.get("orderId", "")),
            "symbol":           self.symbol,
            "side":             side,
            "price":            float(price_str),
            "quantity":         float(qty_str),
            "status":           response.get("status", "NEW"),
            "timestamp":        ts,
            "error":            None,
        }

    def get_order_status(self, client_order_id: str) -> dict:
        """
        Holt den aktuellen Status einer Order ueber die clientOrderId.

        Returns die Raw-Binance-Response (mit zusaetzlichem 'error'-Feld
        bei Misserfolg). Aufrufer sollte 'status' auswerten:
            NEW / PARTIALLY_FILLED / FILLED / CANCELED / REJECTED / EXPIRED
        """
        params = {
            "symbol":           self.symbol,
            "origClientOrderId": client_order_id,
        }
        return self._signed_request("GET", "/api/v3/order", params)

    def get_open_orders(self) -> Optional[list]:
        """
        Phase Live-2.4 / 2.5-Fix (L-22): Batched Polling — alle offenen
        Orders fuer self.symbol mit einem einzigen API-Call.

        Effizienter als Einzel-Polling pro tracked clientOrderId:
        bei N offenen Orders 1 Request statt N. Reduziert Rate-Limit-
        Druck (Weight des Endpoints ist auch nur 6 statt 2*N).

        Returns:
            list[dict] bei Erfolg (kann auch leer sein wenn wirklich
                       keine Orders offen sind).
            None       bei API-Fehler / unbekanntem Stand. Aufrufer
                       muss das pruefen und Poll-Cycle ueberspringen,
                       damit tracked Orders nicht faelschlich als
                       "verschwunden" interpretiert werden (L-22 Fix).
        """
        params = {"symbol": self.symbol}
        data = self._signed_request("GET", "/api/v3/openOrders", params)
        if isinstance(data, dict) and "error" in data:
            return None
        if not isinstance(data, list):
            return None
        return data

    def cancel_order(self, client_order_id: str) -> dict:
        """
        Storniert eine offene LIMIT-Order ueber die clientOrderId.

        Returns Raw-Response. Bei Erfolg enthaelt sie u.a. 'status':'CANCELED'
        und 'executedQty' (falls schon teilweise gefuellt).
        """
        params = {
            "symbol":           self.symbol,
            "origClientOrderId": client_order_id,
        }
        return self._signed_request("DELETE", "/api/v3/order", params)

    def get_my_trades(self, binance_order_id) -> list:
        """
        Phase Live-4.1 (L-5): Holt die einzelnen Trade-Fills einer Order
        ueber /api/v3/myTrades.

        Hintergrund: /api/v3/order (get_order_status) liefert KEIN fills[]-
        Array. Fuer LIMIT-Orders bedeutet das, dass die echten Commission-
        Werte nicht aus der Status-Abfrage gewonnen werden koennen. Erst
        myTrades liefert pro Match price/qty/commission/commissionAsset.

        Format der zurueckgegebenen Items ist mit fills[] aus place-/
        execute-Responses kompatibel, sodass _aggregate_fills(...) sie
        direkt verarbeiten kann.

        Args:
            binance_order_id: orderId (int oder str-int) von Binance.
                              Strings werden tolerant in int gecastet.

        Returns:
            list[dict] mit Keys price/qty/commission/commissionAsset.
            Leere Liste bei API-Fehler oder keinen Trades — defensiv,
            damit der Aufrufer auf den bisherigen 'commission=0'-Pfad
            zurueckfallen kann ohne zu crashen.
        """
        try:
            order_id_int = int(binance_order_id)
        except (TypeError, ValueError):
            return []
        params = {
            "symbol":  self.symbol,
            "orderId": order_id_int,
        }
        data = self._signed_request("GET", "/api/v3/myTrades", params)
        if isinstance(data, dict) and "error" in data:
            return []
        if not isinstance(data, list):
            return []
        # myTrades-Felder bereits kompatibel mit _aggregate_fills:
        # price/qty/commission/commissionAsset sind dieselben Keys.
        return data

    def execute_market_buy_real(
        self,
        amount_usdt:     float,
        client_order_id: Optional[str] = None,
    ) -> dict:
        """
        L-16-Vorbereitung: Echte MARKET-BUY-Order mit clientOrderId und
        Partial-Fill-Aggregation. Wird vom LiveRunner._ensure_initial_buys
        ab Phase Live-2.2 aufgerufen.

        Im Gegensatz zum alten execute_buy:
          - clientOrderId fuer Idempotenz (L-2)
          - exec_price = gewichteter avg ueber alle fills (L-6)
          - exec_qty   = Summe der fills[].qty
          - fee        = Summe der fills[].commission (echte Fees, nicht
                         lokal geschaetzt — L-5-Vorgriff bereits hier)

        Args:
            amount_usdt     : USDT-Betrag (quoteOrderQty)
            client_order_id : Optional, wird generiert wenn None

        Returns dict:
            {
                "client_order_id":  ...,
                "binance_order_id": ...,
                "symbol":           ...,
                "side":             "BUY",
                "amount_usdt":      Eingesetzter USDT-Betrag,
                "exec_price":       gewichteter avg-price,
                "exec_qty":         total qty,
                "commission":       total commission (echte Binance-Fee),
                "commission_asset": "USDT"/"BNB"/.../"mixed",
                "status":           "FILLED" / "rejected",
                "timestamp":        ...,
                "error":            str | None,
            }
        """
        ts = naive_utc_now().isoformat()
        if client_order_id is None:
            client_order_id = self._make_client_order_id()

        params = {
            "symbol":           self.symbol,
            "side":             "BUY",
            "type":             "MARKET",
            "quoteOrderQty":    round(amount_usdt, 2),
            "newClientOrderId": client_order_id,
        }
        response = self._signed_request("POST", "/api/v3/order", params)
        if "error" in response:
            return {
                "client_order_id":  client_order_id,
                "binance_order_id": "",
                "symbol":           self.symbol,
                "side":             "BUY",
                "amount_usdt":      amount_usdt,
                "exec_price":       0.0,
                "exec_qty":         0.0,
                "commission":       0.0,
                "commission_asset": None,
                "status":           "rejected",
                "timestamp":        ts,
                "error":            response["error"],
            }

        fills = response.get("fills", []) or []
        agg   = self._aggregate_fills(fills)
        # Balances aktualisieren (Binance hat USDT abgebucht + Coin gutgeschrieben)
        self._update_balances()
        self.state.filled_orders += 1
        self.state.total_fees    += agg["total_commission"]

        return {
            "client_order_id":  client_order_id,
            "binance_order_id": str(response.get("orderId", "")),
            "symbol":           self.symbol,
            "side":             "BUY",
            "amount_usdt":      amount_usdt,
            "exec_price":       agg["avg_price"],
            "exec_qty":         agg["total_qty"],
            "commission":       agg["total_commission"],
            "commission_asset": agg["commission_asset"],
            "status":           response.get("status", "FILLED"),
            "timestamp":        ts,
            "error":            None,
        }