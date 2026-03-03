"""
src/data/cache_manager.py
=========================
Zentraler Cache-Manager fuer OHLCV-Marktdaten.

Speichert heruntergeladene Kerzen lokal als CSV und laedt sie
bei Bedarf wieder. Vermeidet unnoetige API-Aufrufe.

Dateinamenschema: {SYMBOL}_{interval}_{days}d.csv
Beispiel:         BTCUSDT_1h_30d.csv

Autor: Enes Eryilmaz
Projekt: Grid-Trading-Framework (Bachelorarbeit OST)
"""

import os
import json
import pandas as pd
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional

from config.settings import (
    CACHE_DIR,
    CACHE_PRICE_SUBDIR,
    CACHE_MAX_AGE_HOURS,
    CACHE_MIN_ROWS,
    CACHE_TOP100_FILE,
    CACHE_UNAVAILABLE_FILE,
    CACHE_LAST_SCAN_FILE,
)
from src.data.binance_api import fetch_klines, get_symbol


# ---------------------------------------------------------------------------
# Pfad-Hilfsfunktionen
# ---------------------------------------------------------------------------

def _get_price_cache_dir() -> Path:
    """Gibt den Pfad zum Preis-Cache-Verzeichnis zurueck und erstellt es."""
    path = CACHE_DIR / CACHE_PRICE_SUBDIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def _get_cache_filepath(symbol: str, interval: str, days: int) -> Path:
    """
    Gibt den vollstaendigen Pfad einer Cache-Datei zurueck.

    Dateinamenschema: {SYMBOL}_{interval}_{days}d.csv
    Beispiel:         BTCUSDT_1h_30d.csv

    Args:
        symbol  : Normalisiertes Symbol (z.B. "BTCUSDT")
        interval: Kerzen-Intervall (z.B. "1h")
        days    : Anzahl Tage im Zeitraum

    Returns:
        Vollstaendiger Pfad zur Cache-Datei
    """
    filename = f"{symbol}_{interval}_{days}d.csv"
    return _get_price_cache_dir() / filename


def _is_cache_valid(filepath: Path) -> bool:
    """
    Prueft ob eine Cache-Datei existiert und noch aktuell ist.

    Eine Cache-Datei gilt als veraltet, wenn sie aelter als
    CACHE_MAX_AGE_HOURS Stunden ist.

    Args:
        filepath: Pfad zur Cache-Datei

    Returns:
        True wenn Cache gueltig, False wenn veraltet oder nicht vorhanden
    """
    if not filepath.exists():
        return False

    age_seconds = datetime.now().timestamp() - filepath.stat().st_mtime
    age_hours   = age_seconds / 3600

    return age_hours < CACHE_MAX_AGE_HOURS


# ---------------------------------------------------------------------------
# Preis-Cache: Lesen & Schreiben
# ---------------------------------------------------------------------------

def _load_from_cache(filepath: Path) -> Optional[pd.DataFrame]:
    """
    Laedt einen DataFrame aus einer CSV-Cache-Datei.

    Args:
        filepath: Pfad zur Cache-Datei

    Returns:
        DataFrame oder None bei Fehler
    """
    try:
        df = pd.read_csv(filepath, parse_dates=["timestamp"])
        if len(df) >= CACHE_MIN_ROWS:
            return df
        return None
    except Exception as e:
        print(f"Cache-Lesefehler ({filepath.name}): {e}")
        return None


def _save_to_cache(df: pd.DataFrame, filepath: Path) -> bool:
    """
    Speichert einen DataFrame als CSV-Cache-Datei.

    Args:
        df      : DataFrame mit OHLCV-Daten
        filepath: Ziel-Pfad

    Returns:
        True bei Erfolg, False bei Fehler
    """
    try:
        filepath.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(filepath, index=False)
        return True
    except Exception as e:
        print(f"Cache-Schreibfehler ({filepath.name}): {e}")
        return False


# ---------------------------------------------------------------------------
# Hauptfunktion: Preisdaten laden (Cache oder API)
# ---------------------------------------------------------------------------

def get_price_data(
    coin:     str,
    days:     int  = 30,
    interval: str  = "1h",
    force:    bool = False,
) -> tuple[pd.DataFrame, bool]:
    """
    Laedt OHLCV-Preisdaten – aus Cache oder frisch von Binance.

    Ablauf:
        1. Cache pruefen (existiert + aktuell + genuegend Zeilen)
        2. Falls Cache gueltig und force=False -> Cache zurueckgeben
        3. Sonst -> Binance API aufrufen und Ergebnis cachen

    Args:
        coin    : Coin-Symbol (z.B. "BTC", "BTCUSDT")
        days    : Anzahl Tage in die Vergangenheit
        interval: Kerzen-Intervall ("1m","5m","15m","1h","4h","1d")
        force   : True = Cache ignorieren, immer neu laden

    Returns:
        Tuple (df, from_cache):
            df         : DataFrame mit OHLCV-Daten (leer bei Fehler)
            from_cache : True wenn Daten aus Cache geladen wurden

    Beispiel:
        df, from_cache = get_price_data("BTC", days=30, interval="1h")
    """
    symbol   = get_symbol(coin)
    filepath = _get_cache_filepath(symbol, interval, days)

    # --- Cache verwenden falls gueltig ---
    if not force and _is_cache_valid(filepath):
        df = _load_from_cache(filepath)
        if df is not None:
            print(f"Cache: {filepath.name} ({len(df)} Kerzen)")
            return df, True

    # --- Frische Daten von Binance holen ---
    print(f"API: Lade {symbol} {interval} ({days} Tage) von Binance...")

    end_date   = datetime.utcnow()
    start_date = end_date - timedelta(days=days)

    symbol_out, df, err = fetch_klines(
        coin       = coin,
        interval   = interval,
        start_date = start_date,
        end_date   = end_date,
    )

    if err or df is None or df.empty:
        print(f"API-Fehler fuer {symbol}: {err}")
        return pd.DataFrame(), False

    # --- Nur speichern wenn genuegend Daten vorhanden ---
    if len(df) >= CACHE_MIN_ROWS:
        saved = _save_to_cache(df, filepath)
        if saved:
            print(f"Gespeichert: {filepath.name} ({len(df)} Kerzen)")
    else:
        print(f"Zu wenig Daten fuer {symbol} ({len(df)} Kerzen) – nicht gecacht.")

    return df, False


# ---------------------------------------------------------------------------
# Top-100 Cache
# ---------------------------------------------------------------------------

def load_top100_cache() -> list[str]:
    """
    Laedt die gecachte Top-100-Coin-Liste.

    Returns:
        Liste der Coin-Symbole oder leere Liste
    """
    try:
        if CACHE_TOP100_FILE.exists():
            df = pd.read_csv(CACHE_TOP100_FILE)
            return df["symbol"].tolist()
    except Exception as e:
        print(f"Top100-Cache Lesefehler: {e}")
    return []


def save_top100_cache(symbols: list[str]) -> bool:
    """
    Speichert die Top-100-Coin-Liste als CSV.

    Args:
        symbols: Liste der Coin-Symbole

    Returns:
        True bei Erfolg
    """
    try:
        CACHE_TOP100_FILE.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame({"symbol": symbols}).to_csv(CACHE_TOP100_FILE, index=False)
        return True
    except Exception as e:
        print(f"Top100-Cache Schreibfehler: {e}")
        return False


# ---------------------------------------------------------------------------
# Unavailable Coins Cache
# ---------------------------------------------------------------------------

def load_unavailable_coins() -> set[str]:
    """
    Laedt die Blacklist nicht verfuegbarer Coins.

    Returns:
        Set mit Coin-Symbolen
    """
    try:
        if CACHE_UNAVAILABLE_FILE.exists():
            with open(CACHE_UNAVAILABLE_FILE, "r") as f:
                return set(json.load(f))
    except Exception as e:
        print(f"Unavailable-Cache Lesefehler: {e}")
    return set()


def save_unavailable_coins(coin_set: set[str]) -> bool:
    """
    Speichert die Blacklist nicht verfuegbarer Coins.

    Args:
        coin_set: Set mit Coin-Symbolen

    Returns:
        True bei Erfolg
    """
    try:
        CACHE_UNAVAILABLE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(CACHE_UNAVAILABLE_FILE, "w") as f:
            json.dump(sorted(list(coin_set)), f)
        return True
    except Exception as e:
        print(f"Unavailable-Cache Schreibfehler: {e}")
        return False


# ---------------------------------------------------------------------------
# Scan-Zeitstempel
# ---------------------------------------------------------------------------

def get_last_scan_time() -> datetime:
    """
    Laedt den Zeitstempel des letzten Coin-Scans.

    Returns:
        datetime des letzten Scans oder datetime.min wenn kein Scan
    """
    try:
        if CACHE_LAST_SCAN_FILE.exists():
            with open(CACHE_LAST_SCAN_FILE, "r") as f:
                return datetime.fromisoformat(f.read().strip())
    except Exception:
        pass
    return datetime.min


def save_last_scan_time() -> None:
    """Speichert den aktuellen Zeitpunkt als letzten Scan-Zeitstempel."""
    try:
        CACHE_LAST_SCAN_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(CACHE_LAST_SCAN_FILE, "w") as f:
            f.write(datetime.now().isoformat())
    except Exception as e:
        print(f"Scan-Zeitstempel Schreibfehler: {e}")