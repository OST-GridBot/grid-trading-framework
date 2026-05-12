# Recentering- und Trailing-Mechanik (Core-Analyse)

**Stand:** 2026-05-12
**Quelle:** `src/strategy/grid_bot.py`
**Zweck:** Grundlage für Aufträge D.4 (Visualisierung) und C (Optimizer-Anpassungen).

---

## 1 — Übersicht in einem Satz

Beide Mechanismen werden in jedem `process_candle`-Aufruf **nach** der Trade-Ausführung geprüft (`grid_bot.py:403-409`). Trailing reagiert sofort bei **Berührung** der aktuellen Grenze; Recentering reagiert **verzögert**, erst wenn der Preis die Grenze um den `recenter_threshold` (Default 5 %) verlässt.

---

## 2 — Auftrag E: Recentering im Detail

### 2.1 Trigger

`_check_recentering(current_price)` — `grid_bot.py:624-646`:

```python
near_upper = current_price >= self.upper_price * (1 + self.recenter_threshold)
near_lower = current_price <= self.lower_price * (1 - self.recenter_threshold)

if (near_upper and self.enable_recentering_up) or \
   (near_lower and self.enable_recentering_down):
    self._recenter_grid(current_price)
```

- **Aufruf-Frequenz:** einmal pro Kerze, am Ende von `process_candle` (Z 404-405).
- **Schwelle:** Preis muss `recenter_threshold` **über** Upper bzw. **unter** Lower liegen. Default = 5 % (`__init__`-Parameter `recenter_threshold: float = 0.05`).
- **Bedingung `>=` / `<=`:** Auslösung exakt bei Erreichen der Schwelle, nicht erst bei Überschreitung.

### 2.2 Aufbau des neuen Grids

`_recenter_grid(current_price)` — `grid_bot.py:648-671`:

```python
half_range = (self.upper_price - self.lower_price) / 2
self.lower_price = max(current_price - half_range, current_price * 0.5)
self.upper_price = current_price + half_range
self.grid_lines = calculate_grid_lines(self.lower_price, self.upper_price,
                                       self.num_grids, self.grid_mode)
self._build_grids(current_price)
self.last_traded_price = None
self.recentering_count += 1
```

- **Range-Breite:** bleibt erhalten (`half_range` aus altem Grid wird auf neuen `current_price` umgerechnet).
- **Zentrum:** wandert komplett auf `current_price`.
- **Floor:** Lower kann nicht unter 50 % des aktuellen Preises fallen (Schutz vor Negativ-/Null-Werten).
- **Grid-Linien:** komplett neu berechnet via `calculate_grid_lines`.

### 2.3 Was passiert mit bestehenden Orders / Inventar?

`_build_grids` — `grid_bot.py:225-260`:

```python
self.grids = {}  # ⚠ alle alten GridStates verworfen
for idx, price in enumerate(self.grid_lines):
    ...
    self.grids[price] = GridState(price=..., side=..., trade_amount=...)
```

- **Grid-States werden komplett verworfen** und auf den neuen Linien neu aufgebaut. `trade_count` pro alter Linie geht verloren (für die neuen Linien beginnt der Zähler bei 0).
- **Position (`self.position["usdt"]` und `["coin"]`) bleibt erhalten** — also keine Zwangsschliessung, kein Verkauf von Bestand.
- **`coin_inventory` (FIFO-Liste der Käufe für Profit-Tracking) bleibt erhalten.**
- **`last_traded_price = None`** verhindert, dass der erste Trade nach dem Recentering durch die `if grid.price != self.last_traded_price`-Sperre blockiert wird.

→ Praktische Konsequenz: Der Bot hält nach dem Recentering sein gesamtes Coin-Inventar, auch wenn das Inventar zu Preisen unterhalb der neuen Lower gekauft wurde. Diese Coins werden erst verkauft, wenn der Preis wieder in die neue Range zurückkehrt und ein Sell-Grid durchschritten wird.

### 2.4 Verzug zwischen Trigger und Ausführung

**Kein Verzug** — Trigger und Grid-Neuaufbau passieren synchron im selben `process_candle`-Aufruf. In der nächsten Kerze handelt der Bot bereits auf dem neuen Grid.

### 2.5 Event-Logging — **fehlt!**

`_recenter_grid` zählt nur `self.recentering_count += 1` hoch (Z 671). Es gibt **kein** `recentering_events`-Array analog zu `trailing_events`.

**Vorschlag für Auftrag D.4 (Visualisierung):**

```python
# in __init__:
self.recentering_events: List[dict] = []

# am Ende von _recenter_grid:
if self._current_timestamp is not None:
    self.recentering_events.append({
        "timestamp": self._current_timestamp,
        "new_lower": float(self.lower_price),
        "new_upper": float(self.upper_price),
        "trigger_price": float(current_price),
        "direction": "up" if current_price >= old_upper else "down",
    })
```

Persistenz in `get_state` / `load_state` analog zu `trailing_events` (Z 779 + 821). Adapter `bot_view_from_bot_state` / `bot_view_from_backtest_result` und `simulate_grid_bot`-Result-Dict müssen ebenfalls den neuen Key durchreichen — exakt das Muster aus Sub A.2.

---

## 3 — Auftrag F: Trailing im Detail

### 3.1 Trigger

`_check_trailing(current_price)` — `grid_bot.py:677-720`:

```python
grid_step = (self.upper_price - self.lower_price) / self.num_grids

# Trailing UP
if self.enable_trailing_up and current_price >= self.upper_price:
    ...

# Trailing DOWN
elif self.enable_trailing_down and current_price <= self.lower_price:
    ...
```

- **Aufruf-Frequenz:** einmal pro Kerze, direkt **nach** dem Recentering-Check (Z 408-409).
- **Schwelle:** `current_price >= upper_price` bzw. `<= lower_price` — Auslösung bei **Berührung** der aktuellen Grenze, nicht erst nach Verlassen.
- **Schritt-Grösse:** ein einziger `grid_step` (= Abstand zweier benachbarter Grid-Linien) pro Trigger. Auch wenn der Preis in einer einzigen Kerze mehrere Grid-Steps überspringt, wandert das Grid nur **einen** Step. In der nächsten Kerze kann erneut getriggert werden.

### 3.2 ★ User-Frage: wandert auch die andere Grenze mit? ★

**Ja — beide Grenzen wandern synchron um genau einen `grid_step`.**

Trailing UP (Z 689-695):
```python
new_upper = self.upper_price + grid_step
new_lower = self.lower_price + grid_step  # ← Lower wandert MIT nach oben
...
self._shift_grid(new_lower, new_upper, current_price)
```

Trailing DOWN (Z 706-712):
```python
new_lower = self.lower_price - grid_step
new_upper = self.upper_price - grid_step  # ← Upper wandert MIT nach unten
...
self._shift_grid(new_lower, new_upper, current_price)
```

→ **Die Range-Breite bleibt konstant**, das Grid wandert als Einheit mit dem Preis mit. Praktisch: bei `lower=60'000`, `upper=80'000`, `num_grids=10` ist `grid_step = 2'000`. Trailing-Up-Trigger → neues `lower=62'000`, `upper=82'000`. Untere Buy-Linie bei 60'000 ist weg.

### 3.3 Stop-Preis

Trailing-Up wird durch `trailing_up_stop` gekappt (Z 693-694): erreicht `new_upper` den Stop, wird **kein** Shift durchgeführt (`return` ohne Logging). Analog `trailing_down_stop` für Trailing-Down. Das Grid bleibt am letzten gültigen Stand stehen.

### 3.4 Neuaufbau des Grids

`_shift_grid` — `grid_bot.py:722-737`:

```python
self.lower_price = max(new_lower, current_price * 0.01)
self.upper_price = new_upper
self.grid_lines = calculate_grid_lines(...)
self._build_grids(current_price)
self.last_traded_price = None
```

Identisches Pattern wie Recentering: Grid-States komplett verworfen und neu aufgebaut, Position/Inventar bleiben erhalten, `last_traded_price` zurückgesetzt. **Einziger Unterschied:** kein `recentering_count`-Inkrement, stattdessen `trailing_count += 1` und `trailing_events`-Append im aufrufenden `_check_trailing`.

### 3.5 Event-Logging

`trailing_events`-Array wird in `_check_trailing` befüllt (Z 697-703 für Up, Z 714-720 für Down). Felder: `timestamp`, `new_lower`, `new_upper`, `direction` ∈ {"up","down"}. Wurde in Sub A.2 eingeführt.

### 3.6 Verzug

**Kein Verzug** — Trigger und Shift passieren synchron im selben `process_candle`-Aufruf.

---

## 4 — Reaktiv vs. proaktiv: Klarstellung

Die intuitive Aufteilung **„Trailing reaktiv / Recentering proaktiv"** trifft nicht ganz zu — **beide Mechanismen sind technisch reaktiv** (greifen nach Candle-Close, nicht prognostisch). Sie unterscheiden sich nur in der **Toleranzschwelle**:

| Eigenschaft | Trailing | Recentering |
|---|---|---|
| Trigger-Schwelle | bei Berührung der Range-Grenze | Range-Grenze + `threshold` (default 5 %) |
| Bewegungs-Grösse | **ein** Grid-Step | volle Re-Zentrierung auf Current-Price |
| Range-Breite nach Shift | bleibt | bleibt (mit 50%-Floor für Lower) |
| Wandert die andere Grenze mit? | **Ja, synchron** | n/a — komplett neues Zentrum |
| Events geloggt? | Ja (`trailing_events`) | **Nein — fehlt** |
| Reaktion bei Mehrfach-Step in einer Kerze | nur 1 Step pro Kerze | sofort komplett neu zentriert |
| Aufrufreihenfolge in `process_candle` | nach Recentering | vor Trailing |

**Fazit:** Trailing reagiert **früher** (kleinere Schwelle) und **kleinteiliger** (1 Step). Recentering reagiert **später** (höhere Schwelle) und **gröber** (volle Zentrierung). Beide sind im Strict-Sense reaktiv. Eine echt-proaktive Variante (z. B. „rechne mit Trend, verschiebe vorab") gibt es heute nicht.

---

## 5 — Implikationen für Folgeaufträge

### Auftrag D.4 — Recentering-Visualisierung

- Voraussetzung: `recentering_events`-Array einbauen (Vorschlag in §2.5).
- Im Chart analog zu Trailing-Step-Linien: zwei orange/violette Step-Linien für `new_lower` und `new_upper`, gefüttert aus `recentering_events`.
- Im Gegensatz zu Trailing sind Recentering-Sprünge potenziell gross (volle Zentrierung) — die Step-Linien zeigen klare Sprung-Stufen.

### Auftrag C — Optimizer-Logik

- **Trailing Up vs. Down:** Die heutige Mechanik verschiebt bei Trailing-Up auch die Lower-Grenze nach oben (also „weniger Buy-Bereich unten"). Bei Markt-Aufwärtstrend ist das gewünscht. Bei seitwärts trendigem Markt mit lokalen Spitzen kann das hingegen schädlich sein (Bot verliert die Möglichkeit, bei einem Rücksetzer unten zu kaufen).
- Für die Optimierungs-Bewertung relevant: Trailing-Up alleine ist asymmetrisch (Range wandert nur in eine Richtung). Down-Variante existiert spiegelverkehrt. Dass laut Auftrag C nur Up in die Optimierung einfliesst, ist methodisch sauber, solange die untersuchten Zeiträume tendenziell aufwärtsgerichtet oder seitwärts sind — bei reinen Bärenmärkten würde Trailing-Up nie greifen.
- **Recentering analog:** nur Up-Variante in der Optimierung; dieselbe Logik. Methodisch in Ordnung.

### Robustheit / Korrektheits-Beobachtungen

1. **`_build_grids` verwirft `trade_count` pro Linie.** Konsequenz: nach Recentering/Trailing zeigt `components/tab_grid_levels.py` für die neuen Linien `trade_count=0`. Die Anzeige rechnet die Trades aus `trade_log` jedoch neu zusammen — das ist konsistent. ✔
2. **Recentering vor Trailing in `process_candle`:** Wenn beide Mechanismen aktiv wären (UI verhindert das via gegenseitige Verriegelung), würde Recentering zuerst zünden und Trailing danach in der Regel nicht mehr. Verriegelung sollte bestehen bleiben.
3. **`_current_timestamp`-Pattern:** Wird nur für Trailing-Events genutzt. Bei Recentering-Events-Einführung kann derselbe Mechanismus mitverwendet werden (Z 356 in `process_candle`).

---

**Autor:** Enes Eryilmaz · Grid-Trading-Framework (Bachelorarbeit OST)
