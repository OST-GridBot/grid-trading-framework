"""
components/tab_drawdown.py
==========================
Render-Komponente fuer den Drawdown-Tab in der Bot-Detail-Ansicht.

Drei Bereiche:
    A) Uebersichts-Box  : Max DD, Phasen S1/S2, gedrosselte Trades, eingespart
    B) Plotly-DD-Chart  : DD-Verlauf + Schwellen-Linien + Hintergrund-Zonen
    C) Phasen-Tabelle   : Aggregierte Drossel-Phasen mit Stufe & Eingespart

Datenquelle: view["dd_history"] = [{"timestamp", "dd_pct", "factor"}, ...]
gefuellt durch GridBot.process_candle bei jeder Kerze (immer, auch bei
deaktivierter Drosselung).

Eingespartes Kapital pro Trade (Variante a):
    saved_usdt = trade_usdt * (1/factor - 1)
Interpretierbar als "Cash das nicht in fallende Phase nachgekauft wurde".

Autor: Enes Eryilmaz
Projekt: Grid-Trading-Framework (Bachelorarbeit OST)
"""

from bisect import bisect_right
from typing import List, Optional, Tuple

import pandas as pd
import streamlit as st


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def _parse_ts(ts) -> Optional[pd.Timestamp]:
    """Robustes Parsen: pd.Timestamp | str | None -> pd.Timestamp | None."""
    if ts is None or ts == "":
        return None
    try:
        return pd.Timestamp(ts)
    except Exception:
        return None


def _format_duration(td: pd.Timedelta) -> str:
    """Timedelta -> kompakte Anzeige (z.B. '13d 10h', '5h 12m', '45m')."""
    if pd.isna(td) or td.total_seconds() <= 0:
        return "–"
    total_sec = int(td.total_seconds())
    days, rem = divmod(total_sec, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    if days > 0:
        return f"{days}d {hours}h"
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def _factor_to_stufe(factor: float) -> str:
    """
    Mapped factor auf diskrete Stufe (drei Werte):
        - 'normal' : factor ~ 1.0  (keine Drosselung)
        - 's1'     : factor ~ 0.50 (Schwelle 1)
        - 's2'     : factor ~ 0.25 (Schwelle 2)
    """
    if factor >= 0.999:
        return "normal"
    if factor >= 0.40:
        return "s1"
    return "s2"


def _stufe_label(stufe: str, factor: float) -> str:
    """Anzeige-Label fuer Stufe inkl. Prozent-Wert."""
    if stufe == "normal":
        return "Normal (100%)"
    pct = int(round(factor * 100))
    if stufe == "s2":
        return f"Schwelle 2 ({pct}%)"
    return f"Schwelle 1 ({pct}%)"


def _lookup_factor_at(
    sorted_ts: List[pd.Timestamp],
    factors:   List[float],
    target:    pd.Timestamp,
) -> float:
    """
    Liefert den DD-Faktor, der zum Zeitpunkt 'target' aktiv war.

    Verwendet bisect_right auf einer sortierten Timestamp-Liste, um den
    letzten Eintrag <= target zu finden. Vor dem ersten Eintrag: 1.0
    (keine Drosselung aktiv).
    """
    if not sorted_ts:
        return 1.0
    idx = bisect_right(sorted_ts, target) - 1
    if idx < 0:
        return 1.0
    return float(factors[idx])


# ---------------------------------------------------------------------------
# Phasen-Aggregation
# ---------------------------------------------------------------------------

def _aggregate_phases(
    dd_history: list,
    trade_log:  list,
    bt_end_ts:  Optional[pd.Timestamp],
) -> List[dict]:
    """
    Aggregiert dd_history zu Phasen anhand der diskreten Stufe.

    Eine Phase = zusammenhaengender Block mit gleicher Stufe (Normal / S1 / S2).
    Phasen wechseln nur bei echten Stufen-Uebergaengen, nicht bei DD-Schwankungen
    innerhalb derselben Stufe. Damit verschwinden die "Mini-Phasen", die durch
    DD-Pingponging um eine Schwelle herum entstanden waren.

    Normal-Phasen werden ebenfalls erfasst, damit der zeitliche Verlauf
    lueckenlos in der Tabelle sichtbar ist.

    Args:
        dd_history : Liste von {timestamp, dd_pct, factor}
        trade_log  : Trade-Log fuer Trade-Zaehlung + Saved-USDT pro Phase
        bt_end_ts  : Letzter Timestamp im Backtest (fuer offene Phasen).

    Returns:
        Liste von dicts: {start, end, stufe, factor, max_dd, num_trades,
                           saved_usdt, is_open}.
        stufe in {"normal", "s1", "s2"}.
    """
    if not dd_history:
        return []

    # 1) dd_history nach Timestamp sortieren (defensive; sollte schon sortiert sein)
    parsed = []
    for ev in dd_history:
        ts = _parse_ts(ev.get("timestamp"))
        if ts is None:
            continue
        parsed.append((ts, float(ev.get("dd_pct", 0.0) or 0.0),
                            float(ev.get("factor", 1.0) or 1.0)))
    parsed.sort(key=lambda x: x[0])
    if not parsed:
        return []

    sorted_ts   = [t for t, _, _ in parsed]
    factors_seq = [f for _, _, f in parsed]

    # 2) Phasen identifizieren: Bloecke mit gleicher Stufe (inkl. 'normal').
    #    Phasenwechsel nur bei Stufen-Uebergang, NICHT bei Faktor-Variation
    #    innerhalb derselben Stufe (factor=0.50 bleibt S1, auch wenn DD schwankt).
    phases: List[dict] = []
    current: Optional[dict] = None
    for ts, dd, fac in parsed:
        stufe = _factor_to_stufe(fac)
        if current is None:
            current = {"start": ts, "end": ts, "stufe": stufe,
                        "factor": fac, "max_dd": dd, "is_open": False}
        elif stufe != current["stufe"]:
            # Echter Stufen-Uebergang: alte Phase schliessen, neue starten
            current["end"] = ts
            phases.append(current)
            current = {"start": ts, "end": ts, "stufe": stufe,
                        "factor": fac, "max_dd": dd, "is_open": False}
        else:
            current["end"] = ts
            if dd > current["max_dd"]:
                current["max_dd"] = dd
            # Faktor in Phase erfrischen (bei S1/S2 ohnehin identisch;
            # bei Normal ohne Effekt).
            current["factor"] = fac

    # Letzte Phase: offen, falls Drossel-Stufe; Normal-Phase regulaer abschliessen
    if current is not None:
        if current["stufe"] != "normal":
            current["is_open"] = True
            if bt_end_ts is not None:
                current["end"] = bt_end_ts
        phases.append(current)

    # 3) Pro Phase: Trades zaehlen + saved_usdt akkumulieren.
    #    Bei Normal-Phasen: num_trades = alle Grid-Trades im Zeitfenster,
    #    saved_usdt = 0 (Tabelle zeigt '–').
    for ph in phases:
        s, e = ph["start"], ph["end"]
        n_trades = 0
        saved    = 0.0
        for t in trade_log:
            t_ts = _parse_ts(t.get("timestamp"))
            if t_ts is None or not (s <= t_ts <= e):
                continue
            # Initial-Buys ueberspringen (gehoeren nicht zum Grid-Flow)
            if t.get("type") == "BUY" and t.get("initial"):
                continue
            if ph["stufe"] == "normal":
                # Normal-Phase: alle Grid-Trades zaehlen, kein Saved.
                n_trades += 1
                continue
            # S1/S2: nur Trades zaehlen, die tatsaechlich gedrosselt wurden.
            fac_at = _lookup_factor_at(sorted_ts, factors_seq, t_ts)
            if fac_at >= 1.0 - 1e-9:
                continue
            n_trades += 1
            trade_usdt = float(t.get("amount", 0) or 0) * float(t.get("price", 0) or 0)
            if fac_at > 1e-9:
                saved += trade_usdt * (1.0 / fac_at - 1.0)
        ph["num_trades"] = n_trades
        ph["saved_usdt"] = saved

    return phases


# ---------------------------------------------------------------------------
# Render-Bausteine
# ---------------------------------------------------------------------------

def _render_overview_box(
    phases:           List[dict],
    dd_history:       list,
    trade_log:        list,
    total_throttled:  int,
    total_trades:     int,
    total_saved:      float,
    max_dd_pct:       float,
) -> None:
    """A) Uebersichts-Box mit Aggregat-Kennzahlen oben im Tab.

    max_dd_pct kommt aus metrics.max_drawdown_pct (zentrale Quelle),
    damit Performance-Tab und DD-Tab garantiert identische Werte zeigen.
    """

    # Phasen nach Stufe trennen (neue Stufen-Logik)
    s1 = [p for p in phases if p.get("stufe") == "s1"]
    s2 = [p for p in phases if p.get("stufe") == "s2"]

    def _sum_duration(phs: List[dict]) -> pd.Timedelta:
        total = pd.Timedelta(0)
        for p in phs:
            total += (p["end"] - p["start"])
        return total

    s1_dur = _format_duration(_sum_duration(s1))
    s2_dur = _format_duration(_sum_duration(s2))

    st.markdown(
        f"""
        <div style='padding:14px 18px; border:1px solid #334155;
                     border-radius:8px; background:rgba(255,255,255,0.02);
                     margin-bottom:14px;'>
            <div style='display:grid; grid-template-columns: repeat(5, 1fr); gap:18px;'>
                <div>
                    <div style='color:#94A3B8; font-size:0.75rem; text-transform:uppercase;
                                 letter-spacing:0.5px; margin-bottom:4px;'>Max Drawdown</div>
                    <div style='color:#F87171; font-size:1.3rem; font-weight:700;'>
                        {max_dd_pct:.2f}%
                    </div>
                </div>
                <div>
                    <div style='color:#94A3B8; font-size:0.75rem; text-transform:uppercase;
                                 letter-spacing:0.5px; margin-bottom:4px;'>Phasen Schwelle 1</div>
                    <div style='color:#FBBF24; font-size:1.3rem; font-weight:700;'>
                        {len(s1)}
                    </div>
                    <div style='color:#64748B; font-size:0.75rem; margin-top:2px;'>
                        {s1_dur} gesamt
                    </div>
                </div>
                <div>
                    <div style='color:#94A3B8; font-size:0.75rem; text-transform:uppercase;
                                 letter-spacing:0.5px; margin-bottom:4px;'>Phasen Schwelle 2</div>
                    <div style='color:#F87171; font-size:1.3rem; font-weight:700;'>
                        {len(s2)}
                    </div>
                    <div style='color:#64748B; font-size:0.75rem; margin-top:2px;'>
                        {s2_dur} gesamt
                    </div>
                </div>
                <div>
                    <div style='color:#94A3B8; font-size:0.75rem; text-transform:uppercase;
                                 letter-spacing:0.5px; margin-bottom:4px;'>Gedrosselte Trades</div>
                    <div style='color:#E2E8F0; font-size:1.3rem; font-weight:700;'>
                        {total_throttled} / {total_trades}
                    </div>
                </div>
                <div>
                    <div style='color:#94A3B8; font-size:0.75rem; text-transform:uppercase;
                                 letter-spacing:0.5px; margin-bottom:4px;'>Eingespartes Kapital</div>
                    <div style='color:#34D399; font-size:1.3rem; font-weight:700;'>
                        ≈ {total_saved:,.0f} USDT
                    </div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_dd_chart(
    dd_history: list,
    thr1:       float,
    thr2:       float,
) -> None:
    """B) Plotly-DD-Chart mit Schwellen-Linien und Hintergrund-Zonen."""
    try:
        import plotly.graph_objects as go
    except ImportError:
        st.warning("Plotly nicht installiert — Chart kann nicht gerendert werden.")
        return

    # DataFrame mit -dd_pct (negativ nach unten)
    ts  = [_parse_ts(ev.get("timestamp")) for ev in dd_history]
    dd  = [-float(ev.get("dd_pct", 0) or 0) * 100 for ev in dd_history]
    # Nones rausfiltern
    pairs = [(t, d) for t, d in zip(ts, dd) if t is not None]
    if not pairs:
        st.info("Keine gueltigen Timestamps in der DD-Historie.")
        return
    xs, ys = zip(*pairs)

    y_min = min(ys + (-thr2 * 100 * 1.2,)) - 1
    y_max = 1.0  # immer etwas Headroom ueber 0

    fig = go.Figure()

    # Hintergrund-Zonen (Hrects)
    fig.add_hrect(y0=-thr1 * 100, y1=0,
                   line_width=0, fillcolor="rgba(100,116,139,0.05)")
    fig.add_hrect(y0=-thr2 * 100, y1=-thr1 * 100,
                   line_width=0, fillcolor="rgba(251,191,36,0.15)")
    fig.add_hrect(y0=y_min, y1=-thr2 * 100,
                   line_width=0, fillcolor="rgba(248,113,113,0.15)")

    # Schwellen-Linien
    fig.add_hline(y=-thr1 * 100, line_width=1, line_dash="dash",
                   line_color="#FBBF24",
                   annotation_text=f"Schwelle 1 ({thr1*100:.0f}%)",
                   annotation_position="top right",
                   annotation_font_color="#FBBF24",
                   annotation_font_size=11)
    fig.add_hline(y=-thr2 * 100, line_width=1, line_dash="dash",
                   line_color="#F87171",
                   annotation_text=f"Schwelle 2 ({thr2*100:.0f}%)",
                   annotation_position="top right",
                   annotation_font_color="#F87171",
                   annotation_font_size=11)

    # DD-Linie
    fig.add_trace(go.Scatter(
        x=xs, y=ys, mode="lines", name="Drawdown",
        line=dict(color="#E2E8F0", width=1.5),
        hovertemplate="<b>%{x|%Y-%m-%d %H:%M}</b><br>DD: %{y:.2f}%<extra></extra>",
    ))

    fig.update_layout(
        height=360,
        margin=dict(l=10, r=10, t=20, b=10),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#E2E8F0", size=11),
        showlegend=False,
        yaxis=dict(title="Drawdown (%)", range=[y_min, y_max],
                    gridcolor="rgba(148,163,184,0.1)", zeroline=True,
                    zerolinecolor="rgba(148,163,184,0.3)"),
        xaxis=dict(title=None, gridcolor="rgba(148,163,184,0.1)"),
    )
    st.plotly_chart(fig, use_container_width=True)


def _render_phases_table(phases: List[dict], is_running: bool) -> None:
    """C) Phasen-Tabelle mit Spalten-Styling.

    Zeigt alle Phasen inkl. 'Normal' (kein Drosseln). 'Eingespart' bleibt
    bei Normal-Phasen leer ('–'), Stufe wird neutral grau gerendert.

    Args:
        phases     : aggregierte Phasen aus _aggregate_phases
        is_running : True bei PT/LT-Bots mit Status 'running' -> offene
                     Phase am Ende zeigt 'laufend'; False bei BT/completed
                     oder gestoppten Bots -> stattdessen End-Timestamp.
    """
    if not phases:
        st.info("Keine Phasen-Daten verfuegbar.")
        return

    rows = []
    for p in phases:
        dur = p["end"] - p["start"]
        # 'laufend' nur fuer offene Phasen wenn Bot tatsaechlich laeuft;
        # bei BT/completed -> End-Timestamp anzeigen.
        if p["is_open"] and is_running:
            end_label = "laufend"
        else:
            end_label = p["end"].strftime("%Y-%m-%d %H:%M")
        stufe     = p.get("stufe", "normal")
        # Eingespart: bei Normal '-', sonst USDT-Summe
        if stufe == "normal":
            saved_str = "–"
        else:
            saved_str = f"≈ {p['saved_usdt']:,.0f} USDT"
        rows.append({
            "Start":           p["start"].strftime("%Y-%m-%d %H:%M"),
            "Ende":            end_label,
            "Dauer":           _format_duration(dur),
            "Stufe":           _stufe_label(stufe, p["factor"]),
            "Max DD in Phase": f"{p['max_dd']*100:.2f}%",
            "Trades":          p["num_trades"],
            "Eingespart":      saved_str,
        })

    df = pd.DataFrame(rows)

    # Styler: Stufen-Spalte einfaerben (Normal grau, S1 gelb, S2 rot)
    def _stufe_color(val: str) -> str:
        if "Schwelle 2" in str(val):
            return "color:#F87171; font-weight:600;"
        if "Schwelle 1" in str(val):
            return "color:#FBBF24; font-weight:600;"
        if "Normal" in str(val):
            return "color:#94A3B8; font-weight:500;"
        return ""

    styler = df.style.map(_stufe_color, subset=["Stufe"])
    st.dataframe(styler, use_container_width=True, hide_index=True)


# ---------------------------------------------------------------------------
# Hauptfunktion
# ---------------------------------------------------------------------------

def render_tab_drawdown(view: dict) -> None:
    """
    Rendert den Drawdown-Tab:
        A) Uebersichts-Box  (HTML-Box mit 5 Kennzahlen)
        B) Plotly-Chart     (DD-Verlauf + Schwellen + Zonen)
        C) Phasen-Tabelle   (Aggregat pro Drossel-Phase)

    Edge-Cases:
        • cfg.enable_dd_throttle == False  -> Hinweis, Chart + Tabelle unterdrueckt
        • dd_history leer (alter Snapshot) -> Hinweis "Keine DD-Historie"
        • Keine Phasen                     -> Box + Chart, Tabelle ersetzt durch Hinweis
        • Offene Phase                     -> Ende="laufend" (PT/LT) bzw. BT-Ende
    """
    cfg        = view.get("config", {}) or {}
    dd_history = view.get("dd_history", []) or []
    trade_log  = view.get("trade_log",  []) or []
    metrics    = view.get("metrics",    {}) or {}
    mode       = view.get("mode", "")
    status     = view.get("status", "")

    # Edge-Case: keine History (alter Snapshot ohne Tracking oder Bot noch nicht gelaufen)
    if not dd_history:
        st.info("Keine Drawdown-Historie verfuegbar. "
                "Bei aelteren Bot-Snapshots wurde dieser Verlauf noch nicht "
                "getrackt — fuehre einen neuen Backtest aus oder warte auf "
                "neue Kerzen-Updates.")
        return

    # Hinweis (dezent): bei deaktivierter Drosselung wird trotzdem der
    # DD-Verlauf gezeigt; Tabelle enthaelt nur eine Normal-Phase.
    if not cfg.get("enable_dd_throttle", False):
        st.caption("Hinweis: DD-Drosselung war fuer diesen Bot nicht "
                    "aktiviert. Der DD-Verlauf wird informativ angezeigt.")

    thr1 = float(cfg.get("dd_threshold_1", 0.10) or 0.10)
    thr2 = float(cfg.get("dd_threshold_2", 0.20) or 0.20)
    # Defensive: Schwellen sortieren, falls vertauscht persistiert
    thr1, thr2 = sorted([thr1, thr2])

    # BT-Ende bestimmen (fuer offene Phasen + Tabellen-"Ende"-Spalte)
    bt_end_ts = _parse_ts(dd_history[-1].get("timestamp"))
    is_running = (mode in ("paper", "live") and status == "running")

    # Phasen aggregieren
    phases = _aggregate_phases(dd_history, trade_log, bt_end_ts)

    # Aggregat-Kennzahlen fuer Box
    total_throttled = sum(p["num_trades"] for p in phases)
    total_trades    = sum(
        1 for t in trade_log
        if not (t.get("type") == "BUY" and t.get("initial"))
    )
    total_saved = sum(p["saved_usdt"] for p in phases)

    # A) Uebersichts-Box
    # Max-DD aus metrics (zentrale Quelle, identische Formel wie dd_history-
    # Tracking in GridBot.process_candle -> garantiert dieselbe Zahl wie im
    # Performance & Risk Tab).
    max_dd_pct = float(metrics.get("max_drawdown_pct", 0) or 0)
    _render_overview_box(phases, dd_history, trade_log,
                          total_throttled, total_trades, total_saved,
                          max_dd_pct)

    # B) Chart
    _render_dd_chart(dd_history, thr1, thr2)

    # C) Phasen-Tabelle
    st.markdown("##### Drossel-Phasen")
    _render_phases_table(phases, is_running)
