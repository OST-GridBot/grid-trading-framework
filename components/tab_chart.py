"""
components/tab_chart.py
=======================
Render-Komponente fuer den Chart-Tab in der Bot-Detail-Ansicht.

Konsumiert eine BotView und zeichnet:
    - Preis-Candles + Volumen (via plot_grid_chart_v2)
    - Grid-Linien (aus bot.state.grids falls vorhanden, sonst live aus config)
    - Trade-Marker auf den Candles

Verwendet die zentrale Lightweight-Charts-Komponente; kein eigenes
Chart-Rendering.

Autor: Enes Eryilmaz
Projekt: Grid-Trading-Framework (Bachelorarbeit OST)
"""

from typing import Optional

import pandas as pd
import streamlit as st

from components.chart_v2       import plot_grid_chart_v2
from components.chart_settings import render_chart_settings
from src.data.cache_manager    import get_price_data
from src.strategy.grid_builder import calculate_grid_lines
from src.utils.timezone        import convert_df_timestamps, utc_to_zurich


# Days-Map fuer den Chart-Default je Intervall.
# Bei BT wird stattdessen view["period"]["days"] verwendet (falls vorhanden).
_DAYS_BY_INTERVAL = {
    "1m": 1, "5m": 1, "15m": 2, "1h": 7, "4h": 14, "1d": 30,
}

# T.1: Vorlauf-Kontext vor dem Von-Datum bei BT (in Tagen je Intervall).
# Ziel: User sieht historischen Verlauf VOR Sim-Start, damit der Marker
# am Von-Datum einen Kontext hat. Selbe Map-Logik wie _DAYS_BY_INTERVAL,
# um Konsistenz zu wahren.
_BT_CONTEXT_DAYS = {
    "1m": 1, "5m": 1, "15m": 2, "1h": 7, "4h": 14, "1d": 30,
}


def render_tab_chart(
    view:           dict,
    df:             Optional[pd.DataFrame] = None,
    height:         int  = 560,
    settings_key:   str  = "detail",
) -> None:
    """
    Rendert den Chart-Tab fuer eine BotView. Plus Chart-Einstellungen-
    Expander unter dem Chart (Toggles fuer Grid-Linien, Order-Marker,
    Bot-Start, Magnet-Crosshair, Volumen).

    Args:
        view         : BotView-Dict (siehe components/bot_view.py)
        df           : Optional. Wenn None, wird via get_price_data geladen.
        height       : Chart-Hoehe in Pixel
        settings_key : Key-Praefix fuer die Chart-Einstellungen-Widgets,
                       damit setup/detail/pending sich nicht ueberschreiben.
    """
    coin     = view.get("coin", "")
    interval = view.get("interval", "1h")
    cfg      = view.get("config", {})

    # ── DataFrame beschaffen ────────────────────────────────────────────────
    # T.1: Bei BT mit period.start_date+end_date laden wir den HISTORISCHEN
    # Sim-Zeitraum (sd-vorlauf .. ed) statt der letzten X Tage ab heute.
    # Vorlauf je Intervall (siehe _BT_CONTEXT_DAYS) gibt visuellen Kontext
    # VOR dem Bot-Start-Marker. Bei PT/LT bleibt die heutige Logik.
    if df is None:
        period = view.get("period") or {}
        try:
            if (view.get("mode") == "backtest"
                    and period.get("start_date")
                    and period.get("end_date")):
                from datetime import date as _date, timedelta as _td
                sd = _date.fromisoformat(period["start_date"])
                ed = _date.fromisoformat(period["end_date"])
                vorlauf = _BT_CONTEXT_DAYS.get(interval, 7)
                load_start = sd - _td(days=vorlauf)
                df, _ = get_price_data(
                    coin, days=int(period.get("days", 30)),
                    interval=interval,
                    start_date=load_start, end_date=ed,
                )
            else:
                days = _DAYS_BY_INTERVAL.get(interval, 7)
                if period and period.get("days"):
                    try:
                        days = max(days, int(period["days"]))
                    except Exception:
                        pass
                df, _ = get_price_data(coin, days=days, interval=interval)
        except Exception as e:
            st.warning(f"Chart-Fehler: {e}")
            return

    if df is None or df.empty:
        st.info("Keine Chart-Daten verfügbar.")
        return

    df_display = convert_df_timestamps(df)

    # ── Grid-Linien bestimmen ───────────────────────────────────────────────
    # Bevorzugt die echten Bot-Grid-Positionen aus dem State (PT/LT mit
    # laufendem Bot); sonst live aus der Config berechnen (BT, oder PT/LT
    # ohne State).
    state       = view.get("state") or {}
    state_grids = state.get("grids") or {}
    grid_lines  = []
    if state_grids:
        try:
            grid_lines = sorted([float(k) for k in state_grids.keys()])
        except Exception:
            grid_lines = []
    if not grid_lines:
        try:
            grid_lines = calculate_grid_lines(
                float(cfg.get("lower_price", 0)),
                float(cfg.get("upper_price", 0)),
                int(cfg.get("num_grids", 10)),
                cfg.get("grid_mode", "arithmetic"),
            )
        except Exception:
            grid_lines = []

    # ── Trade-Log: Timestamps nach Zurich konvertieren ─────────────────────
    trade_log_display = []
    for t in view.get("trade_log", []):
        t2 = dict(t)
        try:
            t2["timestamp"] = utc_to_zurich(t2["timestamp"])
        except Exception:
            pass
        trade_log_display.append(t2)

    # ── Chart-Einstellungen ─────────────────────────────────────────────────
    settings = render_chart_settings(key_prefix=settings_key)

    # ── Bot-Start-Timestamp ableiten ────────────────────────────────────────
    # BT: aus period["start_date"] (00:00 UTC), PT/LT: aus created_at.
    # plot_grid_chart_v2 filtert intern, falls Timestamp ausserhalb des
    # sichtbaren Kerzen-Bereichs liegt.
    bot_start_ts = None
    if settings["show_bot_start"]:
        try:
            period = view.get("period") or {}
            sd = period.get("start_date")
            if sd:
                ts = pd.to_datetime(sd)
            else:
                ts = pd.to_datetime(view.get("created_at", ""))
            if ts is not None and not pd.isna(ts):
                # Zurich-lokal -> Unix-UTC fuer Lightweight Charts.
                # Verhindert den +2h-Versatz (Auftrag X.1).
                from src.utils.timezone import zurich_to_unix
                bot_start_ts = zurich_to_unix(ts)
        except Exception:
            bot_start_ts = None

    # ── Render ──────────────────────────────────────────────────────────────
    upper = float(grid_lines[-1]) if grid_lines else float(cfg.get("upper_price", 0))
    lower = float(grid_lines[0])  if grid_lines else float(cfg.get("lower_price", 0))

    # ── D: Vorschau-Linien oberhalb Upper bei Trailing/Recentering ──────────
    # Trailing-Pfad gewinnt wenn beide aktiv waeren (defensive).
    grid_lines_outside = []
    try:
        from src.strategy.grid_builder import extrapolate_grid_above
        gm = cfg.get("grid_mode", "arithmetic")
        max_price_outside = None
        if cfg.get("enable_trailing_up") and cfg.get("trailing_up_stop"):
            max_price_outside = float(cfg["trailing_up_stop"])
        elif cfg.get("enable_recentering_up") and upper > 0:
            max_price_outside = upper * 1.20
        if max_price_outside and grid_lines:
            grid_lines_outside = extrapolate_grid_above(
                grid_lines, gm, max_price_outside
            )
    except Exception:
        grid_lines_outside = []

    # ── TP/SL-Preise bestimmen ──────────────────────────────────────────────
    # PT/LT: aus persistiertem State (bot.stop_loss_price / take_profit_price).
    # BT  : aus Config neu berechnen (identische Formel wie GridBot.__init__).
    sl_price = state.get("stop_loss_price")
    tp_price = state.get("take_profit_price")
    if sl_price is None:
        try:
            sl_pct = cfg.get("stop_loss_pct")
            if sl_pct is not None and lower > 0:
                sl_price = float(lower) * (1 - float(sl_pct))
        except Exception:
            sl_price = None
    if tp_price is None:
        try:
            tp_pct = cfg.get("take_profit_pct")
            if tp_pct is not None and upper > 0:
                tp_price = float(upper) * (1 + float(tp_pct))
        except Exception:
            tp_price = None

    # ── Trailing-Up-Stop bestimmen (Binance-Standard: nur Up-Variante) ──────
    # PT/LT aus State (BotRunner persistiert die Werte), BT aus Config.
    tr_up_stop = state.get("trailing_up_stop")
    if tr_up_stop is None:
        tr_up_stop = cfg.get("trailing_up_stop")

    # Trailing-Events: Timestamps nach Zurich konvertieren (analog Trade-Log)
    trailing_events_display = []
    for ev in (view.get("trailing_events") or []):
        ev2 = dict(ev)
        try:
            ev2["timestamp"] = utc_to_zurich(ev2["timestamp"])
        except Exception:
            pass
        trailing_events_display.append(ev2)

    # Recentering-Events analog
    recentering_events_display = []
    for ev in (view.get("recentering_events") or []):
        ev2 = dict(ev)
        try:
            ev2["timestamp"] = utc_to_zurich(ev2["timestamp"])
        except Exception:
            pass
        recentering_events_display.append(ev2)

    # ── M.1: Y-Anker fuer Chart-Zentrierung ─────────────────────────────────
    # BT  -> erster Close (Preis am Von-Datum), aus df_display.
    # PT/LT -> letzter Close (aktueller Preis).
    chart_anchor = None
    if df_display is not None and not df_display.empty:
        try:
            if view.get("mode") == "backtest":
                chart_anchor = float(df_display["close"].iloc[0])
            else:
                chart_anchor = float(df_display["close"].iloc[-1])
        except Exception:
            chart_anchor = None

    # ── M.2 / U.1: TP/SL-Trigger-Marker als LISTEN aus trade_log ──────────
    # Seit N.1 koennen SL/TP mehrfach pro Bot-Lauf triggern. Quelle: alle
    # trade_log-Eintraege mit force_sell=True (force_sell_trigger gibt die
    # Art an). Funktioniert auch fuer alte Snapshots, da Force-Sells
    # bereits seit langem im trade_log persistiert sind.
    sl_triggers_list = []
    tp_triggers_list = []
    for t in (trade_log_display or []):
        if not t.get("force_sell"):
            continue
        ts_raw = t.get("timestamp")
        # cprice = Marktpreis bei Trigger (close der Trigger-Kerze);
        # Fallback price falls cprice fehlt.
        pr_raw = t.get("cprice") if t.get("cprice") is not None else t.get("price")
        trig_kind = t.get("force_sell_trigger")
        if not ts_raw or pr_raw is None:
            continue
        try:
            entry = {"time": utc_to_zurich(ts_raw), "price": float(pr_raw)}
        except Exception:
            continue
        if trig_kind == "stop_loss":
            sl_triggers_list.append(entry)
        elif trig_kind == "take_profit":
            tp_triggers_list.append(entry)

    plot_grid_chart_v2(
        df                  = df_display,
        grid_lines          = grid_lines,
        trade_log           = trade_log_display,
        coin                = coin,
        interval            = interval,
        show_volume         = settings["show_volume"],
        upper_price         = upper,
        lower_price         = lower,
        height              = height,
        show_grid_lines     = settings["show_grid_lines"],
        show_grid_labels    = settings["show_grid_labels"],
        show_order_markers  = settings["show_order_markers"],
        bot_start_timestamp = bot_start_ts,
        magnet_crosshair    = settings["magnet_crosshair"],
        trailing_events     = trailing_events_display,
        show_trailing_steps = settings["show_trailing_steps"],
        stop_loss_price     = sl_price,
        take_profit_price   = tp_price,
        show_stop_loss      = settings["show_stop_loss"],
        show_take_profit    = settings["show_take_profit"],
        trailing_up_stop    = tr_up_stop,
        show_trailing_stops = settings["show_trailing_stops"],
        recentering_events     = recentering_events_display,
        show_recentering_steps = settings["show_recentering_steps"],
        show_range_fill        = settings["show_range_fill"],
        show_trailing_fill     = settings["show_trailing_fill"],
        show_recentering_fill  = settings["show_recentering_fill"],
        chart_anchor_price        = chart_anchor,
        sl_triggers               = sl_triggers_list,
        tp_triggers               = tp_triggers_list,
        show_sltp_trigger_markers = settings.get("show_sltp_trigger_markers", True),
        grid_lines_outside        = grid_lines_outside,
        show_grid_outside_range   = settings.get("show_grid_outside_range", True),
    )
