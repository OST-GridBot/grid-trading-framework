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
        <div style="display: flex; align-items: center; justify-content: space-between;">
            <div>
                <div style="font-family: 'Space Mono', monospace; font-size: 1.35rem;
                            font-weight: 700; color: #E2E8F0; line-height: 1.3;">
                    Grid Bot<br>Dashboard
                </div>
                <div style="font-size: 0.7rem; color: #374151; margin-top: 4px;">
                    Bachelorarbeit OST · Enes Eryilmaz
                </div>
            </div>
            <a href="/" target="_self" style="
                display: inline-block;
                padding: 6px 14px;
                background: rgba(255,255,255,0.06);
                border: 1px solid rgba(255,255,255,0.12);
                border-radius: 6px;
                color: #E2E8F0;
                font-size: 0.85rem;
                font-weight: 600;
                text-decoration: none;
                cursor: pointer;
                white-space: nowrap;
            ">Cockpit</a>
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

if "nav_redirect" in st.session_state:
    redirect = st.session_state.pop("nav_redirect")
    st.session_state["navigation"] = redirect

selected = st.sidebar.radio(
    "",
    list(PAGES.keys()),
    label_visibility = "collapsed",
    key = "navigation",
    index = None,
)

st.sidebar.divider()

# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

page = PAGES.get(selected, "cockpit")

if page in ("cockpit", None) or selected is None:
    from pages.page_market import show_market
    show_market()

elif page == "backtesting":
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