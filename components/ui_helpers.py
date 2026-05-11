"""
components/ui_helpers.py
========================
Zentrale UI-Helper fuer wiederkehrende Layout-Elemente.

Konsolidierung aus Phase 4 (Sub 4.5, Option A — nur byte-identische
Duplikate). Bewusst NICHT enthalten:
    - pages/page_scanner._label    enthaelt zusaetzlich margin-top:0 fuer
                                   den Scanner-Header
    - components/bot_setup_form._label / _caption / _divider
                                   Form-Stil mit eigenen Farben und
                                   Spacings (kompaktere Layout-Variante)

Falls spaeter ein einheitliches Theming gewuenscht ist, wuerden diese
Custom-Varianten in einem separaten Refactor mit variant-Parametern
zusammengefuehrt.

Autor: Enes Eryilmaz
Projekt: Grid-Trading-Framework (Bachelorarbeit OST)
"""


# Standard-Page-Header (PT/LT/Market)
LABEL_STYLE = (
    "font-size:1.15rem; font-weight:600; color:#CBD5E1; "
    "font-family:Inter,-apple-system,sans-serif; text-transform:uppercase; "
    "letter-spacing:0.06em; margin-bottom:4px;"
)


def label(text: str) -> str:
    """Standard-Page-Header-Label (HTML-Snippet)."""
    return f"<div style='{LABEL_STYLE}'>{text}</div>"


# Coin-Auswahlliste (verwendet von Market-Page und bot_setup_form).
# Reihenfolge nach Marktkapitalisierung; Top-20-Coins.
COINS = [
    "BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "DOGE", "AVAX",
    "DOT", "MATIC", "LINK", "UNI", "ATOM", "LTC", "BCH",
    "NEAR", "APT", "OP", "ARB", "FTM",
]
