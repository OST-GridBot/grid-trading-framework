"""
components/tab_optimizer.py
===========================
Render-Komponente fuer den Optimizer-Tab in der Bot-Detail-Ansicht.

Zeigt eine Tabelle aller 288 ROI-Kombinationen mit allen vier Scores
(ROI, Sharpe, Calmar, CAGR). User kann nach jeder Spalte sortieren
(Default: ROI absteigend). Button 'Neu berechnen' triggert die volle
Suche; Ergebnis wird im session_state pro Bot gecached.

Mode-abhaengig:
    BT  : DataFrame = period.start_date .. period.end_date (Sim-Zeitraum)
    PT/LT: DataFrame = view.created_at .. jetzt (rueckwirkend)

Autor: Enes Eryilmaz
Projekt: Grid-Trading-Framework (Bachelorarbeit OST)
"""

from datetime import date, datetime
import pandas as pd
import streamlit as st


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------

_MODE_LABELS = {
    "arithmetic":        "Arithmetisch",
    "geometric":         "Geometrisch",
    "asymmetric_bottom": "Bottom heavy",
    "asymmetric_top":    "Top heavy",
}


def _bot_cache_key(view: dict) -> str:
    """Eindeutiger Cache-Key pro Bot (id + coin + interval)."""
    return (f"opt_result_{view.get('id','')}_{view.get('coin','')}_"
            f"{view.get('interval','')}")


def _load_dataframe_for_view(view: dict):
    """DataFrame fuer Optimizer holen — mode-abhaengig.

    BT  : period.start_date .. end_date (= original Sim-Zeitraum).
    PT/LT: ab view.created_at bis jetzt (rueckwirkend).
    """
    from src.data.cache_manager import get_price_data
    coin     = view.get("coin", "")
    interval = view.get("interval", "1h")
    mode     = view.get("mode", "")

    if mode == "backtest":
        period = view.get("period") or {}
        sd_str = period.get("start_date")
        ed_str = period.get("end_date")
        if not (sd_str and ed_str):
            return None, "Kein period.start_date / period.end_date im View."
        try:
            sd = date.fromisoformat(sd_str)
            ed = date.fromisoformat(ed_str)
        except Exception as e:
            return None, f"Datums-Parse-Fehler: {e}"
        try:
            df, _ = get_price_data(coin, days=int(period.get("days", 30)),
                                    interval=interval,
                                    start_date=sd, end_date=ed)
            return df, None
        except Exception as e:
            return None, f"get_price_data-Fehler: {e}"

    # PT/LT: ab created_at
    created_at = view.get("created_at", "")
    try:
        sd = pd.to_datetime(created_at).date()
    except Exception:
        return None, "view.created_at nicht parsebar."
    ed = date.today()
    days = max(1, (ed - sd).days)
    try:
        df, _ = get_price_data(coin, days=days, interval=interval,
                                start_date=sd, end_date=ed)
        return df, None
    except Exception as e:
        return None, f"get_price_data-Fehler: {e}"


def render_tab_optimizer(view: dict) -> None:
    """Rendert den Optimizer-Tab fuer eine BotView."""
    # Unsaved Live-View (BT-Pipeline vor Speicherung): view["id"] = "".
    # Optimizer braucht eine persistente Bot-ID fuer Caching + Mode-Logik.
    # -> Hinweis statt Tab-Inhalt.
    if not view.get("id"):
        st.info("Speichere den Backtest zuerst, um den Optimizer zu verwenden.")
        return

    cfg              = view.get("config") or {}
    total_investment = float(cfg.get("total_investment", 10_000) or 10_000)
    fee_rate         = float(cfg.get("fee_rate", 0.001) or 0.001)
    interval         = view.get("interval", "1h")
    mode             = view.get("mode", "")
    cache_key        = _bot_cache_key(view)

    # Mode-Beschreibung
    if mode == "backtest":
        period = view.get("period") or {}
        st.caption(
            f"Optimiert auf den Sim-Zeitraum "
            f"{period.get('start_date','–')} bis {period.get('end_date','–')}."
        )
    else:
        st.caption(
            "Optimiert rueckwirkend ab Bot-Start bis heute."
        )

    if st.button("Neu berechnen", key=f"{cache_key}_btn",
                  use_container_width=True, type="primary"):
        df, err = _load_dataframe_for_view(view)
        if err:
            st.error(err)
            return
        if df is None or df.empty:
            st.warning("Keine Preisdaten verfügbar.")
            return
        with st.spinner("Optimierung läuft…"):
            from src.backtesting.optimizer import evaluate_all_combos
            range_basis = "median" if mode == "backtest" else "current_price"
            results = evaluate_all_combos(
                df=df, total_investment=total_investment,
                fee_rate=fee_rate, interval=interval,
                range_basis=range_basis,
            )
        st.session_state[cache_key] = results

    results = st.session_state.get(cache_key)
    if not results:
        st.info("Klick auf 'Neu berechnen' um die Optimierung zu starten.")
        return

    # ── Tabelle ────────────────────────────────────────────────────────────
    rows = []
    for r in results:
        mech_parts = []
        if r.get("enable_trailing_up"):
            mech_parts.append("Trailing")
        if r.get("enable_recentering_up"):
            mech_parts.append("Recentering")
        mech = " + ".join(mech_parts) if mech_parts else "—"
        rows.append({
            "Range":         f"±{r['range_pct']*100:.0f}%",
            "Grids":         r["num_grids"],
            "Modus":         _MODE_LABELS.get(r["grid_mode"], r["grid_mode"]),
            "Mechanismen":   mech,
            "ROI %":         r["roi_pct"],
            "Sharpe":        r["sharpe"],
            "Calmar":        r["calmar"],
            "CAGR %":        r["cagr_pct"],
            "Max DD %":      r["max_dd_pct"],
            "Trades":        r["num_trades"],
        })
    df_out = pd.DataFrame(rows).sort_values("ROI %", ascending=False).reset_index(drop=True)

    st.markdown(
        f"<div style='font-size:0.78rem; color:#94A3B8; "
        f"margin-bottom:6px;'>{len(df_out)} Kombinationen — "
        f"Default sortiert nach ROI absteigend (Spalten klickbar für "
        f"andere Sortierung).</div>",
        unsafe_allow_html=True,
    )
    st.dataframe(
        df_out,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Grids":   st.column_config.NumberColumn(format="%d"),
            "ROI %":   st.column_config.NumberColumn(format="%+.2f"),
            "Sharpe":  st.column_config.NumberColumn(format="%.3f"),
            "Calmar":  st.column_config.NumberColumn(format="%.3f"),
            "CAGR %":  st.column_config.NumberColumn(format="%+.2f"),
            "Max DD %":st.column_config.NumberColumn(format="%.2f"),
            "Trades":  st.column_config.NumberColumn(format="%d"),
        },
    )
