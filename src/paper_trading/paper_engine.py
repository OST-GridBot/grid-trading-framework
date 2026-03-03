# src/paper_trading/engine.py
# Paper-Trading Engine - Bachelorarbeit Ziel 10
# Autor: Enes Eryilmaz

import json, pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field, asdict

from config.settings import (
    DEFAULT_FEE_RATE, DEFAULT_GRID_MODE, DEFAULT_NUM_GRIDS,
    DEFAULT_RESERVE_PCT, PAPER_TRADING_UPDATE_INTERVAL, CACHE_DIR,
)
from src.data.binance_api import fetch_klines_df
from src.strategy.grid_bot import GridBot
from src.strategy.risk import calculate_drawdown
from src.backtesting.metrics import calculate_roi, calculate_sharpe_ratio

STATE_FILE = Path(CACHE_DIR) / "paper_trading_state.json"

@dataclass
class PaperTradingConfig:
    coin: str
    lower_price: float
    upper_price: float
    total_investment: float = 10_000.0
    num_grids: int = DEFAULT_NUM_GRIDS
    grid_mode: str = DEFAULT_GRID_MODE
    fee_rate: float = DEFAULT_FEE_RATE
    reserve_pct: float = DEFAULT_RESERVE_PCT
    stop_loss_pct: Optional[float] = None
    enable_recentering: bool = False
    interval: str = "1h"
    update_interval_s: int = PAPER_TRADING_UPDATE_INTERVAL

@dataclass
class PaperTradingState:
    config: dict
    position: dict = field(default_factory=lambda: {"usdt": 0.0, "coin": 0.0})
    trade_log: list = field(default_factory=list)
    daily_values: dict = field(default_factory=dict)
    initial_price: float = 0.0
    last_price: float = 0.0
    start_time: str = ""
    last_update: str = ""
    num_candles: int = 0
    is_running: bool = False
    stop_loss_hit: bool = False
    recentering_count: int = 0

class PaperTradingEngine:
    def __init__(self, config: PaperTradingConfig):
        self.config = config
        self.bot: Optional[GridBot] = None
        self.state: Optional[PaperTradingState] = None
        self._running = False

    def start(self, resume: bool = False) -> dict:
        if resume and STATE_FILE.exists():
            return self._resume_session()
        return self._start_new_session()

    def _start_new_session(self) -> dict:
        from datetime import timedelta
        start = datetime.now() - timedelta(days=3)
        end = datetime.now()
        df, meta, err = fetch_klines_df(self.config.coin, self.config.interval, start_date=start, end_date=end)
        if err or df is None or df.empty:
            return {"error": f"Preisdaten nicht verfuegbar: {err}"}
        initial_price = float(df["close"].iloc[-1])
        self.bot = GridBot(
            total_investment=self.config.total_investment,
            lower_price=self.config.lower_price,
            upper_price=self.config.upper_price,
            num_grids=self.config.num_grids,
            grid_mode=self.config.grid_mode,
            fee_rate=self.config.fee_rate,
            initial_price=initial_price,
            reserve_pct=self.config.reserve_pct,
            stop_loss_pct=self.config.stop_loss_pct,
            enable_recentering=self.config.enable_recentering,
        )
        self.state = PaperTradingState(
            config=asdict(self.config), position=dict(self.bot.position),
            initial_price=initial_price, last_price=initial_price,
            start_time=datetime.now().isoformat(),
            last_update=datetime.now().isoformat(), is_running=True,
        )
        self._save_state()
        self._running = True
        print(f"Paper-Trading gestartet: {self.config.coin} @ {initial_price}")
        return {"status": "started", "coin": self.config.coin,
                "initial_price": initial_price, "grid_lines": self.bot.grid_lines,
                "position": dict(self.bot.position)}

    def _resume_session(self) -> dict:
        if not self._load_state():
            return self._start_new_session()
        self._running = True
        self.state.is_running = True
        self._save_state()
        return {"status": "resumed", "coin": self.state.config.get("coin"),
                "trades": len(self.state.trade_log), "position": self.state.position}

    def process_latest_candle(self) -> dict:
        if not self._running or self.bot is None:
            return {"error": "Engine nicht gestartet."}
        if self.state and self.state.stop_loss_hit:
            return {"error": "Stop-Loss ausgeloest."}
        start = datetime.now() - timedelta(days=2)
        end = datetime.now()
        df, meta, err = fetch_klines_df(self.config.coin, self.config.interval, start_date=start, end_date=end)
        if err or df is None or df.empty:
            return {"error": f"API-Fehler: {err}"}
        candle = df.iloc[-2]
        trades_before = len(self.bot.trade_log)
        self.bot.process_candle(candle)
        new_trades = self.bot.trade_log[trades_before:]
        current_price = float(candle["close"])
        portfolio_val = self.bot.position["usdt"] + self.bot.position["coin"] * current_price
        date_str = pd.to_datetime(candle["timestamp"]).strftime("%Y-%m-%d")
        if self.state:
            self.state.position = dict(self.bot.position)
            self.state.trade_log = self.bot.trade_log
            self.state.daily_values[date_str] = portfolio_val
            self.state.last_price = current_price
            self.state.last_update = datetime.now().isoformat()
            self.state.num_candles += 1
            self.state.stop_loss_hit = self.bot.stop_loss_triggered
            self.state.recentering_count = self.bot.recentering_count
            self._save_state()
        roi = calculate_roi(self.config.total_investment, portfolio_val)
        dd = calculate_drawdown(self.state.daily_values if self.state else {})
        return {"current_price": current_price, "portfolio_value": round(portfolio_val, 2),
                "roi_pct": round(roi, 4), "max_dd_pct": dd.max_drawdown_pct,
                "num_trades": len(self.bot.trade_log), "new_trades": new_trades,
                "position": dict(self.bot.position), "stop_loss_hit": self.bot.stop_loss_triggered,
                "timestamp": pd.to_datetime(candle["timestamp"]).isoformat()}

    def stop(self) -> dict:
        self._running = False
        if self.state:
            self.state.is_running = False
            self._save_state()
        if self.bot is None:
            return {"status": "stopped"}
        final_price = self.state.last_price if self.state else 0
        final_value = self.bot.position["usdt"] + self.bot.position["coin"] * final_price
        roi = calculate_roi(self.config.total_investment, final_value)
        sharpe = calculate_sharpe_ratio(self.state.daily_values if self.state else {})
        dd = calculate_drawdown(self.state.daily_values if self.state else {})
        print(f"Paper-Trading gestoppt. ROI: {roi:.2f}% | Trades: {len(self.bot.trade_log)}")
        return {"status": "stopped", "final_value": round(final_value, 2),
                "roi_pct": round(roi, 4), "sharpe": sharpe,
                "max_dd_pct": dd.max_drawdown_pct, "num_trades": len(self.bot.trade_log),
                "trade_log": self.bot.trade_log, "recentering": self.bot.recentering_count}

    def get_live_metrics(self) -> dict:
        if self.bot is None or self.state is None:
            return {}
        final_price = self.state.last_price
        portfolio_val = self.bot.position["usdt"] + self.bot.position["coin"] * final_price
        roi = calculate_roi(self.config.total_investment, portfolio_val)
        sharpe = calculate_sharpe_ratio(self.state.daily_values)
        dd = calculate_drawdown(self.state.daily_values)
        bh_roi = ((final_price - self.state.initial_price) / self.state.initial_price * 100
                  if self.state.initial_price > 0 else 0)
        return {
            "coin": self.config.coin, "current_price": final_price,
            "portfolio_value": round(portfolio_val, 2), "roi_pct": round(roi, 4),
            "bh_roi_pct": round(bh_roi, 4), "outperformance": round(roi - bh_roi, 4),
            "sharpe": sharpe, "max_dd_pct": dd.max_drawdown_pct,
            "num_trades": len(self.bot.trade_log), "position": dict(self.bot.position),
            "is_running": self._running, "last_update": self.state.last_update,
            "num_candles": self.state.num_candles, "recentering": self.bot.recentering_count,
            "stop_loss_hit": self.bot.stop_loss_triggered,
            "daily_values": self.state.daily_values,
            "grid_lines": self.bot.grid_lines, "trade_log": self.bot.trade_log,
        }

    def _save_state(self) -> None:
        if self.state is None: return
        try:
            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(STATE_FILE, "w") as f:
                json.dump(asdict(self.state), f, indent=2, default=str)
        except Exception as e:
            print(f"Paper-Trading State-Fehler: {e}")

    def _load_state(self) -> bool:
        try:
            with open(STATE_FILE, "r") as f:
                data = json.load(f)
            self.state = PaperTradingState(**data)
            return True
        except Exception as e:
            print(f"State laden fehlgeschlagen: {e}")
            return False

def load_existing_state() -> Optional[dict]:
    if not STATE_FILE.exists(): return None
    try:
        with open(STATE_FILE) as f: return json.load(f)
    except Exception: return None

def clear_state() -> None:
    if STATE_FILE.exists():
        STATE_FILE.unlink()
        print("Paper-Trading: State geloescht.")