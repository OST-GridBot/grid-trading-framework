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
from typing import Optional

from config.settings import (
    DEFAULT_NUM_GRIDS,
    DEFAULT_GRID_MODE,
    DEFAULT_FEE_RATE,
    DEFAULT_MIN_NOTIONAL,
    MIN_NUM_GRIDS,
    MAX_NUM_GRIDS,
)
from src.analysis.indicators import get_atr_stats


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


def extrapolate_grid_above(
    grid_lines: list,
    grid_mode:  str,
    max_price:  float,
) -> list:
    """
    Extrapoliert Grid-Linien oberhalb der hoechsten aktiven Linie bis
    max_price. Genutzt fuer die Vorschau-Darstellung im Chart, wenn
    Trailing-Up oder Recentering aktiv ist (Auftrag D).

    Step-Berechnung mode-abhaengig:
        arithmetic / asymmetric_*: linearer letzter Step
            (grid_lines[-1] - grid_lines[-2])
        geometric: gleicher Ratio
            (grid_lines[-1] / grid_lines[-2])

    Args:
        grid_lines : sortierte Liste aktiver Linien (mind. 2 Elemente)
        grid_mode  : "arithmetic" / "geometric" / "asymmetric_bottom" /
                     "asymmetric_top"
        max_price  : Obergrenze fuer die Extrapolation (z.B.
                     trailing_up_stop oder upper * 1.20)

    Returns:
        Liste extrapolierter Preise > grid_lines[-1] und <= max_price.
        Leer wenn Input unzureichend oder max_price <= grid_lines[-1].
    """
    if not grid_lines or len(grid_lines) < 2:
        return []
    last = float(grid_lines[-1])
    if max_price <= last:
        return []

    out: list = []
    if grid_mode == "geometric":
        prev = float(grid_lines[-2])
        if prev <= 0:
            return []
        ratio = last / prev
        if ratio <= 1.0:
            return []
        cur = last * ratio
        # Hard limit gegen unendliche Schleifen
        for _ in range(500):
            if cur > max_price:
                break
            out.append(cur)
            cur = cur * ratio
    else:
        # arithmetic + asymmetric_*: linearer letzter Step
        step = last - float(grid_lines[-2])
        if step <= 0:
            return []
        cur = last + step
        for _ in range(500):
            if cur > max_price:
                break
            out.append(cur)
            cur += step
    return out


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


def validate_min_investment(
    total_investment: float,
    num_grids:        int,
    reserve_pct:      float = 0.0,
    min_notional:     float = DEFAULT_MIN_NOTIONAL,
) -> Optional[str]:
    """
    Z.X2: Prueft ob das Investment fuer die gewaehlte Konfiguration
    ausreicht. Binance Spot erfordert pro Order >= min_notional USDT
    (NOTIONAL-Filter). Fuer einen Grid-Bot heisst das:

        base_amount = total × (1 − reserve_pct) / num_grids >= min_notional

    Args:
        total_investment : Geplantes Investment in USDT
        num_grids        : Anzahl Grid-Intervalle
        reserve_pct      : Kapitalreserve (0.0 – 1.0)
        min_notional     : Mindestbetrag pro Order (Default 5 USDT,
                           Binance-Standard fuer USDT-Paare)

    Returns:
        Fehler-String mit konkretem Mindestbetrag, oder None wenn OK.
    """
    if num_grids <= 0:
        return None  # andere Validation faengt das ab
    effective   = float(total_investment) * (1.0 - float(reserve_pct or 0.0))
    base_amount = effective / num_grids
    if base_amount >= min_notional:
        return None
    # Erforderliches Minimum berechnen
    required = (min_notional * num_grids) / (1.0 - float(reserve_pct or 0.0))
    return (
        f"Investment zu niedrig: {total_investment:.2f} USDT bei "
        f"{num_grids} Grids und {reserve_pct*100:.0f}% Reserve ergibt "
        f"{base_amount:.2f} USDT pro Grid (Binance-Minimum: "
        f"{min_notional:.0f} USDT). Mindestens "
        f"{required:.2f} USDT erforderlich."
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

    usdt_per_grid = total_investment / num_grids

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
# ATR-basierte Grid-Anzahl-Vorschlaege
# ---------------------------------------------------------------------------

def suggest_atr_grid_counts(
    df:          pd.DataFrame,
    range_usdt:  float,
    multipliers: Optional[list] = None,
) -> dict:
    """
    Schlaegt Grid-Anzahlen basierend auf ATR vor.

    Fuer jeden Multiplikator wird berechnet, wie viele Grids in die gegebene
    Range passen, wenn der Grid-Abstand = ATR × Multiplikator betraegt.

    Args:
        df          : OHLCV-DataFrame fuer die ATR-Berechnung
        range_usdt  : Grid-Range in USDT (upper - lower)
        multipliers : Liste der ATR-Multiplikatoren (Default: [0.5, 1.0, 1.5])

    Returns:
        dict mit:
            atr_usdt    : ATR-Wert in USDT
            suggestions : dict {multiplier: grid_count} fuer jeden Multiplikator
    """
    if multipliers is None:
        multipliers = [0.5, 1.0, 1.5]

    atr_usdt, _ = get_atr_stats(df)
    if atr_usdt <= 0 or range_usdt <= 0:
        return {"atr_usdt": atr_usdt, "suggestions": {m: 0 for m in multipliers}}

    return {
        "atr_usdt":    atr_usdt,
        "suggestions": {
            m: max(2, round(range_usdt / (atr_usdt * m))) for m in multipliers
        },
    }