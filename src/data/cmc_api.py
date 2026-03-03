"""
src/data/cmc_api.py
===================
Abruf der Top-100-Coins von der CoinMarketCap API.

Funktionen:
    - get_top100_symbols() : Top-100 Coins abrufen und Stablecoins filtern
    - update_top100_cache(): Cache aktualisieren (API + Binance-Check)

Kein API-Key der Binance noetig – nur CMC_API_KEY in .env erforderlich.

Autor: Enes Eryilmaz
Projekt: Grid-Trading-Framework (Bachelorarbeit OST)
"""

import requests
from typing import Optional

from config.settings import (
    CMC_API_KEY,
    CMC_BASE_URL,
    CMC_LISTINGS_ENDPOINT,
    CMC_REQUEST_TIMEOUT,
    CMC_TOP_N,
    STABLECOINS,
)
from src.data.cache_manager import (
    load_top100_cache,
    save_top100_cache,
    load_unavailable_coins,
    save_unavailable_coins,
)
from src.data.binance_api import validate_symbol


# ---------------------------------------------------------------------------
# Top-100 Coins abrufen
# ---------------------------------------------------------------------------

def get_top100_symbols(api_key: Optional[str] = None) -> tuple:
    """
    Ruft die Top-100 Coins nach Marktkapitalisierung von CoinMarketCap ab.
    Filtert automatisch Stablecoins heraus (definiert in settings.py).

    Args:
        api_key: CMC API-Key (optional, sonst aus settings.py)

    Returns:
        Tuple (symbols, error):
            symbols: Liste der Coin-Symbole ohne Stablecoins
            error  : Fehlermeldung oder leerer String bei Erfolg

    Beispiel:
        symbols, err = get_top100_symbols()
        # symbols = ["BTC", "ETH", "XRP", ...]
    """
    key = api_key or CMC_API_KEY

    if not key:
        return [], (
            "Kein CMC API-Key gefunden. "
            "Bitte CMC_API_KEY in .env eintragen."
        )

    url     = f"{CMC_BASE_URL}{CMC_LISTINGS_ENDPOINT}"
    headers = {
        "Accepts":           "application/json",
        "X-CMC_PRO_API_KEY": key,
    }
    params = {
        "start":   "1",
        "limit":   str(CMC_TOP_N),
        "convert": "USD",
    }

    try:
        response = requests.get(
            url,
            headers=headers,
            params=params,
            timeout=CMC_REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.Timeout:
        return [], "CMC API-Timeout: Server antwortet nicht."
    except requests.exceptions.ConnectionError:
        return [], "Verbindungsfehler: Keine Internetverbindung."
    except requests.exceptions.HTTPError as e:
        return [], f"HTTP-Fehler: {e}"
    except Exception as e:
        return [], f"Unbekannter Fehler: {e}"

    # Fehlercheck CMC API
    status = data.get("status", {})
    if status.get("error_code", 0) != 0:
        return [], f"CMC API-Fehler: {status.get('error_message', 'Unbekannt')}"

    # Symbole extrahieren und Stablecoins filtern
    raw_symbols = [entry["symbol"] for entry in data.get("data", [])]
    filtered    = [s for s in raw_symbols if s not in STABLECOINS]

    if not filtered:
        return [], "Keine gueltigen Symbole von CMC erhalten."

    return filtered, ""


# ---------------------------------------------------------------------------
# Cache aktualisieren
# ---------------------------------------------------------------------------

def update_top100_cache(
    force:         bool = False,
    check_binance: bool = True,
) -> tuple:
    """
    Aktualisiert den Top-100-Cache.

    Ablauf:
        1. Falls Cache vorhanden und force=False -> Cache zurueckgeben
        2. Sonst -> CMC API aufrufen
        3. Optional: Binance-Verfuegbarkeit pruefen
        4. Ergebnis cachen

    Args:
        force        : True = Cache ignorieren, immer neu laden
        check_binance: True = Nur Binance-handelbare Coins zurueckgeben

    Returns:
        Tuple (symbols, error):
            symbols: Liste verfuegbarer Coin-Symbole
            error  : Fehlermeldung oder leerer String bei Erfolg
    """
    # Cache verwenden falls vorhanden
    if not force:
        cached = load_top100_cache()
        if cached:
            print(f"Top100-Cache geladen: {len(cached)} Coins")
            return cached, ""

    # Frische Daten von CMC holen
    print("Lade Top-100 Coins von CoinMarketCap...")
    symbols, err = get_top100_symbols()

    if err or not symbols:
        # Fallback: alten Cache verwenden
        fallback = load_top100_cache()
        if fallback:
            print(f"CMC-Fehler - verwende alten Cache ({len(fallback)} Coins)")
            return fallback, ""
        return [], err or "Keine Symbole verfuegbar."

    # Binance-Verfuegbarkeit pruefen
    if check_binance:
        symbols = _filter_binance_available(symbols)

    # Cache speichern
    if symbols:
        save_top100_cache(symbols)
        print(f"Top100-Cache aktualisiert: {len(symbols)} Coins")

    return symbols, ""


# ---------------------------------------------------------------------------
# Hilfsfunktion: Binance-Verfuegbarkeit pruefen
# ---------------------------------------------------------------------------

def _filter_binance_available(symbols: list) -> list:
    """
    Filtert Coins heraus, die nicht auf Binance Spot handelbar sind.
    Verwendet lokale Blacklist um wiederholte API-Aufrufe zu vermeiden.

    Args:
        symbols: Liste der Coin-Symbole

    Returns:
        Gefilterte Liste nur mit Binance-verfuegbaren Coins
    """
    unavailable       = load_unavailable_coins()
    available         = []
    newly_unavailable = set()

    for symbol in symbols:
        if symbol in unavailable:
            continue

        is_valid, _ = validate_symbol(symbol)

        if is_valid:
            available.append(symbol)
        else:
            print(f"  Nicht auf Binance verfuegbar: {symbol}")
            newly_unavailable.add(symbol)

    # Blacklist aktualisieren
    if newly_unavailable:
        updated = unavailable | newly_unavailable
        save_unavailable_coins(updated)
        print(f"Blacklist aktualisiert: {sorted(newly_unavailable)}")

    return available