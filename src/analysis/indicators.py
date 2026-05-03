"""
src/analysis/indicators.py
==========================
Technische Indikatoren fuer Grid-Bot und Coin-Scanner.

Indikatoren:
    - ADX  : Average Directional Index (Trendstaerke)
    - ATR  : Average True Range (Volatilitaet in USDT und %)
    - Vola : Annualisierte Volatilitaet (monatlich + jaehrlich)
    - BB   : Bollinger Bands (Preisbereich + Bandbreite)

Alle Schwellenwerte sind in config/settings.py definiert.

Autor: Enes Eryilmaz
Projekt: Grid-Trading-Framework (Bachelorarbeit OST)
"""

import numpy as np
import pandas as pd
from typing import Optional

from config.settings import (
    ADX14_SIDEWAYS_MAX, ADX14_WARNING_MAX,
    ADX30_SIDEWAYS_MAX, ADX30_WARNING_MAX,
    ATR_PCT_MIN, ATR_PCT_MAX,
    COLOR_GREEN, COLOR_ORANGE, COLOR_RED,
)


# ---------------------------------------------------------------------------
# ADX – Average Directional Index
# ---------------------------------------------------------------------------

def calculate_adx(
    df:     pd.DataFrame,
    period: int = 14,
    method: str = "sma",
) -> pd.DataFrame:
    """
    Berechnet den Average Directional Index (ADX).

    Der ADX misst die Staerke eines Trends – nicht seine Richtung.
    Werte unter 20 deuten auf einen Seitwärtsmarkt hin (gut fuer Grid-Bots),
    Werte ueber 25 auf einen starken Trend (Grid-Bot weniger geeignet).

    Args:
        df    : DataFrame mit Spalten [high, low, close]
        period: Glaettungsperiode (Standard: 14)
        method: "sma" (Simple) oder "ema" (Exponential Moving Average)

    Returns:
        DataFrame mit Spalten:
            adx      : ADX-Wert (Trendstaerke)
            plus_di  : +DI (aufwaerts gerichtete Bewegung)
            minus_di : -DI (abwaerts gerichtete Bewegung)

    Hinweis:
        Im Prototyp wurde ADX30 faelschlicherweise mit period=14 berechnet.
        Dieser Bug ist hier behoben – period wird korrekt verwendet.
    """
    up_move   = df["high"].diff()
    down_move = df["low"].diff().abs()

    plus_dm  = pd.Series(
        np.where((up_move > down_move) & (up_move > 0), up_move, 0),
        index=df.index,
    )
    minus_dm = pd.Series(
        np.where((down_move > up_move) & (down_move > 0), down_move, 0),
        index=df.index,
    )

    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - df["close"].shift()).abs(),
        (df["low"]  - df["close"].shift()).abs(),
    ], axis=1).max(axis=1)

    if method == "ema":
        atr      = tr.ewm(span=period, adjust=False).mean()
        plus_di  = 100 * plus_dm.ewm(span=period, adjust=False).mean() / atr
        minus_di = 100 * minus_dm.ewm(span=period, adjust=False).mean() / atr
        dx       = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
        adx      = dx.ewm(span=period, adjust=False).mean()
    else:  # sma (Standard)
        atr      = tr.rolling(period).mean()
        plus_di  = 100 * plus_dm.rolling(period).sum() / atr
        minus_di = 100 * minus_dm.rolling(period).sum() / atr
        dx       = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
        adx      = dx.rolling(period).mean()

    return pd.DataFrame({
        "adx":      adx,
        "plus_di":  plus_di,
        "minus_di": minus_di,
    })


def get_adx_value(df: pd.DataFrame, period: int = 14) -> float:
    """
    Gibt den aktuellen ADX-Wert (letzter Datenpunkt) zurueck.

    Args:
        df    : DataFrame mit OHLCV-Daten
        period: ADX-Periode (14 oder 30)

    Returns:
        ADX-Wert als float (0.0 bei Fehler)
    """
    result = calculate_adx(df, period=period)
    val    = result["adx"].iloc[-1]
    return float(val) if not pd.isna(val) else 0.0


def get_adx_color(adx_value: float, period: int = 14) -> str:
    """
    Gibt die Anzeigefarbe basierend auf dem ADX-Wert zurueck.

    Args:
        adx_value: ADX-Wert
        period   : 14 (kurzfristig) oder 30 (langfristig)

    Returns:
        Farb-String (COLOR_GREEN / COLOR_ORANGE / COLOR_RED)
    """
    if period == 14:
        if adx_value < ADX14_SIDEWAYS_MAX:
            return COLOR_GREEN
        elif adx_value < ADX14_WARNING_MAX:
            return COLOR_ORANGE
        return COLOR_RED
    else:  # period == 30
        if adx_value < ADX30_SIDEWAYS_MAX:
            return COLOR_GREEN
        elif adx_value < ADX30_WARNING_MAX:
            return COLOR_ORANGE
        return COLOR_RED


# ---------------------------------------------------------------------------
# ATR – Average True Range
# ---------------------------------------------------------------------------

def calculate_atr(
    df:     pd.DataFrame,
    period: int = 14,
) -> pd.Series:
    """
    Berechnet die Average True Range (ATR) als Zeitreihe.

    Die ATR misst die durchschnittliche Preisschwankung pro Kerze
    in absoluten USDT-Werten.

    Args:
        df    : DataFrame mit Spalten [high, low, close]
        period: Glaettungsperiode (Standard: 14)

    Returns:
        pd.Series mit ATR-Werten
    """
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - df["close"].shift()).abs(),
        (df["low"]  - df["close"].shift()).abs(),
    ], axis=1).max(axis=1)

    return tr.rolling(period).mean()


def get_atr_stats(df: pd.DataFrame) -> tuple:
    """
    Berechnet ATR in USDT und in Prozent (% vom Durchschnittskurs).

    Der prozentuale ATR ist besonders nuetzlich um die Grid-Abstands-
    Eignung zu beurteilen: ATR% sollte zwischen ATR_PCT_MIN und
    ATR_PCT_MAX liegen (definiert in settings.py).

    Args:
        df: DataFrame mit Spalten [high, low, close]

    Returns:
        Tuple (atr_usdt, atr_pct):
            atr_usdt: Durchschnittliche True Range in USDT
            atr_pct : Durchschnittliche True Range in %
    """
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - df["close"].shift()).abs(),
        (df["low"]  - df["close"].shift()).abs(),
    ], axis=1).max(axis=1)

    # Standard 14-Perioden ATR (Wilder EWM) statt einfachem Durchschnitt
    atr_usdt      = float(tr.ewm(span=14, adjust=False).mean().iloc[-1])
    current_close = float(df["close"].iloc[-1])
    atr_pct       = (atr_usdt / current_close) * 100 if current_close > 0 else 0.0

    return float(atr_usdt), float(atr_pct)


# ---------------------------------------------------------------------------
# Volatilitaet – annualisiert
# ---------------------------------------------------------------------------

# Anzahl Kerzen pro Monat und Jahr je Intervall
_INTERVAL_FACTORS = {
    "1m":  {"monthly": 43_200, "yearly": 525_600},
    "5m":  {"monthly":  8_640, "yearly": 105_120},
    "15m": {"monthly":  2_880, "yearly":  35_040},
    "1h":  {"monthly":    720, "yearly":   8_760},
    "4h":  {"monthly":    180, "yearly":   2_190},
    "1d":  {"monthly":     30, "yearly":     365},
}


def calculate_volatility(
    df:       pd.DataFrame,
    interval: str,
) -> tuple:
    """
    Berechnet die annualisierte historische Volatilitaet.

    Basiert auf der Standardabweichung der prozentualen Preisaenderung
    pro Kerze, hochskaliert auf Monats- und Jahresbasis.

    Theoretischer Hintergrund (Bachelorarbeit Kap. 1.2):
        - Volatility Clustering: Phasen hoher Vola folgen auf hohe Vola
        - Mean Reversion: Extreme Vola-Phasen normalisieren sich

    Args:
        df      : DataFrame mit Spalte [close]
        interval: Kerzen-Intervall ("1m","5m","15m","1h","4h","1d")

    Returns:
        Tuple (vola_monthly, vola_yearly):
            vola_monthly: Monatliche Volatilitaet in %
            vola_yearly : Jaehrliche Volatilitaet in %
            Beide None wenn Intervall nicht unterstuetzt.
    """
    if "price_change" not in df.columns:
        df = df.copy()
        df["price_change"] = df["close"].pct_change() * 100

    if df["price_change"].isna().all():
        return None, None

    factors = _INTERVAL_FACTORS.get(interval)
    if not factors:
        return None, None

    std_pct      = df["price_change"].std()
    vola_monthly = std_pct * np.sqrt(factors["monthly"])
    vola_yearly  = std_pct * np.sqrt(factors["yearly"])

    return float(vola_monthly), float(vola_yearly)


# ---------------------------------------------------------------------------
# Bollinger Bands
# ---------------------------------------------------------------------------

def calculate_bollinger_bands(
    df:     pd.DataFrame,
    period: int   = 20,
    std:    float = 2.0,
) -> pd.DataFrame:
    """
    Berechnet Bollinger Bands.

    Bollinger Bands berechnen einen Preiskanal um einen gleitenden
    Durchschnitt. Sie sind nützlich fuer:
        - Grid-Range-Bestimmung: Bands definieren sinnvolle Preisgrenzen
        - Marktregime-Erkennung: Enge Bands = Range-Markt, weite = Trend

    Args:
        df    : DataFrame mit Spalte [close]
        period: Laenge des gleitenden Durchschnitts (Standard: 20)
        std   : Anzahl Standardabweichungen fuer die Bands (Standard: 2.0)

    Returns:
        DataFrame mit Spalten:
            bb_middle : Mittleres Band (SMA)
            bb_upper  : Oberes Band (SMA + std * Standardabweichung)
            bb_lower  : Unteres Band (SMA - std * Standardabweichung)
            bb_width  : Bandbreite in % ((upper - lower) / middle * 100)
            bb_pct    : %B – Position des Preises im Band (0=unten, 1=oben)
    """
    close     = df["close"]
    sma       = close.rolling(period).mean()
    std_dev   = close.rolling(period).std()

    upper     = sma + std * std_dev
    lower     = sma - std * std_dev
    bb_width  = ((upper - lower) / sma * 100).where(sma > 0)
    bb_pct    = ((close - lower) / (upper - lower)).where((upper - lower) > 0)

    return pd.DataFrame({
        "bb_middle": sma,
        "bb_upper":  upper,
        "bb_lower":  lower,
        "bb_width":  bb_width,
        "bb_pct":    bb_pct,
    })


def get_bb_stats(df: pd.DataFrame) -> tuple:
    """
    Gibt aktuelle Bollinger Band Kennzahlen zurueck.

    Args:
        df: DataFrame mit OHLCV-Daten

    Returns:
        Tuple (bb_width, bb_pct, bb_upper, bb_lower):
            bb_width : Aktuelle Bandbreite in %
            bb_pct   : Position des Preises im Band (0-1)
            bb_upper : Oberes Band (aktuell)
            bb_lower : Unteres Band (aktuell)
    """
    bb = calculate_bollinger_bands(df)
    return (
        float(bb["bb_width"].iloc[-1]) if not pd.isna(bb["bb_width"].iloc[-1]) else 0.0,
        float(bb["bb_pct"].iloc[-1])   if not pd.isna(bb["bb_pct"].iloc[-1])   else 0.5,
        float(bb["bb_upper"].iloc[-1]) if not pd.isna(bb["bb_upper"].iloc[-1]) else 0.0,
        float(bb["bb_lower"].iloc[-1]) if not pd.isna(bb["bb_lower"].iloc[-1]) else 0.0,
    )


# ---------------------------------------------------------------------------
# Scanner-Scoring
# ---------------------------------------------------------------------------

def calculate_grid_score(
    adx14:    float,
    atr_pct:  float,
    volume:   float,
    adx30:    Optional[float] = None,
) -> tuple:
    """
    Berechnet den Grid-Eignung-Score fuer den Coin-Scanner.

    Scoring (0-4 Punkte):
        +1 Punkt: ADX14 < ADX14_SIDEWAYS_MAX  (kein kurzfristiger Trend)
        +1 Punkt: ADX30 < ADX30_SIDEWAYS_MAX  (kein langfristiger Trend)
        +1 Punkt: ATR% zwischen ATR_PCT_MIN und ATR_PCT_MAX (geeignete Vola)
        +1 Punkt: Volumen > MIN_VOLUME_USDT   (genuegend Liquiditaet)

    Args:
        adx14   : ADX-Wert mit Periode 14
        atr_pct : ATR in Prozent
        volume  : 24h Handelsvolumen in USDT
        adx30   : ADX-Wert mit Periode 30 (optional)

    Returns:
        Tuple (score, details):
            score  : Gesamt-Score (0-4)
            details: Dictionary mit Einzelbewertungen
    """
    from config.settings import MIN_VOLUME_USDT

    score   = 0
    details = {}

    # ADX14
    adx14_ok          = adx14 < ADX14_SIDEWAYS_MAX
    details["adx14"]  = adx14_ok
    if adx14_ok:
        score += 1

    # ADX30
    if adx30 is not None:
        adx30_ok         = adx30 < ADX30_SIDEWAYS_MAX
        details["adx30"] = adx30_ok
        if adx30_ok:
            score += 1
    else:
        details["adx30"] = None

    # ATR%
    atr_ok           = ATR_PCT_MIN <= atr_pct <= ATR_PCT_MAX
    details["atr"]   = atr_ok
    if atr_ok:
        score += 1

    # Volumen
    vol_ok            = volume >= MIN_VOLUME_USDT
    details["volume"] = vol_ok
    if vol_ok:
        score += 1

    return score, details