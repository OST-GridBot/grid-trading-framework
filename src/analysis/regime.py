"""
src/analysis/regime.py
======================
Marktregime-Erkennung fuer den Grid-Bot.

Erkennt automatisch ob sich ein Markt in einer Range- oder Trendphase
befindet. Dies ist die Grundlage fuer dynamische Grid-Anpassungen
(Bachelorarbeit Ziel 8b).

Regime-Typen:
    - range      : Seitwärtsmarkt – Grid-Bot geeignet
    - trend_up   : Aufwaertstrend – Grid-Bot weniger geeignet
    - trend_down : Abwaertstrend – Grid-Bot weniger geeignet

Autor: Enes Eryilmaz
Projekt: Grid-Trading-Framework (Bachelorarbeit OST)
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass
from typing import Optional

from config.settings import (
    ADX14_SIDEWAYS_MAX, ADX14_WARNING_MAX,
    ADX30_SIDEWAYS_MAX, ADX30_WARNING_MAX,
    COLOR_GREEN, COLOR_ORANGE, COLOR_RED,
)
from src.analysis.indicators import (
    get_adx_value,
    get_atr_stats,
    calculate_bollinger_bands,
)


# ---------------------------------------------------------------------------
# Datenklasse fuer Regime-Ergebnis
# ---------------------------------------------------------------------------

@dataclass
class RegimeResult:
    """
    Ergebnis der Marktregime-Erkennung.

    Attributes:
        regime     : Erkanntes Regime ("range", "trend_up", "trend_down")
        confidence : Konfidenz der Einschaetzung in % (0-100)
        adx14      : ADX-Wert mit Periode 14
        adx30      : ADX-Wert mit Periode 30
        bb_width   : Bollinger Band Breite in %
        price_vs_sma: Abstand Preis zu SMA in %
        recommendation: Handlungsempfehlung fuer Grid-Bot
        color      : Anzeigefarbe (gruen/orange/rot)
        signals    : Dictionary mit Einzelsignalen
    """
    regime:         str
    confidence:     float
    adx14:          float
    adx30:          float
    bb_width:       float
    price_vs_sma:   float
    recommendation: str
    color:          str
    signals:        dict


# ---------------------------------------------------------------------------
# Regime-Erkennung
# ---------------------------------------------------------------------------

def detect_regime(
    df:       pd.DataFrame,
    interval: str = "1h",
) -> RegimeResult:
    """
    Erkennt das aktuelle Marktregime anhand mehrerer Indikatoren.

    Methodik:
        Kombination von ADX14, ADX30, Bollinger Band Breite und
        Preis-SMA-Abstand. Jedes Signal liefert einen Beitrag zur
        Gesamteinschaetzung. Die Konfidenz steigt mit der Anzahl
        uebereinstimmender Signale.

    Regime-Logik:
        Range-Markt  : ADX14 < 20 UND ADX30 < 15 UND enge BB
        Trend-Markt  : ADX14 > 25 ODER ADX30 > 25 ODER weite BB
        Uebergang    : Werte zwischen den Schwellenwerten

    Args:
        df      : DataFrame mit OHLCV-Daten (mind. 50 Kerzen)
        interval: Kerzen-Intervall (fuer spaetere Erweiterungen)

    Returns:
        RegimeResult mit allen Kennzahlen und Empfehlungen
    """
    # --- Indikatoren berechnen ---
    adx14 = get_adx_value(df, period=14)
    adx30 = get_adx_value(df, period=30)

    bb        = calculate_bollinger_bands(df, period=20)
    bb_width  = float(bb["bb_width"].iloc[-1])  if not pd.isna(bb["bb_width"].iloc[-1])  else 0.0
    bb_middle = float(bb["bb_middle"].iloc[-1]) if not pd.isna(bb["bb_middle"].iloc[-1]) else 0.0

    current_price = float(df["close"].iloc[-1])
    price_vs_sma  = ((current_price - bb_middle) / bb_middle * 100) if bb_middle > 0 else 0.0

    # --- Einzelsignale bewerten ---
    signals = _evaluate_signals(adx14, adx30, bb_width, price_vs_sma)

    # --- Regime bestimmen ---
    regime, confidence = _determine_regime(signals)

    # --- Trend-Richtung bestimmen ---
    if regime == "trend":
        adx_result = _get_adx_dataframe(df)
        regime = _determine_trend_direction(df, adx_result)

    # --- Empfehlung und Farbe ---
    recommendation = _get_recommendation(regime, confidence)
    color          = _get_regime_color(regime, confidence)

    return RegimeResult(
        regime         = regime,
        confidence     = round(confidence, 1),
        adx14          = round(adx14, 2),
        adx30          = round(adx30, 2),
        bb_width       = round(bb_width, 2),
        price_vs_sma   = round(price_vs_sma, 2),
        recommendation = recommendation,
        color          = color,
        signals        = signals,
    )


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def _evaluate_signals(
    adx14:       float,
    adx30:       float,
    bb_width:    float,
    price_vs_sma: float,
) -> dict:
    """
    Bewertet jedes Signal als range, trend oder neutral.

    Returns:
        Dictionary mit Signal-Bewertungen und Staerken
    """
    signals = {}

    # ADX14 Signal
    if adx14 < ADX14_SIDEWAYS_MAX:
        signals["adx14"] = {"value": adx14, "signal": "range",   "weight": 2}
    elif adx14 < ADX14_WARNING_MAX:
        signals["adx14"] = {"value": adx14, "signal": "neutral", "weight": 1}
    else:
        signals["adx14"] = {"value": adx14, "signal": "trend",   "weight": 2}

    # ADX30 Signal
    if adx30 < ADX30_SIDEWAYS_MAX:
        signals["adx30"] = {"value": adx30, "signal": "range",   "weight": 2}
    elif adx30 < ADX30_WARNING_MAX:
        signals["adx30"] = {"value": adx30, "signal": "neutral", "weight": 1}
    else:
        signals["adx30"] = {"value": adx30, "signal": "trend",   "weight": 2}

    # Bollinger Band Breite Signal
    # Enge Bands (< 3%) = Range, Weite Bands (> 8%) = Trend
    if bb_width < 3.0:
        signals["bb_width"] = {"value": bb_width, "signal": "range",   "weight": 1}
    elif bb_width > 8.0:
        signals["bb_width"] = {"value": bb_width, "signal": "trend",   "weight": 1}
    else:
        signals["bb_width"] = {"value": bb_width, "signal": "neutral", "weight": 1}

    # Preis vs SMA Signal
    # Nahe am SMA (< 1%) = Range, Weit vom SMA (> 3%) = Trend
    abs_pct = abs(price_vs_sma)
    if abs_pct < 1.0:
        signals["price_sma"] = {"value": price_vs_sma, "signal": "range",   "weight": 1}
    elif abs_pct > 3.0:
        signals["price_sma"] = {"value": price_vs_sma, "signal": "trend",   "weight": 1}
    else:
        signals["price_sma"] = {"value": price_vs_sma, "signal": "neutral", "weight": 1}

    return signals


def _determine_regime(signals: dict) -> tuple:
    """
    Bestimmt das Gesamtregime und die Konfidenz aus den Einzelsignalen.

    Returns:
        Tuple (regime, confidence):
            regime    : "range", "trend" oder "neutral"
            confidence: Konfidenz in % (0-100)
    """
    range_score  = sum(s["weight"] for s in signals.values() if s["signal"] == "range")
    trend_score  = sum(s["weight"] for s in signals.values() if s["signal"] == "trend")
    total_weight = sum(s["weight"] for s in signals.values())

    if total_weight == 0:
        return "neutral", 50.0

    if trend_score > range_score:
        confidence = (trend_score / total_weight) * 100
        return "trend", confidence
    elif range_score > trend_score:
        confidence = (range_score / total_weight) * 100
        return "range", confidence
    else:
        return "neutral", 50.0


def _get_adx_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Berechnet ADX DataFrame fuer Trendrichtungsbestimmung."""
    from src.analysis.indicators import calculate_adx
    return calculate_adx(df, period=14)


def _determine_trend_direction(
    df:         pd.DataFrame,
    adx_result: pd.DataFrame,
) -> str:
    """
    Bestimmt ob der Trend aufwaerts oder abwaerts gerichtet ist.

    Verwendet +DI und -DI des ADX sowie SMA-Vergleich.

    Returns:
        "trend_up" oder "trend_down"
    """
    plus_di  = float(adx_result["plus_di"].iloc[-1])
    minus_di = float(adx_result["minus_di"].iloc[-1])

    # SMA Vergleich als zweites Signal
    sma_20  = df["close"].rolling(20).mean().iloc[-1]
    sma_50  = df["close"].rolling(50).mean().iloc[-1]
    sma_up  = sma_20 > sma_50 if not (pd.isna(sma_20) or pd.isna(sma_50)) else None

    # Mehrheitsentscheid
    up_signals   = sum([plus_di > minus_di, sma_up is True])
    down_signals = sum([plus_di < minus_di, sma_up is False])

    return "trend_up" if up_signals >= down_signals else "trend_down"


def _get_recommendation(regime: str, confidence: float) -> str:
    """
    Gibt eine Handlungsempfehlung fuer den Grid-Bot zurueck.

    Args:
        regime    : Erkanntes Regime
        confidence: Konfidenz in %

    Returns:
        Empfehlungstext
    """
    if regime == "range":
        if confidence >= 75:
            return "Grid-Bot starten – stabiler Seitwärtsmarkt erkannt"
        return "Grid-Bot moeglich – Seitwärtsmarkt mit geringer Konfidenz"
    elif regime == "trend_up":
        if confidence >= 75:
            return "Grid-Bot pausieren – starker Aufwaertstrend aktiv"
        return "Grid-Bot mit Vorsicht – moeglicher Aufwaertstrend"
    elif regime == "trend_down":
        if confidence >= 75:
            return "Grid-Bot stoppen – starker Abwaertstrend aktiv"
        return "Grid-Bot mit Vorsicht – moeglicher Abwaertstrend"
    return "Marktlage unklar – abwarten"


def _get_regime_color(regime: str, confidence: float) -> str:
    """Gibt die Anzeigefarbe fuer das Regime zurueck."""
    if regime == "range":
        return COLOR_GREEN if confidence >= 75 else COLOR_ORANGE
    elif regime in ("trend_up", "trend_down"):
        return COLOR_RED if confidence >= 75 else COLOR_ORANGE
    return COLOR_ORANGE


# ---------------------------------------------------------------------------
# Hilfsfunktion fuer UI
# ---------------------------------------------------------------------------

def regime_summary(result: RegimeResult) -> dict:
    """
    Gibt eine vereinfachte Zusammenfassung fuer die UI zurueck.

    Args:
        result: RegimeResult von detect_regime()

    Returns:
        Dictionary fuer direkte Anzeige in Streamlit
    """
    regime_labels = {
        "range":      "Range-Markt (Seitwärts)",
        "trend_up":   "Trend-Markt (Aufwaerts)",
        "trend_down": "Trend-Markt (Abwaerts)",
        "neutral":    "Unklare Marktlage",
    }

    return {
        "label":          regime_labels.get(result.regime, result.regime),
        "confidence":     result.confidence,
        "recommendation": result.recommendation,
        "color":          result.color,
        "adx14":          result.adx14,
        "adx30":          result.adx30,
        "bb_width":       result.bb_width,
    }