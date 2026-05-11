# CLAUDE.md — Grid-Trading-Framework

Bachelorarbeit OST. Streamlit-App zur Analyse und Optimierung von Grid-Trading-Bots
im Krypto-Spot-Markt. Single-User-App, lokal auf macOS.

---

## Hauptaufgabe von Claude

**Code-Konsolidierung und Qualitätssicherung.** Konkret:

- Redundanzen aufspüren und entfernen (gleiche Logik an mehreren Stellen, doppelte Berechnungen, parallele Implementierungen)
- Inkonsistenzen beseitigen (z.B. unterschiedliche Schlüsselnamen für dasselbe Konzept zwischen Modulen)
- Code sauberer, effizienter und qualitativ hochwertiger machen — bei gleichbleibender Korrektheit
- Klare Verantwortlichkeiten zwischen Modulen herstellen (eine Sache, eine Stelle)

**Konkrete Aufträge kommen vom User** (Aufgabe für Aufgabe). Claude geht nicht eigenmächtig auf Refactoring-Tour.

**Aber:** Wenn Claude während einer Aufgabe Redundanzen, Bugs oder Inkonsistenzen ausserhalb des aktuellen Auftrags bemerkt, soll er sie **kurz melden** (1-2 Sätze, am Ende der Antwort). Nicht eigenmächtig fixen. Der User entscheidet ob daraus eine neue Aufgabe wird.

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

1. **Lese-Befehle (`cat`, `ls`, `grep`, `find`, `git status`, `git diff`, `git log`) darf Claude selbständig ausführen.** Alles andere — Datei-Änderungen, Datei-Erstellungen, Datei-Löschungen, Bash-Befehle die etwas verändern, Git-Operationen ausser Lesen, Pip-Installationen — **NIEMALS** ohne explizite User-Erlaubnis.

2. **User testet selbst.** Claude startet weder Streamlit noch Bots. Syntax-Checks (`py_compile`, AST) nach Erlaubnis OK.

3. **Aufgaben isoliert halten.** Bei "mach Aufgabe X" nur X ausführen. Verwandte Aufgaben dürfen vorgeschlagen, aber nicht ohne Rückfrage mitgenommen werden.

4. **Sprache: Deutsch.** Code-Kommentare auf Deutsch.

5. **Spot-Markt only.** Kein Futures, keine Hebel-Logik, keine Liquidations-Mechanik.

6. **Branch:** nur `main`. Keine Feature-Branches ohne Erlaubnis.

7. **Commit- und Merge-Workflow:**
   - Nachdem der User initiales "ok" zu einem Sub-Plan gegeben hat UND alle Zwischenschritte während der Bearbeitung einzeln bestätigt wurden, darf Claude Code am Ende selbstständig:
     a) Smoke-Test ausführen
     b) Bei grünem Smoke-Test: `git add` + `git commit`
     c) Bei grünem Commit: lokal nach `main` mergen
   - **Niemals selbstständig pushen.** Vor jedem `git push` muss der User explizit gefragt werden.
   - Bei rotem Smoke-Test: KEIN Commit, sondern dem User melden mit Befund.

8. **Niemals:** API-Keys lesen oder loggen, `.env` lesen, `data/cache/` löschen, Live-Broker ohne Erlaubnis testen.

9. **Antwort-Stil:** knapp, präzise, keine Phasen-Pläne, keine 3-Optionen-Endlosschleifen. Bei Unsicherheit kurz nachfragen statt spekulieren.

---

## Häufig gebrauchte Befehle

```bash
# Umgebung aktivieren (immer zuerst)
source venv/bin/activate

# App starten
streamlit run Home.py

# Syntax-Check einer Datei
python -m py_compile <pfad>

# Git-Status prüfen
git status && git diff
```

---

## User-Profil

Keine umfassende Programmiererfahrung. Schritte präzise erklären, Konsequenzen
benennen, keine Fachbegriffe ohne Erläuterung.