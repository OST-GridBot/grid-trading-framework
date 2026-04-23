# Grid-Trading-Framework

> **Bachelorarbeit OST – Ostschweizer Fachhochschule**  
> Autor: Enes Eryilmaz | Betreuer: SOM-LEWI  
> *Grid-Bots als Investitionsinstrument für Krypto-Anlagen: Analyse, Optimierung und Implementierung*

**Live Demo:** [grid-bot-ost.streamlit.app](https://grid-bot-ost.streamlit.app)

---

## Inhaltsverzeichnis

1. [Projektbeschreibung](#projektbeschreibung)
2. [Features](#features)
3. [Architektur](#architektur)
4. [Projektstruktur](#projektstruktur)
5. [Installation](#installation)
6. [Konfiguration](#konfiguration)
7. [Verwendung](#verwendung)
8. [Optionale Funktionen](#optionale-funktionen)
9. [Kennzahlen](#kennzahlen)
10. [Deployment](#deployment)

---

## Projektbeschreibung

Dieses Framework implementiert einen vollständigen Grid-Trading-Bot für Kryptowährungen auf Basis der Binance API. Es deckt drei Betriebsmodi ab:

- **Backtesting** – Historische Simulation mit vollständiger Kennzahlenberechnung
- **Paper Trading** – Echtzeit-Simulation ohne echtes Kapital (Multi-Bot-System)
- **Live Trading** – Anbindung an Binance Spot-Markt *(in Entwicklung)*

### Was ist ein Grid-Bot?

Ein Grid-Bot platziert automatisch Kauf- und Verkaufsorders in gleichmässigen Preisabständen innerhalb einer definierten Range. Bei jeder Preisbewegung durch eine Grid-Linie wird ein Trade ausgeführt. Der Gewinn entsteht durch die Preisdifferenz zwischen Kauf- und Verkaufslevel abzüglich Gebühren.

---

## Features

### Backtesting
- Simulation über beliebige historische Zeiträume (Binance Klines API)
- 14 Risiko- und Performancekennzahlen
- Buy & Hold Vergleich
- Multi-Coin Backtesting
- Grid-Anzahl Optimierung (Sharpe, ROI, Calmar, Min. Drawdown)
- Interaktiver Chart mit Grid-Linien und Trade-Markern

### Paper Trading
- Multi-Bot System (bis zu 10 Bots gleichzeitig)
- Persistente Bot-States (JSON-Dateien)
- Echtzeit-Preisaktualisierung via Binance API
- Vollständige Metriken wie im Backtesting
- Trade-Log mit Timestamp, Preis, Menge und Gewinn

### Coin Scanner
- Top-100 Coins nach Marktkapitalisierung
- ATR-basierte Volatilitätsanalyse
- ADX-basierte Regime-Erkennung
- Grid-Eignung Score pro Coin

---

## Architektur
Streamlit UI (Home.py + pages/)
│
├── Backtesting Engine (src/backtesting/)
│       └── simulate_grid_bot() → GridBot
│
├── Paper Trading (src/trading/)
│       ├── BotStore (Persistenz)
│       └── BotRunner (Logik)
│
├── Grid-Bot Kernlogik (src/strategy/)
│       ├── GridBot (process_candle, FIFO-Inventar)
│       └── GridBuilder (arithmetic, geometric, asymmetric)
│
├── Marktdaten (src/data/)
│       ├── Binance API (fetch_klines_df)
│       └── Cache Manager (CSV-Append-Strategie)
│
└── Analyse (src/analysis/)
├── Indikatoren (ATR, ADX, Bollinger)
└── Regime-Erkennung (detect_regime)

---

## Projektstruktur
grid-trading-framework/
├── Home.py                          # Streamlit Router + Cockpit
├── requirements.txt                 # Python Dependencies
├── runtime.txt                      # Python Version (Streamlit Cloud)
├── .env                             # API Keys (lokal, nie committed)
│
├── pages/
│   ├── page_market.py               # Cockpit / Live Chart
│   ├── page_backtesting.py          # Backtesting Interface
│   ├── page_scanner.py              # Coin Scanner
│   ├── page_paper_trading.py        # Paper Trading Multi-Bot
│   └── page_live_trading.py         # Live Trading (Stub)
│
├── src/
│   ├── metrics.py                   # 14 Performancekennzahlen
│   ├── strategy/
│   │   ├── grid_bot.py              # GridBot Kernlogik
│   │   └── grid_builder.py          # Grid-Linien Berechnung
│   ├── backtesting/
│   │   ├── engine.py                # run_backtest()
│   │   └── optimizer.py             # Grid-Anzahl Optimierung
│   ├── trading/
│   │   ├── bot_store.py             # Bot Persistenz (JSON)
│   │   ├── engine.py                # BotRunner
│   │   └── paper_broker.py          # Paper Trading Broker
│   ├── data/
│   │   ├── binance_api.py           # Binance Klines API
│   │   └── cache_manager.py         # CSV Cache (Append-Strategie)
│   └── analysis/
│       ├── indicators.py            # ATR, ADX, Bollinger Bands
│       └── regime.py                # Marktregime-Erkennung
│
├── components/
│   ├── chart.py                     # Plotly Charts
│   └── metrics_display.py           # Metriken UI-Komponenten
│
└── config/
└── settings.py                  # Globale Konfiguration

---

## Installation

### Voraussetzungen

- Python 3.9+
- Binance Account (für API Keys)
- Git

### Lokale Installation

```bash
# Repository klonen
git clone https://github.com/OST-GridBot/grid-trading-framework.git
cd grid-trading-framework

# Virtuelle Umgebung erstellen
python3 -m venv venv
source venv/bin/activate  # macOS/Linux
# venv\Scripts\activate   # Windows

# Dependencies installieren
pip install -r requirements.txt

# Umgebungsvariablen konfigurieren
cp .env.example .env
# .env mit API Keys befüllen (siehe Konfiguration)

# App starten
streamlit run Home.py
```

---

## Konfiguration

### API Keys (.env)

Erstelle eine `.env` Datei im Projektroot:

```env
BINANCE_API_KEY=dein_binance_api_key
BINANCE_SECRET_KEY=dein_binance_secret_key
CMC_API_KEY=dein_coinmarketcap_api_key
```

**Binance API Berechtigungen:**
- ✅ Enable Reading (Pflicht)
- ✅ Enable Spot Trading (für Live Trading)
- ❌ Enable Withdrawals (niemals aktivieren)

### Globale Einstellungen (config/settings.py)

```python
DEFAULT_NUM_GRIDS   = 10       # Standard Anzahl Grids
DEFAULT_GRID_MODE   = "arithmetic"
DEFAULT_FEE_RATE    = 0.001    # 0.1% Binance Gebühr
DEFAULT_RESERVE_PCT = 0.03     # 3% Kapitalreserve
```

---

## Verwendung

### Backtesting

1. Streamlit App starten: `streamlit run Home.py`
2. Navigation → **Backtesting**
3. Coin, Intervall und Zeitraum wählen
4. Grid-Parameter konfigurieren (Grenzen, Anzahl Grids, Modus)
5. Optionale Funktionen aktivieren (Recentering, Trailing, ATR, etc.)
6. **Simulation starten** klicken
7. Ergebnisse in Chart, Equity-Kurve und Metriken analysieren

### Paper Trading

1. Navigation → **Paper Trading**
2. **Neuer Bot** → Parameter konfigurieren
3. Bot erstellen und starten
4. **Preis aktualisieren** klicken um neue Kerzen zu verarbeiten
5. Metriken und Trade-Log in Bot-Detailansicht einsehen

---

## Optionale Funktionen

Alle optionalen Funktionen können unabhängig voneinander aktiviert werden und sind vollständig kombinierbar.

### Stop-Loss
Stoppt den Bot automatisch bei definiertem Portfolio-Verlust.
Parameter: stop_loss_pct (5%–50%)

### Re-Centering
Grid wird reaktiv neu zentriert wenn der Preis die Grenzen überschreitet.
Parameter: enable_recentering, recenter_threshold (1%–20%)
Hinweis: Nicht kombinierbar mit Grid Trailing

### Asymmetrische Grids
Ungleiche Grid-Abstände für mehr Aktivität in bestimmten Preiszonen.
Modi: arithmetic, geometric, asymmetric_bottom, asymmetric_top

### Variable Ordergrössen
Unterschiedliches Kapital pro Grid-Level — mehr Kapital unten, weniger oben.
Parameter: weight_bottom (1x–5x), weight_top (0x–1x)

### Drawdown-Drosselung
Reduziert Ordergrösse automatisch bei steigendem Portfolio-Verlust.
Parameter: dd_threshold_1 (-10% → 50%), dd_threshold_2 (-20% → 25%)

### Grid Trailing
Grid folgt dem Preis diskret (1 Grid-Schritt pro Auslösung) nach oben oder unten.
Parameter: enable_trailing_up, enable_trailing_down
trailing_up_stop, trailing_down_stop
Hinweis: Re-Centering wird deaktiviert wenn Trailing aktiv

### Volatilitätsbasierte Grid-Anpassung (ATR)
Grid-Range wird automatisch basierend auf der ATR berechnet.
Parameter: enable_atr_adjust, atr_multiplier (0.5x–5x)
Formel: Grid-Abstand = ATR × Multiplikator

### Regime-Erkennung
Erkennt Range- vs. Trendmarkt und zeigt farbige Warnung an (kein automatischer Eingriff).
Indikatoren: ADX14, ADX30, Bollinger Band Breite, Preis vs. SMA
Grün = Range, Rot = Trend, Orange = Unklar

---

## Kennzahlen

| Kennzahl | Beschreibung | Gut wenn |
|---|---|---|
| ROI | Gesamtrendite in % | > 0% |
| CAGR | Annualisierte Rendite | > 10% |
| Sharpe Ratio | Risikoadjustierte Rendite | ≥ 1.0 |
| Calmar Ratio | CAGR / Max Drawdown | ≥ 1.0 |
| Max Drawdown | Grösster Peak-to-Trough Verlust | < 20% |
| Win-Rate | Anteil profitabler Trades | > 50% |
| Profit-Faktor | Bruttogewinn / Bruttoverlust | ≥ 1.5 |
| Grid Efficiency | Anteil aktiver Grid-Levels | > 50% |
| Ø Profit/Trade | Durchschnittlicher Gewinn pro Trade | > 0 |
| Buy & Hold | Vergleich mit passiver Strategie | Bot > BnH |

---

## Deployment

### Streamlit Community Cloud

1. Repository auf GitHub public machen
2. Auf [share.streamlit.io](https://share.streamlit.io) einloggen
3. Repository `OST-GridBot/grid-trading-framework` auswählen
4. Main file: `Home.py`
5. **Secrets** konfigurieren:
```toml
BINANCE_API_KEY = "dein_api_key"
BINANCE_SECRET_KEY = "dein_api_secret"
CMC_API_KEY = "dein_cmc_key"
```

### Sicherheitshinweise

- Die `.env` Datei wird nie committed (in `.gitignore`)
- API Keys werden ausschliesslich via `os.getenv()` geladen
- Withdraw-Rechte auf Binance niemals aktivieren
- Für Cloud-Deployment: separaten Read-Only API Key verwenden

---

## Lizenz

Dieses Projekt wurde im Rahmen einer Bachelorarbeit an der OST – Ostschweizer Fachhochschule erstellt. Alle Rechte vorbehalten.

---

*Erstellt mit Python 3.9 · Streamlit · Binance API · TradingView Lightweight Charts*
