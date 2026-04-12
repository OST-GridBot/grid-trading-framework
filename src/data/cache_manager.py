"""
src/data/cache_manager.py
=========================
Zentraler Cache-Manager fuer OHLCV-Marktdaten.

Speichert heruntergeladene Kerzen lokal als CSV und laedt sie
bei Bedarf wieder. Vermeidet unnoetige API-Aufrufe.

Dateinamenschema:
    Mit Datum : {SYMBOL}_{interval}_{start}_{end}.csv  -> BTCUSDT_1h_20240101_20240131.csv
    Ohne Datum: {SYMBOL}_{interval}_{days}d.csv        -> BTCUSDT_1h_30d.csv

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
    path = CACHE_DIR / CACHE_PRICE_SUBDIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def _get_cache_filepath(
    symbol:     str,
    interval:   str,
    days:       int,
    start_date: Optional[date] = None,
    end_date:   Optional[date] = None,
) -> Path:
    """
    Gibt den Pfad zur Cache-Datei zurueck.

    Mit Datum : BTCUSDT_1h_20240101_20240131.csv
    Ohne Datum: BTCUSDT_1h_30d.csv
    """
    if start_date and end_date:
        s = start_date.strftime("%Y%m%d") if hasattr(start_date, "strftime") else str(start_date).replace("-", "")
        e = end_date.strftime("%Y%m%d")   if hasattr(end_date,   "strftime") else str(end_date).replace("-", "")
        filename = f"{symbol}_{interval}_{s}_{e}.csv"
    else:
        filename = f"{symbol}_{interval}_{days}d.csv"
    return _get_price_cache_dir() / filename


def _is_cache_valid(filepath: Path) -> bool:
    """Prueft ob Cache-Datei existiert und noch aktuell ist."""
    if not filepath.exists():
        return False
    age_hours = (datetime.now().timestamp() - filepath.stat().st_mtime) / 3600
    return age_hours < CACHE_MAX_AGE_HOURS


def _load_from_cache(filepath: Path) -> Optional[pd.DataFrame]:
    """Laedt DataFrame aus CSV-Cache."""
    try:
        df = pd.read_csv(filepath, parse_dates=["timestamp"])
        return df if len(df) >= CACHE_MIN_ROWS else None
    except Exception as e:
        print(f"Cache-Lesefehler ({filepath.name}): {e}")
        return None


def _save_to_cache(df: pd.DataFrame, filepath: Path) -> bool:
    """Speichert DataFrame als CSV-Cache."""
    try:
        filepath.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(filepath, index=False)
        return True
    except Exception as e:
        print(f"Cache-Schreibfehler ({filepath.name}): {e}")
        return False


# ---------------------------------------------------------------------------
# Hauptfunktion: Preisdaten laden
# ---------------------------------------------------------------------------

def get_price_data(
    coin:       str,
    days:       int            = 30,
    interval:   str            = "1h",
    force:      bool           = False,
    start_date: Optional[date] = None,
    end_date:   Optional[date] = None,
) -> tuple[pd.DataFrame, bool]:
    """
    Laedt OHLCV-Preisdaten – aus Cache oder frisch von Binance.

    Args:
        coin       : Coin-Symbol (z.B. "BTC")
        days       : Tage zurueck (Fallback wenn kein start_date)
        interval   : Kerzen-Intervall
        force      : Cache ignorieren
        start_date : Startdatum (optional)
        end_date   : Enddatum (optional)

    Returns:
        (df, from_cache)
    """
    symbol = get_symbol(coin)

    # 1. Datum berechnen
    if end_date is None:
        end_dt = datetime.utcnow()
    else:
        end_dt = datetime.combine(end_date, datetime.max.time())

    if start_date is None:
        start_dt = end_dt - timedelta(days=days)
    else:
        start_dt = datetime.combine(start_date, datetime.min.time())

    days = max(1, (end_dt - start_dt).days)

    # 2. Cache-Pfad mit korrektem Datum
    filepath = _get_cache_filepath(symbol, interval, days, start_date, end_date)

    # 3. Cache pruefen
    # Wenn Enddatum heute ist: Cache ignorieren (Daten könnten veraltet sein)
    from datetime import date as _date
    _end_is_today = (end_date is None) or (
        hasattr(end_date, "date") and end_date.date() >= _date.today()
    ) or (
        hasattr(end_date, "year") and end_date >= _date.today()
    )
    if not force and not _end_is_today and _is_cache_valid(filepath):
        # Historischer Zeitraum: Cache direkt verwenden
        df = _load_from_cache(filepath)
        if df is not None:
            print(f"Cache: {filepath.name} ({len(df)} Kerzen)")
            return df, True
    elif not force and _end_is_today and filepath.exists():
        # Enddatum heute: Append-Strategie — neue Kerzen an Cache anhängen
        df_cached = _load_from_cache(filepath)
        if df_cached is not None:
            last_cached_ts = pd.to_datetime(df_cached["timestamp"].iloc[-1])
            now_utc = datetime.utcnow()
            # Nur Append wenn letzte Kerze älter als 1 Intervall
            _interval_mins = {"1m":1,"5m":5,"15m":15,"1h":60,"4h":240,"1d":1440}.get(interval, 60)
            _age_mins = (now_utc - last_cached_ts.to_pydatetime()).total_seconds() / 60
            if _age_mins < _interval_mins:
                # Cache ist aktuell genug
                print(f"Cache (aktuell): {filepath.name} ({len(df_cached)} Kerzen)")
                return df_cached, True
            # Neue Kerzen ab letzter Kerze holen
            print(f"Cache-Append: lade neue Kerzen ab {last_cached_ts} (vor {_age_mins:.0f} min)...")
            _diff_mins = (now_utc - last_cached_ts.to_pydatetime()).total_seconds() / 60
            _max_bars  = min(max(int(_diff_mins / _interval_mins) + 10, 10), 5000)
            _start_ts  = last_cached_ts.to_pydatetime().replace(tzinfo=__import__("datetime").timezone.utc)
            _end_ts    = now_utc.replace(tzinfo=__import__("datetime").timezone.utc)
            from src.data.binance_api import fetch_klines_df as _fkdf
            df_new, _meta, _err_new = _fkdf(coin, interval, _start_ts, _end_ts, max_bars=_max_bars)
            if (not _err_new) and df_new is not None and hasattr(df_new, "empty") and not df_new.empty:
                df_merged = pd.concat([df_cached, df_new]).drop_duplicates(
                    subset="timestamp", keep="last"
                ).sort_values("timestamp").reset_index(drop=True)
                _save_to_cache(df_merged, filepath)
                print(f"Cache-Append OK: {len(df_cached)}+{len(df_new)}={len(df_merged)} Kerzen, last={df_merged['timestamp'].iloc[-1]}")
                return df_merged, True
            else:
                print(f"Cache-Append fehlgeschlagen (err={_err_new}), nutze alten Cache")
                return df_cached, True

    # 4. API aufrufen
    print(f"API: Lade {symbol} {interval} ({days} Tage) von Binance...")
    symbol_out, df, err = fetch_klines(
        coin       = coin,
        interval   = interval,
        start_date = start_dt,
        end_date   = end_dt,
    )

    if err or df is None or df.empty:
        print(f"API-Fehler fuer {symbol}: {err}")
        return pd.DataFrame(), False

    # 5. Cachen
    if len(df) >= CACHE_MIN_ROWS:
        saved = _save_to_cache(df, filepath)
        if saved:
            print(f"Gespeichert: {filepath.name} ({len(df)} Kerzen)")
    else:
        print(f"Zu wenig Daten ({len(df)} Kerzen) – nicht gecacht.")

    return df, False


# ---------------------------------------------------------------------------
# Top-100 Cache
# ---------------------------------------------------------------------------

def load_top100_cache() -> list[str]:
    try:
        if CACHE_TOP100_FILE.exists():
            return pd.read_csv(CACHE_TOP100_FILE)["symbol"].tolist()
    except Exception as e:
        print(f"Top100-Cache Lesefehler: {e}")
    return []


def save_top100_cache(symbols: list[str]) -> bool:
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
    try:
        if CACHE_UNAVAILABLE_FILE.exists():
            with open(CACHE_UNAVAILABLE_FILE, "r") as f:
                return set(json.load(f))
    except Exception as e:
        print(f"Unavailable-Cache Lesefehler: {e}")
    return set()


def save_unavailable_coins(coin_set: set[str]) -> bool:
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
    try:
        if CACHE_LAST_SCAN_FILE.exists():
            with open(CACHE_LAST_SCAN_FILE, "r") as f:
                return datetime.fromisoformat(f.read().strip())
    except Exception:
        pass
    return datetime.min


def save_last_scan_time() -> None:
    try:
        CACHE_LAST_SCAN_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(CACHE_LAST_SCAN_FILE, "w") as f:
            f.write(datetime.now().isoformat())
    except Exception as e:
        print(f"Scan-Zeitstempel Schreibfehler: {e}")