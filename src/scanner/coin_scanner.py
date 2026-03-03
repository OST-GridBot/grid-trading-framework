"""
src/scanner/coin_scanner.py
===========================
Automatischer Coin-Scanner fuer Grid-Bot-Eignung.

Bewertet Top-100 Coins anhand technischer Indikatoren und
gibt eine sortierte Rangliste der geeignetsten Coins zurueck.

Scoring (0-4 Punkte):
    +1 : ADX14 < ADX14_SIDEWAYS_MAX  (kein kurzfristiger Trend)
    +1 : ADX30 < ADX30_SIDEWAYS_MAX  (kein langfristiger Trend)
    +1 : ATR% zwischen ATR_PCT_MIN und ATR_PCT_MAX
    +1 : Volumen > MIN_VOLUME_USDT

Theoretischer Hintergrund (Bachelorarbeit Ziel 5):
    Grid-Bots profitieren von seitwärts tendierenden Maerkten mit
    ausreichender Volatilitaet. Der ADX misst die Trendstaerke,
    ATR die Volatilitaet. Hohe Liquiditaet (Volumen) ist
    Voraussetzung fuer zuverlaessige Order-Ausfuehrung.

Autor: Enes Eryilmaz
Projekt: Grid-Trading-Framework (Bachelorarbeit OST)
"""

import time
import pandas as pd
import numpy as np
from typing import Optional

from config.settings import (
    ADX14_SIDEWAYS_MAX,
    ADX30_SIDEWAYS_MAX,
    ATR_PCT_MIN,
    ATR_PCT_MAX,
    MIN_VOLUME_USDT,
    SCANNER_LOOKBACK_DAYS,
    DEFAULT_INTERVAL,
)
from src.data.cache_manager import get_price_data, get_last_scan_time, save_last_scan_time
from src.data.cmc_api import update_top100_cache
from src.analysis.indicators import get_adx_value, get_atr_stats, calculate_volatility
from src.analysis.regime import detect_regime


# ---------------------------------------------------------------------------
# Hauptfunktion
# ---------------------------------------------------------------------------

def run_scanner(
    coins:           Optional[list] = None,
    interval:        str            = DEFAULT_INTERVAL,
    days:            int            = SCANNER_LOOKBACK_DAYS,
    min_score:       int            = 0,
    force_reload:    bool           = False,
    progress_callback = None,
) -> pd.DataFrame:
    """
    Scannt Coins auf Grid-Bot-Eignung und gibt Rangliste zurueck.

    Ablauf:
        1. Coin-Liste laden (CMC Top-100 oder manuell)
        2. Fuer jeden Coin: Preisdaten laden
        3. Indikatoren berechnen (ADX14, ADX30, ATR, Volumen)
        4. Score berechnen (0-4)
        5. Regime bestimmen
        6. Sortiert nach Score zurueckgeben

    Args:
        coins            : Liste von Coins (None = Top-100 von CMC)
        interval         : Kerzen-Intervall
        days             : Lookback-Periode in Tagen
        min_score        : Mindest-Score fuer Aufnahme in Ergebnis
        force_reload     : Cache ignorieren
        progress_callback: Funktion fuer Fortschrittsanzeige (z.B. Streamlit)

    Returns:
        DataFrame mit sortierten Scan-Ergebnissen
    """
    # Coin-Liste laden
    if coins is None:
        coins, err = update_top100_cache(force=force_reload, check_binance=True)
        if err or not coins:
            print(f"Scanner: Fehler beim Laden der Coin-Liste: {err}")
            return pd.DataFrame()

    print(f"Scanner: {len(coins)} Coins werden gescannt...")
    results = []

    for i, coin in enumerate(coins):
        # Fortschritt
        if progress_callback:
            progress_callback(i + 1, len(coins), coin)

        result = _scan_single_coin(coin, interval, days, force_reload)
        if result and result["score"] >= min_score:
            results.append(result)

        # Rate Limiting
        time.sleep(0.05)

    if not results:
        print("Scanner: Keine Ergebnisse gefunden.")
        return pd.DataFrame()

    df = pd.DataFrame(results)
    df = df.sort_values(
        ["score", "adx14"],
        ascending=[False, True]
    ).reset_index(drop=True)

    save_last_scan_time()
    print(f"Scanner: {len(df)} Coins gefunden (Score >= {min_score}).")
    return df


# ---------------------------------------------------------------------------
# Einzelnen Coin scannen
# ---------------------------------------------------------------------------

def _scan_single_coin(
    coin:         str,
    interval:     str,
    days:         int,
    force_reload: bool,
) -> Optional[dict]:
    """
    Berechnet alle Kennzahlen fuer einen einzelnen Coin.

    Args:
        coin        : Coin-Symbol (z.B. "BTC")
        interval    : Kerzen-Intervall
        days        : Lookback-Periode
        force_reload: Cache ignorieren

    Returns:
        Dictionary mit Scan-Ergebnissen oder None bei Fehler
    """
    try:
        df, _ = get_price_data(coin, days=days, interval=interval, force=force_reload)
        if df is None or df.empty or len(df) < 50:
            return None

        # Indikatoren berechnen
        adx14     = get_adx_value(df, period=14)
        adx30     = get_adx_value(df, period=30)
        atr_usdt, atr_pct = get_atr_stats(df)
        vm, vy    = calculate_volatility(df, interval)

        # Aktueller Preis und Volumen
        current_price  = float(df["close"].iloc[-1])
        avg_volume     = float(df["quote_volume"].mean()) if "quote_volume" in df.columns else 0.0

        # Regime bestimmen
        regime_result  = detect_regime(df, interval)

        # Score berechnen
        score, details = _calculate_score(adx14, adx30, atr_pct, avg_volume)

        return {
            "coin":           coin.upper(),
            "score":          score,
            "regime":         regime_result.regime,
            "regime_conf":    regime_result.confidence,
            "adx14":          round(adx14,       2),
            "adx30":          round(adx30,       2),
            "atr_usdt":       round(atr_usdt,    4),
            "atr_pct":        round(atr_pct,     3),
            "volume_usdt":    round(avg_volume,  0),
            "price":          round(current_price, 6),
            "vola_monthly":   round(vm, 2) if vm else None,
            "adx14_ok":       details["adx14"],
            "adx30_ok":       details["adx30"],
            "atr_ok":         details["atr"],
            "volume_ok":      details["volume"],
            "recommendation": _get_recommendation(score, regime_result.regime),
        }

    except Exception as e:
        print(f"Scanner: Fehler bei {coin}: {e}")
        return None


# ---------------------------------------------------------------------------
# Score berechnen
# ---------------------------------------------------------------------------

def _calculate_score(
    adx14:      float,
    adx30:      float,
    atr_pct:    float,
    volume:     float,
) -> tuple:
    """
    Berechnet Grid-Eignung-Score (0-4 Punkte).

    Returns:
        Tuple (score, details)
    """
    score   = 0
    details = {}

    adx14_ok = adx14 < ADX14_SIDEWAYS_MAX
    adx30_ok = adx30 < ADX30_SIDEWAYS_MAX
    atr_ok   = ATR_PCT_MIN <= atr_pct <= ATR_PCT_MAX
    vol_ok   = volume >= MIN_VOLUME_USDT

    details["adx14"]  = adx14_ok
    details["adx30"]  = adx30_ok
    details["atr"]    = atr_ok
    details["volume"] = vol_ok

    if adx14_ok: score += 1
    if adx30_ok: score += 1
    if atr_ok:   score += 1
    if vol_ok:   score += 1

    return score, details


# ---------------------------------------------------------------------------
# Empfehlung
# ---------------------------------------------------------------------------

def _get_recommendation(score: int, regime: str) -> str:
    """Gibt eine Handlungsempfehlung basierend auf Score und Regime."""
    if score == 4 and regime == "range":
        return "Sehr geeignet – Grid-Bot starten"
    elif score >= 3 and regime == "range":
        return "Geeignet – Grid-Bot moeglich"
    elif score >= 3 and regime != "range":
        return "Bedingt geeignet – Regime beachten"
    elif score == 2:
        return "Eingeschraenkt geeignet"
    elif score <= 1:
        return "Nicht geeignet"
    return "Pruefen"


# ---------------------------------------------------------------------------
# Hilfsfunktionen fuer UI
# ---------------------------------------------------------------------------

def get_top_coins(df_scan: pd.DataFrame, n: int = 10) -> pd.DataFrame:
    """Gibt die Top-N Coins aus dem Scan-Ergebnis zurueck."""
    if df_scan.empty:
        return pd.DataFrame()
    return df_scan.head(n)


def get_coins_by_score(df_scan: pd.DataFrame, score: int) -> pd.DataFrame:
    """Filtert Coins nach einem bestimmten Score."""
    if df_scan.empty:
        return pd.DataFrame()
    return df_scan[df_scan["score"] == score].reset_index(drop=True)


def format_scan_summary(df_scan: pd.DataFrame) -> str:
    """Gibt eine Zusammenfassung des Scan-Ergebnisses als Text zurueck."""
    if df_scan.empty:
        return "Keine Scan-Ergebnisse verfuegbar."

    total    = len(df_scan)
    score4   = len(df_scan[df_scan["score"] == 4])
    score3   = len(df_scan[df_scan["score"] == 3])
    score2   = len(df_scan[df_scan["score"] == 2])
    range_ct = len(df_scan[df_scan["regime"] == "range"])

    return (
        f"Scan-Ergebnis: {total} Coins analysiert\n"
        f"  Score 4 (sehr geeignet): {score4}\n"
        f"  Score 3 (geeignet):      {score3}\n"
        f"  Score 2 (eingeschraenkt):{score2}\n"
        f"  Range-Markt erkannt:     {range_ct}"
    )