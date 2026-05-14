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

Reihenfolge: oberste Linie zuerst (Level N+1 oben), unterste unten.

Autor: Enes Eryilmaz
Projekt: Grid-Trading-Framework (Bachelorarbeit OST)
"""

import pandas as pd
import streamlit as st


# ---------------------------------------------------------------------------
# Pure helper - testbar ohne Streamlit-Runtime
# ---------------------------------------------------------------------------

def _compute_grid_levels(view: dict) -> list:
    """
    Liefert eine Liste mit einem Dict pro Grid-Linie. Felder:
        level       (int)    aufsteigend, 1 = unterstes Grid
        price       (float)
        order_usdt  (float)  Order-Volumen pro Linie (USDT)
        num_trades  (int)    Anzahl Trades auf dieser Linie (BUY+SELL)
        profit_usdt (float)  Summe profit_gross aller SELL-Trades auf dieser Linie
    """
    cfg         = view.get("config") or {}
    state       = view.get("state") or {}
    state_grids = state.get("grids") or {}

    # ── 1. Grid-Linien bestimmen ────────────────────────────────────────────
    if state_grids:
        # Lebende PT/LT-Bots: echte Linien aus state
        try:
            prices = sorted([float(k) for k in state_grids.keys()])
        except Exception:
            prices = []
    else:
        # BT-Snapshot oder PT/LT ohne state: aus config rechnen
        try:
            from src.strategy.grid_builder import calculate_grid_lines
            prices = calculate_grid_lines(
                float(cfg.get("lower_price", 0)),
                float(cfg.get("upper_price", 0)),
                int(cfg.get("num_grids", 10)),
                cfg.get("grid_mode", "arithmetic"),
            )
        except Exception:
            prices = []

    if not prices:
        return []

    n_lines   = len(prices)
    num_grids = int(cfg.get("num_grids", n_lines - 1) or (n_lines - 1))

    # ── 2. Order-Volumen pro Linie ──────────────────────────────────────────
    # Konsistent mit GridBot._initialize_grids und _build_grids:
    #   base_amount = effective_investment / num_grids  (kein Tippfehler -
    #     Definition "num_grids = Intervalle", verteilt auf alle N+1 Linien)
    total_invest = float(cfg.get("total_investment", 0) or 0)
    reserve_pct  = float(cfg.get("reserve_pct", 0) or 0)
    effective    = total_invest * (1 - reserve_pct)
    base_amount  = (effective / num_grids) if num_grids > 0 else 0.0

    # Alle Grid-Linien erhalten die gleiche Allokation (entspricht
    # GridBot._build_grids).
    weights = [1.0] * n_lines

    # ── 3. Trade-Statistik pro Linie ────────────────────────────────────────
    # Preis-Schluessel mit 6 signifikanten Stellen, konsistent mit metrics.py
    trade_log       = view.get("trade_log") or []
    trades_by_price = {}
    profit_by_price = {}
    for t in trade_log:
        # Initial-Buys (Binance-Setup) sind keine Grid-Trades — sie liegen
        # zwar auf den Sell-Linien (price = nominelle Sell-Linie seit M.4),
        # gehoeren aber zum Setup-Pool und werden hier ausgefiltert.
        # Konsistent mit src/analysis/metrics.py:num_trades-Filter.
        if str(t.get("type", "")).upper() == "BUY" and t.get("initial"):
            continue
        p = t.get("price")
        if p is None or (isinstance(p, (int, float)) and p <= 0):
            continue
        key = f"{p:.6g}"
        trades_by_price[key] = trades_by_price.get(key, 0) + 1
        if str(t.get("type", "")).upper() == "SELL":
            # Brutto-Profit bevorzugt; Fallback auf netto-profit
            pg = t.get("profit_gross")
            if pg is None:
                pg = t.get("profit", 0) or 0
            profit_by_price[key] = profit_by_price.get(key, 0.0) + (pg or 0)

    # ── 4. Zeilen zusammenstellen ───────────────────────────────────────────
    rows = []
    for i, price in enumerate(prices):
        key = f"{price:.6g}"
        rows.append({
            "level":       i + 1,
            "price":       float(price),
            "order_usdt":  base_amount * weights[i],
            "num_trades":  trades_by_price.get(key, 0),
            "profit_usdt": profit_by_price.get(key, 0.0),
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
            "Level":           r["level"],
            "Preis":           r["price"],
            "Order-Volumen":   r["order_usdt"],
            "Anzahl Trades":   r["num_trades"],
            "Profit":          r["profit_usdt"],
        }
        for r in rows_sorted
    ])

    st.dataframe(
        df,
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
