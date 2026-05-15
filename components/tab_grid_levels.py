"""
components/tab_grid_levels.py
=============================
Render-Komponente fuer den Grid-Levels-Tab in der Bot-Detail-Ansicht.

Zeigt eine Tabelle mit allen Grid-Linien des Bots:
    - Level-Nummerierung (1 = unterstes Grid, N+1 = oberstes)
    - Preis der Linie
    - Order-Volumen pro Linie (USDT)
    - Anzahl Trades auf dieser Linie
    - Realisierter Profit auf dieser Linie (USDT) - Summe profit_gross
      aller SELL-Trades auf dem Preis
    - Status: Aktiv / Initial (entfernt) / Neu durch Shift (L.2)

Dynamisch bei Recentering-/Trailing-Shifts: Initial-Linien und aktuelle
Linien werden vereinigt, jede mit Status. Zwischen-Shifts werden nicht
als eigene Zeilen gezeigt (Lesbarkeit).

Reihenfolge: oberste Linie zuerst (Level N+1 oben), unterste unten.

Autor: Enes Eryilmaz
Projekt: Grid-Trading-Framework (Bachelorarbeit OST)
"""

import pandas as pd
import streamlit as st


# ---------------------------------------------------------------------------
# Pure helper - testbar ohne Streamlit-Runtime
# ---------------------------------------------------------------------------

# L.2: Status-Werte + Farben
_STATUS_ACTIVE   = "Aktiv"
_STATUS_INITIAL  = "Initial (entfernt)"
_STATUS_SHIFTED  = "Neu durch Shift"

_STATUS_COLORS = {
    _STATUS_ACTIVE:  "#E2E8F0",  # weiss/normal
    _STATUS_INITIAL: "#94A3B8",  # grau
    _STATUS_SHIFTED: "#34D399",  # gruen
}


def _compute_current_lines(view: dict, cfg: dict, num_grids: int,
                            grid_mode: str) -> list:
    """Aktuelle (= zuletzt aktive) Grid-Linien rekonstruieren.

    Reihenfolge:
      1) PT/LT mit state.grids -> direkt aus den Keys.
      2) Sonst: aus letztem Recentering- oder Trailing-Event
         (new_lower / new_upper).
      3) Fallback: Initial-Range (= keine Shifts gewesen).
    """
    state       = view.get("state") or {}
    state_grids = state.get("grids") or {}
    if state_grids:
        try:
            return sorted([float(k) for k in state_grids.keys()])
        except Exception:
            pass

    # Letztes Event (Recentering oder Trailing) finden
    from src.strategy.grid_builder import calculate_grid_lines
    events = []
    for ev in (view.get("trailing_events") or []):
        events.append(ev)
    for ev in (view.get("recentering_events") or []):
        events.append(ev)
    if events:
        try:
            last = max(events, key=lambda e: str(e.get("timestamp", "")))
            nl = float(last.get("new_lower"))
            nu = float(last.get("new_upper"))
            return calculate_grid_lines(nl, nu, num_grids, grid_mode)
        except Exception:
            pass

    # Fallback: Initial-Range
    try:
        return calculate_grid_lines(
            float(cfg.get("lower_price", 0)),
            float(cfg.get("upper_price", 0)),
            num_grids, grid_mode,
        )
    except Exception:
        return []


def _compute_grid_levels(view: dict) -> list:
    """
    Liefert eine Liste mit einem Dict pro Grid-Linie. Felder:
        level       (int)    Nummerierung, 1 = unterste angezeigte Linie
        price       (float)
        order_usdt  (float)  Order-Volumen pro Linie (USDT)
        num_trades  (int)    Anzahl Trades auf dieser Linie (BUY+SELL)
        profit_usdt (float)  Summe profit_gross aller SELL-Trades
        status      (str)    "Aktiv" / "Initial (entfernt)" /
                             "Neu durch Shift"
    """
    cfg = view.get("config") or {}
    num_grids = int(cfg.get("num_grids", 10) or 10)
    grid_mode = cfg.get("grid_mode", "arithmetic")

    # ── 1. Initial- und Current-Linien rekonstruieren ──────────────────────
    from src.strategy.grid_builder import calculate_grid_lines
    try:
        initial_lines = calculate_grid_lines(
            float(cfg.get("lower_price", 0)),
            float(cfg.get("upper_price", 0)),
            num_grids, grid_mode,
        )
    except Exception:
        initial_lines = []
    current_lines = _compute_current_lines(view, cfg, num_grids, grid_mode)

    if not initial_lines and not current_lines:
        return []

    # Vereinigung mit Rundung (6 signifikante Stellen)
    def _key(p):
        return float(f"{float(p):.6g}")
    initial_set = {_key(p) for p in initial_lines}
    current_set = {_key(p) for p in current_lines}
    all_prices  = sorted(initial_set | current_set)

    # ── 2. Order-Volumen ───────────────────────────────────────────────────
    total_invest = float(cfg.get("total_investment", 0) or 0)
    reserve_pct  = float(cfg.get("reserve_pct", 0) or 0)
    effective    = total_invest * (1 - reserve_pct)
    base_amount  = (effective / num_grids) if num_grids > 0 else 0.0

    # ── 3. Trade-Statistik pro Preis ───────────────────────────────────────
    trade_log       = view.get("trade_log") or []
    trades_by_price = {}
    profit_by_price = {}
    for t in trade_log:
        # Initial-Buys (Binance-Setup) ausfiltern (analog metrics.num_trades)
        if str(t.get("type", "")).upper() == "BUY" and t.get("initial"):
            continue
        p = t.get("price")
        if p is None or (isinstance(p, (int, float)) and p <= 0):
            continue
        key = f"{p:.6g}"
        trades_by_price[key] = trades_by_price.get(key, 0) + 1
        if str(t.get("type", "")).upper() == "SELL":
            pg = t.get("profit_gross")
            if pg is None:
                pg = t.get("profit", 0) or 0
            profit_by_price[key] = profit_by_price.get(key, 0.0) + (pg or 0)

    # ── 4. Zeilen mit Status ───────────────────────────────────────────────
    rows = []
    for i, price in enumerate(all_prices):
        key = f"{price:.6g}"
        in_init    = price in initial_set
        in_current = price in current_set
        if in_current and in_init:
            status = _STATUS_ACTIVE
        elif in_current and not in_init:
            status = _STATUS_SHIFTED
        else:  # in_init and not in_current
            status = _STATUS_INITIAL
        rows.append({
            "level":       i + 1,
            "price":       float(price),
            "order_usdt":  base_amount,
            "num_trades":  trades_by_price.get(key, 0),
            "profit_usdt": profit_by_price.get(key, 0.0),
            "status":      status,
        })
    return rows


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------

def render_tab_grid_levels(view: dict) -> None:
    """Rendert den Grid-Levels-Tab fuer eine BotView."""
    rows = _compute_grid_levels(view)
    if not rows:
        st.info("Keine Grid-Linien verfügbar.")
        return

    # Oberste Linie zuerst -> aufsteigend nach Level absteigend sortieren
    rows_sorted = sorted(rows, key=lambda r: r["level"], reverse=True)

    df = pd.DataFrame([
        {
            "Level":         r["level"],
            "Preis":         r["price"],
            "Order-Volumen": r["order_usdt"],
            "Anzahl Trades": r["num_trades"],
            "Profit":        r["profit_usdt"],
            "Status":        r["status"],
        }
        for r in rows_sorted
    ])

    def _color_status(val):
        c = _STATUS_COLORS.get(str(val))
        return f"color: {c}; font-weight: 600;" if c else ""

    styled = df.style.applymap(_color_status, subset=["Status"])

    st.dataframe(
        styled,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Level": st.column_config.NumberColumn(format="%d"),
            "Preis": st.column_config.NumberColumn(format="$%.2f"),
            "Order-Volumen": st.column_config.NumberColumn(
                "Order-Volumen (USDT)", format="$%.2f"
            ),
            "Anzahl Trades": st.column_config.NumberColumn(format="%d"),
            "Profit": st.column_config.NumberColumn(
                "Realisierter Profit (USDT)", format="$%+.2f"
            ),
        },
    )
