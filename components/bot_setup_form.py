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
        "enable_trailing_down":   False,
        "trailing_up_stop":       None,
        "trailing_down_stop":     None,
        # Grid Trigger (None = Bot startet sofort, Wert = Bot wartet auf Touch)
        "grid_trigger_price":     None,
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


def _section_capital(mode: str) -> dict:
    """Startkapital."""
    st.markdown(_divider(), unsafe_allow_html=True)
    st.markdown(_label("Startkapital"), unsafe_allow_html=True)
    val = st.number_input("", min_value=100.0, max_value=1_000_000.0,
                           value=10_000.0, step=500.0,
                           key=f"{mode}_new_capital",
                           label_visibility="collapsed")
    return {"total_investment": float(val)}


def _load_current_price(coin: str, interval: str) -> Optional[float]:
    """Holt den letzten Schlusskurs fuer Smart-Setup / Default-Range."""
    try:
        days = _DAYS_BY_INTERVAL.get(interval, 7)
        df, _ = get_price_data(coin, days=days, interval=interval)
        if df is not None and not df.empty:
            return float(df["close"].iloc[-1])
    except Exception:
        pass
    return None


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
        "maximize_sharpe":   (3, 1, 1, 2),  # 576
        "maximize_calmar":   (3, 1, 2, 1),  # 576
        "minimize_drawdown": (1, 2, 2, 1),  # 384
    }
    mech, sl, dd, vo = table.get(objective, (3, 1, 1, 1))
    return n_range * n_grids * n_modes * mech * sl * dd * vo


_SMART_INFO = {
    "maximize_roi":    ("Sucht die Konfiguration mit dem hoechsten Gesamtgewinn. "
                        "Variiert: Range, Anzahl Grids, Modus, Recentering, Trailing."),
    "maximize_sharpe": ("Sucht das beste Verhaeltnis von Gewinn zu Volatilitaet "
                        "(risikobereinigt). Variiert zusaetzlich: Variable Orders."),
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

    # H1: nur zwei UI-Optionen (Backend kennt weiterhin alle 4 Objectives)
    options = {
        "maximize_roi":    "Maximales ROI",
        "maximize_sharpe": "Bester Sharpe",
    }
    obj = st.radio("Optimierungsziel",
                    list(options.keys()),
                    format_func=lambda x: options[x],
                    horizontal=True,
                    key=f"{mode}_smart_obj",
                    label_visibility="collapsed")

    # H3: Transparenz-Info-Box - was wird optimiert + Kombi-Counter
    _info  = _SMART_INFO.get(obj, "")
    _combo = _smart_combos_count(obj)
    st.markdown(
        f"<div style='font-size:0.72rem; color:#94A3B8; padding:6px 10px; "
        f"background:rgba(255,255,255,0.02); border-radius:4px; "
        f"margin-top:4px; margin-bottom:6px;'>"
        f"<b style='color:#CBD5E1;'>🎯 {options[obj]}:</b> {_info} "
        f"<span style='color:#64748B;'>{_combo} Kombinationen werden getestet.</span>"
        f"</div>",
        unsafe_allow_html=True
    )

    if st.button("🎯 Optimale Parameter berechnen", key=f"{mode}_smart_run",
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

    # Trailing-Label
    _tr_up = bool(getattr(_res, "enable_trailing_up",   False))
    _tr_dn = bool(getattr(_res, "enable_trailing_down", False))
    if _tr_up and _tr_dn:   _tr_lbl = "Up + Down"
    elif _tr_up:            _tr_lbl = "Nur Up"
    elif _tr_dn:            _tr_lbl = "Nur Down"
    else:                   _tr_lbl = "Inaktiv"

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


def _render_chart_main(params: dict) -> None:
    """
    Live-Chart-Vorschau im Hauptbereich + Chart-Einstellungen-Expander.
    Wird AUSSERHALB des with-Sidebar-Contexts aufgerufen, damit Streamlit
    den Chart in den Hauptbereich rendert (nicht in die Sidebar).
    """
    from components.chart_settings import render_chart_settings

    coin     = params.get("coin", "")
    interval = params.get("interval", "1h")
    lower    = float(params.get("lower_price", 0) or 0)
    upper    = float(params.get("upper_price", 0) or 0)
    num      = int(params.get("num_grids", 10) or 10)
    gm       = params.get("grid_mode", "arithmetic")
    try:
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
            trailing_down_stop  = params.get("trailing_down_stop"),
            show_trailing_stops = settings["show_trailing_stops"],
        )
    except Exception as e:
        st.caption(f"Chart nicht verfügbar: {e}")


def _section_risk(mode: str) -> dict:
    """Gebuehrenrate + Kapitalreserve."""
    st.markdown(_divider(), unsafe_allow_html=True)
    st.markdown(_label("Risiko & Kapital"), unsafe_allow_html=True)
    st.markdown(_caption("Gebührenrate (%)"), unsafe_allow_html=True)
    fee_pct = st.number_input("", 0.0, 1.0, DEFAULT_FEE_RATE * 100, 0.01,
                               format="%.3f", key=f"{mode}_new_fee",
                               label_visibility="collapsed")
    st.markdown(_caption("Kapitalreserve (%)"), unsafe_allow_html=True)
    reserve_pct = st.slider("", 0.0, 20.0, DEFAULT_RESERVE_PCT * 100, 1.0,
                             key=f"{mode}_new_reserve",
                             label_visibility="collapsed") / 100
    return {"fee_rate": fee_pct / 100, "reserve_pct": float(reserve_pct),
            "_fee_pct": fee_pct}


def _section_stop_loss(mode: str, lower_price: float = 0.0) -> dict:
    st.markdown(_divider(), unsafe_allow_html=True)
    enabled = st.checkbox(
        "Stop-Loss aktivieren", key=f"{mode}_new_sl",
        help=("Schliesst alle Positionen, wenn der Preis um den eingestellten "
              "Prozentsatz unter die untere Grid-Grenze fällt."),
    )
    pct = None
    if enabled:
        pct = st.slider("", 1.0, 50.0,
                         float(st.session_state.get(f"{mode}_new_sl_pct", 20.0)),
                         1.0, key=f"{mode}_new_sl_pct",
                         label_visibility="collapsed") / 100
        # Live-Anzeige des berechneten Preis-Schwellwerts (analog Backend-Logik).
        if lower_price and lower_price > 0:
            sl_price = lower_price * (1 - pct)
            st.markdown(
                _caption(
                    f"Stop-Loss bei <b style='color:#E2E8F0;'>"
                    f"{sl_price:,.2f} USDT</b> "
                    f"(Lower {lower_price:,.2f} × −{int(pct*100)}%)"
                ),
                unsafe_allow_html=True,
            )
    return {"stop_loss_pct": pct}


def _section_take_profit(mode: str, upper_price: float = 0.0) -> dict:
    enabled = st.checkbox(
        "Take-Profit aktivieren", key=f"{mode}_new_tp",
        help=("Schliesst alle Positionen, wenn der Preis um den eingestellten "
              "Prozentsatz über die obere Grid-Grenze steigt."),
    )
    pct = None
    if enabled:
        pct = st.slider("", 1.0, 100.0,
                         float(st.session_state.get(f"{mode}_new_tp_pct", 20.0)),
                         1.0, key=f"{mode}_new_tp_pct",
                         label_visibility="collapsed") / 100
        # Live-Anzeige des berechneten Preis-Schwellwerts (analog Backend-Logik).
        if upper_price and upper_price > 0:
            tp_price = upper_price * (1 + pct)
            st.markdown(
                _caption(
                    f"Take-Profit bei <b style='color:#E2E8F0;'>"
                    f"{tp_price:,.2f} USDT</b> "
                    f"(Upper {upper_price:,.2f} × +{int(pct*100)}%)"
                ),
                unsafe_allow_html=True,
            )
    return {"take_profit_pct": pct}


def _section_grid_trigger(mode: str, lower: float, upper: float,
                          current_price: Optional[float]) -> dict:
    """
    Optionaler Grid Trigger Price. Bot wartet bis Marktpreis diesen Wert
    beruehrt — dann erst wird das Initial-Setup ausgefuehrt.
    """
    st.markdown(_divider(), unsafe_allow_html=True)
    enabled = st.checkbox(
        "Grid Trigger aktivieren", key=f"{mode}_new_trigger",
        help=("Bot wartet auf Preis-Beruehrung dieses Werts. Erst dann "
              "werden Grid und Initial-Orders aufgebaut. Leer = Bot startet "
              "sofort zum aktuellen Marktpreis."),
    )
    trigger_price = None
    if enabled:
        # Default = Mitte der Range
        default_trigger = float((lower + upper) / 2.0) if (lower and upper) else (
            float(current_price) if current_price else 0.0
        )
        prior = float(st.session_state.get(f"{mode}_new_trigger_price",
                                            default_trigger))
        trigger_price = st.number_input(
            "Trigger-Preis (USDT)",
            min_value=0.0, value=prior, step=1.0,
            key=f"{mode}_new_trigger_price", label_visibility="collapsed",
        )
        if trigger_price <= 0:
            trigger_price = None
        elif current_price and current_price > 0:
            direction = "Anstieg" if current_price < trigger_price else (
                "Rueckgang" if current_price > trigger_price else "sofort"
            )
            st.markdown(
                _caption(
                    f"Aktueller Preis: <b style='color:#E2E8F0;'>{current_price:,.2f}</b> "
                    f"USDT &nbsp;→&nbsp; wartet auf <b style='color:#E2E8F0;'>{direction}</b>"
                ),
                unsafe_allow_html=True,
            )
    return {"grid_trigger_price": trigger_price}


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
        "Recentering aktivieren",
        key=f"{mode}_new_recenter",
        disabled=trailing_active,
        help="Nicht kombinierbar mit Grid Trailing" if trailing_active else None,
    )
    if trailing_active and enabled:
        enabled = False
    up, down, thr = False, False, 0.05
    if enabled:
        if f"{mode}_new_recenter_up" not in st.session_state:
            st.session_state[f"{mode}_new_recenter_up"] = True
        c1, c2 = st.columns([1, 17])
        with c2:
            up   = st.checkbox("Recentering Up",   value=True,
                                key=f"{mode}_new_recenter_up")
            down = st.checkbox("Recentering Down", value=False,
                                key=f"{mode}_new_recenter_down")
        st.markdown(_caption("Recentering-Schwelle (%)"), unsafe_allow_html=True)
        thr = st.slider("", 1.0, 20.0, 5.0, 1.0,
                         key=f"{mode}_new_recenter_thr",
                         label_visibility="collapsed") / 100
    return {"enable_recentering_up":  up,
            "enable_recentering_down": down,
            "recenter_threshold":     thr}


def _section_trailing(mode: str, recenter_active: bool,
                      lower: float, upper: float) -> dict:
    enabled = st.checkbox(
        "Grid Trailing aktivieren",
        key=f"{mode}_new_trailing",
        disabled=recenter_active,
        help="Nicht kombinierbar mit Recentering" if recenter_active else None,
    )
    if recenter_active and enabled:
        enabled = False
    up, down, up_stop, down_stop = False, False, None, None
    if enabled:
        up   = st.checkbox("Trailing Up",   value=True, key=f"{mode}_new_tr_up")
        down = st.checkbox("Trailing Down", value=True, key=f"{mode}_new_tr_down")
        if up:
            st.markdown(_caption("Trailing Up Stop ($)"), unsafe_allow_html=True)
            v = st.number_input("", min_value=0.0,
                                 value=float(upper * 1.10) if upper > 0 else 0.0,
                                 step=10.0, key=f"{mode}_new_tr_up_stop",
                                 label_visibility="collapsed")
            up_stop = v if v > 0 else None
        if down:
            st.markdown(_caption("Trailing Down Stop ($)"), unsafe_allow_html=True)
            v = st.number_input("", min_value=0.0,
                                 value=float(lower * 0.90) if lower > 0 else 0.0,
                                 step=10.0, key=f"{mode}_new_tr_down_stop",
                                 label_visibility="collapsed")
            down_stop = v if v > 0 else None
    return {"enable_trailing_up":   up,
            "enable_trailing_down": down,
            "trailing_up_stop":     up_stop,
            "trailing_down_stop":   down_stop}


# ---------------------------------------------------------------------------
# Hauptfunktion
# ---------------------------------------------------------------------------

def render_bot_setup_form(
    mode:      str,
    on_submit: Callable[[dict], None],
    on_back:   Callable[[], None],
) -> None:
    """
    Rendert die Bot-Aufsetzen-Form fuer einen Modus.

    Layout:
        Sidebar     : "← Zurueck" + alle Konfigurations-Inputs + Submit
        Hauptbereich: Live-Chart-Vorschau (aktualisiert sich bei jeder
                      Sidebar-Parameter-Aenderung)

    Args:
        mode      : "backtest" | "paper" | "live"
        on_submit : Wird bei Klick auf Submit mit dem params-Dict aufgerufen.
        on_back   : "← Zurueck"-Callback.
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
        params.update(_section_capital(mode))

        # Smart-Setup
        _section_smart_setup(mode, params["coin"], params["interval"],
                              params["total_investment"], params.get("period"))

        # Live-aktueller Preis fuer Range-Default
        current_price = _load_current_price(params["coin"], params["interval"])

        params.update(_section_grid_bounds(mode, current_price))
        params.update(_section_grid_count_and_mode(
            mode, params["coin"], params["interval"],
            params["lower_price"], params["upper_price"],
        ))

        # ── Sektion: Risiko & Kapital ────────────────────────────────────────
        # Header kommt aus _section_risk (Label "Risiko & Kapital")
        risk = _section_risk(mode)
        params.update({k: v for k, v in risk.items() if not k.startswith("_")})
        params.update(_section_stop_loss(mode, params["lower_price"]))
        params.update(_section_take_profit(mode, params["upper_price"]))
        params.update(_section_grid_trigger(
            mode, params["lower_price"], params["upper_price"], current_price
        ))
        params.update(_section_dd_throttle(mode))
        params.update(_section_variable_orders(mode))

        # ── Sektion: Dynamische Mechanismen ──────────────────────────────────
        st.markdown(_divider(), unsafe_allow_html=True)
        st.markdown(_label("Dynamische Mechanismen"), unsafe_allow_html=True)
        params.update(_section_atr_adjust(mode))
        # Recentering / Trailing - gegenseitige Verriegelung via session_state
        tr_active = st.session_state.get(f"{mode}_new_trailing", False)
        params.update(_section_recentering(mode, trailing_active=tr_active))
        rc_active = st.session_state.get(f"{mode}_new_recenter", False)
        params.update(_section_trailing(mode, recenter_active=rc_active,
                                         lower=params["lower_price"],
                                         upper=params["upper_price"]))

        # Submit
        st.markdown(_divider(), unsafe_allow_html=True)
        submit_lbl = ("Backtest starten" if mode == "backtest"
                      else "Bot starten")
        if st.button(submit_lbl, key=f"{mode}_submit", type="primary",
                      use_container_width=True):
            submit_triggered = True

    # ── Hauptbereich: Live-Chart-Vorschau ───────────────────────────────────
    _render_chart_main(params)

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
