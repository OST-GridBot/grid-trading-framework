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
    df:           pd.DataFrame,
    grid_lines:   list,
    trade_log:    list,
    coin:         str   = "BTC",
    interval:     str   = "1h",
    show_volume:  bool  = True,
    upper_price:  Optional[float] = None,
    lower_price:  Optional[float] = None,
    height:       int   = 560,
) -> None:

    def _to_unix(ts_val):
        try:
            ts = pd.to_datetime(ts_val)
            if ts.tzinfo is not None:
                ts = ts.tz_localize(None)
            return int(ts.timestamp())
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
    for t in trade_log:
        try:
            ts = _to_unix(t["timestamp"])
            if ts is None:
                continue
            is_buy = "BUY" in str(t.get("type", "")).upper()
            markers.append({
                "time":     ts,
                "is_buy":   is_buy,
                "price":    float(t.get("price", 0)),
                "profit":   t.get("profit", None),
                "amount":   float(t.get("amount", 0)),
                "fee":      float(t.get("fee", 0)),
            })
        except Exception:
            continue
    markers.sort(key=lambda x: x["time"])

    price_lines = [round(float(gl), 4) for gl in grid_lines]
    has_volume  = show_volume and bool(volume_data)

    candles_json     = json.dumps(candles)
    volume_json      = json.dumps(volume_data)
    markers_json     = json.dumps(markers)
    price_lines_json = json.dumps(price_lines)
    upper_json       = json.dumps(round(float(upper_price), 4) if upper_price else None)
    lower_json       = json.dumps(round(float(lower_price), 4) if lower_price else None)
    coin_js          = json.dumps(coin)
    interval_js      = json.dumps(interval)
    date_range_js    = json.dumps(date_range_str)
    has_vol_js       = "true" if has_volume else "false"

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
  #hdr-info {{ display:flex; align-items:center; gap:10px; flex:1; min-width:0; }}
  #hdr-coin {{ font-size:15px; font-weight:600; color:#E2E8F0; letter-spacing:0.01em; }}
  #hdr-interval {{
    font-size:11px; color:#60A5FA;
    background:rgba(59,130,246,0.12); border:1px solid rgba(59,130,246,0.25);
    border-radius:4px; padding:2px 7px; letter-spacing:0.03em;
  }}
  #hdr-dates {{ font-size:11px; color:#475569; letter-spacing:0.01em; }}

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

  /* Vol label */
  #vol-label {{
    position:absolute; bottom:28px; right:80px; z-index:90;
    font-size:11px; color:rgba(148,163,184,0.6);
    pointer-events:none; display:none; letter-spacing:0.02em;
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
      <span id="hdr-dates"></span>
    </div>
    <div id="toolbar">
      <button class="tb-btn" onclick="fitAll()">Fit</button>
      <button class="tb-btn" onclick="zoomIn()">+</button>
      <button class="tb-btn" onclick="zoomOut()">−</button>
      <button class="tb-btn" id="btn-pan" onclick="togglePan()">Pan</button>
      <div class="tb-sep" id="vol-sep" style="display:none"></div>
      <button class="tb-btn" id="btn-vol" style="display:none" onclick="toggleVol()">Vol</button>
    </div>
  </div>
  <div id="chart-wrap">
    <div id="chart"></div>
    <div id="marker-overlay"></div>
    <div id="vol-label"></div>
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
  const candles    = {candles_json};
  const volData    = {volume_json};
  const allMarkers = {markers_json};
  const priceLines = {price_lines_json};
  const upperPrice = {upper_json};
  const lowerPrice = {lower_json};
  const coinName   = {coin_js};
  const interval   = {interval_js};
  const dateRange  = {date_range_js};
  const hasVol     = {has_vol_js};

  // Marker colours — slightly darker than original
  const BUY_COLOR  = '#158A50';  // darker green
  const SELL_COLOR = '#B83C3C';  // darker red

  document.getElementById('hdr-coin').textContent     = coinName + '/USDT';
  document.getElementById('hdr-interval').textContent = interval;
  document.getElementById('hdr-dates').textContent    = dateRange;

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
  let panMode    = false;
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
    crosshair: {{ mode:LightweightCharts.CrosshairMode.Normal }},
    rightPriceScale: {{
      borderColor: 'rgba(255,255,255,0.08)',
      scaleMargins: hasVol ? marginsOn : marginsOff,
    }},
    timeScale: {{
      borderColor:'rgba(255,255,255,0.08)', timeVisible:true, secondsVisible:false,
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

  priceLines.forEach(p => candleSeries.createPriceLine({{
    price:p, color:'rgba(100,160,255,0.35)', lineWidth:1,
    lineStyle:LightweightCharts.LineStyle.Dotted, axisLabelVisible:false,
  }}));
  if (upperPrice) candleSeries.createPriceLine({{
    price:upperPrice, color:'rgba(59,130,246,0.9)', lineWidth:2,
    lineStyle:LightweightCharts.LineStyle.Solid, axisLabelVisible:true, title:'Upper',
  }});
  if (lowerPrice) candleSeries.createPriceLine({{
    price:lowerPrice, color:'rgba(59,130,246,0.9)', lineWidth:2,
    lineStyle:LightweightCharts.LineStyle.Solid, axisLabelVisible:true, title:'Lower',
  }});
  chart.timeScale().fitContent();

  // ── Volume ────────────────────────────────────────────────
  if (hasVol && volData.length > 0) {{
    document.getElementById('vol-sep').style.display = 'block';
    document.getElementById('btn-vol').style.display = 'block';
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
  function togglePan() {{
    panMode = !panMode;
    chart.applyOptions({{
      handleScale: {{ mouseWheel:!panMode, pinch:!panMode, axisPressedMouseMove:!panMode }},
      handleScroll: {{ mouseWheel:panMode, pressedMouseMove:true, horzTouchDrag:true }},
    }});
    document.getElementById('btn-pan').classList.toggle('active', panMode);
  }}
  function toggleVol() {{
    if (!volSeries) return;
    volVisible = !volVisible;
    volSeries.applyOptions({{ visible:volVisible }});
    chart.applyOptions({{ rightPriceScale:{{ scaleMargins:volVisible ? marginsOn : marginsOff }} }});
    document.getElementById('btn-vol').classList.toggle('active', !volVisible);
    if (!volVisible) document.getElementById('vol-label').style.display='none';
  }}

  // ── Tooltip ───────────────────────────────────────────────
  const tooltip  = document.getElementById('tooltip');
  const volLabel = document.getElementById('vol-label');
  let mouseX=0, mouseY=0;
  document.addEventListener('mousemove', e => {{ mouseX=e.clientX; mouseY=e.clientY; }});

  const fmt = v => typeof v==='number'
    ? v.toLocaleString('de-CH', {{minimumFractionDigits:2, maximumFractionDigits:4}}) : '—';
  const fmtVol = v => typeof v==='number'
    ? v.toLocaleString('de-CH', {{maximumFractionDigits:2}}) : '—';

  chart.subscribeCrosshairMove(param => {{
    // Redraw markers so they stay in sync with crosshair movement
    drawMarkers();

    if (!param || !param.time || !param.seriesData) {{
      tooltip.style.display='none'; volLabel.style.display='none'; return;
    }}
    const data = param.seriesData.get(candleSeries);
    if (!data) {{ tooltip.style.display='none'; return; }}

    const isUp = data.close >= data.open;
    const ms   = markerMap[param.time];

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

    if (hasVol && volVisible) {{
      const vol = volMap[param.time];
      if (vol !== undefined) {{
        volLabel.textContent='Vol  ' + fmtVol(vol); volLabel.style.display='block';
      }} else {{ volLabel.style.display='none'; }}
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
