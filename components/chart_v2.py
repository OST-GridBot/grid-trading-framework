"""
components/chart_v2.py
TradingView Lightweight Charts™ v4 Integration
Autor: Enes Eryilmaz – Grid-Trading-Framework (Bachelorarbeit OST)
"""

import json
import pandas as pd
import streamlit.components.v1 as components
from typing import Optional


def plot_grid_chart_v2(
    df:                  pd.DataFrame,
    grid_lines:          list,
    trade_log:           list,
    coin:                str   = "BTC",
    interval:            str   = "1h",
    show_volume:         bool  = True,
    upper_price:         Optional[float] = None,
    lower_price:         Optional[float] = None,
    height:              int   = 560,
    show_grid_lines:     bool  = True,
    show_grid_labels:    bool  = False,
    show_order_markers:  bool  = True,
    bot_start_timestamp: Optional[int]   = None,
    magnet_crosshair:    bool  = False,
    trailing_events:     Optional[list]  = None,
    show_trailing_steps: bool  = True,
    stop_loss_price:     Optional[float] = None,
    take_profit_price:   Optional[float] = None,
    show_stop_loss:      bool  = True,
    show_take_profit:    bool  = True,
    trailing_up_stop:    Optional[float] = None,
    show_trailing_stops: bool  = True,
    recentering_events:     Optional[list] = None,
    show_recentering_steps: bool  = True,
    show_range_fill:        bool  = True,
    show_trailing_fill:     bool  = True,
    show_recentering_fill:  bool  = True,
    # M.1 — Anker fuer Y-Achsen-Zentrierung (None = Auto-Scale)
    chart_anchor_price:        Optional[float] = None,
    # M.2 / U.1 — TP/SL-Trigger-Marker als LISTEN (mehrere Trigger pro Bot-
    # Lauf moeglich seit N.1 Re-Trigger). Jeder Eintrag: {time, price}.
    # Backward-Compat: None / leere Liste -> keine Marker.
    sl_triggers:               Optional[list]  = None,
    tp_triggers:               Optional[list]  = None,
    show_sltp_trigger_markers: bool            = True,
    # D — graue Vorschau-Linien oberhalb der current Upper-Range
    grid_lines_outside:        Optional[list]  = None,
    show_grid_outside_range:   bool            = True,
) -> None:

    def _to_unix(ts_val):
        """
        Wandelt einen Zurich-lokalen Timestamp in Unix-UTC-Sekunden um.
        Die Eingangswerte kommen aus convert_df_timestamps/utc_to_zurich
        und sind damit naive Zurich-Werte. Lightweight Charts erwartet
        Unix-UTC; Browser lokalisiert danach automatisch.
        """
        try:
            from src.utils.timezone import zurich_to_unix
            return zurich_to_unix(ts_val)
        except Exception:
            return None

    try:
        date_from = pd.to_datetime(df["timestamp"].iloc[0]).strftime("%d.%m.%Y")
        date_to   = pd.to_datetime(df["timestamp"].iloc[-1]).strftime("%d.%m.%Y")
        date_range_str = f"{date_from} – {date_to}"
    except Exception:
        date_range_str = ""

    candles = []
    for _, row in df.iterrows():
        t = _to_unix(row["timestamp"])
        if t is None:
            continue
        candles.append({
            "time":  t,
            "open":  round(float(row["open"]),  4),
            "high":  round(float(row["high"]),  4),
            "low":   round(float(row["low"]),   4),
            "close": round(float(row["close"]), 4),
        })
    candles.sort(key=lambda x: x["time"])

    volume_data = []
    if show_volume and "volume" in df.columns:
        for _, row in df.iterrows():
            t = _to_unix(row["timestamp"])
            if t is None:
                continue
            is_up = float(row["close"]) >= float(row["open"])
            volume_data.append({
                "time":  t,
                "value": round(float(row["volume"]), 2),
                "color": "rgba(52,211,153,0.4)" if is_up else "rgba(248,113,113,0.4)",
            })
        volume_data.sort(key=lambda x: x["time"])

    markers = []
    if show_order_markers:
        for t in trade_log:
            try:
                ts = _to_unix(t["timestamp"])
                if ts is None:
                    continue
                is_buy = "BUY" in str(t.get("type", "")).upper()
                # UI-Polish 2: cprice (exec_price) statt price (Grid-Linie)
                # als Y-Position. Semantisch korrekt fuer alle Modi: Marker
                # zeigt WO der Trade stattfand, nicht wo die Anchor-Grid-
                # Linie liegt. Im LT war price bei Initial-Buys = Sell-Linie
                # weit ueber Markt → fiel oft aus dem sichtbaren Y-Range →
                # priceToCoordinate returnte null → Marker nicht gerendert.
                # cprice = exec_price liegt am echten Markt → sichtbar.
                # Backward-Compat fuer alte Snapshots ohne cprice → Fallback
                # auf price.
                markers.append({
                    "time":     ts,
                    "is_buy":   is_buy,
                    "price":    float(t.get("cprice") or t.get("price", 0)),
                    "profit":   t.get("profit", None),
                    "amount":   float(t.get("amount", 0)),
                    "fee":      float(t.get("fee", 0)),
                })
            except Exception:
                continue
    markers.sort(key=lambda x: x["time"])

    # Bot-Start-Marker (separat von order-markers, andere Render-Logik via JS)
    df_start_ts = candles[0]["time"]  if candles else None
    df_end_ts   = candles[-1]["time"] if candles else None
    bot_start_visible = (
        bot_start_timestamp is not None
        and df_start_ts is not None
        and df_end_ts is not None
        and df_start_ts <= int(bot_start_timestamp) <= df_end_ts
    )
    bot_start_ts = int(bot_start_timestamp) if bot_start_visible else None

    price_lines = [round(float(gl), 4) for gl in grid_lines] if show_grid_lines else []
    # D: graue Vorschau-Linien oberhalb der aktiven Range
    outside_lines = ([round(float(gl), 4) for gl in (grid_lines_outside or [])]
                      if (show_grid_outside_range and show_grid_lines) else [])
    has_volume  = show_volume and bool(volume_data)

    # Trailing-Stufen aufbereiten: zwei Linien-Daten-Listen (lower + upper).
    # Datenpunkte ueber 6 sig. Stellen sortiert; Lightweight-Charts erwartet
    # streng aufsteigende time-Werte ohne Duplikate.
    trail_lower_data = []
    trail_upper_data = []
    if show_trailing_steps and trailing_events:
        for ev in trailing_events:
            ts = _to_unix(ev.get("timestamp"))
            if ts is None:
                continue
            try:
                nl = float(ev.get("new_lower"))
                nu = float(ev.get("new_upper"))
            except Exception:
                continue
            trail_lower_data.append({"time": ts, "value": round(nl, 4)})
            trail_upper_data.append({"time": ts, "value": round(nu, 4)})
        trail_lower_data.sort(key=lambda x: x["time"])
        trail_upper_data.sort(key=lambda x: x["time"])
        # Duplikate (gleiche time) entfernen - behalte letzten Wert
        def _dedup(items):
            seen = {}
            for it in items:
                seen[it["time"]] = it["value"]
            return [{"time": t, "value": v} for t, v in sorted(seen.items())]
        trail_lower_data = _dedup(trail_lower_data)
        trail_upper_data = _dedup(trail_upper_data)
        # Fill-Start = ERSTER Trailing-Event (zeigt: hier wurde Trailing aktiv).
        # Die eingefaerbte Range ist konstant der juengste Stand — eine
        # bewusste Vereinfachung; der historische Verlauf ist ueber die
        # Step-Linien selbst sichtbar.
        trailing_fill_start_ts = (trail_upper_data[0]["time"]
                                   if trail_upper_data else None)
        # Step-Linie bis Chart-Ende verlaengern, damit auch ein einzelner
        # Event sichtbar ist (WithSteps zeichnet sonst nur einen Punkt).
        if df_end_ts is not None:
            if trail_lower_data and trail_lower_data[-1]["time"] < df_end_ts:
                trail_lower_data.append(
                    {"time": df_end_ts, "value": trail_lower_data[-1]["value"]}
                )
            if trail_upper_data and trail_upper_data[-1]["time"] < df_end_ts:
                trail_upper_data.append(
                    {"time": df_end_ts, "value": trail_upper_data[-1]["value"]}
                )
    else:
        trailing_fill_start_ts = None

    # Recentering-Events analog Trailing aufbereiten.
    recenter_lower_data = []
    recenter_upper_data = []
    if show_recentering_steps and recentering_events:
        for ev in recentering_events:
            ts = _to_unix(ev.get("timestamp"))
            if ts is None:
                continue
            try:
                nl = float(ev.get("new_lower"))
                nu = float(ev.get("new_upper"))
            except Exception:
                continue
            recenter_lower_data.append({"time": ts, "value": round(nl, 4)})
            recenter_upper_data.append({"time": ts, "value": round(nu, 4)})
        recenter_lower_data.sort(key=lambda x: x["time"])
        recenter_upper_data.sort(key=lambda x: x["time"])
        def _dedup_rc(items):
            seen = {}
            for it in items:
                seen[it["time"]] = it["value"]
            return [{"time": t, "value": v} for t, v in sorted(seen.items())]
        recenter_lower_data = _dedup_rc(recenter_lower_data)
        recenter_upper_data = _dedup_rc(recenter_upper_data)
        # Fill-Start = ERSTER Recentering-Event (analog Trailing).
        recenter_fill_start_ts = (recenter_upper_data[0]["time"]
                                   if recenter_upper_data else None)
        # Step-Linie bis Chart-Ende verlaengern (analog Trailing).
        if df_end_ts is not None:
            if recenter_lower_data and recenter_lower_data[-1]["time"] < df_end_ts:
                recenter_lower_data.append(
                    {"time": df_end_ts, "value": recenter_lower_data[-1]["value"]}
                )
            if recenter_upper_data and recenter_upper_data[-1]["time"] < df_end_ts:
                recenter_upper_data.append(
                    {"time": df_end_ts, "value": recenter_upper_data[-1]["value"]}
                )
    else:
        recenter_fill_start_ts = None

    candles_json        = json.dumps(candles)
    volume_json         = json.dumps(volume_data)
    markers_json        = json.dumps(markers)
    price_lines_json    = json.dumps(price_lines)
    outside_lines_json  = json.dumps(outside_lines)
    upper_json          = json.dumps(round(float(upper_price), 4) if upper_price else None)
    lower_json          = json.dumps(round(float(lower_price), 4) if lower_price else None)
    coin_js             = json.dumps(coin)
    interval_js         = json.dumps(interval)
    date_range_js       = json.dumps(date_range_str)
    has_vol_js          = "true" if has_volume else "false"
    show_grid_labels_js = "true" if show_grid_labels else "false"
    magnet_js           = "true" if magnet_crosshair else "false"
    bot_start_ts_json   = json.dumps(bot_start_ts)
    trail_lower_json    = json.dumps(trail_lower_data)
    trail_upper_json    = json.dumps(trail_upper_data)

    # TP/SL-Preise nur senden, wenn Toggle aktiv UND Preis gesetzt.
    sl_val = (
        round(float(stop_loss_price), 4)
        if (show_stop_loss and stop_loss_price is not None and stop_loss_price > 0)
        else None
    )
    tp_val = (
        round(float(take_profit_price), 4)
        if (show_take_profit and take_profit_price is not None and take_profit_price > 0)
        else None
    )
    stop_loss_json   = json.dumps(sl_val)
    take_profit_json = json.dumps(tp_val)

    # Trailing-Stops nur senden, wenn Toggle aktiv UND Wert gesetzt.
    tr_up_val = (
        round(float(trailing_up_stop), 4)
        if (show_trailing_stops and trailing_up_stop is not None and trailing_up_stop > 0)
        else None
    )
    trailing_up_stop_json   = json.dumps(tr_up_val)

    recenter_lower_json = json.dumps(recenter_lower_data)
    recenter_upper_json = json.dumps(recenter_upper_data)
    # Erste und letzte Kerze fuer die statische Range-Fill-BaselineSeries.
    first_ts_json = json.dumps(df_start_ts)
    last_ts_json  = json.dumps(df_end_ts)
    show_range_fill_js       = "true" if show_range_fill else "false"
    show_trailing_fill_js    = "true" if show_trailing_fill else "false"
    show_recentering_fill_js = "true" if show_recentering_fill else "false"
    # trailing_fill_start_ts / recenter_fill_start_ts werden nicht mehr
    # benoetigt (Fill folgt dynamisch den Step-Linien). Lokale Variablen
    # bleiben fuer Debugging, fliessen aber nicht ins JS.
    _ = trailing_fill_start_ts, recenter_fill_start_ts

    # M.1 — Y-Anker fuer autoscaleInfoProvider
    chart_anchor_json = json.dumps(
        round(float(chart_anchor_price), 4) if chart_anchor_price else None
    )

    # M.2 / U.1 — TP/SL-Trigger-Marker als Listen.
    # Jeder Eintrag: {time: unix_ts, price: float}. Defensive: ungueltige
    # Eintraege (None timestamp / price) werden uebersprungen.
    def _serialize_triggers(triggers):
        if not triggers or not show_sltp_trigger_markers:
            return []
        out = []
        for trig in triggers:
            if not isinstance(trig, dict):
                continue
            ts = _to_unix(trig.get("time"))
            pr = trig.get("price")
            if ts is None or pr is None:
                continue
            try:
                out.append({"time": ts, "price": round(float(pr), 4)})
            except (TypeError, ValueError):
                continue
        return out
    sl_triggers_json = json.dumps(_serialize_triggers(sl_triggers))
    tp_triggers_json = json.dumps(_serialize_triggers(tp_triggers))

    HEADER_H = 44
    chart_h  = height - HEADER_H

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ background:#0F1117; overflow:hidden; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif; }}
  #wrapper {{ display:flex; flex-direction:column; width:100%; height:{height}px; }}

  /* Header */
  #header {{
    height:{HEADER_H}px; background:#0F1117;
    border-bottom:1px solid rgba(255,255,255,0.07);
    display:flex; align-items:center; padding:0 12px; gap:16px; flex-shrink:0;
  }}
  #hdr-info {{ display:flex; align-items:center; gap:10px; min-width:0; flex-shrink:0; }}
  #hdr-coin {{ font-size:15px; font-weight:600; color:#E2E8F0; letter-spacing:0.01em; }}
  #hdr-interval {{
    font-size:11px; color:#60A5FA;
    background:rgba(59,130,246,0.12); border:1px solid rgba(59,130,246,0.25);
    border-radius:4px; padding:2px 7px; letter-spacing:0.03em;
  }}
  #hdr-date  {{ font-size:11px; color:#94A3B8; letter-spacing:0.01em;
                 font-variant-numeric:tabular-nums; }}

  /* OHLC + Volumen der Hover-Kerze (mittig) */
  #hdr-ohlc {{
    display:flex; align-items:center; gap:12px;
    flex:1; justify-content:center; min-width:0;
    font-size:11px; letter-spacing:0.02em;
  }}
  .ohlc-pair {{ display:flex; align-items:center; gap:4px; }}
  .ohlc-lbl  {{ color:#475569; font-weight:600; }}
  .ohlc-val  {{ color:#CBD5E1; font-variant-numeric:tabular-nums; }}
  .ohlc-up   {{ color:#34D399; }}
  .ohlc-down {{ color:#F87171; }}

  /* Toolbar */
  #toolbar {{ display:flex; gap:4px; align-items:center; flex-shrink:0; }}
  .tb-btn {{
    background:rgba(255,255,255,0.04); border:1px solid rgba(255,255,255,0.09);
    color:#64748B; border-radius:5px; padding:4px 10px; font-size:12px;
    cursor:pointer; transition:all 0.15s; user-select:none; line-height:1;
  }}
  .tb-btn:hover {{ background:rgba(255,255,255,0.08); color:#CBD5E1; }}
  .tb-btn.active {{
    background:rgba(59,130,246,0.15); border-color:rgba(59,130,246,0.4); color:#60A5FA;
  }}
  .tb-sep {{ width:1px; height:16px; background:rgba(255,255,255,0.08); margin:0 2px; }}

  /* Chart wrap */
  #chart-wrap {{ position:relative; flex:1; overflow:hidden; }}
  #chart {{ width:100%; height:100%; }}

  /* Custom marker overlay — sits on top of chart */
  #marker-overlay {{
    position:absolute; top:0; left:0;
    width:100%; height:100%;
    pointer-events:none; overflow:hidden; z-index:10;
  }}

  /* Tooltip */
  #tooltip {{
    position:fixed; z-index:9999;
    background:rgba(8,10,18,0.94); border:1px solid rgba(255,255,255,0.11);
    border-radius:7px; padding:7px 11px; font-size:12px; color:#94A3B8;
    pointer-events:none; display:none; white-space:nowrap;
    box-shadow:0 4px 14px rgba(0,0,0,0.5);
  }}
  .tt-close {{ font-size:13px; font-weight:600; }}
  .tt-up    {{ color:#34D399; }}
  .tt-down  {{ color:#F87171; }}
  .tt-row   {{ display:flex; justify-content:space-between; gap:22px; margin:2px 0; }}
  .tt-lbl   {{ color:#4B5563; }}
  .tt-div   {{ border-top:1px solid rgba(255,255,255,0.07); margin:5px 0 4px; }}
  .tt-profit {{ color:#34D399; font-weight:500; }}
  .tt-loss   {{ color:#F87171; font-weight:500; }}
</style>
</head>
<body>
<div id="wrapper">
  <div id="header">
    <div id="hdr-info">
      <span id="hdr-coin"></span>
      <span id="hdr-interval"></span>
    </div>
    <div class="tb-sep"></div>
    <span id="hdr-date">—</span>
    <div class="tb-sep"></div>
    <div id="hdr-ohlc">
      <span class="ohlc-pair"><span class="ohlc-lbl">O</span><span class="ohlc-val" id="hdr-o">—</span></span>
      <span class="ohlc-pair"><span class="ohlc-lbl">H</span><span class="ohlc-val" id="hdr-h">—</span></span>
      <span class="ohlc-pair"><span class="ohlc-lbl">L</span><span class="ohlc-val" id="hdr-l">—</span></span>
      <span class="ohlc-pair"><span class="ohlc-lbl">C</span><span class="ohlc-val" id="hdr-c">—</span></span>
      <span class="ohlc-pair"><span class="ohlc-lbl">V</span><span class="ohlc-val" id="hdr-v">—</span></span>
    </div>
    <div class="tb-sep"></div>
    <div id="toolbar">
      <button class="tb-btn" onclick="fitAll()">Fit</button>
      <button class="tb-btn" onclick="zoomIn()">+</button>
      <button class="tb-btn" onclick="zoomOut()">−</button>

    </div>
  </div>
  <div id="chart-wrap">
    <div id="chart"></div>
    <div id="marker-overlay"></div>
  </div>
</div>

<div id="tooltip">
  <div id="tt-normal"><span class="tt-close" id="tt-close">—</span></div>
  <div id="tt-marker" style="display:none">
    <div class="tt-row"><span class="tt-lbl">O</span><span id="tt-o">—</span></div>
    <div class="tt-row"><span class="tt-lbl">H</span><span id="tt-h" class="tt-up">—</span></div>
    <div class="tt-row"><span class="tt-lbl">L</span><span id="tt-l" class="tt-down">—</span></div>
    <div class="tt-row"><span class="tt-lbl">C</span><span id="tt-c">—</span></div>
    <div class="tt-div"></div>
    <div class="tt-row"><span class="tt-lbl">Price</span> <span id="tt-oprice">—</span></div>
    <div class="tt-row"><span class="tt-lbl">Amount</span><span id="tt-amount">—</span></div>
    <div class="tt-row"><span class="tt-lbl">Fee</span>   <span id="tt-fee">—</span></div>
    <div class="tt-row" id="tt-prow" style="display:none">
      <span class="tt-lbl">Profit</span><span id="tt-profit">—</span>
    </div>
  </div>
</div>

<script src="https://unpkg.com/lightweight-charts@4.2.0/dist/lightweight-charts.standalone.production.js"></script>
<script>
  const candles        = {candles_json};
  const volData        = {volume_json};
  const allMarkers     = {markers_json};
  const priceLines     = {price_lines_json};
  const outsideLines   = {outside_lines_json};
  const upperPrice     = {upper_json};
  const lowerPrice     = {lower_json};
  const coinName       = {coin_js};
  const interval       = {interval_js};
  const dateRange      = {date_range_js};
  const hasVol         = {has_vol_js};
  const showGridLabels = {show_grid_labels_js};
  const magnetCrosshair = {magnet_js};
  const botStartTs     = {bot_start_ts_json};
  const trailLowerData = {trail_lower_json};
  const trailUpperData = {trail_upper_json};
  const stopLossPrice  = {stop_loss_json};
  const takeProfitPrice = {take_profit_json};
  const trailingUpStop   = {trailing_up_stop_json};
  const recenterLowerData = {recenter_lower_json};
  const recenterUpperData = {recenter_upper_json};
  const firstTs           = {first_ts_json};
  const lastTs            = {last_ts_json};
  const showRangeFill        = {show_range_fill_js};
  const showTrailingFill     = {show_trailing_fill_js};
  const showRecenteringFill  = {show_recentering_fill_js};
  const chartAnchorPrice     = {chart_anchor_json};
  const slTriggers           = {sl_triggers_json};
  const tpTriggers           = {tp_triggers_json};

  // Marker colours — slightly darker than original
  const BUY_COLOR  = '#158A50';  // darker green
  const SELL_COLOR = '#B83C3C';  // darker red

  document.getElementById('hdr-coin').textContent     = coinName + '/USDT';
  document.getElementById('hdr-interval').textContent = interval;

  // Marker lookup by timestamp
  const markerMap = {{}};
  allMarkers.forEach(m => {{
    if (!markerMap[m.time]) markerMap[m.time] = [];
    markerMap[m.time].push(m);
  }});

  // Volume lookup
  const volMap = {{}};
  volData.forEach(v => {{ volMap[v.time] = v.value; }});

  let volVisible = true;
  let volSeries  = null;
  const marginsOn  = {{ top:0.05, bottom:0.28 }};
  const marginsOff = {{ top:0.05, bottom:0.05 }};

  // ── Chart ─────────────────────────────────────────────────
  const chartEl = document.getElementById('chart');
  const chartH  = chartEl.parentElement.offsetHeight || {chart_h};

  const chart = LightweightCharts.createChart(chartEl, {{
    width:  window.innerWidth,
    height: chartH,
    layout: {{
      background: {{ type:LightweightCharts.ColorType.Solid, color:'#0F1117' }},
      textColor: '#94A3B8',
    }},
    grid: {{
      vertLines: {{ color:'rgba(255,255,255,0.04)' }},
      horzLines: {{ color:'rgba(255,255,255,0.04)' }},
    }},
    crosshair: {{ mode: magnetCrosshair ? LightweightCharts.CrosshairMode.Magnet
                                          : LightweightCharts.CrosshairMode.Normal }},
    rightPriceScale: {{
      borderColor: 'rgba(255,255,255,0.08)',
      scaleMargins: hasVol ? marginsOn : marginsOff,
    }},
    timeScale: {{
      borderColor:'rgba(255,255,255,0.08)', timeVisible:true, secondsVisible:false,
    }},
    localization: {{
      locale: 'de-CH',
      timeFormatter: (ts) => {{
        const d = new Date(ts * 1000);
        const day = String(d.getDate()).padStart(2, '0');
        const months = ['Jan','Feb','Mär','Apr','Mai','Jun','Jul','Aug','Sep','Okt','Nov','Dez'];
        const month = months[d.getMonth()];
        const year = d.getFullYear();
        const hh = String(d.getHours()).padStart(2, '0');
        const mm = String(d.getMinutes()).padStart(2, '0');
        return day + '. ' + month + ' ' + year + ' ' + hh + ':' + mm;
      }},
    }},
    handleScroll: {{ mouseWheel:true, pressedMouseMove:true, horzTouchDrag:true }},
    handleScale:  {{ mouseWheel:true, pinch:true, axisPressedMouseMove:true }},
  }});

  const candleSeries = chart.addCandlestickSeries({{
    upColor:'#34D399', downColor:'#F87171',
    borderUpColor:'#34D399', borderDownColor:'#F87171',
    wickUpColor:'#34D399', wickDownColor:'#F87171',
  }});
  candleSeries.setData(candles);

  // ── M.1 — Y-Achsen-Zentrierung um Anker-Preis ─────────────
  // Wenn chartAnchorPrice gesetzt ist, ueberschreibt der Auto-Scale-Info-
  // Provider den Default-Bereich so, dass der Anker (PT/LT: aktueller
  // Preis; BT: Preis am Von-Datum) vertikal in der Y-Achsen-Mitte liegt.
  // halfRange wird aus der maximalen Kerzen-Abweichung vom Anker
  // berechnet, sodass alle Daten sichtbar bleiben (+5% Padding).
  if (chartAnchorPrice !== null && candles.length > 0) {{
    let maxAbs = 0;
    candles.forEach(c => {{
      maxAbs = Math.max(maxAbs,
                         Math.abs(c.high - chartAnchorPrice),
                         Math.abs(c.low  - chartAnchorPrice));
    }});
    const halfRange = (maxAbs > 0 ? maxAbs : chartAnchorPrice * 0.05) * 1.05;
    candleSeries.applyOptions({{
      autoscaleInfoProvider: () => ({{
        priceRange: {{
          minValue: chartAnchorPrice - halfRange,
          maxValue: chartAnchorPrice + halfRange,
        }},
      }}),
    }});
  }}

  // Bot-Start + TP/SL-Trigger-Marker auf der candleSeries.
  // setMarkers() ersetzt die komplette Marker-Liste, deshalb wird hier
  // ein gemeinsames Array gebaut und einmal gesetzt.
  const seriesMarkers = [];
  if (botStartTs !== null) {{
    seriesMarkers.push({{
      time:     botStartTs,
      position: 'belowBar',
      color:    '#60A5FA',
      shape:    'arrowUp',
      text:     'Bot Start',
    }});
  }}
  // U.1: alle SL/TP-Trigger-Events visualisieren (mehrere pro Bot-Lauf
  // moeglich seit N.1 Re-Trigger).
  if (Array.isArray(slTriggers)) {{
    slTriggers.forEach(function(trig) {{
      seriesMarkers.push({{
        time:     trig.time,
        position: 'aboveBar',
        color:    '#EF4444',
        shape:    'circle',
        text:     'SL',
      }});
    }});
  }}
  if (Array.isArray(tpTriggers)) {{
    tpTriggers.forEach(function(trig) {{
      seriesMarkers.push({{
        time:     trig.time,
        position: 'aboveBar',
        color:    '#10B981',
        shape:    'circle',
        text:     'TP',
      }});
    }});
  }}
  // setMarkers erwartet aufsteigende Zeitstempel
  seriesMarkers.sort((a, b) => a.time - b.time);
  if (seriesMarkers.length > 0) {{
    candleSeries.setMarkers(seriesMarkers);
  }}

  priceLines.forEach((p, idx) => candleSeries.createPriceLine({{
    price:p, color:'rgba(100,160,255,0.35)', lineWidth:1,
    lineStyle:LightweightCharts.LineStyle.Dotted,
    axisLabelVisible: showGridLabels,
    title: showGridLabels ? ('L' + (idx + 1)) : '',
  }}));
  // D: graue Vorschau-Linien oberhalb der current Upper-Range
  outsideLines.forEach((p) => candleSeries.createPriceLine({{
    price:p, color:'rgba(100,116,139,0.35)', lineWidth:1,
    lineStyle:LightweightCharts.LineStyle.Dashed,
    axisLabelVisible: showGridLabels,
    title: '',
  }}));
  if (upperPrice) candleSeries.createPriceLine({{
    price:upperPrice, color:'rgba(59,130,246,0.9)', lineWidth:2,
    lineStyle:LightweightCharts.LineStyle.Solid, axisLabelVisible:true, title:'Upper',
  }});
  if (lowerPrice) candleSeries.createPriceLine({{
    price:lowerPrice, color:'rgba(59,130,246,0.9)', lineWidth:2,
    lineStyle:LightweightCharts.LineStyle.Solid, axisLabelVisible:true, title:'Lower',
  }});
  // ── Stop-Loss-Linie (rot, gestrichelt) ────────────────────
  if (stopLossPrice !== null) candleSeries.createPriceLine({{
    price:stopLossPrice, color:'#EF4444', lineWidth:2,
    lineStyle:LightweightCharts.LineStyle.Dashed, axisLabelVisible:true, title:'SL',
  }});
  // ── Take-Profit-Linie (gruen, gestrichelt) ────────────────
  if (takeProfitPrice !== null) candleSeries.createPriceLine({{
    price:takeProfitPrice, color:'#10B981', lineWidth:2,
    lineStyle:LightweightCharts.LineStyle.Dashed, axisLabelVisible:true, title:'TP',
  }});
  // ── Trailing-Stops (orange, gestrichelt) ──────────────────
  // Obergrenze: ueber diesen Preis wandert das Grid nicht hinaus.
  // Untergrenze analog nach unten.
  if (trailingUpStop !== null) candleSeries.createPriceLine({{
    price:trailingUpStop, color:'#F97316', lineWidth:2,
    lineStyle:LightweightCharts.LineStyle.Dashed, axisLabelVisible:true, title:'Trail-Up Stop',
  }});
  // ── Grid Trailing-Stufen (orange Step-Linien) ─────────────
  // Pro Trailing-Trigger ein Datenpunkt; Stufen entstehen via LineType.WithSteps.
  if (trailLowerData.length > 0) {{
    const trailLowerSeries = chart.addLineSeries({{
      color:'#F97316', lineWidth:2,
      lineStyle:LightweightCharts.LineStyle.Solid,
      lineType:LightweightCharts.LineType.WithSteps,
      priceLineVisible:false, lastValueVisible:false,
      crosshairMarkerVisible:false,
    }});
    trailLowerSeries.setData(trailLowerData);
  }}
  if (trailUpperData.length > 0) {{
    const trailUpperSeries = chart.addLineSeries({{
      color:'#F97316', lineWidth:2,
      lineStyle:LightweightCharts.LineStyle.Solid,
      lineType:LightweightCharts.LineType.WithSteps,
      priceLineVisible:false, lastValueVisible:false,
      crosshairMarkerVisible:false,
    }});
    trailUpperSeries.setData(trailUpperData);
  }}

  // ── Recentering-Stufen (gelb, analog Trailing) ────────────
  if (recenterLowerData.length > 0) {{
    const recLowerSeries = chart.addLineSeries({{
      color:'#FCD34D', lineWidth:2,
      lineStyle:LightweightCharts.LineStyle.Solid,
      lineType:LightweightCharts.LineType.WithSteps,
      priceLineVisible:false, lastValueVisible:false,
      crosshairMarkerVisible:false,
    }});
    recLowerSeries.setData(recenterLowerData);
  }}
  if (recenterUpperData.length > 0) {{
    const recUpperSeries = chart.addLineSeries({{
      color:'#FCD34D', lineWidth:2,
      lineStyle:LightweightCharts.LineStyle.Solid,
      lineType:LightweightCharts.LineType.WithSteps,
      priceLineVisible:false, lastValueVisible:false,
      crosshairMarkerVisible:false,
    }});
    recUpperSeries.setData(recenterUpperData);
  }}

  // ── Range-Fuelle (statisch, blau) ─────────────────────────
  // BaselineSeries: faerbt nur den Bereich ZWISCHEN baseValue (lower)
  // und der Linie (upper) ein. Unterhalb von baseValue bleibt unsichtbar
  // (bottomFillColor transparent). Linie selbst unsichtbar.
  if (showRangeFill && upperPrice !== null && lowerPrice !== null
      && firstTs !== null && lastTs !== null) {{
    const rangeFillSeries = chart.addBaselineSeries({{
      baseValue:         {{ type:'price', price: lowerPrice }},
      topLineColor:      'rgba(0,0,0,0)',
      topFillColor1:     'rgba(59,130,246,0.08)',
      topFillColor2:     'rgba(59,130,246,0.08)',
      bottomLineColor:   'rgba(0,0,0,0)',
      bottomFillColor1:  'rgba(0,0,0,0)',
      bottomFillColor2:  'rgba(0,0,0,0)',
      lineWidth:1,
      priceLineVisible:false, lastValueVisible:false,
      crosshairMarkerVisible:false,
    }});
    rangeFillSeries.setData([
      {{ time: firstTs, value: upperPrice }},
      {{ time: lastTs,  value: upperPrice }},
    ]);
  }}

  // ── Trailing-Range-Fuelle (pro Step-Phase eine BaselineSeries) ─
  // Dynamische Faerbung zwischen Lower- und Upper-Step-Linie. Pro
  // Phase (zwischen zwei aufeinander folgenden Event-Timestamps) wird
  // eine eigene BaselineSeries mit konstantem upper/lower angelegt.
  // So folgt die Faerbung exakt dem Step-Verlauf.
  function _renderStepFill(lowerData, upperData, colorRgba) {{
    const n = Math.min(lowerData.length, upperData.length);
    for (let i = 0; i < n - 1; i++) {{
      const startTs = upperData[i].time;
      const endTs   = upperData[i+1].time;
      if (endTs <= startTs) continue;
      const upper = upperData[i].value;
      const lower = lowerData[i].value;
      const s = chart.addBaselineSeries({{
        baseValue:        {{ type:'price', price: lower }},
        topLineColor:     'rgba(0,0,0,0)',
        topFillColor1:    colorRgba,
        topFillColor2:    colorRgba,
        bottomLineColor:  'rgba(0,0,0,0)',
        bottomFillColor1: 'rgba(0,0,0,0)',
        bottomFillColor2: 'rgba(0,0,0,0)',
        lineWidth:1,
        priceLineVisible:false, lastValueVisible:false,
        crosshairMarkerVisible:false,
      }});
      s.setData([
        {{ time: startTs, value: upper }},
        {{ time: endTs,   value: upper }},
      ]);
    }}
  }}

  if (showTrailingFill && trailLowerData.length > 0 && trailUpperData.length > 0) {{
    _renderStepFill(trailLowerData, trailUpperData, 'rgba(249,115,22,0.08)');
  }}

  // ── Recentering-Range-Fuelle (pro Step-Phase, gelb) ───────
  if (showRecenteringFill && recenterLowerData.length > 0 && recenterUpperData.length > 0) {{
    _renderStepFill(recenterLowerData, recenterUpperData, 'rgba(252,211,77,0.08)');
  }}

  // ── Magnet-Crosshair-Marker ───────────────────────────────
  // CandlestickSeries zeigt keinen Crosshair-Marker. Damit der User im
  // Magnet-Modus visuelles Feedback bekommt, wo der Crosshair einrastet,
  // legen wir eine unsichtbare LineSeries (transparent) ueber die Closes
  // und aktivieren nur den Crosshair-Marker.
  if (magnetCrosshair) {{
    const magnetSeries = chart.addLineSeries({{
      color:'rgba(0,0,0,0)', lineWidth:1,
      priceLineVisible:false, lastValueVisible:false,
      crosshairMarkerVisible:true,
      crosshairMarkerRadius:5,
      crosshairMarkerBorderColor:'#60A5FA',
      crosshairMarkerBackgroundColor:'#60A5FA',
    }});
    magnetSeries.setData(candles.map(c => ({{ time:c.time, value:c.close }})));
  }}

  chart.timeScale().fitContent();

  // ── Volume ────────────────────────────────────────────────
  if (hasVol && volData.length > 0) {{
    volSeries = chart.addHistogramSeries({{
      priceFormat:{{ type:'volume' }}, priceScaleId:'vol',
      lastValueVisible:false, priceLineVisible:false,
    }});
    chart.priceScale('vol').applyOptions({{ scaleMargins:{{ top:0.82, bottom:0.0 }} }});
    volSeries.setData(volData);
  }}

  // ── Custom Marker Overlay ─────────────────────────────────
  // Draws triangles at EXACT grid price (Y) and candle time (X)
  const overlay = document.getElementById('marker-overlay');

  function drawMarkers() {{
    overlay.innerHTML = '';
    if (allMarkers.length === 0) return;

    allMarkers.forEach(m => {{
      const x = chart.timeScale().timeToCoordinate(m.time);
      const y = candleSeries.priceToCoordinate(m.price);
      if (x === null || y === null) return;

      // SVG triangle
      const size  = 7;   // half-base (~10% smaller)
      const h     = 11;  // height (~10% smaller)
      const color = m.is_buy ? BUY_COLOR : SELL_COLOR;

      const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      svg.setAttribute('width',  (size * 2 + 4).toString());
      svg.setAttribute('height', (h + 4).toString());
      svg.style.cssText = `
        position:absolute;
        left:${{Math.round(x - size - 2)}}px;
        top:${{m.is_buy ? Math.round(y - h - 3) : Math.round(y + 2)}}px;
        overflow:visible;
        pointer-events:none;
      `;

      const poly = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
      let points;
      if (m.is_buy) {{
        // Triangle pointing UP, tip at top
        points = `${{size}},1 1,${{h}} ${{size * 2 - 1}},${{h}}`;
      }} else {{
        // Triangle pointing DOWN, tip at bottom
        points = `1,1 ${{size * 2 - 1}},1 ${{size}},${{h}}`;
      }}
      poly.setAttribute('points', points);
      poly.setAttribute('fill', color);
      poly.setAttribute('stroke', 'rgba(255,255,255,0.55)');
      poly.setAttribute('stroke-width', '1');
      poly.setAttribute('stroke-linejoin', 'round');
      svg.appendChild(poly);
      overlay.appendChild(svg);
    }});
  }}

  // Redraw markers on any chart change
  chart.timeScale().subscribeVisibleTimeRangeChange(drawMarkers);
  chart.timeScale().subscribeVisibleLogicalRangeChange(drawMarkers);
  setTimeout(drawMarkers, 80);

  // ── Toolbar ───────────────────────────────────────────────
  function fitAll() {{ chart.timeScale().fitContent(); }}
  function zoomIn() {{
    const ts=chart.timeScale(), r=ts.getVisibleRange();
    if (!r) return;
    const mid=(r.from+r.to)/2, h=(r.to-r.from)*0.3;
    ts.setVisibleRange({{from:mid-h, to:mid+h}});
  }}
  function zoomOut() {{
    const ts=chart.timeScale(), r=ts.getVisibleRange();
    if (!r) return;
    const mid=(r.from+r.to)/2, h=(r.to-r.from)*0.85;
    ts.setVisibleRange({{from:mid-h, to:mid+h}});
  }}

  // ── Tooltip ───────────────────────────────────────────────
  const tooltip = document.getElementById('tooltip');
  // Header-OHLC-Spans + Hover-Datum (mittlere Sektion, aktualisiert bei
  // Crosshair-Move)
  const hdrO    = document.getElementById('hdr-o');
  const hdrH    = document.getElementById('hdr-h');
  const hdrL    = document.getElementById('hdr-l');
  const hdrC    = document.getElementById('hdr-c');
  const hdrV    = document.getElementById('hdr-v');
  const hdrDate = document.getElementById('hdr-date');

  // M.5 — Hover-Datum-Formatter ("13. Mai 2026 14:30")
  function _fmtHoverDate(unixTs) {{
    if (typeof unixTs !== 'number') return '—';
    const d = new Date(unixTs * 1000);
    const day = String(d.getDate()).padStart(2, '0');
    const months = ['Jan','Feb','Mär','Apr','Mai','Jun','Jul','Aug','Sep','Okt','Nov','Dez'];
    const month = months[d.getMonth()];
    const year = d.getFullYear();
    const hh = String(d.getHours()).padStart(2, '0');
    const mm = String(d.getMinutes()).padStart(2, '0');
    return day + '. ' + month + ' ' + year + ' ' + hh + ':' + mm;
  }}
  let mouseX=0, mouseY=0;
  document.addEventListener('mousemove', e => {{ mouseX=e.clientX; mouseY=e.clientY; }});

  const fmt = v => typeof v==='number'
    ? v.toLocaleString('de-CH', {{minimumFractionDigits:2, maximumFractionDigits:4}}) : '—';
  const fmtVol = v => typeof v==='number'
    ? v.toLocaleString('de-CH', {{maximumFractionDigits:2}}) : '—';

  // Reset Header-OHLC + Hover-Datum auf "—" wenn kein Crosshair-Wert
  function _resetHdrOHLC() {{
    hdrO.textContent = '—';
    hdrH.textContent = '—';
    hdrL.textContent = '—';
    hdrC.textContent = '—'; hdrC.className = 'ohlc-val';
    hdrV.textContent = '—';
    hdrDate.textContent = '—';
  }}

  chart.subscribeCrosshairMove(param => {{
    // Redraw markers so they stay in sync with crosshair movement
    drawMarkers();

    if (!param || !param.time || !param.seriesData) {{
      tooltip.style.display='none';
      _resetHdrOHLC();
      return;
    }}
    const data = param.seriesData.get(candleSeries);
    if (!data) {{ tooltip.style.display='none'; _resetHdrOHLC(); return; }}

    const isUp = data.close >= data.open;
    const ms   = markerMap[param.time];

    // Header-Datum + OHLC + Volumen aktualisieren
    hdrDate.textContent = _fmtHoverDate(param.time);
    hdrO.textContent = fmt(data.open);
    hdrH.textContent = fmt(data.high);
    hdrL.textContent = fmt(data.low);
    hdrC.textContent = fmt(data.close);
    hdrC.className   = 'ohlc-val ' + (isUp ? 'ohlc-up' : 'ohlc-down');
    if (hasVol) {{
      const vol = volMap[param.time];
      hdrV.textContent = (vol !== undefined) ? fmtVol(vol) : '—';
    }} else {{
      hdrV.textContent = '—';
    }}

    if (ms && ms.length > 0) {{
      document.getElementById('tt-normal').style.display='none';
      document.getElementById('tt-marker').style.display='block';
      document.getElementById('tt-o').textContent = fmt(data.open);
      document.getElementById('tt-h').textContent = fmt(data.high);
      document.getElementById('tt-l').textContent = fmt(data.low);
      const ttc = document.getElementById('tt-c');
      ttc.textContent = fmt(data.close); ttc.className = isUp ? 'tt-up' : 'tt-down';
      // Find closest marker to cursor Y position
      let m = ms[0];
      if (ms.length > 1 && param.point) {{
        let minDist = Infinity;
        ms.forEach(candidate => {{
          const markerY = candleSeries.priceToCoordinate(candidate.price);
          if (markerY !== null) {{
            const dist = Math.abs(markerY - param.point.y);
            if (dist < minDist) {{ minDist = dist; m = candidate; }}
          }}
        }});
      }}
      document.getElementById('tt-oprice').textContent = fmt(m.price);
      document.getElementById('tt-amount').textContent = fmt(m.amount);
      document.getElementById('tt-fee').textContent    = '$' + fmt(m.fee);
      const prow = document.getElementById('tt-prow');
      if (!m.is_buy && m.profit !== null && m.profit !== undefined) {{
        const pe = document.getElementById('tt-profit');
        pe.textContent = (m.profit >= 0 ? '+' : '') + fmt(m.profit) + ' USDT';
        pe.className   = m.profit >= 0 ? 'tt-profit' : 'tt-loss';
        prow.style.display='flex';
      }} else {{ prow.style.display='none'; }}
    }} else {{
      document.getElementById('tt-marker').style.display='none';
      document.getElementById('tt-normal').style.display='block';
      const ttClose = document.getElementById('tt-close');
      ttClose.textContent = fmt(data.close);
      ttClose.className   = 'tt-close ' + (isUp ? 'tt-up' : 'tt-down');
    }}

    tooltip.style.display='block';
    const tw=tooltip.offsetWidth||130, th=tooltip.offsetHeight||70;
    let lx=mouseX+14, ly=mouseY-14;
    if (lx+tw > window.innerWidth)  lx=mouseX-tw-14;
    if (ly+th > window.innerHeight) ly=mouseY-th-4;
    if (ly < 0) ly=4;
    tooltip.style.left=lx+'px'; tooltip.style.top=ly+'px';
  }});

  // ── Resize ────────────────────────────────────────────────
  window.addEventListener('resize', () => {{
    const w=window.innerWidth;
    const h=document.getElementById('chart-wrap').offsetHeight;
    chart.applyOptions({{width:w, height:h}});
    setTimeout(drawMarkers, 50);
  }});
</script>
</body>
</html>"""

    components.html(html, height=height + 4, scrolling=False)
