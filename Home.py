"""
Home.py
=======
Hauptdatei des Grid-Trading-Frameworks.
Sidebar-Navigation steuert welche Seite angezeigt wird.

Autor: Enes Eryilmaz
Projekt: Grid-Trading-Framework (Bachelorarbeit OST)
"""

import streamlit as st

st.set_page_config(
    page_title = "Grid Bot Dashboard",
    page_icon  = "⚡",
    layout     = "wide",
    initial_sidebar_state = "expanded",
)

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=Inter:wght@300;400;500;600&display=swap');
    html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
    .stApp { background: #0A0C10; }
    h1, h2, h3 { font-family: 'Space Mono', monospace !important; }
    .block-container { padding-top: 1.5rem !important; }
    [data-testid="stSidebarNav"] { display: none !important; }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Sidebar Navigation
# ---------------------------------------------------------------------------

st.sidebar.markdown("""
    <div style="padding: 8px 0 10px 0;">
        <div style="font-family: 'Space Mono', monospace; font-size: 1.35rem;
                    font-weight: 700; color: #E2E8F0; line-height: 1.3;">
            Grid Bot<br>Dashboard
        </div>
        <div style="font-size: 0.7rem; color: #374151; margin-top: 4px;">
            Bachelorarbeit OST · Enes Eryilmaz
        </div>
    </div>
""", unsafe_allow_html=True)

st.sidebar.divider()

st.sidebar.markdown(
    "<div style='font-size:1.15rem; color:#CBD5E1; font-family:Inter,-apple-system,sans-serif; "
    "font-weight:600; text-transform:uppercase; letter-spacing:0.06em; "
    "margin-bottom:4px;'>Navigation</div>",
    unsafe_allow_html=True
)

PAGES = {
    "📊  Backtesting":    "backtesting",
    "🔍  Coin Scanner":   "scanner",
    "📄  Paper Trading":  "paper_trading",
    "🔴  Live Trading":   "live_trading",
}

selected = st.sidebar.radio(
    "",
    list(PAGES.keys()),
    label_visibility = "collapsed",
    key = "navigation",
)

st.sidebar.divider()

# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

page = PAGES[selected]

if page == "backtesting":
    from pages.page_backtesting import show_backtesting
    show_backtesting()

elif page == "scanner":
    from pages.page_scanner import show_scanner
    show_scanner()

elif page == "paper_trading":
    from pages.page_paper_trading import show_paper_trading
    show_paper_trading()

elif page == "live_trading":
    from pages.page_live_trading import show_live_trading
    show_live_trading()