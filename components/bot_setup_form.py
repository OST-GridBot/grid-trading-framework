"""
components/bot_setup_form.py
============================
Render-Komponente fuer die Bot-Aufsetzen-Form (BT/PT/LT).

Sammelt alle Sim-/Bot-Parameter und liefert sie beim Submit als params-
Dict an die Page. Die Page entscheidet selbst, was damit geschieht:
    BT   : run_backtest(**params) + bot_store.save_backtest(...)
    PT/LT: bot_store.create_bot(mode=..., **params)

Mode-Spezifika:
    - BT  hat einen Zeitraum (period) und das Intervall "1d" zusaetzlich.
    - PT/LT haben Smart-Setup auf Basis des aktuellen Preises;
      BT auf Basis des historischen Medians ueber den Zeitraum.

Alle Widget-Keys haben das Praefix f"{mode}_new_*", damit keine Kollision
mit den heutigen pt_new_*/lt_new_*-Keys auftritt (Phase 3 migriert PT/LT
schrittweise).

Autor: Enes Eryilmaz
Projekt: Grid-Trading-Framework (Bachelorarbeit OST)
"""

from typing import Callable, Optional
from datetime import date, timedelta

import streamlit as st

from config.settings import (
    DEFAULT_FEE_RATE, DEFAULT_RESERVE_PCT, DEFAULT_NUM_GRIDS,
)
from src.data.cache_manager import get_price_data
from src.strategy.grid_builder import (
    calculate_grid_lines, suggest_atr_grid_counts,
)
from src.utils.timezone import convert_df_timestamps
from components.chart_v2 import plot_grid_chart_v2
from components.ui_helpers import COINS


# ---------------------------------------------------------------------------
# Konstanten / lokale UI-Helper (Form-eigene Label-/Caption-Variante)
# ---------------------------------------------------------------------------

_DAYS_BY_INTERVAL = {"1m": 1, "5m": 1, "15m": 2, "1h": 7, "4h": 14, "1d": 30}


def _label(text: str) -> str:
    return (f"<div style='font-size:1.1rem; font-weight:600; color:#94A3B8; "
            f"letter-spacing:0.04em; margin-top:6px; margin-bottom:2px;'>{text}</div>")


def _caption(text: str) -> str:
    return f"<div style='font-size:0.78rem; color:#94A3B8; margin-bottom:2px;'>{text}</div>"


def _divider() -> str:
    return ("<hr style='border:none; border-top:1px solid rgba(255,255,255,0.08); "
            "margin:8px 0;'>")


# ---------------------------------------------------------------------------
# Default-Params (pure, testbar)
# ---------------------------------------------------------------------------

def _default_params(mode: str) -> dict:
    """
    Liefert ein params-Dict mit Default-Werten fuer einen gegebenen Mode.
    Dient als Schema-Vorlage (alle Submit-relevanten Keys vorhanden) und
    als Smoke-Test-Fixpunkt.
    """
    return {
        "name":             "",
        "coin":             "BTC",
        "interval":         "1h",
        "total_investment": 10_000.0,
        "period":           ({"start_date": "", "end_date": "", "days": 30}
                              if mode == "backtest" else None),
        "lower_price":      0.0,
        "upper_price":      0.0,
        "num_grids":        DEFAULT_NUM_GRIDS,
        "grid_mode":        "arithmetic",
        "fee_rate":         DEFAULT_FEE_RATE,
        "reserve_pct":      DEFAULT_RESERVE_PCT,
        "stop_loss_pct":    None,
        "take_profit_pct":  None,
        "stop_loss_roi_pct":   None,
        "take_profit_roi_pct": None,
        "stop_loss_pl_usdt":   None,
        "take_profit_pl_usdt": None,
        "enable_dd_throttle":     False,
        "dd_threshold_1":         0.10,
        "dd_threshold_2":         0.20,
        "enable_variable_orders": False,
        "weight_bottom":          2.0,
        "weight_top":             0.5,
        "enable_atr_adjust":      False,
        "atr_multiplier":         1.0,
        "enable_atr_dynamic":     False,
        "atr_dynamic_threshold":  0.15,
        "enable_recentering_up":   False,
        "enable_recentering_down": False,
        "recenter_threshold":      0.05,
        "enable_trailing_up":     False,
        "trailing_up_stop":       None,
        "trail_stop_levels":      False,
        # Grid Trigger (None = Bot startet sofort, Wert = Bot wartet auf Touch)
        "grid_trigger_price":     None,
        # Initial-Buy (Binance-Standard True). False = Bot startet rein USDT.
        "enable_initial_buy":     True,
    }


# ---------------------------------------------------------------------------
# Section-Helper (geben gesammelte Werte als Dict zurueck)
# ---------------------------------------------------------------------------

def _section_basic(mode: str) -> dict:
    """Bot-Name + Coin + Intervall + (Zeitraum bei BT)."""
    p: dict = {}
    st.markdown(_label("Bot-Name"), unsafe_allow_html=True)
    placeholder = ("z.B. BTC Bear 2025" if mode == "backtest"
                   else "z.B. BTC Range Bot, ETH Swing...")
    p["name"] = st.text_input("", placeholder=placeholder,
                               label_visibility="collapsed",
                               key=f"{mode}_new_name").strip()

    st.markdown(_divider(), unsafe_allow_html=True)
    st.markdown(_label("Coin"), unsafe_allow_html=True)
    coin_mode = st.radio("", ["Aus Liste", "Eigene Eingabe"],
                          horizontal=True, key=f"{mode}_new_coin_mode",
                          label_visibility="collapsed")
    if coin_mode == "Aus Liste":
        p["coin"] = st.selectbox("", COINS, label_visibility="collapsed",
                                  key=f"{mode}_new_coin")
    else:
        p["coin"] = st.text_input("", value="BTC", label_visibility="collapsed",
                                   key=f"{mode}_new_coin_input").upper().strip()

    st.markdown(_divider(), unsafe_allow_html=True)
    st.markdown(_label("Intervall"), unsafe_allow_html=True)
    intervals = ["1m","5m","15m","1h","4h","1d"] if mode == "backtest" else \
                ["1m","5m","15m","1h","4h"]
    p["interval"] = st.radio("", intervals, index=3, horizontal=True,
                              key=f"{mode}_new_interval",
                              label_visibility="collapsed")

    if mode == "backtest":
        st.markdown(_divider(), unsafe_allow_html=True)
        st.markdown(_label("Zeitraum"), unsafe_allow_html=True)
        col_d1, col_d2 = st.columns(2)
        with col_d1:
            start = st.date_input("Von", value=date.today() - timedelta(days=30),
                                   key=f"{mode}_new_start")
        with col_d2:
            end   = st.date_input("Bis", value=date.today(),
                                   key=f"{mode}_new_end")
        days = max(1, (end - start).days)
        st.caption(f"→ {days} Tage")
        p["period"] = {"start_date": str(start), "end_date": str(end), "days": days}
        # Fuer Folgesektionen: bei BT speichern wir start/end auch zugaenglich
        p["_period_start"] = start
        p["_period_end"]   = end
    else:
        p["period"] = None
    return p


def _section_capital(mode: str, current_price: Optional[float] = None) -> dict:
    """
    Kapital-Sektion (frueher "Startkapital" + "Risiko & Kapital" zusammen):
      - Startkapital
      - Initial-Buy-Toggle (Default an = Binance-Standard)
      - Grid Trigger (eingebettet, ohne eigenen Divider)
      - Gebuehrenrate
      - Kapitalreserve
    """
    st.markdown(_divider(), unsafe_allow_html=True)
    st.markdown(_label("Kapital"), unsafe_allow_html=True)

    # ── Startkapital ────────────────────────────────────────────────────────
    st.markdown(_caption("Startkapital (USDT)"), unsafe_allow_html=True)
    capital = st.number_input("", min_value=100.0, max_value=1_000_000.0,
                               value=10_000.0, step=500.0,
                               key=f"{mode}_new_capital",
                               label_visibility="collapsed")

    # ── Initial-Buy-Toggle ──────────────────────────────────────────────────
    # Default True = Binance-Standard (Bot baut Coin-Inventar zum Start auf).
    # False = Bot startet rein mit USDT, ohne sofortige Marktkaeufe.
    enable_initial_buy = st.checkbox(
        "Initial-Buy", value=True, key=f"{mode}_new_initial_buy",
        help=("Beim Bot-Start werden sofort Coins auf den Sell-Linien über "
              "dem Startpreis gekauft (Binance-Standard). Deaktivieren = "
              "Bot startet rein mit USDT und kauft erst, wenn der Preis "
              "eine Buy-Linie unten durchschreitet."),
    )

    # ── Grid Trigger (eingebettet) ──────────────────────────────────────────
    trigger = _section_grid_trigger_inline(mode, current_price)

    # ── Gebuehrenrate + Kapitalreserve ──────────────────────────────────────
    st.markdown(_caption("Gebührenrate (%)"), unsafe_allow_html=True)
    fee_pct = st.number_input("", 0.0, 1.0, DEFAULT_FEE_RATE * 100, 0.01,
                               format="%.3f", key=f"{mode}_new_fee",
                               label_visibility="collapsed")
    st.markdown(_caption("Kapitalreserve (%)"), unsafe_allow_html=True)
    reserve_pct = st.slider("", 0.0, 20.0, DEFAULT_RESERVE_PCT * 100, 1.0,
                             key=f"{mode}_new_reserve",
                             label_visibility="collapsed") / 100

    return {
        "total_investment":   float(capital),
        "enable_initial_buy": bool(enable_initial_buy),
        "grid_trigger_price": trigger,
        "fee_rate":           fee_pct / 100,
        "reserve_pct":        float(reserve_pct),
        "_fee_pct":           fee_pct,
    }


def _load_current_price(
    coin:     str,
    interval: str,
    period:   Optional[dict] = None,
    mode:     str            = "paper",
) -> Optional[float]:
    """
    Liefert den Referenzpreis fuer Range-Defaults und Live-Chart-Anker.

    - PT/LT: letzter Schlusskurs (Live-Preis).
    - BT   : Schlusskurs am Von-Datum (erster Close im BT-Zeitraum),
             damit ± X%-Range-Vorbelegung, Grid Trigger-Vergleich und
             Live-Chart-Grid-Linien auf den historischen Bot-Start-Preis
             bezogen werden — nicht auf den Heute-Preis.
             Faellt bei unvollstaendigem Period auf letzten Close zurueck.
    """
    try:
        if (mode == "backtest" and period
                and period.get("start_date") and period.get("end_date")):
            from datetime import date as _date
            sd = _date.fromisoformat(period["start_date"])
            ed = _date.fromisoformat(period["end_date"])
            df, _ = get_price_data(
                coin, days=period.get("days", 30),
                interval=interval, start_date=sd, end_date=ed,
            )
            if df is not None and not df.empty:
                return float(df["close"].iloc[0])  # erster Close = Von-Datum
        # Default-Pfad (PT/LT oder BT-Fallback)
        days = _DAYS_BY_INTERVAL.get(interval, 7)
        df, _ = get_price_data(coin, days=days, interval=interval)
        if df is not None and not df.empty:
            return float(df["close"].iloc[-1])
    except Exception:
        pass
    return None


def params_differ(a: Optional[dict], b: Optional[dict]) -> bool:
    """
    True, wenn sich die BT-relevanten Parameter zwischen a und b
    unterscheiden. Vergleicht alle Keys ausser solche, die mit "_"
    beginnen oder "name" heissen (rein UI-Metadata).

    Wird von page_backtesting verwendet, um ein gespeichertes
    Pending-Result automatisch zu verwerfen, sobald der User in der
    Sidebar Parameter aendert.
    """
    if a is None and b is None:
        return False
    if a is None or b is None:
        return True
    def _clean(d: dict) -> dict:
        return {k: v for k, v in d.items()
                if not str(k).startswith("_") and k != "name"}
    return _clean(a) != _clean(b)


def _smart_combos_count(objective: str) -> int:
    """
    Berechnet die Anzahl Kombinationen die smart_grid_setup pro Objective
    testet. Synchron mit den Konstanten in
    src/backtesting/optimizer.py:smart_grid_setup. Bei Backend-Aenderungen
    bitte hier mitziehen.
    """
    n_range = 4   # range_pcts = [0.05, 0.10, 0.15, 0.20]
    n_grids = 6   # grid_counts = [5, 10, 15, 20, 25, 30]
    n_modes = 4   # arithmetic, geometric, asymmetric_bottom/top
    # Mechanismus-Kombis je nach Objective (gleiche Mapping wie im Backend)
    table = {
        "maximize_roi":      (3, 1, 1, 1),  # mech, sl, dd, vo  -> 288
        "maximize_sharpe":   (3, 1, 3, 3),  # 96 × 3 × 3 × 3   -> 2592
        "maximize_calmar":   (3, 1, 2, 1),  # 576
        "minimize_drawdown": (1, 2, 2, 1),  # 384
    }
    mech, sl, dd, vo = table.get(objective, (3, 1, 1, 1))
    return n_range * n_grids * n_modes * mech * sl * dd * vo


# Smart-Setup-Info-Texte. Aktuell wird in der UI nur ROI angeboten — die
# anderen Branches im Backend-Optimizer bleiben fuer eventuelle spaetere
# Reaktivierung erhalten, sind aber hier nicht mehr referenziert.
_SMART_INFO = {
    "maximize_roi": ("Sucht die Konfiguration mit dem höchsten Gesamtgewinn. "
                     "Variiert: Range, Anzahl Grids, Modus, Recentering, Trailing."),
}


def _section_smart_setup(
    mode:             str,
    coin:             str,
    interval:         str,
    total_investment: float,
    period:           Optional[dict],
) -> None:
    """Smart-Setup-Box - schreibt Ergebniswerte in {mode}_new_*-Keys."""
    st.markdown(_divider(), unsafe_allow_html=True)
    st.markdown(_label("Smart Grid-Bot"), unsafe_allow_html=True)
    st.caption("Findet automatisch die beste Parametrisierung anhand "
                "historischer Daten.")

    # Aktuell wird ausschliesslich auf ROI optimiert. Die Optimierungsziel-
    # Wahl ist bewusst aus der UI entfernt; die anderen Branches im Backend
    # (Sharpe/Calmar/MinDrawdown) bleiben fuer eventuelle Reaktivierung.
    obj = "maximize_roi"

    # Transparenz-Info-Box: was wird optimiert + Kombi-Counter
    _info  = _SMART_INFO[obj]
    _combo = _smart_combos_count(obj)
    st.markdown(
        f"<div style='font-size:0.72rem; color:#94A3B8; padding:6px 10px; "
        f"background:rgba(255,255,255,0.02); border-radius:4px; "
        f"margin-top:4px; margin-bottom:6px;'>"
        f"<b style='color:#CBD5E1;'>Maximales ROI:</b> {_info} "
        f"<span style='color:#64748B;'>{_combo} Kombinationen werden getestet.</span>"
        f"</div>",
        unsafe_allow_html=True
    )

    if st.button("Optimale Parameter berechnen", key=f"{mode}_smart_run",
                  use_container_width=True):
        try:
            # H2: konsolidierte Backend-Funktion mit range_basis-Param.
            # BT nutzt Median des Sim-Zeitraums; PT/LT nutzen aktuellen Preis.
            from src.backtesting.optimizer import smart_grid_setup
            if mode == "backtest":
                days = (period or {}).get("days", 30)
                range_basis = "median"
            else:
                days = _DAYS_BY_INTERVAL.get(interval, 7)
                range_basis = "current_price"
            df, _ = get_price_data(coin, days=days, interval=interval)
            res = smart_grid_setup(
                df=df, total_investment=total_investment,
                objective=obj, interval=interval,
                range_basis=range_basis,
            )
            st.session_state[f"{mode}_smart_result"] = res
            st.session_state[f"{mode}_smart_error"]  = None if res else "Keine Daten verfügbar."
        except Exception as e:
            st.session_state[f"{mode}_smart_result"] = None
            st.session_state[f"{mode}_smart_error"]  = str(e)

    _res = st.session_state.get(f"{mode}_smart_result")
    _err = st.session_state.get(f"{mode}_smart_error")
    if _err:
        st.warning(_err)
        return
    if _res is None:
        return

    # H4: Ergebnis-Box inkl. Mechanismen
    _mode_lbl = {"arithmetic":"Arithmetisch","geometric":"Geometrisch",
                 "asymmetric_bottom":"Bottom Heavy","asymmetric_top":"Top Heavy"
                }.get(_res.grid_mode, _res.grid_mode)
    if _res.expected_roi_pct <= 0:
        st.warning(f"Kein profitables Setup gefunden (ROI: {_res.expected_roi_pct:+.2f}%)")
    else:
        st.success(f"Erwartetes ROI: {_res.expected_roi_pct:+.2f}%")

    # Recentering-Label
    _rc_up = bool(getattr(_res, "enable_recentering_up",   False))
    _rc_dn = bool(getattr(_res, "enable_recentering_down", False))
    if _rc_up and _rc_dn:   _rc_lbl = "Up + Down"
    elif _rc_up:            _rc_lbl = "Nur Up"
    elif _rc_dn:            _rc_lbl = "Nur Down"
    else:                   _rc_lbl = "Inaktiv"

    # Trailing-Label (nur Up-Variante, Binance-Standard)
    _tr_lbl = "Aktiv" if bool(getattr(_res, "enable_trailing_up", False)) else "Inaktiv"

    # Optionale Mechanismen (nur anzeigen wenn aktiv)
    _box_html = (
        f"<div style='font-size:0.78rem; color:#94A3B8; padding:8px 10px; "
        f"background:rgba(255,255,255,0.03); border-radius:4px; margin-top:6px;'>"
        f"<b style='color:#E2E8F0;'>Untere Grenze:</b> ${_res.lower_price:,.2f}<br>"
        f"<b style='color:#E2E8F0;'>Obere Grenze:</b> ${_res.upper_price:,.2f}<br>"
        f"<b style='color:#E2E8F0;'>Anzahl Grids:</b> {_res.num_grids}<br>"
        f"<b style='color:#E2E8F0;'>Grid-Modus:</b> {_mode_lbl}<br>"
        f"<b style='color:#E2E8F0;'>Recentering:</b> {_rc_lbl}<br>"
        f"<b style='color:#E2E8F0;'>Grid Trailing:</b> {_tr_lbl}"
    )
    _sl = getattr(_res, "stop_loss_pct", None)
    if _sl is not None:
        _box_html += f"<br><b style='color:#E2E8F0;'>Stop-Loss:</b> Aktiv ({int(_sl*100)}%)"
    if getattr(_res, "enable_dd_throttle", False):
        _box_html += f"<br><b style='color:#E2E8F0;'>DD-Drosselung:</b> Aktiv"
    if getattr(_res, "enable_variable_orders", False):
        _box_html += f"<br><b style='color:#E2E8F0;'>Variable Orders:</b> Aktiv"
    _box_html += "</div>"
    st.markdown(_box_html, unsafe_allow_html=True)

    if st.button("Übernehmen", key=f"{mode}_smart_apply",
                  use_container_width=True, type="primary"):
        st.session_state[f"{mode}_new_lower"] = float(_res.lower_price)
        st.session_state[f"{mode}_new_upper"] = float(_res.upper_price)
        st.session_state[f"{mode}_new_grids"] = int(_res.num_grids)
        if _res.grid_mode in ("arithmetic", "geometric"):
            st.session_state[f"{mode}_gm_active"] = "Symmetrisch"
            st.session_state[f"{mode}_gm_sym"]    = ("Arithmetisch" if _res.grid_mode == "arithmetic"
                                                     else "Geometrisch")
        else:
            st.session_state[f"{mode}_gm_active"] = "Asymmetrisch"
            st.session_state[f"{mode}_gm_asym"]   = ("Bottom heavy" if _res.grid_mode == "asymmetric_bottom"
                                                     else "Top heavy")
        # Mechanismen aus dem Smart-Setup uebernehmen
        st.session_state[f"{mode}_new_recenter"]      = bool(getattr(_res, "enable_recentering_up", False)
                                                              or getattr(_res, "enable_recentering_down", False))
        st.session_state[f"{mode}_new_recenter_up"]   = bool(getattr(_res, "enable_recentering_up",   False))
        st.session_state[f"{mode}_new_recenter_down"] = bool(getattr(_res, "enable_recentering_down", False))
        if getattr(_res, "stop_loss_pct", None) is not None:
            st.session_state[f"{mode}_new_sl"]     = True
            st.session_state[f"{mode}_new_sl_pct"] = float(_res.stop_loss_pct * 100)
        st.rerun()


def _section_grid_bounds(mode: str, current_price: Optional[float]) -> dict:
    """Range-Inputs (prozentual oder absolut)."""
    cp = current_price or 0.0
    lower_s = round(cp * 0.90, 2) if cp > 0 else 0.0
    upper_s = round(cp * 1.10, 2) if cp > 0 else 0.0
    step    = float(round(cp * 0.01, 2)) if cp > 0 else 1.0

    st.markdown(_divider(), unsafe_allow_html=True)
    st.markdown(_label("Grid-Grenzen"), unsafe_allow_html=True)
    if cp > 0:
        st.markdown(
            f"<div style='font-size:0.75rem; color:#94A3B8; margin-bottom:4px;'>"
            f"Aktueller Preis: <b style='color:#E2E8F0;'>{cp:,.2f} USDT</b></div>",
            unsafe_allow_html=True
        )

    pct_mode = st.checkbox("Preisgrenzen prozentual setzen", value=False,
                            key=f"{mode}_new_pct_mode")
    if pct_mode and cp > 0:
        c1, c2 = st.columns(2)
        with c1:
            st.markdown(_caption("Untere Grenze (%)"), unsafe_allow_html=True)
            pct_l = st.number_input("", 1.0, 50.0, 10.0, 1.0,
                                     key=f"{mode}_new_pct_lower",
                                     label_visibility="collapsed")
        with c2:
            st.markdown(_caption("Obere Grenze (%)"), unsafe_allow_html=True)
            pct_u = st.number_input("", 1.0, 50.0, 10.0, 1.0,
                                     key=f"{mode}_new_pct_upper",
                                     label_visibility="collapsed")
        lower_price = round(cp * (1 - pct_l / 100), 2)
        upper_price = round(cp * (1 + pct_u / 100), 2)
        st.caption(f"→ {lower_price:,.2f} – {upper_price:,.2f} USDT")
    else:
        c1, c2 = st.columns(2)
        with c1:
            st.markdown(_caption("Untere Grenze ($)"), unsafe_allow_html=True)
            lower_price = st.number_input(
                "", min_value=0.001, value=float(lower_s),
                step=step, key=f"{mode}_new_lower",
                label_visibility="collapsed"
            )
        with c2:
            st.markdown(_caption("Obere Grenze ($)"), unsafe_allow_html=True)
            upper_price = st.number_input(
                "", min_value=0.001, value=float(upper_s),
                step=step, key=f"{mode}_new_upper",
                label_visibility="collapsed"
            )
    return {"lower_price": float(lower_price), "upper_price": float(upper_price)}


def _section_grid_count_and_mode(
    mode:          str,
    coin:          str,
    interval:      str,
    lower_price:   float,
    upper_price:   float,
) -> dict:
    """Anzahl Grids + Gewinn/Grid-Info + ATR-Vorschlaege + Grid-Modus."""
    st.markdown(_divider(), unsafe_allow_html=True)
    st.markdown(_label("Anzahl Grids"), unsafe_allow_html=True)
    num_grids = int(st.number_input(
        "", min_value=2, max_value=100,
        value=int(st.session_state.get(f"{mode}_new_grids", DEFAULT_NUM_GRIDS)),
        step=1, key=f"{mode}_new_grids", label_visibility="collapsed"
    ))

    # Gewinn pro Grid (Vorschau) - fee_pct kommt aus session_state, weil
    # _section_risk in der neuen Reihenfolge erst NACH dieser Section laeuft
    fee_rate_pct = st.session_state.get(f"{mode}_new_fee", DEFAULT_FEE_RATE * 100)
    fee = fee_rate_pct / 100
    _gm_active = st.session_state.get(f"{mode}_gm_active", "Symmetrisch")
    _gm_sym    = st.session_state.get(f"{mode}_gm_sym", "Arithmetisch")
    preview_mode = ("arithmetic" if (_gm_active == "Symmetrisch" and _gm_sym == "Arithmetisch")
                    else "geometric")
    try:
        if preview_mode == "arithmetic":
            step  = (upper_price - lower_price) / num_grids
            gmin  = (step / upper_price - 2 * fee) * 100
            gmax  = (step / lower_price - 2 * fee) * 100
        else:
            ratio = (upper_price / lower_price) ** (1 / num_grids)
            gmin  = (ratio - 1 - 2 * fee) * 100
            gmax  = gmin
        gcolor = "#34D399" if gmin > 0 else "#F87171"
        st.markdown(
            f"<div style='margin-top:4px; margin-bottom:4px; padding:6px 10px; "
            f"background:rgba(52,211,153,0.07); border-left:3px solid {gcolor}; "
            f"border-radius:4px; font-size:0.78rem;'>"
            f"<span style='color:{gcolor}; font-weight:600;'>Gewinn pro Grid (nach Fees):</span>"
            f"<span style='color:{gcolor};'> {gmin:.2f}% – {gmax:.2f}%</span></div>",
            unsafe_allow_html=True
        )
    except Exception:
        pass

    # ATR-Vorschlaege
    try:
        days = _DAYS_BY_INTERVAL.get(interval, 7)
        df, _ = get_price_data(coin, days=days, interval=interval)
        if df is not None and not df.empty:
            atr_info = suggest_atr_grid_counts(df, upper_price - lower_price)
            with st.expander("Volatilitätsbasierte Vorschläge"):
                _atr  = atr_info["atr_usdt"]
                _s05  = atr_info["suggestions"][0.5]
                _s10  = atr_info["suggestions"][1.0]
                _s15  = atr_info["suggestions"][1.5]
                st.markdown(
                    f"<div style='font-size:0.75rem; color:#94A3B8;'>"
                    f"ATR (14 Kerzen) = <b style='color:#E2E8F0;'>{_atr:,.2f} USDT</b><br>"
                    f"× 0.5 → {_s05} Grids · × 1.0 → {_s10} Grids · × 1.5 → {_s15} Grids"
                    f"</div>",
                    unsafe_allow_html=True
                )
    except Exception:
        pass

    # Grid-Modus
    st.markdown(_divider(), unsafe_allow_html=True)
    st.markdown(_label("Grid-Modus"), unsafe_allow_html=True)
    gm_active = st.radio("", ["Symmetrisch", "Asymmetrisch"], horizontal=True,
                          key=f"{mode}_gm_active", label_visibility="collapsed")
    st.markdown(_caption("Symmetrisch"), unsafe_allow_html=True)
    gm_sym = st.radio("", ["Arithmetisch", "Geometrisch"], horizontal=True,
                       key=f"{mode}_gm_sym",
                       disabled=(gm_active != "Symmetrisch"),
                       label_visibility="collapsed")
    st.markdown(_caption("Asymmetrisch"), unsafe_allow_html=True)
    gm_asym = st.radio("", ["Bottom heavy", "Top heavy"], horizontal=True,
                        key=f"{mode}_gm_asym",
                        disabled=(gm_active != "Asymmetrisch"),
                        label_visibility="collapsed")
    if gm_active == "Symmetrisch":
        grid_mode = "arithmetic" if gm_sym == "Arithmetisch" else "geometric"
    else:
        grid_mode = "asymmetric_bottom" if gm_asym == "Bottom heavy" else "asymmetric_top"

    return {"num_grids": num_grids, "grid_mode": grid_mode}


def _render_chart_main(params: dict, mode: str = "paper") -> None:
    """
    Live-Chart-Vorschau im Hauptbereich + Chart-Einstellungen-Expander.
    Wird AUSSERHALB des with-Sidebar-Contexts aufgerufen, damit Streamlit
    den Chart in den Hauptbereich rendert (nicht in die Sidebar).

    Bei BT zeigt der Chart den Kerzen-Bereich VOM-Datum bis BIS-Datum.
    Bei PT/LT die letzten X Tage abhaengig vom Intervall.
    """
    from components.chart_settings import render_chart_settings

    coin     = params.get("coin", "")
    interval = params.get("interval", "1h")
    lower    = float(params.get("lower_price", 0) or 0)
    upper    = float(params.get("upper_price", 0) or 0)
    num      = int(params.get("num_grids", 10) or 10)
    gm       = params.get("grid_mode", "arithmetic")
    try:
        period = params.get("period") or {}
        if (mode == "backtest" and period.get("start_date")
                and period.get("end_date")):
            from datetime import date as _date
            sd = _date.fromisoformat(period["start_date"])
            ed = _date.fromisoformat(period["end_date"])
            df, _ = get_price_data(
                coin, days=period.get("days", 30),
                interval=interval, start_date=sd, end_date=ed,
            )
        else:
            days = _DAYS_BY_INTERVAL.get(interval, 7)
            df, _ = get_price_data(coin, days=days, interval=interval)
        if df is None or df.empty:
            st.info("Keine Preisdaten verfügbar.")
            return
        df_disp = convert_df_timestamps(df)
        try:
            gl = calculate_grid_lines(lower, upper, num, gm)
        except Exception:
            gl = []

        # Chart-Einstellungen (Bot-Start gibts in der Setup-Vorschau nicht)
        settings = render_chart_settings(key_prefix="setup")

        # SL/TP live aus aktuellen Slider-Werten (identische Formel wie GridBot)
        sl_pct_v = params.get("stop_loss_pct")
        tp_pct_v = params.get("take_profit_pct")
        sl_price_v = (
            float(lower) * (1 - float(sl_pct_v))
            if (sl_pct_v is not None and lower > 0) else None
        )
        tp_price_v = (
            float(upper) * (1 + float(tp_pct_v))
            if (tp_pct_v is not None and upper > 0) else None
        )

        plot_grid_chart_v2(
            df                  = df_disp,
            grid_lines          = gl,
            trade_log           = [],
            coin                = coin,
            interval            = interval,
            show_volume         = settings["show_volume"],
            upper_price         = float(gl[-1]) if gl else upper,
            lower_price         = float(gl[0])  if gl else lower,
            height              = 540,
            show_grid_lines     = settings["show_grid_lines"],
            show_grid_labels    = settings["show_grid_labels"],
            show_order_markers  = settings["show_order_markers"],
            bot_start_timestamp = None,  # Setup-Vorschau hat keinen Bot-Start
            magnet_crosshair    = settings["magnet_crosshair"],
            stop_loss_price     = sl_price_v,
            take_profit_price   = tp_price_v,
            show_stop_loss      = settings["show_stop_loss"],
            show_take_profit    = settings["show_take_profit"],
            trailing_up_stop    = params.get("trailing_up_stop"),
            show_trailing_stops = settings["show_trailing_stops"],
            # Setup-Vorschau hat keine Events (Bot existiert noch nicht)
            recentering_events     = [],
            show_recentering_steps = settings["show_recentering_steps"],
            show_range_fill        = settings["show_range_fill"],
            show_trailing_fill     = settings["show_trailing_fill"],
            show_recentering_fill  = settings["show_recentering_fill"],
            # M.1: Vorschau-Chart vertikal auf den Anker-Preis zentrieren.
            # BT  -> erster Close im DF (= Von-Datum-Preis).
            # PT/LT -> letzter Close (aktueller Preis).
            chart_anchor_price        = (float(df["close"].iloc[0])
                                          if mode == "backtest"
                                          else float(df["close"].iloc[-1])),
            # SL/TP-Trigger gibt's im Setup-Stadium noch nicht
            sl_trigger                = None,
            tp_trigger                = None,
            show_sltp_trigger_markers = settings.get("show_sltp_trigger_markers", True),
        )
    except Exception as e:
        st.caption(f"Chart nicht verfügbar: {e}")


def _sl_tp_price_pair(side: str, mode: str, ref_price: float,
                       sub_mode: str) -> Optional[float]:
    """
    Rendert ein Pair aus zwei halbbreiten number_inputs fuer den Price-Modus:
      links : absoluter USDT-Preis
      rechts: Prozent relativ zur Grenze (Upper bei TP, Lower bei SL)
    Je nach sub_mode ist eines aktiv und das andere disabled mit dem
    automatisch berechneten Aequivalent als Anzeige.

    Returns: finalen take_profit_pct/stop_loss_pct (relativ zur Grenze)
             als Backend-kompatibler Wert. None wenn ref_price <= 0.
    """
    if ref_price <= 0:
        return None
    # Default-Werte (15 %): TP = +15 %, SL = +15 % unter lower
    default_pct = 15.0
    default_abs = (ref_price * 1.15 if side == "tp" else ref_price * 0.85)
    abs_key  = f"{mode}_new_{side}_price_abs"
    pct_key  = f"{mode}_new_{side}_price_pct"

    # Defaults wenn noch nicht in session_state
    if abs_key not in st.session_state:
        st.session_state[abs_key] = float(default_abs)
    if pct_key not in st.session_state:
        st.session_state[pct_key] = float(default_pct)

    # Vor dem Render das disabled-Feld synchronisieren, sodass beide
    # Felder immer konsistent zueinander sind. Source-of-truth ist das
    # aktive Feld (sub_mode bestimmt das).
    if sub_mode == "Manuell (USDT)":
        abs_v = float(st.session_state[abs_key])
        if side == "tp":
            st.session_state[pct_key] = (abs_v / ref_price - 1.0) * 100.0
        else:
            st.session_state[pct_key] = (1.0 - abs_v / ref_price) * 100.0
    else:  # "% von Grenze"
        pct_v = float(st.session_state[pct_key])
        if side == "tp":
            st.session_state[abs_key] = ref_price * (1.0 + pct_v / 100.0)
        else:
            st.session_state[abs_key] = ref_price * (1.0 - pct_v / 100.0)

    col_l, col_r = st.columns(2)
    with col_l:
        abs_v = st.number_input(
            "Preis (USDT)", step=1.0, key=abs_key,
            disabled=(sub_mode != "Manuell (USDT)"),
        )
    with col_r:
        pct_v = st.number_input(
            "% von Grenze", step=0.1, key=pct_key,
            disabled=(sub_mode != "% von Grenze"),
        )

    # Backend-Wert immer aus dem AKTIVEN Feld berechnen.
    if sub_mode == "Manuell (USDT)":
        if side == "tp":
            return float(abs_v) / ref_price - 1.0
        return 1.0 - float(abs_v) / ref_price
    else:
        return float(pct_v) / 100.0


def _section_sl_tp(mode: str, lower_price: float = 0.0,
                    upper_price: float = 0.0,
                    total_investment: float = 0.0) -> dict:
    """
    Kombinierte Take-Profit / Stop-Loss-Sektion (Binance-Style).

    Hauptcheckbox aktiviert die Sektion. Daraufhin Modus-Wahl (exklusiv:
    %ROI oder Price) und zwei horizontale Boxen (Take-Profit oben,
    Stop-Loss unten), beide einzeln optional.

    Im Price-Modus zusaetzlich ein Sub-Modus-Radio "Manuell (USDT)" /
    "% von Grenze" — User kann den Stop-Preis entweder absolut in USDT
    oder als Prozent ueber/unter der Grid-Grenze eingeben. Beide Felder
    werden immer nebeneinander gerendert, das jeweils inaktive ist
    disabled und zeigt das automatisch berechnete Aequivalent.

    Modus-Wahl + Sub-Modus sind UI-only (session_state). Backend bekommt
    nur die Felder des gewaehlten Modus.

    P/L-Modus aktuell nicht in der UI exponiert (Backend-Code bleibt fuer
    eventuelle Reaktivierung — analog Sharpe-Branch im Optimizer).
    """
    st.markdown(_divider(), unsafe_allow_html=True)
    main_enabled = st.checkbox(
        "Take-Profit / Stop-Loss",
        key=f"{mode}_new_sltp",
        help=("Schliesst alle Positionen, sobald die Take-Profit- oder "
              "Stop-Loss-Schwelle erreicht ist."),
    )
    empty = {
        "stop_loss_pct":       None, "take_profit_pct":       None,
        "stop_loss_roi_pct":   None, "take_profit_roi_pct":   None,
        "stop_loss_pl_usdt":   None, "take_profit_pl_usdt":   None,
    }
    if not main_enabled:
        return empty

    # ── Modus-Wahl (exklusiv, UI-only) ──────────────────────────────────────
    chosen_mode = st.radio(
        "Modus", options=["%ROI", "Price"],
        horizontal=True, key=f"{mode}_new_sltp_mode",
        label_visibility="collapsed",
    )

    # Sub-Modus-Wahl nur im Price-Modus
    sub_mode = "Manuell (USDT)"
    if chosen_mode == "Price":
        sub_mode = st.radio(
            "Eingabe-Modus",
            options=["Manuell (USDT)", "% von Grenze"],
            horizontal=True, key=f"{mode}_new_sltp_price_sub",
            label_visibility="collapsed",
        )

    # ── Take-Profit Box ─────────────────────────────────────────────────────
    tp_pct_backend: Optional[float] = None
    with st.container(border=True):
        st.markdown(
            "<div style='color:#CBD5E1; font-weight:600; font-size:0.82rem; "
            "margin-bottom:4px;'>Take-Profit</div>",
            unsafe_allow_html=True,
        )
        tp_enabled = st.checkbox("Aktivieren", key=f"{mode}_new_tp_enabled")
        if tp_enabled:
            if chosen_mode == "%ROI":
                tp_roi = st.number_input(
                    "ROI in %",
                    value=float(st.session_state.get(
                        f"{mode}_new_tp_roi_pct_v", 15.0)),
                    step=1.0, key=f"{mode}_new_tp_roi_pct_v",
                    label_visibility="collapsed",
                )
                if total_investment > 0 and tp_roi:
                    gain = total_investment * (tp_roi / 100.0)
                    st.markdown(
                        _caption(
                            f"Take-Profit bei Bot-ROI "
                            f"<b style='color:#E2E8F0;'>≥ +{tp_roi:.1f}%</b> "
                            f"(Gewinn von <b>${gain:,.2f}</b> USDT)"
                        ),
                        unsafe_allow_html=True,
                    )
                if tp_roi and tp_roi > 0:
                    tp_pct_backend = ("roi", float(tp_roi) / 100.0)
            else:  # Price
                tp_pct_backend = ("price",
                                   _sl_tp_price_pair("tp", mode,
                                                      upper_price, sub_mode))

    # ── Stop-Loss Box ───────────────────────────────────────────────────────
    sl_pct_backend: Optional[float] = None
    with st.container(border=True):
        st.markdown(
            "<div style='color:#CBD5E1; font-weight:600; font-size:0.82rem; "
            "margin-bottom:4px;'>Stop-Loss</div>",
            unsafe_allow_html=True,
        )
        sl_enabled = st.checkbox("Aktivieren", key=f"{mode}_new_sl_enabled")
        if sl_enabled:
            if chosen_mode == "%ROI":
                sl_roi = st.number_input(
                    "ROI in %",
                    value=float(st.session_state.get(
                        f"{mode}_new_sl_roi_pct_v", 15.0)),
                    step=1.0, key=f"{mode}_new_sl_roi_pct_v",
                    label_visibility="collapsed",
                )
                if total_investment > 0 and sl_roi:
                    loss = total_investment * (sl_roi / 100.0)
                    st.markdown(
                        _caption(
                            f"Stop-Loss bei Bot-ROI "
                            f"<b style='color:#E2E8F0;'>≤ −{sl_roi:.1f}%</b> "
                            f"(Verlust von <b>${loss:,.2f}</b> USDT)"
                        ),
                        unsafe_allow_html=True,
                    )
                if sl_roi and sl_roi > 0:
                    sl_pct_backend = ("roi", float(sl_roi) / 100.0)
            else:  # Price
                sl_pct_backend = ("price",
                                   _sl_tp_price_pair("sl", mode,
                                                      lower_price, sub_mode))

    # ── Backend-Felder befuellen ────────────────────────────────────────────
    result = dict(empty)
    if isinstance(tp_pct_backend, tuple):
        kind, val = tp_pct_backend
        if val and val > 0:
            if kind == "roi":
                result["take_profit_roi_pct"] = val
            else:
                result["take_profit_pct"] = val
    if isinstance(sl_pct_backend, tuple):
        kind, val = sl_pct_backend
        if val and val > 0:
            if kind == "roi":
                result["stop_loss_roi_pct"] = val
            else:
                result["stop_loss_pct"] = val
    return result


def _section_grid_trigger_inline(mode: str,
                                  current_price: Optional[float]) -> Optional[float]:
    """
    Grid Trigger als Sub-Element der Kapital-Sektion. Kein eigener Divider,
    kein eigenes Section-Label — wird unter Startkapital/Initial-Buy
    eingebettet. Gibt den Trigger-Preis (oder None) zurueck.
    """
    enabled = st.checkbox(
        "Grid Trigger", key=f"{mode}_new_trigger",
        help=("Bot wartet auf Preis-Berührung dieses Werts. Erst dann "
              "werden Grid und Initial-Orders aufgebaut. Aus = Bot startet "
              "sofort zum aktuellen Marktpreis."),
    )
    if not enabled:
        return None
    default_trigger = float(current_price) if current_price else 0.0
    prior = float(st.session_state.get(f"{mode}_new_trigger_price",
                                        default_trigger))
    trigger_price = st.number_input(
        "Trigger-Preis (USDT)",
        min_value=0.0, value=prior, step=1.0,
        key=f"{mode}_new_trigger_price", label_visibility="collapsed",
    )
    if trigger_price <= 0:
        return None
    if current_price and current_price > 0:
        direction = ("Anstieg" if current_price < trigger_price
                     else "Rückgang" if current_price > trigger_price
                     else "sofort")
        st.markdown(
            _caption(
                f"Aktueller Preis: <b style='color:#E2E8F0;'>{current_price:,.2f}</b> "
                f"USDT &nbsp;→&nbsp; wartet auf <b style='color:#E2E8F0;'>{direction}</b>"
            ),
            unsafe_allow_html=True,
        )
    return float(trigger_price)


def _section_dd_throttle(mode: str) -> dict:
    enabled = st.checkbox("Drawdown-Drosselung", key=f"{mode}_new_dd")
    t1, t2 = 0.10, 0.20
    if enabled:
        st.markdown(_caption("Schwelle 1 (%)  → 50% Ordergröße"), unsafe_allow_html=True)
        t1 = st.slider("", 5.0, 30.0, 10.0, 1.0,
                        key=f"{mode}_new_dd_t1", label_visibility="collapsed") / 100
        st.markdown(_caption("Schwelle 2 (%)  → 25% Ordergröße"), unsafe_allow_html=True)
        t2 = st.slider("", 10.0, 50.0, 20.0, 1.0,
                        key=f"{mode}_new_dd_t2", label_visibility="collapsed") / 100
    return {"enable_dd_throttle": enabled, "dd_threshold_1": t1, "dd_threshold_2": t2}


def _section_variable_orders(mode: str) -> dict:
    enabled = st.checkbox("Variable Ordergrößen", key=f"{mode}_new_vo")
    wb, wt = 2.0, 0.5
    if enabled:
        c1, c2 = st.columns(2)
        with c1:
            wb = st.number_input("unten ×", 1.0, 5.0, 2.0, 0.1,
                                  key=f"{mode}_new_vo_b")
        with c2:
            wt = st.number_input("oben ×", 0.1, 2.0, 0.5, 0.1,
                                  key=f"{mode}_new_vo_t")
    return {"enable_variable_orders": enabled, "weight_bottom": wb, "weight_top": wt}


def _section_atr_adjust(mode: str) -> dict:
    enabled = st.checkbox("Volatilitätsbasierte Anpassung", key=f"{mode}_new_atr")
    mult, dyn, dyn_thr = 1.0, False, 0.15
    if enabled:
        mult = st.slider("ATR-Multiplikator", 0.5, 5.0, 1.0, 0.1,
                          key=f"{mode}_new_atr_mult")
        dyn  = st.checkbox("Dynamische Neuberechnung",
                            key=f"{mode}_new_atr_dyn")
        if dyn:
            dyn_thr = st.slider("Schwelle (%)", 5.0, 50.0, 15.0, 1.0,
                                 key=f"{mode}_new_atr_dyn_thr") / 100
    return {"enable_atr_adjust": enabled, "atr_multiplier": mult,
            "enable_atr_dynamic": dyn, "atr_dynamic_threshold": dyn_thr}


def _section_recentering(mode: str, trailing_active: bool) -> dict:
    enabled = st.checkbox(
        "Recentering",
        key=f"{mode}_new_recenter",
        disabled=trailing_active,
        help=("Nicht kombinierbar mit Grid Trailing" if trailing_active else
              "Verschiebt das Grid-Zentrum auf den aktuellen Preis, wenn "
              "dieser um die Schwelle ueber die obere Range-Grenze steigt. "
              "Up-only (Industrie-Standard fuer Spot-Grid-Bots)."),
    )
    if trailing_active and enabled:
        enabled = False
    # Recentering im UI implizit Up-only. Backend-Parameter
    # enable_recentering_down bleibt fuer Backward-Compat existieren,
    # wird hier aber immer False gesetzt.
    up, thr = False, 0.05
    if enabled:
        up = True
        st.markdown(_caption("Recentering-Schwelle (%)"), unsafe_allow_html=True)
        thr = st.slider("", 1.0, 20.0, 5.0, 1.0,
                         key=f"{mode}_new_recenter_thr",
                         label_visibility="collapsed") / 100
    return {"enable_recentering_up":   up,
            "enable_recentering_down": False,
            "recenter_threshold":      thr}


def _section_trailing(mode: str, recenter_active: bool,
                      lower: float, upper: float) -> dict:
    """
    Grid-Trailing-Section (Binance-Standard, nur Up-Variante).

    Trigger im Backend: current_price >= upper + grid_step.
    Trailing-Up-Stop ist immer ein absoluter USDT-Preis im Backend.
    Die UI bietet zwei Eingabe-Modi (Prozent oder Absolut) ueber ein
    Dropdown — Modus-Wahl ist UI-only, nicht persistiert.

    Optional: trail_stop_levels laesst preis-basierte SL/TP-Schwellen
    bei jedem Trailing-Shift um einen Grid-Step mitwandern.
    """
    enabled = st.checkbox(
        "Grid Trailing",
        key=f"{mode}_new_trailing",
        disabled=recenter_active,
        help=("Nicht kombinierbar mit Recentering"
              if recenter_active else None),
    )
    if recenter_active and enabled:
        enabled = False
    up           = False
    up_stop      = None
    trail_levels = False
    if enabled:
        up = True
        # Modus-Wahl Prozent vs. Absolut (UI-only, in session_state).
        mode_key = f"{mode}_new_tr_up_mode"
        chosen_mode = st.radio(
            "Trailing-Up-Stop", options=["% von Upper", "Absolut"],
            horizontal=True, key=mode_key,
        )
        if chosen_mode == "% von Upper":
            st.markdown(_caption("Prozent über Upper-Grenze"),
                        unsafe_allow_html=True)
            pct = st.slider("", 1.0, 50.0,
                             float(st.session_state.get(f"{mode}_new_tr_up_pct", 10.0)),
                             1.0, key=f"{mode}_new_tr_up_pct",
                             label_visibility="collapsed") / 100
            if upper and upper > 0:
                up_stop = float(upper) * (1 + pct)
        else:
            st.markdown(_caption("Absoluter Stop-Preis (USDT)"),
                        unsafe_allow_html=True)
            default_abs = float(upper) * 1.10 if upper > 0 else 0.0
            up_stop = st.number_input(
                "", min_value=0.0,
                value=float(st.session_state.get(f"{mode}_new_tr_up_abs", default_abs)),
                step=1.0, key=f"{mode}_new_tr_up_abs",
                label_visibility="collapsed",
            )
            up_stop = float(up_stop) if up_stop and up_stop > 0 else None

        # Referenz-Anzeige (Upper-Grenze) - in beiden Modi sichtbar.
        if upper and upper > 0:
            st.markdown(
                _caption(
                    f"Upper-Grenze ist bei <b style='color:#E2E8F0;'>"
                    f"{upper:,.2f} USDT</b> gesetzt"
                ),
                unsafe_allow_html=True,
            )

        # Live-Anzeige des absoluten Stop-Preises (immer, unabhaengig vom Modus)
        if up_stop is not None and upper > 0:
            st.markdown(
                _caption(
                    f"Trailing-Up-Stop bei <b style='color:#E2E8F0;'>"
                    f"{up_stop:,.2f} USDT</b>"
                ),
                unsafe_allow_html=True,
            )

        # Optionaler Toggle: SL/TP-Schwellen mitwandern
        trail_levels = st.checkbox(
            "Stopp-Grenzen mitwandern",
            key=f"{mode}_new_trail_stop_levels",
            help=("Preis-basierte SL/TP-Schwellen wandern bei jedem "
                  "Trailing-Shift um einen Grid-Step nach oben mit. "
                  "ROI-basierte Schwellen sind preis-unabhängig und "
                  "bleiben unverändert."),
        )
    return {"enable_trailing_up":   up,
            "trailing_up_stop":     up_stop,
            "trail_stop_levels":    trail_levels}


# ---------------------------------------------------------------------------
# Hauptfunktion
# ---------------------------------------------------------------------------

def render_bot_setup_form(
    mode:                str,
    on_submit:           Callable[[dict], None],
    on_back:             Callable[[], None],
    suppress_main_chart: bool = False,
) -> None:
    """
    Rendert die Bot-Aufsetzen-Form fuer einen Modus.

    Layout:
        Sidebar     : "← Zurueck" + alle Konfigurations-Inputs + Submit
        Hauptbereich: Live-Chart-Vorschau (aktualisiert sich bei jeder
                      Sidebar-Parameter-Aenderung)

    Args:
        mode                : "backtest" | "paper" | "live"
        on_submit           : Wird bei Klick auf Submit mit dem params-Dict
                              aufgerufen.
        on_back             : "← Zurueck"-Callback.
        suppress_main_chart : Wenn True wird der Live-Chart im Hauptbereich
                              NICHT gerendert (BT-Pending-Result-Ansicht).

    Side-Effect:
        Bei jedem Render wird das aktuelle params-Dict (ohne interne
        Helper-Keys und ohne Name) in st.session_state["<mode>_current_params"]
        abgelegt, damit die Page-Ebene Parameter-Aenderungen erkennen kann.
    """
    title = ("Neuen Backtest konfigurieren" if mode == "backtest"
             else "Neuen Bot konfigurieren")

    # Hauptbereich-Header (kompakt - der eigentliche Inhalt steht in der Sidebar)
    st.markdown(f"### {title}")

    params = _default_params(mode)
    submit_triggered = False

    # ── Sidebar: komplette Konfiguration ────────────────────────────────────
    with st.sidebar:
        if st.button("← Zurück", key=f"{mode}_form_back",
                      use_container_width=True):
            on_back()
        st.markdown(_divider(), unsafe_allow_html=True)

        params.update(_section_basic(mode))

        # Referenz-Preis fuer Range-Default + Live-Chart-Anker:
        # BT -> Schlusskurs am Von-Datum, PT/LT -> letzter Live-Preis.
        # Wird VOR _section_capital geladen, damit der Grid-Trigger darin
        # den current_price als Fallback nutzen kann.
        current_price = _load_current_price(
            params["coin"], params["interval"],
            params.get("period"), mode,
        )

        # ── Sektion "Kapital" ────────────────────────────────────────────────
        # Inhalt: Startkapital, Initial-Buy-Toggle, Grid-Trigger,
        # Gebuehrenrate, Kapitalreserve.
        params.update(_section_capital(mode, current_price))

        # Smart-Setup
        _section_smart_setup(mode, params["coin"], params["interval"],
                              params["total_investment"], params.get("period"))

        params.update(_section_grid_bounds(mode, current_price))
        params.update(_section_grid_count_and_mode(
            mode, params["coin"], params["interval"],
            params["lower_price"], params["upper_price"],
        ))

        # ── Sektion: Dynamische Mechanismen ──────────────────────────────────
        st.markdown(_divider(), unsafe_allow_html=True)
        st.markdown(_label("Dynamische Mechanismen"), unsafe_allow_html=True)
        params.update(_section_dd_throttle(mode))
        params.update(_section_variable_orders(mode))
        params.update(_section_atr_adjust(mode))
        # Recentering / Trailing - gegenseitige Verriegelung via session_state
        tr_active = st.session_state.get(f"{mode}_new_trailing", False)
        params.update(_section_recentering(mode, trailing_active=tr_active))
        rc_active = st.session_state.get(f"{mode}_new_recenter", False)
        params.update(_section_trailing(mode, recenter_active=rc_active,
                                         lower=params["lower_price"],
                                         upper=params["upper_price"]))
        params.update(_section_sl_tp(
            mode,
            params["lower_price"], params["upper_price"],
            params["total_investment"],
        ))

        # Submit
        st.markdown(_divider(), unsafe_allow_html=True)
        submit_lbl = ("Backtest starten" if mode == "backtest"
                      else "Bot starten")
        if st.button(submit_lbl, key=f"{mode}_submit", type="primary",
                      use_container_width=True):
            submit_triggered = True

    # ── Aktuelles params-Dict ins session_state schreiben ───────────────────
    # Damit die Page-Ebene Parameter-Aenderungen erkennen und ein gespeichertes
    # Pending-Result automatisch verwerfen kann.
    _params_for_diff = {
        k: v for k, v in params.items()
        if not k.startswith("_") and k not in ("name",)
    }
    st.session_state[f"{mode}_current_params"] = _params_for_diff

    # ── Hauptbereich: Live-Chart-Vorschau ───────────────────────────────────
    if not suppress_main_chart:
        _render_chart_main(params, mode=mode)

    # ── Submit-Validierung + Callback ───────────────────────────────────────
    if submit_triggered:
        if params["lower_price"] >= params["upper_price"]:
            st.error("Untere Grenze muss kleiner als obere sein.")
            return
        if mode == "backtest":
            p = params.get("period") or {}
            if p.get("days", 0) <= 0:
                st.error("Zeitraum ungültig.")
                return
            if not params["name"]:
                params["name"] = f"{params['coin']} {p.get('start_date','')}–{p.get('end_date','')}"
        # internal-only Helper-Keys aus dem params-Dict entfernen
        for k in list(params.keys()):
            if k.startswith("_"):
                params.pop(k, None)
        on_submit(params)
