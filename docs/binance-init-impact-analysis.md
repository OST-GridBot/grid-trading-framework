# Impact-Analyse: Binance-Standard-Init auf bereits erledigte Aufträge

**Stand:** 2026-05-12
**Auslöser:** Commit `849cd76` — `feat(grid_bot): Initial-Setup auf Binance-Standard + Grid Trigger`
**Zweck:** Prüfung ob die Grid-Bot-Umstrukturierung Auswirkungen auf zuvor erledigte Aufgaben hat.

---

## Zusammenfassung

| Aufgabe | Direkte Auswirkung? | Schwere | Aktion nötig? |
|---|---|---|---|
| A — Portfolio-Metriken | ⚠️ Konzeptionell | gering | Optional verfeinern |
| D.1 — Emoji im Titel | ✅ keine | — | nein |
| D.2 — Spalten 5/4 | ✅ keine | — | nein |
| D.3 — Magnet-Marker | ✅ keine | — | nein |
| E — Recentering-Analyse | ⚠️ unvollständig | gering | optional ergänzen |
| F — Trailing-Verifikation | ⚠️ unvollständig | gering | optional ergänzen |
| D.4.1 — Trailing-Linien | ✅ funktioniert weiter | — | nein |
| SL/TP-1..3 | ⚠️ Timing-Nuance | gering | dokumentiert, OK |

Keine Aufgabe ist **gebrochen**. Drei Stellen haben **konzeptionelle Lücken** oder **leichte semantische Verschiebungen**, die der User kennen sollte.

---

## 1 — Auftrag A: Portfolio-Metriken

**Befund:** `_compute_summary_running` (`components/portfolio_view.py:67`) zählt
```python
active_count = sum(1 for v in views if v.get("status") == "running")
```

Das prüft `bot_store.status` (Lebenszyklus: `running`/`stopped`/...), **nicht** den neuen inneren `bot_status` (`waiting_for_trigger`/`active`/`paused`/`stopped`).

**Konsequenz:** Ein PT/LT-Bot, der mit Grid Trigger angelegt wurde, hat `bot_store.status="running"` (Lebenszyklus läuft) UND `bot_status="waiting_for_trigger"` (Mechanik wartet). In der **"Active Bots"-Karte** wird er als aktiv gezählt — obwohl er noch nichts tut.

**Schwere:** gering. Methodisch fragwürdig, aber nicht falsch — der Bot-Runtime ist tatsächlich aktiv (BotRunner-Tick läuft).

**Optionale Verfeinerung:**
```python
active_count = sum(
    1 for v in views
    if v.get("status") == "running"
    and v.get("bot_status") != "waiting_for_trigger"
)
```
Oder Karten-Text erweitern: `"Active Bots: N (M warten)"`.

**Andere Karten** (Best/Worst/Avg ROI, Outperformance B&H) sind nicht betroffen — sie aggregieren `metrics`, das für Trigger-Warte-Bots automatisch leer/0 ist. ✓

---

## 2 — Aufträge D.1, D.2, D.3 (Chart-Einstellungen)

**Befund:** Reine UI-Änderungen (Titel-Text, Spalten-Layout, JS-Marker). Kein Berührungspunkt mit der Bot-Logik.

**Konsequenz:** keine.

---

## 3 — Aufträge E + F: Recentering- und Trailing-Analyse

**Befund:** Der Bericht `docs/recentering-trailing-analysis.md` beschreibt die Mechanik von Recentering (§2) und Trailing (§3). Beide sind **inhaltlich unverändert** durch die Init-Umstellung.

**Was fehlt im Bericht:**
1. **Bot-Lifecycle** — neuer `bot_status` mit den vier Werten (`waiting_for_trigger`/`active`/`paused`/`stopped`).
2. **Grid Trigger** — neuer Auslöser für das Initial-Setup mit Richtungs-Bestimmung beim ersten Candle.
3. **Pufferzone-Konzept** — Init-only Markierung der Linie über dem Initial-Preis, die durch den ersten realen Trade aufgehoben wird.

**Schwere:** gering. Der Bericht ist nicht falsch, nur **unvollständig** hinsichtlich des neuen Lifecycle-Kontexts.

**Optionale Ergänzung:** Neuer Abschnitt §4 oder §5 „Bot-Lifecycle" im bestehenden Bericht. Falls gewünscht, kann ich das in einem kleinen Doc-Commit nachziehen.

---

## 4 — Auftrag D.4.1: Trailing-Stop-Linien im Chart

**Befund:** `tab_chart.py` liest `trailing_up_stop` / `trailing_down_stop` aus `state` (PT/LT) oder `config` (BT, oder Setup-Vorschau). Beide Quellen existieren weiter unverändert.

**Konsequenz:** Funktioniert unverändert auch im `waiting_for_trigger`-Zustand. Die Linien werden gezeichnet, sobald der User Trailing aktiviert hat — als **Vorschau** auf die künftigen Stops. Konsistent zur SL/TP-Visualisierung (Sub SL/TP-3), die ebenfalls aus Config zeichnet, bevor der Bot trade-aktiv ist.

**Schwere:** keine.

---

## 5 — Aufträge SL/TP-1 bis SL/TP-3

**Befund:** SL/TP-Preise werden in `__init__` einmalig berechnet (`stop_loss_price = lower × (1 − sl_pct)` etc.). Sie sind also auch im `waiting_for_trigger`-Status bereits gesetzt.

**Timing der Prüfung:**
- In `process_candle` läuft der SL/TP-Check **erst nach** dem Trigger-Check.
- Im Trigger-Warte-Modus wird `return` ausgeführt, bevor SL/TP-Check erreicht wird → **keine** SL/TP-Auslösung während des Wartens. ✓ Korrekt: kein Inventar, kein realer SL nötig.
- Erste Kerze nach Trigger: `_perform_initial_setup` läuft, dann **derselbe** `process_candle`-Lauf fährt fort und führt SL/TP-Check aus.

**Edge-Case:** Wenn der Preis zur Trigger-Zeit bereits unter `stop_loss_price` liegt (z. B. Range 60k-80k, SL bei 54k, Preis triggert bei 50k), würde der Bot Initial-Setup durchführen und im **gleichen Candle** sofort den SL auslösen. Das ist semantisch korrekt — kann aber überraschen, wenn der User das nicht erwartet.

**Schwere:** gering. Verhalten ist konsistent zur Standard-SL/TP-Logik, nur in einer ungewöhnlichen Zeitfolge.

**Optionale UI-Warnung:** Im Setup-Form könnte eine Warnung erscheinen, wenn `trigger < stop_loss_price` oder `trigger > take_profit_price` gesetzt wird. Nicht jetzt nötig.

---

## 6 — Weitere Beobachtungen (nicht in der Aufgaben-Tabelle, aber relevant)

### 6.1 `num_trades` zählt Initial-Buys mit

In `src/analysis/metrics.py:287` ist `num_trades = len(trade_log)`. Initial-Buys haben `type="BUY"` und stehen im `trade_log` → sie zählen mit.

**Beispiel:** Binance-Beispiel (Range 40k–60k, 5 Grids, Preis 50'100) erzeugt 2 Initial-Buys. Wenn der Bot danach 10 reale Grid-Trades macht, zeigt das UI `num_trades=12` statt `10`.

**Auswirkung auf Metriken:**
- `avg_profit_per_trade`: filtert nach `type=="SELL"` → **nicht betroffen** ✓
- `grid_profit_total_usdt`: filtert nach `type=="SELL"` → **nicht betroffen** ✓
- `fees_paid`: enthält Initial-Buy-Fees (semantisch korrekt, sind real bezahlt)
- `profit_factor`, `sharpe_ratio` etc.: basieren auf Sell-Profits / Returns → **nicht betroffen** ✓
- `num_trades`: **leicht inflationiert** (Cosmetic Issue)

**Optionaler Fix:** `num_trades = len([t for t in trade_log if not t.get("initial")])`. Würde die Anzeige sauberer machen. Kein methodischer Bruch, nur klare Trennung „Setup-Trades vs. Grid-Trades".

### 6.2 `tab_grid_levels` zeigt Initial-Buys NICHT pro Linie

`_compute_grid_levels` gruppiert Trades nach `price` (= Grid-Linien-Preis). Initial-Buys haben `price=initial_price` (z. B. 50'100), nicht den Grid-Linien-Preis (z. B. 56'000). → Initial-Buys landen in keiner Grid-Linien-Gruppe.

**Konsequenz:** Die Sell-Linien oben zeigen `Anzahl Trades = 0`, obwohl die Initial-Buys logisch zu ihnen gehören. **Aber** sobald die Sells durchlaufen, wird der Profit (= `(sell.price - initial_price) × amount`) korrekt auf die jeweilige Sell-Linie attribuiert (`profit_gross` ist im Sell-Trade). ✓

**Schwere:** kosmetisch. Konsistent zur konzeptionellen Trennung „Setup-Trade ≠ Grid-Trade".

### 6.3 Optimizer-Ergebnisse (Auftrag C noch offen)

Wenn Auftrag C umgesetzt wird, müssen die Smart-Setup-Score-Berechnungen die Initial-Buy-Fees mit-berücksichtigen — was sie **automatisch** tun, weil `simulate_grid_bot` jetzt Initial-Buys ausführt. ROI-Werte sind dadurch im Vergleich zu Pre-Sub-Init **leicht niedriger** (typisch −0.1 bis −0.3% je nach Anzahl Initial-Buys und Fee-Rate).

**Auswirkung:** keine, **methodisch sogar realistischer**. Allerdings sind ältere Optimizer-Ergebnisse aus früheren Sessions (falls im Session-State) nicht mehr vergleichbar mit neuen Läufen. Falls relevant: User soll Smart-Setup einmal neu laufen lassen.

### 6.4 Backtest-Datei-Schema

Bestehende `data/cache/bots/*.json` (PT/LT-Bots vor dem Sub-Init oder BT-Snapshots) haben **keine** Felder `bot_status`, `grid_trigger_price`, `initial_buy_*`, `_buffer_zone_price`. `load_state` und `bot_view`-Adapter setzen alle Felder mit Defaults (`"active"`, `None`, `0.0`). Backward-Compat **getestet** (Smoke-Test [23/23] dritter Sub-Test).

**Auswirkung:** Alte Bots laufen weiter ohne Trigger / ohne Initial-Buys (so wie sie damals gestartet wurden). ✓

---

## 7 — Empfohlene Aktionen

| Priorität | Aktion | Aufwand |
|---|---|---|
| niedrig | A: `active_count` um `waiting_for_trigger` ausschliessen | 1 LoC |
| niedrig | Bericht E+F um §4 Bot-Lifecycle erweitern | 30-Min-Edit |
| niedrig | `num_trades` Initial-Buys ausfiltern | 2 LoC |
| optional | UI-Warnung bei `trigger` ausserhalb `[SL, TP]` | 5-10 LoC |

Keine dieser Aktionen ist **dringend** — alles funktioniert wie es soll, nur teilweise mit leichten semantischen Schiefen. Ich warte auf dein Signal, welche du angehen willst.

---

**Autor:** Enes Eryilmaz · Grid-Trading-Framework (Bachelorarbeit OST)
