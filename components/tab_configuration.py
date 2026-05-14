"""
components/tab_configuration.py
===============================
Render-Komponente fuer den Configuration-Tab in der Bot-Detail-Ansicht.

Konsumiert eine BotView (siehe components/bot_view.py) und zeigt:
    - Bot-Identitaet (Coin, Intervall, Zeitraum)
    - Grid-Parameter (Anzahl, Range, Modus)
    - Kapital & Start (Investment, Fees, Reserve, Initial-Buy, Grid-Trigger)
    - Dynamische Mechanismen (DD, Recentering, Trailing, TP/SL)

Status-Labels werden mit Farbcodierung (gruen=aktiv, rot=inaktiv)
gerendert. Bei trail_stop_levels=True zeigen wir bei PT/LT-Bots den
mitgewanderten aktuellen SL/TP-Wert aus dem State.

Die Label-Helfer (_label_*) sind reine Funktionen (kein Streamlit-Runtime
noetig).

Autor: Enes Eryilmaz
Projekt: Grid-Trading-Framework (Bachelorarbeit OST)
"""

import streamlit as st


# ---------------------------------------------------------------------------
# Farben (konsistent mit anderen UI-Komponenten)
# ---------------------------------------------------------------------------

_COL_ACTIVE   = "#10B981"   # Aktiv  -> gruen
_COL_INACTIVE = "#EF4444"   # Inaktiv -> rot


def _active(text: str) -> str:
    return f"<span style='color:{_COL_ACTIVE}; font-weight:600;'>{text}</span>"


def _inactive(text: str = "Inaktiv") -> str:
    return f"<span style='color:{_COL_INACTIVE}; font-weight:600;'>{text}</span>"


# ---------------------------------------------------------------------------
# Label-Helfer (pure functions, geben farbige HTML-Strings zurueck)
# ---------------------------------------------------------------------------

def _label_stop_loss(cfg: dict) -> str:
    """Stop-Loss-Status (Preis / ROI / P/L)."""
    parts = []
    pct = cfg.get("stop_loss_pct")
    if pct:
        parts.append(f"Preis {pct * 100:.0f}%")
    roi = cfg.get("stop_loss_roi_pct")
    if roi:
        parts.append(f"ROI {roi * 100:.0f}%")
    pl = cfg.get("stop_loss_pl_usdt")
    if pl:
        parts.append(f"P/L ${pl:,.0f}")
    if not parts:
        return _inactive()
    return _active("Aktiv (" + " / ".join(parts) + ")")


def _label_take_profit(cfg: dict) -> str:
    """Take-Profit-Status (Preis / ROI / P/L)."""
    parts = []
    pct = cfg.get("take_profit_pct")
    if pct:
        parts.append(f"Preis {pct * 100:.0f}%")
    roi = cfg.get("take_profit_roi_pct")
    if roi:
        parts.append(f"ROI {roi * 100:.0f}%")
    pl = cfg.get("take_profit_pl_usdt")
    if pl:
        parts.append(f"P/L ${pl:,.0f}")
    if not parts:
        return _inactive()
    return _active("Aktiv (" + " / ".join(parts) + ")")


def _label_dd_throttle(cfg: dict) -> str:
    """Drawdown-Drosselung-Status."""
    if not cfg.get("enable_dd_throttle"):
        return _inactive()
    t1 = cfg.get("dd_threshold_1", 0) * 100
    t2 = cfg.get("dd_threshold_2", 0) * 100
    return _active(f"Aktiv (Schwelle 1: {t1:.0f}% / Schwelle 2: {t2:.0f}%)")


def _label_recentering(cfg: dict) -> str:
    """Recentering-Status (Up/Down + Backward-Compat)."""
    legacy = cfg.get("enable_recentering", False)
    up     = cfg.get("enable_recentering_up",   legacy)
    dn     = cfg.get("enable_recentering_down", legacy)
    pct    = cfg.get("recenter_threshold", 0) * 100
    if up and dn:
        return _active(f"Aktiv (Up + Down, {pct:.0f}%)")
    if up:
        return _active(f"Aktiv (nur Up, {pct:.0f}%)")
    if dn:
        return _active(f"Aktiv (nur Down, {pct:.0f}%)")
    return _inactive()


def _label_trailing(cfg: dict) -> str:
    """Grid-Trailing-Status (nur Up-Variante, Binance-Standard).
    F.3: 'TP/SL wandern mit'-Hinweis entfernt — die mitgewanderten
    Werte werden separat unter SL/TP angezeigt (PT/LT only)."""
    if not cfg.get("enable_trailing_up", False):
        return _inactive()
    v = cfg.get("trailing_up_stop")
    stop_str = f"${v:,.2f}" if isinstance(v, (int, float)) else "–"
    return _active(f"Aktiv (Stop: {stop_str})")


def _label_initial_buy(cfg: dict) -> str:
    """Initial-Buy-Status (Default True = Binance-Standard)."""
    if cfg.get("enable_initial_buy", True):
        return _active("Aktiv")
    return _inactive()


def _label_grid_trigger(cfg: dict) -> str:
    """Grid-Trigger-Status: Preis-Wert oder 'sofortiger Start'."""
    trig = cfg.get("grid_trigger_price")
    if not trig:
        return _inactive("Aus (sofortiger Start)")
    return _active(f"${float(trig):,.2f}")


# ---------------------------------------------------------------------------
# Render-Helper
# ---------------------------------------------------------------------------

def _section_header(text: str) -> None:
    """Sub-Header fuer eine Konfigurations-Sektion."""
    st.markdown(
        f"<div style='font-size:0.95rem; font-weight:700; color:#CBD5E1; "
        f"text-transform:uppercase; letter-spacing:0.05em; "
        f"margin: 12px 0 6px 0; padding-bottom:4px; "
        f"border-bottom:1px solid rgba(255,255,255,0.10);'>{text}</div>",
        unsafe_allow_html=True,
    )


def _row(label: str, value_html: str) -> None:
    """Eine Konfigurationszeile: linksbuendiges Label + rechtsstehender Wert."""
    st.markdown(
        f"- **{label}:** {value_html}",
        unsafe_allow_html=True,
    )


def _sub_row(html: str) -> None:
    """Eingerueckte Sub-Zeile (z.B. Mitwandern-Status)."""
    st.markdown(
        f"<div style='margin-left:24px; font-size:0.82rem; color:#94A3B8;'>"
        f"↳ {html}</div>",
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------

def render_tab_configuration(view: dict) -> None:
    """Rendert den Configuration-Tab fuer eine BotView."""
    cfg    = view.get("config", {})
    state  = view.get("state") or {}
    period = view.get("period")     # BT-spezifisch, sonst None
    mode   = view.get("mode", "")

    # ── Bot (Header oben) ───────────────────────────────────────────────────
    col_a, col_b = st.columns(2)
    with col_a:
        _row("Coin", f"{view.get('coin', '–')}/USDT")
        _row("Intervall", view.get("interval", "–"))
    with col_b:
        if period:
            start = period.get("start_date", "–")
            end   = period.get("end_date", "–")
            days  = period.get("days", 0)
            _row("Zeitraum", f"{start} – {end} ({days}d)")

    # ── Grid-Parameter ──────────────────────────────────────────────────────
    _section_header("Grid-Parameter")
    col_a, col_b = st.columns(2)
    with col_a:
        _row("Anzahl Grids", str(cfg.get("num_grids", "–")))
        _row("Untere Grenze", f"${cfg.get('lower_price', 0):,.2f}")
    with col_b:
        _row("Obere Grenze", f"${cfg.get('upper_price', 0):,.2f}")
        _row("Grid-Modus", str(cfg.get("grid_mode", "–")))

    # ── Kapital & Start ─────────────────────────────────────────────────────
    _section_header("Kapital & Start")
    col_a, col_b = st.columns(2)
    with col_a:
        _row("Startkapital", f"${cfg.get('total_investment', 0):,.2f}")
        _row("Gebührenrate", f"{cfg.get('fee_rate', 0) * 100:.3f}%")
        _row("Kapitalreserve", f"{cfg.get('reserve_pct', 0) * 100:.0f}%")
    with col_b:
        _row("Initial-Buy", _label_initial_buy(cfg))
        _row("Grid Trigger", _label_grid_trigger(cfg))

    # ── Dynamische Mechanismen ──────────────────────────────────────────────
    _section_header("Dynamische Mechanismen")
    col_a, col_b = st.columns(2)
    with col_a:
        _row("DD-Drosselung", _label_dd_throttle(cfg))
        _row("Recentering", _label_recentering(cfg))
        _row("Trailing", _label_trailing(cfg))
    with col_b:
        _row("Stop-Loss", _label_stop_loss(cfg))
        # F.3: Mitwandern-Anzeige nur bei PT/LT (BT laeuft deterministisch
        # durch — End-State-Werte sind kein "aktueller" Stand).
        if (mode != "backtest"
                and cfg.get("trail_stop_levels")
                and cfg.get("enable_trailing_up")):
            sl_cur = state.get("stop_loss_price")
            if sl_cur:
                _sub_row(f"mitgewandert: ${float(sl_cur):,.2f}")
        _row("Take-Profit", _label_take_profit(cfg))
        if (mode != "backtest"
                and cfg.get("trail_stop_levels")
                and cfg.get("enable_trailing_up")):
            tp_cur = state.get("take_profit_price")
            if tp_cur:
                _sub_row(f"mitgewandert: ${float(tp_cur):,.2f}")
