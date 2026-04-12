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

def convert_df_timestamps(df, col="timestamp"):
    """Konvertiert eine Timestamp-Spalte eines DataFrames von UTC nach Zurich."""
    df = df.copy()
    df[col] = pd.to_datetime(df[col]).apply(utc_to_zurich)
    return df
