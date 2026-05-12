"""
components/chart_settings.py
============================
Chart-Einstellungen-Sektion (Expander mit Toggles) - wird unter dem Chart
in Bot-Detail und Bot-Setup-Form gerendert.

Liefert ein Settings-Dict, das direkt an plot_grid_chart_v2 weitergereicht
werden kann. Jeder Aufrufer uebergibt einen eindeutigen key_prefix, damit
die Streamlit-Widget-Keys zwischen Setup- und Detail-Kontext nicht
kollidieren.

Autor: Enes Eryilmaz
Projekt: Grid-Trading-Framework (Bachelorarbeit OST)
"""

import streamlit as st


# Standard-Defaults
_DEFAULTS = {
    "show_grid_lines":     True,
    "show_grid_labels":    False,
    "show_order_markers":  True,
    "show_bot_start":      True,
    "magnet_crosshair":    False,
    "show_volume":         True,
    "show_trailing_steps": True,
    "show_stop_loss":      True,
    "show_take_profit":    True,
}


def render_chart_settings(key_prefix: str) -> dict:
    """
    Rendert die Chart-Einstellungen als Expander unter dem Chart.

    Args:
        key_prefix : Eindeutiger Praefix fuer alle Streamlit-Widget-Keys
                     (z.B. "setup", "detail", "pending_bt").

    Returns:
        Settings-Dict mit allen Toggle-Werten.
    """
    settings = {}
    with st.expander("Chart-Einstellungen", expanded=False):
        # Layout-Konvention: Toggles werden zeilenweise aufgefuellt.
        # Aktuell 5 links / 4 rechts. Neue Toggles kommen an die Spalte mit
        # weniger Eintraegen (also der naechste Toggle nach rechts, dann links
        # usw.), damit beide Spalten ausgeglichen bleiben.
        col1, col2 = st.columns(2)
        with col1:
            settings["show_grid_lines"] = st.checkbox(
                "Grid-Linien", value=_DEFAULTS["show_grid_lines"],
                key=f"chs_{key_prefix}_grid_lines"
            )
            settings["show_grid_labels"] = st.checkbox(
                "Grid-Preis-Labels", value=_DEFAULTS["show_grid_labels"],
                key=f"chs_{key_prefix}_grid_labels"
            )
            settings["show_order_markers"] = st.checkbox(
                "Buy/Sell-Marker", value=_DEFAULTS["show_order_markers"],
                key=f"chs_{key_prefix}_order_markers"
            )
            settings["show_bot_start"] = st.checkbox(
                "Bot-Start-Markierung", value=_DEFAULTS["show_bot_start"],
                key=f"chs_{key_prefix}_bot_start"
            )
            settings["magnet_crosshair"] = st.checkbox(
                "Hover-Magnet (Crosshair snappt auf Kerze)",
                value=_DEFAULTS["magnet_crosshair"],
                key=f"chs_{key_prefix}_magnet"
            )
        with col2:
            settings["show_volume"] = st.checkbox(
                "Volumen", value=_DEFAULTS["show_volume"],
                key=f"chs_{key_prefix}_volume"
            )
            settings["show_trailing_steps"] = st.checkbox(
                "Grid Trailing-Stufen (orange)",
                value=_DEFAULTS["show_trailing_steps"],
                key=f"chs_{key_prefix}_trailing_steps"
            )
            settings["show_stop_loss"] = st.checkbox(
                "Stop-Loss-Linie (rot)",
                value=_DEFAULTS["show_stop_loss"],
                key=f"chs_{key_prefix}_stop_loss"
            )
            settings["show_take_profit"] = st.checkbox(
                "Take-Profit-Linie (grün)",
                value=_DEFAULTS["show_take_profit"],
                key=f"chs_{key_prefix}_take_profit"
            )
    return settings
