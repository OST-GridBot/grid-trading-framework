"""
src/utils/timezone.py
=====================
Zentrale Zeitzonenkonvertierung fuer das Grid-Trading-Framework.
Konvertiert UTC-Timestamps auf Europe/Zurich (MEZ/MESZ automatisch).
"""
from zoneinfo import ZoneInfo
import pandas as pd

ZURICH = ZoneInfo("Europe/Zurich")

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
