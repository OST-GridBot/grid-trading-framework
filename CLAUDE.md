# CLAUDE.md — Grid-Trading-Framework

Bachelorarbeit OST. Streamlit-App zur Analyse und Optimierung von Grid-Trading-Bots
im Krypto-Spot-Markt. Single-User-App, lokal auf macOS.

---

## Hauptaufgabe von Claude

**Code-Entwicklung, Konsolidierung und Qualitätssicherung.** Konkret:

- Neue Funktionalität implementieren auf Basis konkreter Aufträge vom User
- Redundanzen aufspüren und entfernen (gleiche Logik an mehreren Stellen, doppelte Berechnungen, parallele Implementierungen)
- Inkonsistenzen beseitigen (z.B. unterschiedliche Schlüsselnamen für dasselbe Konzept zwischen Modulen)
- Code sauberer, effizienter und qualitativ hochwertiger machen — bei gleichbleibender Korrektheit
- Klare Verantwortlichkeiten zwischen Modulen herstellen (eine Sache, eine Stelle)

**Konkrete Aufträge kommen vom User** (Aufgabe für Aufgabe). Claude geht nicht eigenmächtig auf Refactoring-Tour.

**Aber:** Wenn Claude während einer Aufgabe Redundanzen, Bugs oder Inkonsistenzen ausserhalb des aktuellen Auftrags bemerkt, soll er sie **kurz melden** (1-2 Sätze, am Ende der Antwort). Nicht eigenmächtig fixen. Der User entscheidet ob daraus eine neue Aufgabe wird.

---

## Aktuelle Phase: Live-Trading-Implementation

Nach Abschluss von 9 Auftrags-Paketen (M, N, R, O, P, Q, S, T, U) und 3 Initial-Buy-Bug-Fixes (B-1, B-2, B-3) folgt nun der Live-Trading-Ausbau.

**Architektur-Entscheidungen:**
- Echte Binance-Production-API (kein Testnet, echtes Geld)
- LIMIT-Orders auf Grid-Linien (Binance-Grid-Bot-Standard)
- Hintergrund-Worker als eigenständiger Python-Process
- Plattformunabhängig (macOS / Windows / Linux)

**Erhalt bestehender Funktionalität:**
- BT und PT bleiben unverändert
- Alle 9 Pakete und alle 3 Bug-Fixes müssen weiter funktionieren
- Nur LT-Pfad wird erweitert

---

## Tech-Stack

- Python 3 (venv im Repo unter `venv/`)
- Streamlit (Web-UI)
- pandas, numpy (Datenverarbeitung)
- Binance Spot API (Preisdaten + Live-Trading)
- Lightweight Charts™ v4.2.0 via CDN (Chart-Komponente)
- Persistenz: JSON-Dateien unter `data/cache/`, keine DB

---

## Projektstruktur

- `Home.py` — Streamlit-Einstieg
- `pages/` — alle UI-Seiten (Cockpit, Backtesting, Paper/Live Trading, Scanner, Chart-Test)
- `components/` — wiederverwendbare UI-Komponenten (z.B. Chart V2, Metrics-Display)
- `src/strategy/` — Bot-Kernlogik (`grid_bot.py`, `grid_builder.py`)
- `src/backtesting/` — Backtest-Engine + Optimizer
- `src/trading/` — Paper- und Live-Trading-Engine, Bot-Store, Broker
- `src/metrics.py` — zentrale Kennzahlen-Berechnungen
- `src/analysis/` — Indikatoren, Regime-Erkennung
- `src/scanner/` — Coin-Scanner
- `config/` — Settings, Defaults
- `data/cache/` — Bot-States, Preisdaten-Cache

---

## Verbindliche Regeln

### 1. Lese-Befehle — selbstständig erlaubt

Nach dem initialen "ok" zu einem Mini-Plan darf Claude alle Lese-Befehle selbstständig und so oft wie nötig ausführen, ohne erneutes Nachfragen:

- `cat`, `head`, `tail`, `less`, `view`
- `ls`, `find`, `tree`
- `grep`, `rg`, `ripgrep`
- `git status`, `git diff`, `git log`, `git show`, `git branch`
- `python -m py_compile <pfad>` (Syntax-Check)
- AST-basierte Code-Inspektion

**Niemals ohne explizite Erlaubnis:** Datei-Änderungen, Datei-Erstellungen, Datei-Löschungen, Bash-Befehle die etwas verändern, Git-Schreib-Operationen, pip-installationen, Network-Calls.

### 2. User testet selbst

Claude startet weder Streamlit noch Bots noch den Live-Worker. Smoke-Tests in /tmp sind nach Mini-Plan-OK erlaubt.

### 3. Aufgaben isoliert halten

Bei "mach Aufgabe X" nur X ausführen. Verwandte Aufgaben dürfen vorgeschlagen, aber nicht ohne Rückfrage mitgenommen werden.

### 4. Sprache und Schreibweise (user-sichtbare Strings)

**Schweizer Schreibweise: kein deutsches ß, sondern ss.**

- "muss" (nicht "muß")
- "grösser" (nicht "größer")
- "ausserhalb" (nicht "außerhalb")
- "Strasse" (nicht "Straße")

**Korrekte Umlaute:** ö, ä, ü (nicht oe/ae/ue).

- "für" (nicht "fuer")
- "über" (nicht "ueber")
- "Gebühr" (nicht "Gebuehr")

**Status-Bezeichnungen Englisch konsistent:**
- Mechanismen: `active` / `inactive` / `triggered` / `not triggered` / `never triggered` (kleinschrift)
- Bot-Lebenszyklus: `Running` / `Stopped` / `Waiting for Trigger` / `Paused` / `Completed` / `Error` (Title Case)

**Code-Kommentare:** Deutsch, frei in der Schreibweise (oe/ae/ue ok in Kommentaren).

### 5. Spot-Markt only

Kein Futures, keine Hebel-Logik, keine Liquidations-Mechanik.

### 6. Branch

Nur `main`. Keine Feature-Branches ohne Erlaubnis.

### 7. Mini-Plan-Workflow und Commit-Strategie

**Pro Auftrag:**

a) Mini-Plan vorlegen mit:
- konkreten Code-Stellen
- **Betriebsmodi-Analyse** (BT / PT / LT — welche Modi sind betroffen, gibt es Unterschiede)
- **Mehrere Smoke-Tests** (Standard, Edge-Cases, Backward-Compat, Modus-Vergleich)
- Cascade-Wirkung auf bestehende Komponenten
- Commit-Strategie

b) ok abwarten

c) Autonom ausführen:
- Lese-Befehle (siehe Regel 1) frei
- Implementation gemäss Mini-Plan
- Smoke-Tests durchführen

d) Bei grünem Smoke-Test:
- `git add` + `git commit`
- Lokal nach `main` mergen

e) **Niemals selbstständig pushen.** Vor jedem `git push` User explizit fragen.

f) Bei rotem Smoke-Test:
- KEIN Commit
- User mit Befund melden

**Bei grösseren Phasen (mehrere Sub-Aufträge):**
- Vollumfänglicher Regression-Smoke-Test über alle bisherigen Pakete am Ende der Phase

### 8. Betriebsmodi pro Auftrag explizit klären

Pro Auftrag analysieren welche Modi betroffen sind:

- **BT** (Backtest): historische Daten, kein API-Call, Trades simuliert
- **PT** (Paper-Trading): live Preise von Binance, simulierte Trades, keine echten Orders
- **LT** (Live-Trading): live Preise, echte Orders an Binance via API

**Wenn Modi unterschiedlich betroffen:** separate Implementierung oder klare Begründung warum identisch.

**Beispiele für Modus-Differenzen:**
- aktueller Preis (PT/LT: API-Call) vs Referenzpreis (BT: df.iloc-Zugriff)
- echte Orders (LT) vs Simulation (BT/PT)
- Inventar-Resync mit Binance (LT) vs lokaler State (BT/PT)

### 9. Plattformunabhängigkeit

Code muss auf **macOS, Windows und Linux** gleich funktionieren.

**Verboten:**
- Plattformspezifische Services (systemd, launchd, Windows Services)
- Plattformspezifische Pfad-Syntax mit hardcoded Slashes
- OS-spezifische Befehle ohne Fallback

**Erlaubt/Bevorzugt:**
- `pathlib.Path` für Pfade
- Reine Python-Scripts startbar via Terminal
- Subprocess mit cross-platform Befehlen

### 10. Live-Trading-spezifische Regeln

**Binance-Integration:**
- Echte Binance-Production-API (kein Testnet)
- LIMIT-Orders auf Grid-Linien
- exchangeInfo-Validierung pro Symbol (LOT_SIZE, MIN_NOTIONAL, tickSize, stepSize)
- recvWindow + Server-Time-Sync
- Permissions-Check (canTrade, canWithdraw-Warning)

**Order-Management:**
- clientOrderId als UUID für Idempotenz
- Partial-Fill-Aggregation über alle fills[]
- Echte Fees aus fills[i].commission + commissionAsset
- Cancel-on-Stop für offene LIMIT-Orders

**Hintergrund-Worker:**
- Eigenständiges Python-Script (plattformunabhängig)
- Start/Stop via Terminal
- Robust gegen Netzwerk-Errors, Rate-Limits, Exceptions
- Saubere Beendigung über Ctrl+C: offene LIMIT-Orders **nicht canceln**, Bot ruht nur
- Bei nächstem Worker-Start: nahtloser Wiederaufnahme

### 11. Niemals

- API-Keys lesen oder loggen
- `.env` lesen (ausser zur reinen Existenz-Prüfung der Variable, ohne Wert auszugeben)
- `data/cache/` löschen
- Live-Broker ohne Erlaubnis testen
- Echte Orders an Binance ohne explizite User-Bestätigung senden

### 12. Antwort-Stil

Knapp, präzise, keine Phasen-Pläne, keine 3-Optionen-Endlosschleifen. Bei Unsicherheit kurz nachfragen statt spekulieren.

**Anti-Redundanz-Regel (User-Preference):**
- Keine Wiederholung gleicher Info in verschiedenen Formaten
- Keine Zusammenfassung am Ende kurzer Antworten
- Minimal nötige Information

---

## Häufig gebrauchte Befehle

```bash
# Umgebung aktivieren (immer zuerst)
source venv/bin/activate

# App starten
streamlit run Home.py

# Live-Worker starten (Live-Trading)
python live_worker.py

# Syntax-Check einer Datei
python -m py_compile <pfad>

# Git-Status prüfen
git status && git diff
```

---

## Dokumentation für Übergabe

Die BA wird abgegeben mit einem Setup-Guide für den Dozenten. Das Setup-README wächst bei der Live-Trading-Implementation mit.

Zielgruppe: Dozent, technisch versiert, aber kein Vertrauter mit Repo.

Inhalt:
- Setup (Python-Version, venv, Dependencies, .env)
- Binance-API-Key-Anleitung
- Streamlit starten
- Worker starten
- Bedienung (Bot konfigurieren, starten, stoppen)
- Sicherheit (Permissions, IP-Whitelist, kleines Test-Kapital)
- Troubleshooting (Worker-Absturz, Logs, manuelles Order-Cancel)

---

## User-Profil

Keine umfassende Programmiererfahrung. Schritte präzise erklären, Konsequenzen
benennen, keine Fachbegriffe ohne Erläuterung.
