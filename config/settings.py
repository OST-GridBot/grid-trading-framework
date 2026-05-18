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
# Live-Trading (Phase Live-1): recvWindow fuer signed Requests in ms.
# 5000ms ist Binance-Default und reicht bei normalem Netzwerk-Latenz.
BINANCE_RECV_WINDOW     = 5000

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
DEFAULT_RESERVE_PCT      = 0.0
DEFAULT_GRID_RANGE_PCT   = 20.0
MIN_NUM_GRIDS            = 2
MAX_NUM_GRIDS            = 500
# Binance Spot: NOTIONAL-Filter pro Order. Typisch 5 USDT fuer
# USDT-Paare. Wird in validate_min_investment verwendet (Z.X2).
DEFAULT_MIN_NOTIONAL     = 5.0

# Sicherheitspuffer auf MIN_NOTIONAL: bei exakt 5 USDT pro Order wuerde
# bei kleinster Slippage oder Filter-Variation die Order abgelehnt.
# 5% Puffer ist konservativ genug ohne das Mindest-Investment unnoetig
# hoch zu treiben. Wird in validate_min_investment auf Binance-MIN_NOTIONAL
# multipliziert (z.B. 5.00 → 5.25 USDT). Gilt fuer alle Modi (BT/PT/LT).
MIN_NOTIONAL_BUFFER_PCT  = 0.05

# DD-Drosselung: Hysterese-Puffer (Variante B, 20% relativ).
# Faktor verschaerft sich sofort bei Erreichen der Schwelle, lockert
# sich erst wenn DD unter Schwelle * DD_HYSTERESIS_FACTOR faellt.
# Verhindert Pingpong bei DD-Oszillation um eine Schwelle.
# Nicht UI-konfigurierbar (Komplexitaet niedrig halten).
DD_HYSTERESIS_FACTOR     = 0.8

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

# Paper-Trading / Live-Trading
MAX_BOTS_PER_MODE           = 10
MAX_BACKTESTS               = 500   # Maximale Anzahl gespeicherter Backtests

# Live-Worker (Phase Live-3): Polling-Intervall in Sekunden.
# 30s ist unter Binance Rate-Limit-Druck unkritisch und reagiert zugleich
# zeitnah auf Markt-Bewegungen. Wird vom live_worker.py-Script gelesen.
WORKER_INTERVAL_SECONDS     = 30

# Live-Resync (Phase Live-4.3, L-8): Cooldown zwischen Resync-Laeufen.
# Verhindert dass der Worker bei jedem Bot-Tick (alle 30s) einen vollen
# Resync mit 2 zusaetzlichen API-Calls (openOrders + account) ausloest.
# 600s = 10 Min ist gross genug um Rate-Limit zu schonen und klein genug
# um nach Crash-Recovery zeitnah zu syncen.
RESYNC_MIN_INTERVAL_SECONDS = 600

# Coin-Balance-Diskrepanz-Schwelle in Prozent. Wenn das lokale Inventar
# um mehr als diesen Anteil von der Binance-Balance (free+locked)
# abweicht, wird ein Resync-Warning gesetzt. 5% ist tolerant genug fuer
# Rundungs- und Fee-Effekte, aber empfindlich genug fuer echte Drifts.
COIN_BALANCE_DIFF_PCT_WARNING = 5.0

# UI-Farben
COLOR_GREEN        = "#00C853"
COLOR_ORANGE       = "#FF6F00"
COLOR_RED          = "#D50000"