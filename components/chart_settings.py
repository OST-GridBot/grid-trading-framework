"""
components/chart_settings.py
============================
Chart-Einstellungen-Sektion (Expander mit Toggles) - wird unter dem Chart
in Bot-Detail und Bot-Setup-Form gerendert.

Liefert ein Settings-Dict, das direkt an plot_grid_chart_v2 weitergereicht
werden kann. Jeder Aufrufer uebergibt einen eindeutigen key_prefix, damit
die Streamlit-Widget-Keys zwischen Setup- und Detail-Kontext nicht
kollidieren.

Layout: drei Sub-Sektionen mit eigener Ueberschrift (Auftrag M.3):
    Grid-Elemente
    Chart-Anzeige
    Mechanismen-Visualisierung
Keine Farben in den Labels — die Farben sind im Chart selbst sichtbar.

Autor: Enes Eryilmaz
Projekt: Grid-Trading-Framework (Bachelorarbeit OST)
"""

import streamlit as st


# Standard-Defaults
_DEFAULTS = {
    # Grid-Elemente
    "show_grid_lines":     True,
    "show_grid_labels":    False,
    "show_order_markers":  True,
    "show_bot_start":      True,
    "show_range_fill":     True,
    # Chart-Anzeige
    "magnet_crosshair":    False,
    "show_volume":         True,
    # Mechanismen-Visualisierung
    "show_trailing_steps":     True,   # Grid Trailing-Grenzen (Step-Linien)
    "show_trailing_fill":      True,
    "show_trailing_stops":     True,   # Trailing-Stop-Limit-Linie
    "show_recentering_steps":  True,
    "show_recentering_fill":   True,
    "show_sltp_lines":             True,  # SL + TP zusammengefuehrt (M.3)
    "show_sltp_trigger_markers":   True,  # NEU (M.2)
}


def _sub_header(title: str) -> None:
    """Render-Header fuer eine Sub-Sektion innerhalb des Expanders."""
    st.markdown(
        f"<div style='font-size:0.8rem; font-weight:600; color:#94A3B8; "
        f"text-transform:uppercase; letter-spacing:0.05em; "
        f"margin: 8px 0 4px 0; padding-bottom:3px; "
        f"border-bottom:1px solid rgba(255,255,255,0.10);'>{title}</div>",
        unsafe_allow_html=True,
    )


def render_chart_settings(key_prefix: str) -> dict:
    """
    Rendert die Chart-Einstellungen als Expander unter dem Chart, in drei
    thematischen Sub-Sektionen (jede mit 2-spaltigem Toggle-Layout).

    Args:
        key_prefix : Eindeutiger Praefix fuer alle Streamlit-Widget-Keys
                     (z.B. "setup", "detail", "pending_bt").

    Returns:
        Settings-Dict mit allen Toggle-Werten (Backward-Compat: liefert
        auch show_stop_loss / show_take_profit ab, beide gleich
        show_sltp_lines, damit bestehende Caller im Chart-Modul keinen
        Bruch sehen).
    """
    settings = {}
    with st.expander("Chart-Einstellungen", expanded=False):

        # ── Grid-Elemente ──────────────────────────────────────────────────
        _sub_header("Grid-Elemente")
        c1, c2 = st.columns(2)
        with c1:
            settings["show_grid_lines"] = st.checkbox(
                "Grid-Linien", value=_DEFAULTS["show_grid_lines"],
                key=f"chs_{key_prefix}_grid_lines",
            )
            settings["show_order_markers"] = st.checkbox(
                "Order-Marker", value=_DEFAULTS["show_order_markers"],
                key=f"chs_{key_prefix}_order_markers",
            )
            settings["show_range_fill"] = st.checkbox(
                "Normale Grenzen-Fläche",
                value=_DEFAULTS["show_range_fill"],
                key=f"chs_{key_prefix}_range_fill",
            )
        with c2:
            settings["show_grid_labels"] = st.checkbox(
                "Grid-Labels (Preise)",
                value=_DEFAULTS["show_grid_labels"],
                key=f"chs_{key_prefix}_grid_labels",
            )
            settings["show_bot_start"] = st.checkbox(
                "Bot-Start", value=_DEFAULTS["show_bot_start"],
                key=f"chs_{key_prefix}_bot_start",
            )

        # ── Chart-Anzeige ──────────────────────────────────────────────────
        _sub_header("Chart-Anzeige")
        c1, c2 = st.columns(2)
        with c1:
            settings["magnet_crosshair"] = st.checkbox(
                "Magnet-Crosshair",
                value=_DEFAULTS["magnet_crosshair"],
                key=f"chs_{key_prefix}_magnet",
            )
        with c2:
            settings["show_volume"] = st.checkbox(
                "Volumen", value=_DEFAULTS["show_volume"],
                key=f"chs_{key_prefix}_volume",
            )

        # ── Mechanismen-Visualisierung ─────────────────────────────────────
        _sub_header("Mechanismen-Visualisierung")
        c1, c2 = st.columns(2)
        with c1:
            settings["show_trailing_steps"] = st.checkbox(
                "Grid Trailing-Grenzen",
                value=_DEFAULTS["show_trailing_steps"],
                key=f"chs_{key_prefix}_trailing_steps",
            )
            settings["show_trailing_stops"] = st.checkbox(
                "Grid Trailing-Stop-Linie",
                value=_DEFAULTS["show_trailing_stops"],
                key=f"chs_{key_prefix}_trailing_stops",
            )
            settings["show_recentering_steps"] = st.checkbox(
                "Recentering-Grenzen",
                value=_DEFAULTS["show_recentering_steps"],
                key=f"chs_{key_prefix}_recenter_steps",
            )
            settings["show_sltp_lines"] = st.checkbox(
                "SL/TP-Linien",
                value=_DEFAULTS["show_sltp_lines"],
                key=f"chs_{key_prefix}_sltp_lines",
            )
        with c2:
            settings["show_trailing_fill"] = st.checkbox(
                "Grid Trailing-Fläche",
                value=_DEFAULTS["show_trailing_fill"],
                key=f"chs_{key_prefix}_trailing_fill",
            )
            settings["show_recentering_fill"] = st.checkbox(
                "Recentering-Fläche",
                value=_DEFAULTS["show_recentering_fill"],
                key=f"chs_{key_prefix}_recenter_fill",
            )
            settings["show_sltp_trigger_markers"] = st.checkbox(
                "SL/TP-Trigger-Marker",
                value=_DEFAULTS["show_sltp_trigger_markers"],
                key=f"chs_{key_prefix}_sltp_triggers",
            )

    # Backward-Compat: die alten Einzel-Keys werden aus show_sltp_lines
    # abgeleitet, damit Caller (plot_grid_chart_v2) ohne Aenderung greifen.
    settings["show_stop_loss"]   = settings["show_sltp_lines"]
    settings["show_take_profit"] = settings["show_sltp_lines"]
    return settings
