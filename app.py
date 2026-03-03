"""
app.py
======
Startseite des Grid-Trading-Frameworks.
"""

import streamlit as st

st.set_page_config(
    page_title = "Grid Trading Framework",
    page_icon  = "⚡",
    layout     = "wide",
    initial_sidebar_state = "collapsed",
)

# ---------------------------------------------------------------------------
# Custom CSS
# ---------------------------------------------------------------------------

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=Inter:wght@300;400;500;600&display=swap');

    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }

    .stApp {
        background: #0A0C10;
    }

    .hero-title {
        font-family: 'Space Mono', monospace;
        font-size: clamp(2.5rem, 6vw, 4.5rem);
        font-weight: 700;
        color: #F1F5F9;
        line-height: 1.1;
        letter-spacing: -0.02em;
        margin-bottom: 0;
    }

    .hero-accent {
        color: #3B82F6;
    }

    .hero-sub {
        font-size: 1.1rem;
        color: #64748B;
        font-weight: 300;
        margin-top: 12px;
        max-width: 520px;
        line-height: 1.6;
    }

    .card {
        background: rgba(255,255,255,0.03);
        border: 1px solid rgba(255,255,255,0.07);
        border-radius: 12px;
        padding: 24px;
        height: 100%;
        transition: border-color 0.2s;
    }

    .card:hover {
        border-color: rgba(59, 130, 246, 0.4);
    }

    .card-icon {
        font-size: 1.8rem;
        margin-bottom: 12px;
    }

    .card-title {
        font-family: 'Space Mono', monospace;
        font-size: 0.95rem;
        font-weight: 700;
        color: #E2E8F0;
        margin-bottom: 8px;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }

    .card-desc {
        font-size: 0.85rem;
        color: #64748B;
        line-height: 1.5;
    }

    .stat-value {
        font-family: 'Space Mono', monospace;
        font-size: 1.8rem;
        font-weight: 700;
        color: #3B82F6;
    }

    .stat-label {
        font-size: 0.75rem;
        color: #64748B;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        margin-top: 4px;
    }

    .divider {
        border: none;
        border-top: 1px solid rgba(255,255,255,0.06);
        margin: 40px 0;
    }

    .badge {
        display: inline-block;
        padding: 3px 10px;
        border-radius: 20px;
        font-size: 0.7rem;
        font-weight: 600;
        letter-spacing: 0.05em;
        text-transform: uppercase;
    }

    .badge-blue  { background: rgba(59,130,246,0.15); color: #60A5FA; border: 1px solid rgba(59,130,246,0.3); }
    .badge-green { background: rgba(52,211,153,0.15); color: #34D399; border: 1px solid rgba(52,211,153,0.3); }
    .badge-amber { background: rgba(251,191,36,0.15); color: #FBBF24; border: 1px solid rgba(251,191,36,0.3); }
    .badge-red   { background: rgba(248,113,113,0.15); color: #F87171; border: 1px solid rgba(248,113,113,0.3); }

    [data-testid="stSidebar"] { display: none; }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Hero Section
# ---------------------------------------------------------------------------

st.markdown("<div style='padding: 60px 20px 20px 20px;'>", unsafe_allow_html=True)

col_text, col_space = st.columns([3, 1])
with col_text:
    st.markdown("""
        <div class="hero-title">
            Grid Trading<br>
            <span class="hero-accent">Framework</span>
        </div>
        <div class="hero-sub">
            Automatisierter Krypto-Handel mit Grid-Bot Strategie.
            Backtesting, Paper-Trading und Live-Handel auf Binance.
        </div>
    """, unsafe_allow_html=True)

st.markdown("<div style='margin-top: 16px; margin-bottom: 40px;'>", unsafe_allow_html=True)
st.markdown("""
    <span class="badge badge-blue">Bachelorarbeit OST</span>&nbsp;
    <span class="badge badge-green">Binance API</span>&nbsp;
    <span class="badge badge-amber">Paper Trading</span>&nbsp;
    <span class="badge badge-red">Live Trading</span>
""", unsafe_allow_html=True)
st.markdown("</div>", unsafe_allow_html=True)

st.markdown("<hr class='divider'>", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Navigation Cards
# ---------------------------------------------------------------------------

st.markdown("<div style='margin-bottom: 16px; color: #64748B; font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.1em;'>Module</div>", unsafe_allow_html=True)

col1, col2, col3, col4 = st.columns(4)

with col1:
    st.markdown("""
        <div class="card">
            <div class="card-icon">📊</div>
            <div class="card-title">Backtest</div>
            <div class="card-desc">
                Strategie auf historischen Daten testen.
                ROI, Sharpe, Calmar, Drawdown und mehr.
            </div>
        </div>
    """, unsafe_allow_html=True)
    st.page_link("pages/1_backtest.py", label="→ Backtest starten", use_container_width=True)

with col2:
    st.markdown("""
        <div class="card">
            <div class="card-icon">🔍</div>
            <div class="card-title">Coin Scanner</div>
            <div class="card-desc">
                Top-100 Coins automatisch auf Grid-Bot
                Eignung analysieren und ranken.
            </div>
        </div>
    """, unsafe_allow_html=True)
    st.page_link("pages/2_scanner.py", label="→ Scanner starten", use_container_width=True)

with col3:
    st.markdown("""
        <div class="card">
            <div class="card-icon">🧪</div>
            <div class="card-title">Paper Trading</div>
            <div class="card-desc">
                Live-Daten, simuliertes Kapital.
                Bot in Echtzeit testen ohne Risiko.
            </div>
        </div>
    """, unsafe_allow_html=True)
    st.page_link("pages/3_paper_trading.py", label="→ Paper Trading", use_container_width=True)

with col4:
    st.markdown("""
        <div class="card">
            <div class="card-icon">⚡</div>
            <div class="card-title">Live Trading</div>
            <div class="card-desc">
                Echter Handel auf Binance mit
                API-Key. Nur nach Paper Trading!
            </div>
        </div>
    """, unsafe_allow_html=True)
    st.page_link("pages/4_live.py", label="→ Live Trading", use_container_width=True)

st.markdown("<hr class='divider'>", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Stats Row
# ---------------------------------------------------------------------------

st.markdown("<div style='margin-bottom: 16px; color: #64748B; font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.1em;'>Framework</div>", unsafe_allow_html=True)

s1, s2, s3, s4, s5 = st.columns(5)
stats = [
    ("14", "Core Module"),
    ("2", "Broker Modi"),
    ("6", "Kennzahlen"),
    ("4", "Intervalle"),
    ("100+", "Coins"),
]
for col, (val, label) in zip([s1, s2, s3, s4, s5], stats):
    with col:
        st.markdown(f"""
            <div style="text-align:center; padding: 20px 0;">
                <div class="stat-value">{val}</div>
                <div class="stat-label">{label}</div>
            </div>
        """, unsafe_allow_html=True)

st.markdown("</div>", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------

st.markdown("""
    <div style="margin-top: 60px; padding: 20px 0; border-top: 1px solid rgba(255,255,255,0.06);
                color: #374151; font-size: 0.75rem; text-align: center;">
        Grid Trading Framework &nbsp;·&nbsp; Enes Eryilmaz &nbsp;·&nbsp;
        Bachelorarbeit OST 2025 &nbsp;·&nbsp;
        <span style="color: #1F2937;">Python · Streamlit · Binance API</span>
    </div>
""", unsafe_allow_html=True)