"""
src/trading/engine.py
=====================
Vereinte Trading-Engine fuer Paper- und Live-Trading.

Dependency Injection Pattern:
    Paper : TradingEngine(config, broker=PaperBroker(...))
    Live  : TradingEngine(config, broker=LiveBroker(...))

Die Engine entscheidet DASS gehandelt wird.
Der Broker entscheidet WIE die Order ausgefuehrt wird.

Autor: Enes Eryilmaz
Projekt: Grid-Trading-Framework (Bachelorarbeit OST)
"""

import json
import pandas as pd
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field, asdict

from config.settings import (
    DEFAULT_FEE_RATE, DEFAULT_GRID_MODE, DEFAULT_NUM_GRIDS,
    DEFAULT_RESERVE_PCT, CACHE_DIR,
)
from src.data.binance_api import fetch_klines_df
from src.strategy.grid_bot import GridBot
from src.strategy.risk import calculate_drawdown
from src.backtesting.metrics import calculate_roi, calculate_sharpe_ratio

STATE_FILE = Path(CACHE_DIR) / "trading_state.json"

# Wie viele Stunden pro Intervall fuer den Kerzen-Abruf
_INTERVAL_HOURS = {
    "1m": 1, "5m": 1, "15m": 1, "1h": 3, "4h": 12
}


def _now_utc() -> datetime:
    """Gibt aktuelle UTC-Zeit zurueck."""
    return datetime.now(tz=timezone.utc)


@dataclass
class TradingConfig:
    coin:               str
    lower_price:        float
    upper_price:        float
    total_investment:   float           = 10_000.0
    num_grids:          int             = DEFAULT_NUM_GRIDS
    grid_mode:          str             = DEFAULT_GRID_MODE
    fee_rate:           float           = DEFAULT_FEE_RATE
    reserve_pct:        float           = DEFAULT_RESERVE_PCT
    stop_loss_pct:      Optional[float] = None
    enable_recentering: bool            = False
    interval:           str             = "1h"
    mode:               str             = "paper"


@dataclass
class TradingState:
    config:            dict
    mode:              str   = "paper"
    position:          dict  = field(default_factory=lambda: {"usdt": 0.0, "coin": 0.0})
    trade_log:         list  = field(default_factory=list)
    daily_values:      dict  = field(default_factory=dict)
    initial_price:     float = 0.0
    last_price:        float = 0.0
    start_time:        str   = ""
    last_update:       str   = ""
    num_candles:       int   = 0
    is_running:        bool  = False
    stop_loss_hit:     bool  = False
    recentering_count: int   = 0


class TradingEngine:
    def __init__(self, config: TradingConfig, broker):
        self.config   = config
        self.broker   = broker
        self.bot:     Optional[GridBot] = None
        self.state:   Optional[TradingState] = None
        self._running = False

    def start(self, resume: bool = False) -> dict:
        if resume and STATE_FILE.exists():
            return self._resume_session()
        return self._start_new_session()

    def _start_new_session(self) -> dict:
        print(f"Trading [{self.config.mode}]: Neue Session fuer {self.config.coin}")

        # FIX 1: UTC verwenden, nur 2 Stunden fuer aktuellen Preis
        df, meta, err = fetch_klines_df(
            self.config.coin, self.config.interval,
            _now_utc() - timedelta(hours=2),
            _now_utc()
        )
        if err or df is None or df.empty:
            return {"error": f"Preisdaten nicht verfuegbar: {err}"}

        initial_price = float(df["close"].iloc[-1])
        self.bot = GridBot(
            total_investment   = self.config.total_investment,
            lower_price        = self.config.lower_price,
            upper_price        = self.config.upper_price,
            num_grids          = self.config.num_grids,
            grid_mode          = self.config.grid_mode,
            fee_rate           = self.config.fee_rate,
            initial_price      = initial_price,
            reserve_pct        = self.config.reserve_pct,
            stop_loss_pct      = self.config.stop_loss_pct,
            enable_recentering = self.config.enable_recentering,
        )

        self.state = TradingState(
            config        = asdict(self.config),
            mode          = self.config.mode,
            position      = dict(self.bot.position),
            initial_price = initial_price,
            last_price    = initial_price,
            start_time    = _now_utc().isoformat(),
            last_update   = _now_utc().isoformat(),
            is_running    = True,
        )
        self._save_state()
        self._running = True
        print(f"Trading [{self.config.mode}]: Gestartet @ {initial_price}")
        return {
            "status":        "started",
            "mode":          self.config.mode,
            "coin":          self.config.coin,
            "initial_price": initial_price,
            "grid_lines":    self.bot.grid_lines,
            "position":      dict(self.bot.position),
        }

    def _resume_session(self) -> dict:
        print(f"Trading [{self.config.mode}]: Session wird fortgesetzt...")
        if not self._load_state():
            return self._start_new_session()
        self._running = True
        self.state.is_running = True
        self._save_state()
        return {
            "status":   "resumed",
            "mode":     self.state.mode,
            "coin":     self.state.config.get("coin"),
            "trades":   len(self.state.trade_log),
            "position": self.state.position,
        }

    def process_latest_candle(self) -> dict:
        if not self._running or self.bot is None:
            return {"error": "Engine nicht gestartet."}
        if self.state and self.state.stop_loss_hit:
            return {"error": "Stop-Loss ausgeloest."}

        # FIX 2: UTC + nur relevante Stunden laden statt 2 Tage
        hours = _INTERVAL_HOURS.get(self.config.interval, 3)
        df, meta, err = fetch_klines_df(
            self.config.coin, self.config.interval,
            _now_utc() - timedelta(hours=hours),
            _now_utc()
        )
        if err or df is None or df.empty:
            return {"error": f"API-Fehler: {err}"}

        # Vorletzte Kerze = letzte abgeschlossene Kerze
        candle        = df.iloc[-2]
        trades_before = len(self.bot.trade_log)
        self.bot.process_candle(candle)
        new_trades    = self.bot.trade_log[trades_before:]
        broker_orders = []
        ts = _now_utc().isoformat()  # Timestamp = jetzt, nicht historische Kerze

        for trade in new_trades:
            trade_type = trade["type"].upper()
            if "BUY" in trade_type:
                order = self.broker.execute_buy(
                    grid_price  = trade["price"],
                    amount_usdt = trade["amount"] * trade["price"],
                    timestamp   = ts,
                )
                broker_orders.append(order)
            elif "SELL" in trade_type:
                order = self.broker.execute_sell(
                    grid_price  = trade["price"],
                    amount_coin = trade["amount"],
                    timestamp   = ts,
                )
                broker_orders.append(order)

        current_price = float(candle["close"])
        portfolio_val = self.broker.get_portfolio_value(current_price)
        date_str      = _now_utc().strftime("%Y-%m-%d")

        if self.state:
            self.state.position               = dict(self.bot.position)
            self.state.trade_log              = self.bot.trade_log
            self.state.daily_values[date_str] = portfolio_val
            self.state.last_price             = current_price
            self.state.last_update            = _now_utc().isoformat()
            self.state.num_candles           += 1
            self.state.stop_loss_hit          = self.bot.stop_loss_triggered
            self.state.recentering_count      = self.bot.recentering_count
            self._save_state()

        roi = calculate_roi(self.config.total_investment, portfolio_val)
        dd  = calculate_drawdown(self.state.daily_values if self.state else {})
        return {
            "current_price":   current_price,
            "portfolio_value": portfolio_val,
            "roi_pct":         round(roi, 4),
            "max_dd_pct":      dd.max_drawdown_pct,
            "num_trades":      len(self.bot.trade_log),
            "new_trades":      new_trades,
            "broker_orders":   broker_orders,
            "position":        dict(self.bot.position),
            "stop_loss_hit":   self.bot.stop_loss_triggered,
            "timestamp":       _now_utc().isoformat(),
        }

    def stop(self) -> dict:
        self._running = False
        if self.state:
            self.state.is_running = False
            self._save_state()
        if self.bot is None:
            return {"status": "stopped"}
        final_price    = self.state.last_price if self.state else 0
        final_value    = self.broker.get_portfolio_value(final_price)
        roi            = calculate_roi(self.config.total_investment, final_value)
        sharpe         = calculate_sharpe_ratio(self.state.daily_values if self.state else {})
        dd             = calculate_drawdown(self.state.daily_values if self.state else {})
        broker_summary = self.broker.get_summary(final_price)
        print(f"Trading [{self.config.mode}] gestoppt. ROI: {roi:.2f}% | Trades: {len(self.bot.trade_log)}")
        return {
            "status":          "stopped",
            "mode":            self.config.mode,
            "final_value":     round(final_value, 2),
            "roi_pct":         round(roi, 4),
            "sharpe":          sharpe,
            "max_dd_pct":      dd.max_drawdown_pct,
            "num_trades":      len(self.bot.trade_log),
            "trade_log":       self.bot.trade_log,
            "recentering":     self.bot.recentering_count,
            "fees_paid":       broker_summary["total_fees"],
            "total_slippage":  broker_summary["total_slippage"],
            "filled_orders":   broker_summary["filled_orders"],
            "rejected_orders": broker_summary["rejected_orders"],
        }

    def get_live_metrics(self) -> dict:
        if self.bot is None or self.state is None:
            return {}
        final_price    = self.state.last_price
        portfolio_val  = self.broker.get_portfolio_value(final_price)
        roi            = calculate_roi(self.config.total_investment, portfolio_val)
        sharpe         = calculate_sharpe_ratio(self.state.daily_values)
        dd             = calculate_drawdown(self.state.daily_values)
        broker_summary = self.broker.get_summary(final_price)
        bh_roi = ((final_price - self.state.initial_price) / self.state.initial_price * 100
                  if self.state.initial_price > 0 else 0)
        return {
            "coin":            self.config.coin,
            "mode":            self.config.mode,
            "current_price":   final_price,
            "portfolio_value": portfolio_val,
            "roi_pct":         round(roi, 4),
            "bh_roi_pct":      round(bh_roi, 4),
            "outperformance":  round(roi - bh_roi, 4),
            "sharpe":          sharpe,
            "max_dd_pct":      dd.max_drawdown_pct,
            "num_trades":      len(self.bot.trade_log),
            "position":        dict(self.bot.position),
            "is_running":      self._running,
            "last_update":     self.state.last_update,
            "num_candles":     self.state.num_candles,
            "recentering":     self.bot.recentering_count,
            "stop_loss_hit":   self.bot.stop_loss_triggered,
            "daily_values":    self.state.daily_values,
            "grid_lines":      self.bot.grid_lines,
            "trade_log":       self.bot.trade_log,
            "fees_paid":       broker_summary["total_fees"],
            "total_slippage":  broker_summary["total_slippage"],
            "rejected_orders": broker_summary["rejected_orders"],
        }

    def _save_state(self) -> None:
        if self.state is None:
            return
        try:
            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(STATE_FILE, "w") as f:
                json.dump(asdict(self.state), f, indent=2, default=str)
        except Exception as e:
            print(f"State-Fehler: {e}")

    def _load_state(self) -> bool:
        try:
            with open(STATE_FILE, "r") as f:
                data = json.load(f)
            self.state = TradingState(**data)

            cfg        = self.state.config
            last_price = self.state.last_price or self.state.initial_price

            # GridBot erstellen – initialisiert intern Position + coin_inventory
            self.bot = GridBot(
                total_investment   = cfg.get("total_investment", 10000),
                lower_price        = cfg.get("lower_price", 0),
                upper_price        = cfg.get("upper_price", 0),
                num_grids          = cfg.get("num_grids", DEFAULT_NUM_GRIDS),
                grid_mode          = cfg.get("grid_mode", DEFAULT_GRID_MODE),
                fee_rate           = cfg.get("fee_rate", DEFAULT_FEE_RATE),
                initial_price      = last_price,
                reserve_pct        = cfg.get("reserve_pct", DEFAULT_RESERVE_PCT),
                stop_loss_pct      = cfg.get("stop_loss_pct"),
                enable_recentering = cfg.get("enable_recentering", False),
            )

            # Gespeicherten State wiederherstellen (überschreibt GridBot-Init)
            self.bot.trade_log = self.state.trade_log or []
            self.bot.position  = self.state.position  or {"usdt": 0.0, "coin": 0.0}

            # coin_inventory aus trade_log rekonstruieren (FIFO)
            self.bot.coin_inventory = []
            for trade in self.bot.trade_log:
                trade_type = str(trade.get("type", "")).upper()
                amount     = float(trade.get("amount", 0))
                price      = float(trade.get("price", last_price))

                if "BUY" in trade_type:
                    self.bot.coin_inventory.append(
                        (amount, price, pd.Timestamp.now())
                    )
                elif "SELL" in trade_type:
                    # FIFO: älteste Käufe zuerst abbauen
                    remaining = amount
                    while remaining > 0 and self.bot.coin_inventory:
                        amt, bp, ts = self.bot.coin_inventory[0]
                        if amt <= remaining:
                            remaining -= amt
                            self.bot.coin_inventory.pop(0)
                        else:
                            self.bot.coin_inventory[0] = (amt - remaining, bp, ts)
                            remaining = 0

            return True
        except Exception as e:
            print(f"State laden fehlgeschlagen: {e}")
            return False


def load_existing_state() -> Optional[dict]:
    if not STATE_FILE.exists():
        return None
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return None


def clear_state() -> None:
    if STATE_FILE.exists():
        STATE_FILE.unlink()
        print("Trading: State geloescht.")