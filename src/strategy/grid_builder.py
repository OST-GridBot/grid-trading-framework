"""
src/strategy/grid_builder.py
============================
Berechnung und Konfiguration von Grid-Linien.

Unterstuetzte Modi:
    - Arithmetisch : Gleichmaessige USDT-Abstaende zwischen den Levels
    - Geometrisch  : Gleichmaessige prozentuale Abstaende zwischen den Levels

Zusaetzliche Funktionen:
    - Automatische Range-Berechnung (ATR-basiert, BB-basiert)
    - Grid-Profit-Vorschau pro Grid nach Fees
    - Validierung der Grid-Parameter

Theoretischer Hintergrund (Bachelorarbeit Kap. 2):
    Arithmetische Grids eignen sich fuer stabile Preisspannen.
    Geometrische Grids sind bei groesseren Preisspannen vorteilhafter,
    da sie prozentual gleichmaessige Gewinnchancen pro Grid bieten.

Autor: Enes Eryilmaz
Projekt: Grid-Trading-Framework (Bachelorarbeit OST)
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import Optional

from config.settings import (
    DEFAULT_NUM_GRIDS,
    DEFAULT_GRID_MODE,
    DEFAULT_FEE_RATE,
    DEFAULT_GRID_RANGE_PCT,
    MIN_NUM_GRIDS,
    MAX_NUM_GRIDS,
)


# ---------------------------------------------------------------------------
# Datenklassen
# ---------------------------------------------------------------------------

@dataclass
class GridConfig:
    """
    Vollstaendige Grid-Konfiguration.

    Attributes:
        lower_price  : Untere Preisgrenze
        upper_price  : Obere Preisgrenze
        num_grids    : Anzahl Grids
        mode         : "arithmetic" oder "geometric"
        fee_rate     : Gebuehrenrate pro Trade (z.B. 0.001 = 0.1%)
        grid_lines   : Berechnete Grid-Linien (aufsteigend)
        grid_spacing : Durchschnittlicher Abstand zwischen Grids
        profit_per_grid: Erwarteter Gewinn pro Grid-Zyklus nach Fees (%)
    """
    lower_price:     float
    upper_price:     float
    num_grids:       int
    mode:            str
    fee_rate:        float
    grid_lines:      list  = field(default_factory=list)
    grid_spacing:    float = 0.0
    profit_per_grid: float = 0.0


@dataclass
class GridRangeSuggestion:
    """
    Vorgeschlagene Grid-Range basierend auf Marktdaten.

    Attributes:
        lower_price : Vorgeschlagene untere Grenze
        upper_price : Vorgeschlagene obere Grenze
        method      : Methode der Berechnung ("atr", "bb", "pct")
        description : Beschreibung der Methode
    """
    lower_price: float
    upper_price: float
    method:      str
    description: str


# ---------------------------------------------------------------------------
# Grid-Linien berechnen
# ---------------------------------------------------------------------------

def calculate_grid_lines(
    lower_price: float,
    upper_price: float,
    num_grids:   int,
    mode:        str = "arithmetic",
) -> list[float]:
    """
    Berechnet die Grid-Linien zwischen zwei Preislevels.

    Arithmetischer Modus:
        Gleichmaessige USDT-Abstaende. Geeignet fuer enge Preisspannen.
        Beispiel (3 Grids, 100-400 USDT): [100, 200, 300, 400]

    Geometrischer Modus:
        Gleichmaessige prozentuale Abstaende. Geeignet fuer grosse Spannen.
        Beispiel (3 Grids, 100-800 USDT): [100, 200, 400, 800]
        Jeder Schritt = gleicher Prozentsatz (hier 100% Anstieg)

    Args:
        lower_price: Untere Preisgrenze
        upper_price: Obere Preisgrenze
        num_grids  : Anzahl Grids (Anzahl Intervalle, nicht Linien!)
        mode       : "arithmetic" oder "geometric"

    Returns:
        Sortierte Liste der Grid-Preise (num_grids + 1 Linien)

    Raises:
        ValueError: Bei ungueltigen Parametern
    """
    _validate_grid_params(lower_price, upper_price, num_grids)

    if mode == "arithmetic":
        lines = np.linspace(lower_price, upper_price, num_grids + 1).tolist()

    elif mode == "geometric":
        ratio = (upper_price / lower_price) ** (1 / num_grids)
        lines = [round(lower_price * (ratio ** i), 8) for i in range(num_grids + 1)]

    elif mode in ("asymmetric_bottom", "asymmetric_top"):
        # Asymmetrische Grids: engere Abstände unten (bottom_heavy)
        # oder engere Abstände oben (top_heavy)
        # Implementierung via quadratische Verteilung der Punkte
        n = num_grids + 1
        t = np.linspace(0, 1, n)
        if mode == "asymmetric_bottom":
            # Quadratisch: mehr Punkte nahe 0 (unten)
            t_skewed = t ** 2
        else:
            # Quadratisch: mehr Punkte nahe 1 (oben)
            t_skewed = 1 - (1 - t) ** 2
        lines = [lower_price + (upper_price - lower_price) * ti for ti in t_skewed]

    else:
        raise ValueError(
            f"Unbekannter Grid-Modus: '{mode}'. "
            f"Erlaubt: arithmetic, geometric, asymmetric_bottom, asymmetric_top"
        )

    return sorted(lines)


def build_grid_config(
    lower_price: float,
    upper_price: float,
    num_grids:   int   = DEFAULT_NUM_GRIDS,
    mode:        str   = DEFAULT_GRID_MODE,
    fee_rate:    float = DEFAULT_FEE_RATE,
) -> GridConfig:
    """
    Erstellt eine vollstaendige Grid-Konfiguration.

    Berechnet Grid-Linien, Abstände und Gewinnvorschau.

    Args:
        lower_price: Untere Preisgrenze
        upper_price: Obere Preisgrenze
        num_grids  : Anzahl Grids
        mode       : "arithmetic" oder "geometric"
        fee_rate   : Gebuehrenrate pro Trade

    Returns:
        GridConfig mit allen berechneten Werten
    """
    grid_lines      = calculate_grid_lines(lower_price, upper_price, num_grids, mode)
    grid_spacing    = _calculate_avg_spacing(grid_lines)
    profit_per_grid = _calculate_profit_per_grid(grid_lines, fee_rate, mode)

    return GridConfig(
        lower_price     = lower_price,
        upper_price     = upper_price,
        num_grids       = num_grids,
        mode            = mode,
        fee_rate        = fee_rate,
        grid_lines      = grid_lines,
        grid_spacing    = grid_spacing,
        profit_per_grid = profit_per_grid,
    )


# ---------------------------------------------------------------------------
# Automatische Range-Berechnung
# ---------------------------------------------------------------------------

def suggest_grid_range(
    df:            pd.DataFrame,
    current_price: float,
    method:        str   = "atr",
    atr_multiplier: float = 2.0,
) -> GridRangeSuggestion:
    """
    Schlaegt eine Grid-Range basierend auf Marktdaten vor.

    Drei Methoden:
        atr : Range = aktueller Preis +/- (ATR * Multiplikator)
              Passt sich dynamisch der Volatilitaet an
        bb  : Range = Bollinger Band (unteres bis oberes Band)
              Nutzt statistische Preisgrenzen der letzten 20 Kerzen
        pct : Range = aktueller Preis +/- DEFAULT_GRID_RANGE_PCT%
              Einfache prozentuale Abschaetzung (Fallback)

    Args:
        df            : DataFrame mit OHLCV-Daten
        current_price : Aktueller Marktpreis
        method        : "atr", "bb" oder "pct"
        atr_multiplier: Multiplikator fuer ATR-Range (Standard: 2.0)

    Returns:
        GridRangeSuggestion mit lower_price, upper_price und Beschreibung
    """
    if method == "atr":
        return _suggest_atr_range(df, current_price, atr_multiplier)
    elif method == "bb":
        return _suggest_bb_range(df, current_price)
    else:
        return _suggest_pct_range(current_price)


def _suggest_atr_range(
    df:            pd.DataFrame,
    current_price: float,
    multiplier:    float,
) -> GridRangeSuggestion:
    """ATR-basierte Range-Berechnung."""
    from src.analysis.indicators import get_atr_stats
    atr_usdt, _ = get_atr_stats(df)

    offset      = atr_usdt * multiplier
    lower_price = max(current_price - offset, current_price * 0.5)
    upper_price = current_price + offset

    return GridRangeSuggestion(
        lower_price = round(lower_price, 4),
        upper_price = round(upper_price, 4),
        method      = "atr",
        description = (
            f"ATR-basiert: aktueller Preis +/- {multiplier}x ATR "
            f"({round(atr_usdt, 2)} USDT)"
        ),
    )


def _suggest_bb_range(
    df:            pd.DataFrame,
    current_price: float,
) -> GridRangeSuggestion:
    """Bollinger-Band-basierte Range-Berechnung."""
    from src.analysis.indicators import calculate_bollinger_bands
    bb = calculate_bollinger_bands(df, period=20)

    lower_price = float(bb["bb_lower"].iloc[-1])
    upper_price = float(bb["bb_upper"].iloc[-1])

    # Sicherheitspuffer: min. 5% Abstand zum aktuellen Preis
    lower_price = min(lower_price, current_price * 0.95)
    upper_price = max(upper_price, current_price * 1.05)

    return GridRangeSuggestion(
        lower_price = round(lower_price, 4),
        upper_price = round(upper_price, 4),
        method      = "bb",
        description = "Bollinger-Band-basiert: unteres bis oberes Band (20 Perioden)",
    )


def _suggest_pct_range(current_price: float) -> GridRangeSuggestion:
    """Prozentuale Range-Berechnung (Fallback)."""
    pct         = DEFAULT_GRID_RANGE_PCT / 100
    lower_price = current_price * (1 - pct)
    upper_price = current_price * (1 + pct)

    return GridRangeSuggestion(
        lower_price = round(lower_price, 4),
        upper_price = round(upper_price, 4),
        method      = "pct",
        description = f"Prozentual: aktueller Preis +/- {DEFAULT_GRID_RANGE_PCT}%",
    )


# ---------------------------------------------------------------------------
# Gewinn-Vorschau
# ---------------------------------------------------------------------------

def calculate_profit_preview(
    grid_lines: list[float],
    fee_rate:   float = DEFAULT_FEE_RATE,
) -> list[dict]:
    """
    Berechnet den erwarteten Gewinn pro Grid nach Fees.

    Ein Grid-Zyklus besteht aus einem Kauf am unteren Level und
    einem Verkauf am oberen Level. Der Gewinn ergibt sich aus der
    Preisdifferenz abzueglich zweier Gebuehren (Kauf + Verkauf).

    Args:
        grid_lines: Liste der Grid-Preise
        fee_rate  : Gebuehrenrate pro Trade

    Returns:
        Liste von Dictionaries:
            buy_price  : Kaufpreis (unteres Level)
            sell_price : Verkaufspreis (oberes Level)
            profit_pct : Gewinn in % nach Fees
            profit_usdt: Gewinn in USDT pro 1 USDT Investment
            is_profitable: True wenn Gewinn > 0
    """
    preview = []
    for i in range(len(grid_lines) - 1):
        buy_price  = grid_lines[i]
        sell_price = grid_lines[i + 1]

        gross_return = (sell_price - buy_price) / buy_price
        total_fees   = 2 * fee_rate
        net_return   = gross_return - total_fees

        preview.append({
            "buy_price":    round(buy_price,  4),
            "sell_price":   round(sell_price, 4),
            "profit_pct":   round(net_return * 100, 4),
            "profit_usdt":  round(net_return, 6),
            "is_profitable": net_return > 0,
        })

    return preview


# ---------------------------------------------------------------------------
# Validierung
# ---------------------------------------------------------------------------

def _validate_grid_params(
    lower_price: float,
    upper_price: float,
    num_grids:   int,
) -> None:
    """
    Validiert Grid-Parameter und wirft ValueError bei ungueltigem Input.

    Args:
        lower_price: Untere Preisgrenze
        upper_price: Obere Preisgrenze
        num_grids  : Anzahl Grids
    """
    if lower_price <= 0:
        raise ValueError(f"Untere Preisgrenze muss > 0 sein (war: {lower_price})")
    if upper_price <= lower_price:
        raise ValueError(
            f"Obere Preisgrenze ({upper_price}) muss > untere ({lower_price}) sein"
        )
    if not MIN_NUM_GRIDS <= num_grids <= MAX_NUM_GRIDS:
        raise ValueError(
            f"Anzahl Grids muss zwischen {MIN_NUM_GRIDS} und {MAX_NUM_GRIDS} liegen "
            f"(war: {num_grids})"
        )


def validate_grid_config(
    lower_price:      float,
    upper_price:      float,
    num_grids:        int,
    total_investment: float,
    fee_rate:         float = DEFAULT_FEE_RATE,
) -> tuple[bool, list[str]]:
    """
    Prueft ob eine Grid-Konfiguration sinnvoll ist.

    Args:
        lower_price     : Untere Preisgrenze
        upper_price     : Obere Preisgrenze
        num_grids       : Anzahl Grids
        total_investment: Gesamtinvestition in USDT
        fee_rate        : Gebuehrenrate

    Returns:
        Tuple (is_valid, warnings):
            is_valid: True wenn Konfiguration grundsaetzlich gueltig
            warnings: Liste von Warnmeldungen
    """
    warnings = []
    is_valid = True

    try:
        _validate_grid_params(lower_price, upper_price, num_grids)
    except ValueError as e:
        return False, [str(e)]

    grid_lines      = calculate_grid_lines(lower_price, upper_price, num_grids)
    profit_per_grid = _calculate_profit_per_grid(grid_lines, fee_rate)
    usdt_per_grid   = total_investment / num_grids

    if profit_per_grid <= 0:
        warnings.append(
            f"Gewinn pro Grid negativ ({profit_per_grid:.4f}%). "
            f"Gebuehren hoeher als Grid-Abstand – mehr Grids oder groessere Range waehlen."
        )
        is_valid = False

    if usdt_per_grid < 10:
        warnings.append(
            f"Weniger als 10 USDT pro Grid ({usdt_per_grid:.2f} USDT). "
            f"Mindestorder koennte nicht erfuellt werden."
        )

    range_pct = (upper_price - lower_price) / lower_price * 100
    if range_pct < 5:
        warnings.append(
            f"Sehr enge Grid-Range ({range_pct:.1f}%). "
            f"Empfehlung: mindestens 10% Range."
        )

    return is_valid, warnings


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def _calculate_avg_spacing(grid_lines: list[float]) -> float:
    """Berechnet den durchschnittlichen Abstand zwischen Grid-Linien."""
    if len(grid_lines) < 2:
        return 0.0
    spacings = [grid_lines[i+1] - grid_lines[i] for i in range(len(grid_lines)-1)]
    return float(np.mean(spacings))


def _calculate_profit_per_grid(
    grid_lines: list[float],
    fee_rate:   float,
    mode:       str = "arithmetic",
) -> float:
    """
    Berechnet den durchschnittlichen Nettogewinn pro Grid in %.

    Args:
        grid_lines: Liste der Grid-Preise
        fee_rate  : Gebuehrenrate pro Trade
        mode      : Grid-Modus (fuer Dokumentation)

    Returns:
        Durchschnittlicher Nettogewinn pro Grid in %
    """
    if len(grid_lines) < 2:
        return 0.0

    profits = []
    for i in range(len(grid_lines) - 1):
        gross = (grid_lines[i+1] - grid_lines[i]) / grid_lines[i]
        net   = gross - 2 * fee_rate
        profits.append(net * 100)

    return float(np.mean(profits))