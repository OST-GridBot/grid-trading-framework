"""
components/tab_configuration.py
===============================
Render-Komponente fuer den Configuration-Tab in der Bot-Detail-Ansicht.

Konsumiert eine BotView (siehe components/bot_view.py) und zeigt:
    - Bot-Parameter (Coin, Intervall, Zeitraum, Kapital, Grid-Modus, ...)
    - Mechanismen-Status (Stop-Loss, Take-Profit, Recentering, Trailing, ...)

Die Label-Helfer (_label_*) sind reine Funktionen (kein Streamlit-Runtime
noetig) und werden im Smoke-Test direkt geprueft.

Autor: Enes Eryilmaz
Projekt: Grid-Trading-Framework (Bachelorarbeit OST)
"""

import streamlit as st


# ---------------------------------------------------------------------------
# Label-Helfer (pure functions, testbar ohne Streamlit-Runtime)
# ---------------------------------------------------------------------------

def _label_stop_loss(cfg: dict) -> str:
    """
    Stop-Loss-Status als lesbares Label. Beruecksichtigt beide Trigger
    (preis-basiert + ROI-basiert), kommagetrennt.
    """
    parts = []
    pct = cfg.get("stop_loss_pct")
    if pct:
        parts.append(f"Preis {pct * 100:.0f}%")
    roi = cfg.get("stop_loss_roi_pct")
    if roi:
        parts.append(f"ROI {roi * 100:.0f}%")
    return "Aktiv (" + " / ".join(parts) + ")" if parts else "Inaktiv"


def _label_take_profit(cfg: dict) -> str:
    """Take-Profit-Status (Preis + ROI)."""
    parts = []
    pct = cfg.get("take_profit_pct")
    if pct:
        parts.append(f"Preis {pct * 100:.0f}%")
    roi = cfg.get("take_profit_roi_pct")
    if roi:
        parts.append(f"ROI {roi * 100:.0f}%")
    return "Aktiv (" + " / ".join(parts) + ")" if parts else "Inaktiv"


def _label_dd_throttle(cfg: dict) -> str:
    """Drawdown-Drosselung-Status."""
    if not cfg.get("enable_dd_throttle"):
        return "Inaktiv"
    t1 = cfg.get("dd_threshold_1", 0) * 100
    t2 = cfg.get("dd_threshold_2", 0) * 100
    return f"Aktiv (Schwelle 1: {t1:.0f}% / Schwelle 2: {t2:.0f}%)"


def _label_variable_orders(cfg: dict) -> str:
    """Variable-Ordergroessen-Status."""
    if not cfg.get("enable_variable_orders"):
        return "Inaktiv"
    wb = cfg.get("weight_bottom", 1)
    wt = cfg.get("weight_top", 1)
    return f"Aktiv (unten {wb}× / oben {wt}×)"


def _label_recentering(cfg: dict) -> str:
    """
    Recentering-Status. Behandelt Up/Down-Split + Backward-Compat fuer
    alte Bot-States, die nur `enable_recentering` (ohne Suffix) haben.
    """
    # Alter Schluessel wirkt als Fallback fuer beide neuen Flags
    legacy = cfg.get("enable_recentering", False)
    up     = cfg.get("enable_recentering_up",   legacy)
    dn     = cfg.get("enable_recentering_down", legacy)
    pct    = cfg.get("recenter_threshold", 0) * 100
    if up and dn:
        return f"Aktiv (Up + Down, {pct:.0f}%)"
    if up:
        return f"Aktiv (nur Up, {pct:.0f}%)"
    if dn:
        return f"Aktiv (nur Down, {pct:.0f}%)"
    return "Inaktiv"


def _label_atr(cfg: dict) -> str:
    """ATR-Anpassung-Status mit statisch/dynamisch-Modus."""
    if not cfg.get("enable_atr_adjust"):
        return "Inaktiv"
    mult = cfg.get("atr_multiplier", 1.0)
    mode = "dynamisch" if cfg.get("enable_atr_dynamic") else "statisch"
    return f"Aktiv (×{mult}, {mode})"


def _label_trailing(cfg: dict) -> str:
    """Grid-Trailing-Status (nur Up-Variante, Binance-Standard)."""
    if not cfg.get("enable_trailing_up", False):
        return "Inaktiv"
    v = cfg.get("trailing_up_stop")
    stop_str = f"\\${v:,.2f}" if isinstance(v, (int, float)) else "–"
    parts = [f"Stop: {stop_str}"]
    if cfg.get("trail_stop_levels"):
        parts.append("SL/TP wandern mit")
    return f"Aktiv ({' / '.join(parts)})"


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------

def render_tab_configuration(view: dict) -> None:
    """
    Rendert den Configuration-Tab fuer eine BotView.

    Args:
        view: BotView-Dict (siehe components/bot_view.py)
    """
    cfg    = view.get("config", {})
    period = view.get("period")     # BT-spezifisch, sonst None

    col_a, col_b = st.columns(2)

    # ── Spalte A: Bot- und Markt-Parameter ──────────────────────────────────
    with col_a:
        st.markdown(f"- **Coin:** {view.get('coin', '–')}/USDT")
        st.markdown(f"- **Intervall:** {view.get('interval', '–')}")
        if period:
            start = period.get("start_date", "–")
            end   = period.get("end_date", "–")
            days  = period.get("days", 0)
            st.markdown(f"- **Zeitraum:** {start} – {end} ({days}d)")
        st.markdown(f"- **Startkapital:** ${cfg.get('total_investment', 0):,.2f}")
        st.markdown(f"- **Kapitalreserve:** {cfg.get('reserve_pct', 0) * 100:.0f}%")
        st.markdown(f"- **Grid-Modus:** {cfg.get('grid_mode', '–')}")
        st.markdown(f"- **Stop-Loss:** {_label_stop_loss(cfg)}")
        st.markdown(f"- **Take-Profit:** {_label_take_profit(cfg)}")
        st.markdown(f"- **Variable Orders:** {_label_variable_orders(cfg)}")
        st.markdown(f"- **ATR-Anpassung:** {_label_atr(cfg)}")

    # ── Spalte B: Grid-Parameter + Mechanismen ──────────────────────────────
    with col_b:
        st.markdown(f"- **Anzahl Grids:** {cfg.get('num_grids', '–')}")
        st.markdown(f"- **Untere Grenze:** ${cfg.get('lower_price', 0):,.2f}")
        st.markdown(f"- **Obere Grenze:** ${cfg.get('upper_price', 0):,.2f}")
        st.markdown(f"- **Gebührenrate:** {cfg.get('fee_rate', 0) * 100:.3f}%")
        st.markdown(f"- **DD-Drosselung:** {_label_dd_throttle(cfg)}")
        st.markdown(f"- **Recentering:** {_label_recentering(cfg)}")
        st.markdown(f"- **Trailing:** {_label_trailing(cfg)}")
        # Grid Trigger
        trig = cfg.get("grid_trigger_price")
        st.markdown(
            f"- **Grid Trigger:** "
            + ("Aus (sofortiger Start)" if not trig else f"${float(trig):,.2f}")
        )

    # ── Initial-Setup (Binance-Standard) ────────────────────────────────────
    ib_coin = float(view.get("initial_buy_coin_amount", 0.0) or 0.0)
    if ib_coin > 0:
        ib_fee   = float(view.get("initial_buy_fee", 0.0) or 0.0)
        ib_value = float(view.get("initial_buy_value_usdt", 0.0) or 0.0)
        coin_sym = view.get("coin", "")
        st.markdown("---")
        st.markdown(
            f"**Initial-Setup (Binance-Standard):** "
            f"{ib_coin:,.6f} {coin_sym} zum Bot-Start gekauft "
            f"für ${ib_value:,.2f} USDT (Fee ${ib_fee:,.4f})."
        )
