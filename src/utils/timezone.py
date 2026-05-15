"""
src/utils/timezone.py
=====================
Zentrale Zeitzonenkonvertierung fuer das Grid-Trading-Framework.
Konvertiert UTC-Timestamps auf Europe/Zurich (MEZ/MESZ automatisch).

Konvention: alle internen Timestamps = naive UTC (konsistent mit
Cache-CSVs aus Binance). User-Eingaben (Datum) sind Zurich-lokal und
werden vor Verwendung nach UTC konvertiert.
"""
from datetime import datetime, date, time, timezone
from zoneinfo import ZoneInfo
import pandas as pd

ZURICH = ZoneInfo("Europe/Zurich")
UTC    = ZoneInfo("UTC")


def start_of_day_utc(d: date) -> datetime:
    """User-Datum (Zurich-Mitternacht) -> tz-aware UTC datetime."""
    return datetime.combine(d, time.min).replace(tzinfo=ZURICH).astimezone(UTC)


def end_of_day_utc(d: date) -> datetime:
    """User-Datum (Zurich 23:59:59) -> tz-aware UTC datetime."""
    return datetime.combine(d, time.max).replace(tzinfo=ZURICH).astimezone(UTC)


def naive_utc_now() -> datetime:
    """Aktuelle Zeit als naive UTC (kompatibel mit Cache-/Binance-Timestamps).
    Konvention: alle internen State-Timestamps verwenden diese Funktion,
    nicht datetime.now() oder pd.Timestamp.now() (= naive lokale Zeit)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)

def utc_to_zurich(ts) -> pd.Timestamp:
    """Konvertiert einen UTC-Timestamp (naive oder aware) nach Europe/Zurich."""
    ts = pd.to_datetime(ts)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    return ts.tz_convert(ZURICH).tz_localize(None)


def zurich_to_unix(ts) -> int:
    """
    Wandelt einen Zurich-lokalen Timestamp (naive oder aware) in
    Unix-Sekunden (UTC) um — fuer Lightweight Charts.

    Hintergrund: nach convert_df_timestamps liegen Timestamps naiv
    in Zurich-Zeit vor. pandas 2+ interpretiert naive Timestamps via
    `.timestamp()` als UTC, was zu einem +2h-Versatz im Chart fuehrt
    (Browser lokalisiert anschliessend nochmal). Hier explizit als
    Zurich lokalisieren und nach UTC konvertieren.
    """
    ts = pd.to_datetime(ts)
    if ts.tzinfo is None:
        ts = ts.tz_localize(ZURICH)
    return int(ts.tz_convert("UTC").timestamp())


def convert_df_timestamps(df, col="timestamp"):
    """Konvertiert eine Timestamp-Spalte eines DataFrames von UTC nach Zurich."""
    df = df.copy()
    df[col] = pd.to_datetime(df[col]).apply(utc_to_zurich)
    return df
