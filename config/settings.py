"""
config/settings.py
Zentrale Konfigurationsdatei fuer das Grid-Trading-Framework.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Projektpfade
ROOT_DIR  = Path(__file__).resolve().parent.parent
DATA_DIR  = ROOT_DIR / "data"
CACHE_DIR = DATA_DIR / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# API-Keys
BINANCE_API_KEY    = os.getenv("BINANCE_API_KEY", "")
BINANCE_SECRET_KEY = os.getenv("BINANCE_SECRET_KEY", "")
CMC_API_KEY        = os.getenv("CMC_API_KEY", "")

# Binance API
BINANCE_BASE_URL        = "https://api.binance.com"
BINANCE_KLINES_ENDPOINT = "/api/v3/klines"
BINANCE_EXCHANGE_INFO   = "/api/v3/exchangeInfo"
BINANCE_TICKER_ENDPOINT = "/api/v3/ticker/24hr"
BINANCE_REQUEST_TIMEOUT = 15
BINANCE_MAX_LIMIT       = 1000

BINANCE_INTERVAL_MAP = {
    "1m": "1m", "5m": "5m", "15m": "15m",
    "1h": "1h", "4h": "4h", "1d":  "1d",
}
SUPPORTED_INTERVALS = list(BINANCE_INTERVAL_MAP.keys())
DEFAULT_INTERVAL    = "1h"

# CoinMarketCap API
CMC_BASE_URL          = "https://pro-api.coinmarketcap.com"
CMC_LISTINGS_ENDPOINT = "/v1/cryptocurrency/listings/latest"
CMC_REQUEST_TIMEOUT   = 15
CMC_TOP_N             = 100

STABLECOINS = {
    "USDT", "USDC", "DAI", "TUSD", "FDUSD",
    "BUSD", "USDP", "GUSD", "EURT", "XAUT",
    "USDe", "PYUSD", "USD1",
}

# Caching
CACHE_PRICE_SUBDIR     = "prices"
CACHE_TOP100_FILE      = DATA_DIR / "top100_cached.csv"
CACHE_UNAVAILABLE_FILE = DATA_DIR / "unavailable_coins.json"
CACHE_LAST_SCAN_FILE   = DATA_DIR / "last_scan.txt"
CACHE_MAX_AGE_HOURS    = 6
CACHE_MIN_ROWS         = 50

# Grid-Bot Defaults
DEFAULT_TOTAL_INVESTMENT = 10_000.0
DEFAULT_NUM_GRIDS        = 20
DEFAULT_GRID_MODE        = "arithmetic"
DEFAULT_FEE_RATE         = 0.001
DEFAULT_RESERVE_PCT      = 0.03
DEFAULT_GRID_RANGE_PCT   = 20.0
MIN_NUM_GRIDS            = 2
MAX_NUM_GRIDS            = 500

GRID_MODES = {
    "Arithmetisch (gleichmaessige Abstaende)": "arithmetic",
    "Geometrisch (prozentuale Abstaende)":     "geometric",
}

# Backtesting
DEFAULT_BACKTEST_DAYS       = 30
DEFAULT_MAX_BARS            = 1000
OPTIMIZER_DEFAULT_MAX_GRIDS = 50
OPTIMIZER_DEFAULT_STEP_SIZE = 2
OPTIMIZER_MIN_START_GRIDS   = 3

# Coin-Scanner
ADX14_SIDEWAYS_MAX    = 20
ADX14_WARNING_MAX     = 25
ADX30_SIDEWAYS_MAX    = 15
ADX30_WARNING_MAX     = 25
ATR_PCT_MIN           = 0.5
ATR_PCT_MAX           = 4.0
MIN_VOLUME_USDT       = 1_000_000
SCANNER_LOOKBACK_DAYS = 14
SCANNER_INTERVAL      = "1h"

# Paper-Trading
PAPER_TRADING_DEFAULT_CAPITAL = 10_000.0
PAPER_TRADING_UPDATE_INTERVAL = 60

# UI / Streamlit
APP_TITLE          = "Grid-Trading-Framework"
APP_LAYOUT         = "wide"
DEFAULT_CHART_TYPE = "Candlestick"
COLOR_GREEN        = "#00C853"
COLOR_ORANGE       = "#FF6F00"
COLOR_RED          = "#D50000"
COLOR_WHITE        = "#FFFFFF"
COLOR_BLUE         = "#0B5E82"