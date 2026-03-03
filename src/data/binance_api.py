"""
src/data/binance_api.py
=======================
Datenabruf von der Binance REST API (public endpoints).

Funktionen:
    - fetch_klines()    : OHLCV-Kerzen mit automatischer Pagination
    - get_symbol()      : Symbol bereinigen (BTC -> BTCUSDT)
    - validate_symbol() : Pruefen ob Symbol auf Binance existiert

Kein API-Key erforderlich fuer Marktdaten (public endpoints).

Autor: Enes Eryilmaz
Projekt: Grid-Trading-Framework (Bachelorarbeit OST)
"""

import requests
import pandas as pd
import time
from datetime import datetime, date, timezone
from typing import Optional

from config.settings import (
    BINANCE_BASE_URL,
    BINANCE_KLINES_ENDPOINT,
    BINANCE_EXCHANGE_INFO,
    BINANCE_INTERVAL_MAP,
    BINANCE_REQUEST_TIMEOUT,
    BINANCE_MAX_LIMIT,
)


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def get_symbol(coin: str) -> str:
    """
    Bereinigt ein Coin-Symbol zu einem gueltigen Binance Spot-Symbol.
    Beispiele: "BTC" -> "BTCUSDT", "btc" -> "BTCUSDT", "BTCUSDT" -> "BTCUSDT"
    """
    symbol = coin.upper().strip()
    if not symbol.endswith("USDT"):
        symbol = f"{symbol}USDT"
    return symbol


def _to_utc_ms(dt) -> int:
    """Konvertiert date/datetime -> Unix-Timestamp in Millisekunden (UTC)."""
    if isinstance(dt, date) and not isinstance(dt, datetime):
        dt = datetime.combine(dt, datetime.min.time())
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return int(dt.timestamp() * 1000)


def _parse_kline_row(row: list) -> Optional[dict]:
    """
    Parst eine Binance Kline-Zeile in ein Dictionary.
    Binance-Format: [open_time, open, high, low, close, volume,
                     close_time, quote_volume, ...]
    """
    try:
        return {
            "timestamp":    datetime.fromtimestamp(int(row[0]) / 1000,
                                tz=timezone.utc).replace(tzinfo=None),
            "open":         float(row[1]),
            "high":         float(row[2]),
            "low":          float(row[3]),
            "close":        float(row[4]),
            "volume":       float(row[5]),
            "quote_volume": float(row[7]),
        }
    except (IndexError, ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Hauptfunktion: Kerzen abrufen mit Pagination
# ---------------------------------------------------------------------------

def fetch_klines(coin, interval, start_date, end_date, max_bars=None):
    """
    Ruft OHLCV-Kerzen von der Binance REST API ab.

    Verwendet automatische Pagination: Dadurch koennen beliebig viele
    Kerzen abgerufen werden (nicht auf 1000 limitiert wie im Prototyp).

    Args:
        coin       : Coin-Symbol (z.B. "BTC", "ETH", "BTCUSDT")
        interval   : Kerzen-Intervall ("1m","5m","15m","1h","4h","1d")
        start_date : Startdatum
        end_date   : Enddatum
        max_bars   : Max. Anzahl Kerzen (None = unbegrenzt)

    Returns:
        Tuple (symbol, df, error)
            symbol : verwendetes Symbol oder None
            df     : DataFrame [timestamp, open, high, low, close,
                                volume, quote_volume] oder None
            error  : Fehlermeldung oder None bei Erfolg
    """
    binance_interval = BINANCE_INTERVAL_MAP.get(interval)
    if not binance_interval:
        return None, None, (
            f"Ungueltiges Intervall: '{interval}'. "
            f"Erlaubt: {list(BINANCE_INTERVAL_MAP.keys())}"
        )

    try:
        start_ms = _to_utc_ms(start_date)
        end_ms   = _to_utc_ms(end_date)
        now_ms   = _to_utc_ms(datetime.now(tz=timezone.utc))
        end_ms   = min(end_ms, now_ms)
        if start_ms >= end_ms:
            return None, None, "Startdatum muss vor dem Enddatum liegen."
    except Exception as e:
        return None, None, f"Fehler bei Datumskonvertierung: {e}"

    symbol = get_symbol(coin)
    url    = f"{BINANCE_BASE_URL}{BINANCE_KLINES_ENDPOINT}"
    all_records = []
    current_start_ms = start_ms

    while current_start_ms < end_ms:
        if max_bars is not None and len(all_records) >= max_bars:
            break

        params = {
            "symbol":    symbol,
            "interval":  binance_interval,
            "startTime": current_start_ms,
            "endTime":   end_ms,
            "limit":     BINANCE_MAX_LIMIT,
        }

        try:
            response = requests.get(
                url, params=params,
                timeout=BINANCE_REQUEST_TIMEOUT,
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()
            raw_data = response.json()
        except requests.exceptions.Timeout:
            return symbol, None, "API-Timeout: Binance antwortet nicht."
        except requests.exceptions.ConnectionError:
            return symbol, None, "Verbindungsfehler: Keine Internetverbindung."
        except requests.exceptions.HTTPError as e:
            return symbol, None, f"HTTP-Fehler: {e}"
        except Exception as e:
            return symbol, None, f"Unbekannter API-Fehler: {e}"

        if isinstance(raw_data, dict) and "code" in raw_data:
            msg  = raw_data.get("msg", "Unbekannter Fehler")
            code = raw_data.get("code", "?")
            return symbol, None, f"Binance API-Fehler {code}: {msg}"

        if not raw_data:
            break

        batch = [_parse_kline_row(row) for row in raw_data]
        batch = [r for r in batch if r is not None]
        if not batch:
            break

        all_records.extend(batch)

        last_ts = int(raw_data[-1][0])
        if last_ts <= current_start_ms:
            break
        current_start_ms = last_ts + 1

        if len(raw_data) == BINANCE_MAX_LIMIT:
            time.sleep(0.1)

    if not all_records:
        return symbol, None, f"Keine Daten fuer {symbol} im Zeitraum."

    df = pd.DataFrame(all_records)
    df = df.sort_values("timestamp").reset_index(drop=True)

    for col in ["open","high","low","close","volume","quote_volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["timestamp","open","high","low","close"])
    df = df.reset_index(drop=True)

    if max_bars is not None:
        df = df.head(max_bars)

    if df.empty:
        return symbol, None, "DataFrame nach Bereinigung leer."

    return symbol, df, None


# ---------------------------------------------------------------------------
# Symbol-Validierung
# ---------------------------------------------------------------------------

def validate_symbol(coin: str) -> tuple:
    """
    Prueft ob ein Symbol auf Binance Spot handelbar ist.

    Returns:
        Tuple (is_valid: bool, message: str)
    """
    symbol = get_symbol(coin)
    url    = f"{BINANCE_BASE_URL}{BINANCE_EXCHANGE_INFO}"

    try:
        response = requests.get(url, params={"symbol": symbol},
                                timeout=BINANCE_REQUEST_TIMEOUT)
        data = response.json()

        if "code" in data:
            return False, f"Symbol '{symbol}' nicht auf Binance gefunden."

        status = data.get("status", "")
        if status != "TRADING":
            return False, f"Symbol '{symbol}' nicht aktiv (Status: {status})."

        return True, symbol

    except Exception as e:
        return False, f"Validierungsfehler fuer '{symbol}': {e}"


# ---------------------------------------------------------------------------
# Komfort-Wrapper (rueckwaertskompatibel)
# ---------------------------------------------------------------------------

def fetch_klines_df(coin, interval, start_date, end_date, max_bars=1000):
    """
    Wrapper um fetch_klines().
    Gibt (df, meta, error_str) zurueck.
    """
    symbol, df, err = fetch_klines(coin, interval, start_date, end_date, max_bars)

    if df is None or df.empty:
        return None, None, err or "Leeres DataFrame."

    meta = {
        "symbol": symbol,
        "start":  df["timestamp"].min(),
        "end":    df["timestamp"].max(),
        "rows":   len(df),
    }
    return df, meta, ""