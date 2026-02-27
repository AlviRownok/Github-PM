"""
GAM Software PM — ISO 27001 Compliance & Project Management Platform
Branch-level software development intelligence, audit documentation,
and automated project monitoring.
"""

import os
import json
import base64
import datetime as dt
import io
from urllib.parse import urlparse
from collections import Counter, defaultdict

import requests
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from dotenv import load_dotenv
from jinja2 import Template
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm, cm
from reportlab.lib.colors import HexColor
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image as RLImage,
    PageBreak, KeepTogether,
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT

# ═══════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════

load_dotenv()

GITHUB_API = "https://api.github.com"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.join(BASE_DIR, "assets")
LOGO_PATH = os.path.join(ASSETS_DIR, "GAMspm.png")
STATE_FILE = os.path.join(BASE_DIR, ".pm_state.json")
TOKEN_FILE = os.path.join(BASE_DIR, "github_api.txt")

CACHE_TTL = 300  # seconds


def _resolve_token() -> str | None:
    """Load GitHub token from multiple sources (priority order):
    1. Streamlit Cloud Secrets  (st.secrets["GITHUB_TOKEN"])
    2. Environment variable     (GITHUB_TOKEN env var / .env file)
    3. github_api.txt file      (local fallback)
    """
    # 1) Streamlit Secrets
    try:
        tok = st.secrets.get("GITHUB_TOKEN")
        if tok and str(tok).strip():
            return str(tok).strip()
    except Exception:
        pass

    # 2) Environment variable (set by .env or system)
    tok = os.getenv("GITHUB_TOKEN")
    if tok and tok.strip():
        return tok.strip()

    # 3) Local file fallback
    try:
        if os.path.exists(TOKEN_FILE):
            with open(TOKEN_FILE, "r") as f:
                tok = f.read().strip()
                if tok:
                    return tok
    except Exception:
        pass

    return None


GITHUB_TOKEN = _resolve_token()

NAV_SECTIONS = [
    "📊 Command Center",
    "📦 Asset Inventory",
    "📜 Change Ledger",
    "🔐 Access Registry",
    "🚨 Incident Log",
    "🔀 Pull Requests",
    "🧠 Author Intelligence",
    "📅 Project Timeline",
    "🛡️ Compliance Hub",
]

ACTIVITY_TAGS = [
    "Architecture", "Backend", "Frontend", "Database",
    "DevOps", "Security", "Testing", "Documentation",
    "Bug Fix", "Feature", "Refactor", "Config",
]

FILE_CLASS_MAP = {
    "Source Code": {".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".go", ".rs",
                    ".c", ".cpp", ".h", ".cs", ".rb", ".php", ".swift", ".kt",
                    ".scala", ".r", ".m", ".vue", ".svelte"},
    "Configuration": {".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf",
                      ".env", ".properties", ".xml"},
    "Documentation": {".md", ".rst", ".txt", ".doc", ".pdf", ".adoc"},
    "Data": {".csv", ".sql", ".db", ".sqlite", ".parquet", ".jsonl"},
    "Web Assets": {".html", ".css", ".scss", ".less", ".svg", ".png", ".jpg",
                   ".jpeg", ".gif", ".ico", ".woff", ".woff2", ".ttf"},
    "Testing": set(),
    "Dependencies": set(),
    "Build/CI": set(),
}
FILE_NAME_PATTERNS = {
    "Testing": ["test_", "_test.", ".test.", "spec.", ".spec.", "conftest"],
    "Dependencies": ["requirements", "package.json", "pipfile", "cargo.toml",
                     "go.mod", "pom.xml", "build.gradle", "gemfile", "poetry.lock",
                     "yarn.lock", "package-lock"],
    "Build/CI": ["dockerfile", "makefile", ".github", "jenkinsfile",
                 ".gitlab-ci", ".circleci", "tox.ini", "setup.py", "setup.cfg",
                 "pyproject.toml"],
}

# ═══════════════════════════════════════════════════════════════
# Styles
# ═══════════════════════════════════════════════════════════════

CUSTOM_CSS = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');

    /* ─── Global / Light Background ─── */
    .stApp { background-color: #ffffff !important; font-family: 'Inter', sans-serif; }
    .block-container {
        padding-top: 1.5rem !important;
        padding-left: 2rem !important;
        padding-right: 2rem !important;
        max-width: 100% !important;
    }
    header[data-testid="stHeader"] { background: rgba(255,255,255,0.85) !important; backdrop-filter: blur(12px); }

    /* ─── Animations ─── */
    @keyframes fadeInUp {
        from { opacity:0; transform:translateY(18px); }
        to   { opacity:1; transform:translateY(0); }
    }
    @keyframes shimmer {
        0%   { background-position: -200% 0; }
        100% { background-position: 200% 0; }
    }
    @keyframes gradientShift {
        0%, 100% { background-position: 0% 50%; }
        50%      { background-position: 100% 50%; }
    }
    @keyframes pulse { 0%,100%{transform:scale(1)} 50%{transform:scale(1.04)} }

    /* ─── Sidebar (Deep Indigo-Purple) ─── */
    section[data-testid="stSidebar"] {
        background: linear-gradient(195deg, #1a1040 0%, #0f0a2e 60%, #120e33 100%) !important;
        border-right: 1px solid rgba(176,160,240,0.12);
    }
    section[data-testid="stSidebar"] * { color: #d4d0f8 !important; }
    section[data-testid="stSidebar"] .stTextInput > div > div {
        background: rgba(255,255,255,0.07) !important;
        border: 1px solid rgba(176,160,240,0.2) !important;
        border-radius: 10px !important; color: #fff !important;
    }
    section[data-testid="stSidebar"] .stTextInput input { color: #fff !important; }
    section[data-testid="stSidebar"] .stRadio label { color: #c8c2f0 !important; }
    section[data-testid="stSidebar"] .stRadio label:hover { color: #fff !important; }
    section[data-testid="stSidebar"] button[kind="primary"] {
        background: linear-gradient(135deg, #7c5cfc, #b0a0f0) !important;
        color: #fff !important; border: none !important;
        border-radius: 10px !important; font-weight: 600 !important;
        transition: all 0.3s ease;
    }
    section[data-testid="stSidebar"] button[kind="primary"]:hover {
        box-shadow: 0 4px 20px rgba(124,92,252,0.45) !important;
        transform: translateY(-1px);
    }
    section[data-testid="stSidebar"] button[kind="secondary"] {
        background: rgba(255,255,255,0.08) !important;
        color: #c8c2f0 !important; border: 1px solid rgba(176,160,240,0.25) !important;
        border-radius: 10px !important;
    }
    section[data-testid="stSidebar"] hr { border-color: rgba(176,160,240,0.15) !important; }

    /* ─── Main Content Text ─── */
    .stApp h1, .stApp h2, .stApp h3, .stApp h4 { color: #1a1040 !important; font-family: 'Inter', sans-serif; }
    .stApp p, .stApp li, .stApp span { color: #374151; }

    /* ─── Metric Cards ─── */
    .metric-row {
        display: flex; gap: 14px; flex-wrap: wrap; margin-bottom: 20px;
    }
    .mc {
        background: #ffffff;
        border: 1px solid #e4e0f0; border-radius: 14px;
        padding: 18px 22px; flex: 1; min-width: 170px;
        box-shadow: 0 2px 12px rgba(124,92,252,0.06);
        transition: all 0.3s cubic-bezier(.25,.8,.25,1);
        animation: fadeInUp 0.5s ease both;
    }
    .mc:hover {
        transform: translateY(-3px);
        box-shadow: 0 8px 28px rgba(124,92,252,0.12);
        border-color: #b0a0f0;
    }
    .mc .lb { font-size:.72rem; text-transform:uppercase; letter-spacing:.06em; color:#7c5cfc; margin-bottom:4px; font-weight:600; }
    .mc .vl { font-size:1.4rem; font-weight:700; color:#1a1040;
              background: linear-gradient(135deg, #1a1040, #7c5cfc);
              -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
    .mc .dl { font-size:.78rem; margin-top:3px; color:#6b7280; }

    /* ─── Section Header ─── */
    .sh {
        display:flex; align-items:center; gap:12px;
        margin-bottom:22px; padding-bottom:14px;
        border-bottom: 2px solid transparent;
        border-image: linear-gradient(90deg, #7c5cfc, #b0a0f0, #70d0f0) 1;
    }
    .sh .ti { font-size:1.5rem; font-weight:700; color:#1a1040 !important; }
    .sh .ib {
        background: linear-gradient(135deg, rgba(124,92,252,0.12), rgba(176,160,240,0.12));
        color:#7c5cfc;
        padding:4px 10px; border-radius:8px;
        font-size:.72rem; font-weight:600; letter-spacing:.03em;
        border: 1px solid rgba(124,92,252,0.15);
    }
    .sh .su { font-size:.83rem; color:#6b7280; margin-top:3px; }

    /* ─── Health Rings ─── */
    .hr { width:120px; height:120px; border-radius:50%;
          display:flex; align-items:center; justify-content:center;
          font-size:2rem; font-weight:800; margin:0 auto;
          background: #ffffff;
          box-shadow: 0 4px 20px rgba(0,0,0,0.06);
          transition: all 0.3s ease;
    }
    .hr:hover { animation: pulse 0.6s ease; }
    .hr-g { border:4px solid #10b981; color:#10b981; }
    .hr-f { border:4px solid #f59e0b; color:#f59e0b; }
    .hr-p { border:4px solid #ef4444; color:#ef4444; }

    /* ─── Streamlit Metric Overrides ─── */
    div[data-testid="stMetric"] {
        background: #ffffff;
        border-radius:14px; padding:14px 18px;
        border:1px solid #e4e0f0;
        box-shadow: 0 2px 12px rgba(124,92,252,0.06);
        transition: all 0.3s ease;
    }
    div[data-testid="stMetric"]:hover {
        box-shadow: 0 6px 24px rgba(124,92,252,0.1);
        border-color: #b0a0f0;
    }
    div[data-testid="stMetricLabel"] { color:#7c5cfc !important; font-size:.76rem; text-transform:uppercase; letter-spacing:.04em; font-weight:600; }
    div[data-testid="stMetricValue"] { color:#1a1040 !important; font-size:1.2rem; }

    /* ─── Status Badges ─── */
    .sb { display:inline-block; padding:3px 10px; border-radius:20px; font-size:.73rem; font-weight:600; }
    .sb-g { background:rgba(16,185,129,0.1); color:#059669; }
    .sb-r { background:rgba(239,68,68,0.1); color:#dc2626; }
    .sb-y { background:rgba(245,158,11,0.1); color:#d97706; }
    .sb-b { background:rgba(124,92,252,0.1); color:#7c5cfc; }

    /* ─── Timestamp Bar ─── */
    .ts-bar { text-align:right; font-size:.73rem; color:#9ca3af; padding:4px 0 14px; }
    .ts-bar a { color:#7c5cfc !important; text-decoration:none; font-weight:500; }
    .ts-bar a:hover { color:#5b3fd4 !important; }

    /* ─── Sidebar Brand ─── */
    .sidebar-brand {
        display:flex; align-items:center; gap:12px; padding:10px 0 18px;
        border-bottom:1px solid rgba(176,160,240,0.15); margin-bottom:16px;
    }
    .sidebar-brand img { height:42px; border-radius:10px; filter: drop-shadow(0 2px 8px rgba(124,92,252,0.3)); }
    .sidebar-brand .n { font-size:1.15rem; font-weight:700; color:#fff !important;
                        background: linear-gradient(135deg, #b0a0f0, #70d0f0);
                        -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
    .sidebar-brand .t { font-size:.7rem; color:#8b80c8 !important; font-weight:400; }

    /* ─── Charts & DataFrames ─── */
    .stPlotlyChart { border:1px solid #e4e0f0; border-radius:14px; overflow:hidden;
                     box-shadow: 0 2px 10px rgba(0,0,0,0.03); }
    /* Plotly modebar icons — dark on light background */
    .stPlotlyChart .modebar-btn path { fill: #6b7280 !important; }
    .stPlotlyChart .modebar-btn:hover path { fill: #7c5cfc !important; }
    .stPlotlyChart .modebar-group { background: rgba(250,249,255,0.85) !important; border-radius: 6px; }
    .stPlotlyChart .modebar { right: 8px !important; top: 4px !important; }
    div[data-testid="stDataFrame"] { border:1px solid #e4e0f0; border-radius:10px; overflow:hidden; }

    /* ─── Buttons ─── */
    .stApp button[kind="primary"] {
        background: linear-gradient(135deg, #7c5cfc, #b0a0f0) !important;
        color: #fff !important; border: none !important;
        border-radius: 10px; font-weight: 600;
        transition: all 0.3s ease;
    }
    .stApp button[kind="primary"]:hover {
        box-shadow: 0 4px 18px rgba(124,92,252,0.35);
        transform: translateY(-1px);
    }
    .stApp button[kind="secondary"],
    .stApp button:not([kind]) {
        background: #faf9ff !important;
        color: #4a3d8f !important; border: 1px solid #d4cef0 !important;
        border-radius: 10px; font-weight: 500;
        transition: all 0.3s ease;
    }
    .stApp button[kind="secondary"]:hover,
    .stApp button:not([kind]):hover {
        background: #f0eeff !important;
        border-color: #b0a0f0 !important;
        color: #7c5cfc !important;
        box-shadow: 0 2px 12px rgba(124,92,252,0.12);
    }
    .stDownloadButton button {
        background: linear-gradient(135deg, #7c5cfc, #9580f0) !important;
        color: #fff !important; border: none !important;
        border-radius: 10px; font-weight: 600;
    }
    .stDownloadButton button:hover {
        box-shadow: 0 4px 18px rgba(124,92,252,0.35);
        transform: translateY(-1px);
    }

    /* ─── Select Boxes & Inputs ─── */
    .stSelectbox > div > div,
    .stMultiSelect > div > div,
    .stTextInput > div > div,
    .stNumberInput > div > div,
    .stDateInput > div > div {
        border-color: #d4cef0 !important;
        border-radius: 10px !important;
        color: #374151 !important;
    }
    .stSelectbox label, .stMultiSelect label, .stTextInput label,
    .stNumberInput label, .stDateInput label, .stTextArea label {
        color: #4a3d8f !important; font-weight: 500 !important;
    }

    /* ─── Dataframe / Table / GlideDataEditor Overrides ─── */
    div[data-testid="stDataFrame"] {
        --gdg-bg-cell: #ffffff;
        --gdg-bg-cell-medium: #faf9ff;
        --gdg-bg-header: #f0eeff;
        --gdg-bg-header-has-focus: #ede9fe;
        --gdg-bg-header-hovered: #ede9fe;
        --gdg-text-dark: #1f2937;
        --gdg-text-medium: #4b5563;
        --gdg-text-light: #6b7280;
        --gdg-text-header: #1a1040;
        --gdg-border-color: #e4e0f0;
        --gdg-accent-color: #7c5cfc;
        --gdg-accent-light: rgba(124,92,252,0.15);
        --gdg-bg-bubble: #f5f3ff;
        --gdg-bg-bubble-selected: #ede9fe;
        --gdg-link-color: #7c5cfc;
    }

    /* ─── Expanders & Tabs ─── */
    .streamlit-expanderHeader { color: #1a1040 !important; font-weight: 600; }
    .stTabs [data-baseweb="tab"] { color: #6b7280; font-weight: 500; }
    .stTabs [aria-selected="true"] { color: #7c5cfc !important; border-bottom-color: #7c5cfc !important; }

    /* ─── Welcome Hero Card ─── */
    .hero-welcome {
        text-align:center; padding:60px 20px;
        background: linear-gradient(135deg, rgba(124,92,252,0.04), rgba(176,160,240,0.06), rgba(112,208,240,0.04));
        border-radius: 24px; border: 1px solid #e4e0f0;
        animation: fadeInUp 0.6s ease both;
    }
    .hero-welcome .hw-icon { font-size:3.5rem; margin-bottom:16px; }
    .hero-welcome .hw-title {
        font-size:2rem; font-weight:800; margin-bottom:8px;
        background: linear-gradient(135deg, #1a1040, #7c5cfc, #2070e0);
        -webkit-background-clip: text; -webkit-text-fill-color: transparent;
        background-size: 200% auto; animation: gradientShift 4s ease infinite;
    }
    .hero-welcome .hw-sub { font-size:1.05rem; color:#6b7280; max-width:640px; margin:0 auto 24px; line-height:1.6; }
    .hero-welcome .hw-tags { font-size:.85rem; color:#9ca3af; }
    .hero-welcome .hw-tags b { color: #7c5cfc; font-weight: 600; }
</style>
"""

# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════

def _inline_logo() -> str:
    try:
        with open(LOGO_PATH, "rb") as f:
            return base64.b64encode(f.read()).decode()
    except Exception:
        return ""


def _parse_date(val):
    if not val:
        return None
    try:
        return dt.datetime.fromisoformat(val.replace("Z", "+00:00"))
    except Exception:
        return None


def _fmt(d, f="%Y-%m-%d %H:%M"):
    return d.strftime(f) if d else "\u2014"


def _fnum(n):
    if n is None:
        return "\u2014"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def _parse_url(url: str):
    if not url:
        raise ValueError("Empty URL")
    parsed = urlparse(url.strip())
    if "github.com" not in (parsed.netloc or ""):
        raise ValueError("Not a GitHub URL")
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) < 2:
        raise ValueError("Cannot extract owner/repo from URL")
    owner, repo = parts[0], parts[1]
    branch = None
    if len(parts) >= 4 and parts[2] == "tree":
        branch = "/".join(parts[3:])
    return owner, repo, branch


def _classify_file(path: str) -> str:
    name = path.lower().split("/")[-1]
    ext = "." + name.rsplit(".", 1)[-1] if "." in name else ""
    for cls, pats in FILE_NAME_PATTERNS.items():
        for pat in pats:
            if pat in name:
                return cls
    for cls, exts in FILE_CLASS_MAP.items():
        if ext in exts:
            return cls
    return "Other"


def _plotly_layout(height=260, **kw):
    base = dict(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter, sans-serif", color="#1f2937", size=12),
        xaxis=dict(gridcolor="#f0eeff", linecolor="#e4e0f0",
                   title_font=dict(color="#1a1040", size=12),
                   tickfont=dict(color="#374151", size=11)),
        yaxis=dict(gridcolor="#f0eeff", linecolor="#e4e0f0",
                   title_font=dict(color="#1a1040", size=12),
                   tickfont=dict(color="#374151", size=11)),
        legend=dict(font=dict(color="#1f2937", size=11),
                    bgcolor="rgba(255,255,255,0.8)", bordercolor="#e4e0f0", borderwidth=1),
        margin=dict(l=50, r=16, t=28, b=44), height=height,
        colorway=["#7c5cfc", "#2070e0", "#c070e0", "#f0a080", "#70d0f0",
                  "#10b981", "#f59e0b", "#ef4444", "#b0a0f0"],
    )
    base.update(kw)
    return base


# ═══════════════════════════════════════════════════════════════
# GitHub API Layer
# ═══════════════════════════════════════════════════════════════

def _gh_headers():
    h = {"Accept": "application/vnd.github+json", "User-Agent": "github-pm-iso27001"}
    if GITHUB_TOKEN:
        h["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    return h


def _gh_get(path: str, params=None):
    resp = requests.get(f"{GITHUB_API}{path}", headers=_gh_headers(),
                        params=params or {}, timeout=20)
    if resp.status_code in (202, 204, 404):
        return None
    if resp.status_code >= 400:
        try:
            msg = resp.json().get("message", f"HTTP {resp.status_code}")
        except Exception:
            msg = f"HTTP {resp.status_code}"
        raise RuntimeError(f"GitHub API {resp.status_code}: {msg}")
    return resp.json()


def _gh_paginated(path: str, params=None, max_pages=10):
    params = dict(params or {})
    params.setdefault("per_page", 100)
    out = []
    for pg in range(1, max_pages + 1):
        params["page"] = pg
        data = _gh_get(path, params)
        if not isinstance(data, list) or not data:
            break
        out.extend(data)
        if len(data) < params["per_page"]:
            break
    return out


# ═══════════════════════════════════════════════════════════════
# Cached Data Fetchers
# ═══════════════════════════════════════════════════════════════

@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def _fetch_repo(owner, repo):
    return _gh_get(f"/repos/{owner}/{repo}") or {}

@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def _fetch_branches(owner, repo):
    return _gh_paginated(f"/repos/{owner}/{repo}/branches", max_pages=5)

@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def _fetch_languages(owner, repo):
    return _gh_get(f"/repos/{owner}/{repo}/languages") or {}

@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def _fetch_tree(owner, repo, branch):
    return _gh_get(f"/repos/{owner}/{repo}/git/trees/{branch}", {"recursive": "1"}) or {}

@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def _fetch_commits(owner, repo, branch, max_pages=10):
    return _gh_paginated(f"/repos/{owner}/{repo}/commits", {"sha": branch}, max_pages=max_pages)

@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def _fetch_compare(owner, repo, base, head):
    """Use the compare API to get commits unique to head vs base."""
    return _gh_get(f"/repos/{owner}/{repo}/compare/{base}...{head}") or {}

@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def _fetch_default_shas(owner, repo, default_branch):
    cs = _gh_paginated(f"/repos/{owner}/{repo}/commits", {"sha": default_branch}, max_pages=10)
    return {c.get("sha") for c in cs if c.get("sha")}

@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def _fetch_issues(owner, repo):
    return _gh_paginated(f"/repos/{owner}/{repo}/issues", {"state": "all"}, max_pages=5)

@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def _fetch_pulls(owner, repo):
    return _gh_paginated(f"/repos/{owner}/{repo}/pulls", {"state": "all"}, max_pages=5)

@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def _fetch_contributors(owner, repo):
    return _gh_paginated(f"/repos/{owner}/{repo}/contributors", max_pages=3)

@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def _fetch_activity(owner, repo):
    return _gh_get(f"/repos/{owner}/{repo}/stats/commit_activity") or []

@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_commit_detail(owner, repo, sha):
    return _gh_get(f"/repos/{owner}/{repo}/commits/{sha}") or {}

@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def _fetch_milestones(owner, repo):
    return _gh_paginated(f"/repos/{owner}/{repo}/milestones", {"state": "all"}, max_pages=3)


# ═══════════════════════════════════════════════════════════════
# Data Collection & Processing
# ═══════════════════════════════════════════════════════════════

def collect_branch_data(owner, repo, branch):
    """Master data collection for a single branch."""
    repo_info = _fetch_repo(owner, repo)
    if not repo_info or not repo_info.get("full_name"):
        raise RuntimeError(
            f"Repository '{owner}/{repo}' not found or not accessible. "
            "Check the URL and ensure your token has access to this repository."
        )
    default_branch = repo_info.get("default_branch", "main")

    # Branches
    branches_raw = _fetch_branches(owner, repo)
    branch_names = [b.get("name") for b in branches_raw if b.get("name")]

    # Validate the requested branch exists
    if branch_names and branch not in branch_names:
        raise RuntimeError(
            f"Branch '{branch}' not found in {owner}/{repo}. "
            f"Available branches: {', '.join(branch_names[:15])}"
        )

    # Commits — use compare API for accurate branch-only commits
    all_commits = _fetch_commits(owner, repo, branch)
    if branch != default_branch:
        try:
            compare = _fetch_compare(owner, repo, default_branch, branch)
            compare_shas = {c.get("sha") for c in compare.get("commits", []) if c.get("sha")}
            ahead_by = compare.get("ahead_by", 0)
            if compare_shas and len(compare_shas) >= ahead_by:
                # Compare API gave us the full set of unique commits
                raw_commits = [c for c in all_commits if c.get("sha") in compare_shas]
            else:
                # Compare API truncated (>250 commits); fall back to SHA exclusion
                default_shas = _fetch_default_shas(owner, repo, default_branch)
                raw_commits = [c for c in all_commits if c.get("sha") not in default_shas]
        except Exception:
            default_shas = _fetch_default_shas(owner, repo, default_branch)
            raw_commits = [c for c in all_commits if c.get("sha") not in default_shas]
    else:
        raw_commits = all_commits

    commits = []
    author_stats = defaultdict(lambda: {
        "commits": 0, "first": None, "last": None,
        "login": None, "name": None, "avatar": None,
    })

    for c in raw_commits:
        sha = c.get("sha", "")
        cd = c.get("commit", {}) or {}
        ai = cd.get("author", {}) or {}
        ga = c.get("author") or {}

        login = ga.get("login")
        name = ai.get("name") or "Unknown"
        aid = login or name
        date = _parse_date(ai.get("date"))
        msg = (cd.get("message") or "").splitlines()[0]

        commits.append({
            "sha": sha[:7], "sha_full": sha, "message": msg,
            "full_message": cd.get("message") or "",
            "author_id": aid, "author_name": name,
            "author_login": login, "author_avatar": ga.get("avatar_url"),
            "date": date, "date_str": _fmt(date),
            "date_day": date.strftime("%Y-%m-%d") if date else "",
        })

        s = author_stats[aid]
        s["commits"] += 1
        s["login"] = login or s["login"]
        s["name"] = name
        s["avatar"] = ga.get("avatar_url") or s["avatar"]
        if date:
            if s["first"] is None or date < s["first"]:
                s["first"] = date
            if s["last"] is None or date > s["last"]:
                s["last"] = date

    # Issues
    issues_raw = _fetch_issues(owner, repo)
    issues = []
    for i in issues_raw:
        if "pull_request" in i:
            continue
        cr = _parse_date(i.get("created_at"))
        cl = _parse_date(i.get("closed_at"))
        up = _parse_date(i.get("updated_at"))
        labels = [l.get("name") for l in (i.get("labels") or []) if l.get("name")]
        rd = (cl - cr).days if cr and cl else None
        issues.append({
            "number": i.get("number"), "title": i.get("title") or "",
            "state": i.get("state", "open"),
            "author": (i.get("user") or {}).get("login"),
            "assignee": (i.get("assignee") or {}).get("login"),
            "labels": labels, "labels_str": ", ".join(labels),
            "created": cr, "created_str": _fmt(cr),
            "closed": cl, "closed_str": _fmt(cl) if cl else "\u2014",
            "updated": up, "updated_str": _fmt(up),
            "resolution_days": rd, "url": i.get("html_url"),
        })

    # Pull Requests
    pulls_raw = _fetch_pulls(owner, repo)
    pulls = []
    for p in pulls_raw:
        cr = _parse_date(p.get("created_at"))
        cl = _parse_date(p.get("closed_at"))
        mr = _parse_date(p.get("merged_at"))
        hb = (p.get("head") or {}).get("ref")
        bb = (p.get("base") or {}).get("ref")
        md = (mr - cr).days if cr and mr else None
        pulls.append({
            "number": p.get("number"), "title": p.get("title") or "",
            "state": "merged" if mr else p.get("state", "open"),
            "author": (p.get("user") or {}).get("login"),
            "head": hb, "base": bb,
            "created": cr, "created_str": _fmt(cr),
            "closed_str": _fmt(cl) if cl else "\u2014",
            "merged_str": _fmt(mr) if mr else "\u2014",
            "merge_days": md, "url": p.get("html_url"),
            "is_branch": hb == branch or bb == branch,
        })

    branch_pulls = [p for p in pulls if p["is_branch"]]

    # Languages & Tree
    languages = _fetch_languages(owner, repo)
    tree_data = _fetch_tree(owner, repo, branch)
    tree_items = tree_data.get("tree", []) if isinstance(tree_data, dict) else []
    files = []
    for item in tree_items:
        if item.get("type") == "blob":
            path = item.get("path", "")
            files.append({"path": path, "size": item.get("size", 0),
                          "classification": _classify_file(path)})

    # Contributors
    contributors_raw = _fetch_contributors(owner, repo)
    contributors = [
        {"login": c.get("login"), "contributions": c.get("contributions"),
         "avatar": c.get("avatar_url"), "url": c.get("html_url"),
         "type": c.get("type")}
        for c in (contributors_raw or [])
    ]

    # Weekly activity
    activity = _fetch_activity(owner, repo)
    weekly = []
    if isinstance(activity, list):
        for item in activity[-16:]:
            ts = item.get("week")
            if ts:
                weekly.append({
                    "week": dt.datetime.fromtimestamp(ts, dt.UTC).strftime("%Y-%m-%d"),
                    "total": item.get("total", 0),
                })

    # Milestones
    milestones_raw = _fetch_milestones(owner, repo)
    milestones = []
    for m in (milestones_raw or []):
        due = _parse_date(m.get("due_on"))
        milestones.append({
            "title": m.get("title"), "state": m.get("state"),
            "open_issues": m.get("open_issues", 0),
            "closed_issues": m.get("closed_issues", 0),
            "due": due, "due_str": _fmt(due, "%Y-%m-%d") if due else "No due date",
            "description": m.get("description") or "",
        })

    return {
        "owner": owner, "repo": repo, "branch": branch,
        "default_branch": default_branch, "branch_names": branch_names,
        "repo_info": repo_info,
        "repo_url": f"https://github.com/{owner}/{repo}/tree/{branch}",
        "commits": commits, "author_stats": dict(author_stats),
        "issues": issues, "pulls": pulls, "branch_pulls": branch_pulls,
        "languages": languages, "files": files,
        "contributors": contributors, "weekly_activity": weekly,
        "milestones": milestones,
        "pushed_at": _parse_date(repo_info.get("pushed_at")),
        "created_at": _parse_date(repo_info.get("created_at")),
        "fetched_at": dt.datetime.now(dt.UTC),
    }


def _health_score(data):
    score = 50
    commits = data["commits"]
    issues = data["issues"]
    pulls = data["branch_pulls"]

    if commits:
        dated = [c for c in commits if c["date"]]
        if dated:
            latest = max(c["date"] for c in dated)
            days = (dt.datetime.now(dt.UTC) - latest).days
            if days <= 7:
                score += 20
            elif days <= 30:
                score += 12
            elif days <= 90:
                score += 5
            else:
                score -= 10
    else:
        score -= 15

    if issues:
        closed = sum(1 for i in issues if i["state"] == "closed")
        score += int(closed / len(issues) * 15)

    if pulls:
        merged = sum(1 for p in pulls if p["state"] == "merged")
        score += int(merged / len(pulls) * 15)

    n = len(data["author_stats"])
    if n >= 3:
        score += 10
    elif n >= 2:
        score += 5

    return min(100, max(0, score))


# ═══════════════════════════════════════════════════════════════
# State Persistence (PM)
# ═══════════════════════════════════════════════════════════════

def _rd_state() -> dict:
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f) or {}
    except Exception:
        pass
    return {}


def _wr_state(d: dict):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2, default=str)
    except Exception:
        pass


def _load_pm(key):
    return _rd_state().get(key, {})


def _save_pm(key, state):
    s = _rd_state()
    s[key] = state
    _wr_state(s)


def _del_pm(key):
    s = _rd_state()
    s.pop(key, None)
    _wr_state(s)


def _rk(o, r, b):
    return f"{o}/{r}@{b}"


# ═══════════════════════════════════════════════════════════════
# UI Helpers
# ═══════════════════════════════════════════════════════════════

def _metric_row(items):
    cards = ""
    for item in items:
        lb, vl = item[0], item[1]
        dl = item[2] if len(item) > 2 and item[2] else None
        dh = f'<div class="dl">{dl}</div>' if dl else ""
        cards += f'<div class="mc"><div class="lb">{lb}</div><div class="vl">{vl}</div>{dh}</div>'
    st.markdown(f'<div class="metric-row">{cards}</div>', unsafe_allow_html=True)


def _section_hdr(title, subtitle="", iso=None):
    ih = f'<span class="ib">ISO 27001 {iso}</span>' if iso else ""
    sh = f'<div class="su">{subtitle}</div>' if subtitle else ""
    st.markdown(
        f'<div class="sh"><div><div class="ti">{title} {ih}</div>{sh}</div></div>',
        unsafe_allow_html=True,
    )


# ═══════════════════════════════════════════════════════════════
# SECTION: Command Center
# ═══════════════════════════════════════════════════════════════

def page_command_center(D):
    _section_hdr("Command Center", "Real-time branch health and activity overview")

    ri = D["repo_info"]
    commits = D["commits"]
    issues = D["issues"]
    bpulls = D["branch_pulls"]
    hs = _health_score(D)

    hcls = "hr-g" if hs >= 70 else ("hr-f" if hs >= 40 else "hr-p")
    hlbl = "Healthy" if hs >= 70 else ("Fair" if hs >= 40 else "Needs Attention")

    c1, c2 = st.columns([1, 3])
    with c1:
        st.markdown(f'''
        <div style="text-align:center;padding:20px;">
            <div class="hr {hcls}">{hs}</div>
            <div style="margin-top:8px;color:#6b7280;font-size:.83rem;">Branch Health</div>
            <div style="font-weight:600;color:#1a1040;">{hlbl}</div>
        </div>''', unsafe_allow_html=True)

    with c2:
        oi = sum(1 for i in issues if i["state"] == "open")
        op = sum(1 for p in bpulls if p["state"] == "open")
        _metric_row([
            ("Commits on Branch", str(len(commits))),
            ("Contributors", str(len(D["author_stats"]))),
            ("Open Issues", str(oi), f"{len(issues)} total"),
            ("Branch PRs", str(len(bpulls)), f"{op} open"),
            ("Files Tracked", _fnum(len(D["files"]))),
        ])

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Repository", ri.get("full_name", ""))
    c2.metric("Active Branch", D["branch"])
    c3.metric("Default Branch", D["default_branch"])
    c4.metric("Primary Language", ri.get("language") or "\u2014")

    c5, c6, c7, c8 = st.columns(4)
    c5.metric("Stars", ri.get("stargazers_count", 0))
    c6.metric("Forks", ri.get("forks_count", 0))
    c7.metric("Created", _fmt(D["created_at"], "%Y-%m-%d"))
    c8.metric("Last Push", _fmt(D["pushed_at"], "%Y-%m-%d"))

    st.markdown("")
    st.markdown("#### Weekly Commit Activity (Repository Level)")
    if D["weekly_activity"]:
        df = pd.DataFrame(D["weekly_activity"])
        fig = px.area(df, x="week", y="total",
                      labels={"week": "Week", "total": "Commits"},
                      color_discrete_sequence=["#7c5cfc"])
        fig.update_layout(**_plotly_layout(250))
        st.plotly_chart(fig, width='stretch')
    else:
        st.caption("Weekly activity data not yet available from GitHub.")

    st.markdown("#### Recent Commits on Branch")
    if commits[:25]:
        df = pd.DataFrame(commits[:25])[["sha", "message", "author_id", "date_str"]]
        df.columns = ["SHA", "Message", "Author", "Date"]
        st.dataframe(df, width='stretch', hide_index=True)
    else:
        st.caption("No branch-specific commits found.")


# ═══════════════════════════════════════════════════════════════
# SECTION: Asset Inventory
# ═══════════════════════════════════════════════════════════════

def page_asset_inventory(D):
    _section_hdr("Asset Inventory",
                 "Complete information asset register for the branch", iso="A.8")

    files = D["files"]
    languages = D["languages"]

    if not files:
        st.info("No file tree data available for this branch.")
        return

    total_size = sum(f["size"] for f in files)
    clsf = Counter(f["classification"] for f in files)
    exts = Counter(
        "." + f["path"].rsplit(".", 1)[-1] if "." in f["path"] else "(none)"
        for f in files
    )
    dirs = set()
    for f in files:
        parts = f["path"].split("/")
        for i in range(1, len(parts)):
            dirs.add("/".join(parts[:i]))

    sz = f"{total_size / 1024:.0f} KB" if total_size < 1_048_576 else f"{total_size / 1_048_576:.1f} MB"
    _metric_row([
        ("Total Files", str(len(files))),
        ("Directories", str(len(dirs))),
        ("Total Size", sz),
        ("File Types", str(len(exts))),
    ])

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("#### Asset Classification")
        df_c = pd.DataFrame([
            {"Classification": k, "Count": v, "Pct": f"{v / len(files) * 100:.1f}%"}
            for k, v in sorted(clsf.items(), key=lambda x: -x[1])
        ])
        st.dataframe(df_c, width='stretch', hide_index=True)
        if len(df_c) > 1:
            fig = px.pie(df_c, values="Count", names="Classification",
                         color_discrete_sequence=px.colors.qualitative.Set3)
            fig.update_layout(**_plotly_layout(280))
            st.plotly_chart(fig, width='stretch')

    with col2:
        st.markdown("#### Language Distribution")
        if languages:
            tb = sum(languages.values()) or 1
            df_l = pd.DataFrame([
                {"Language": k, "Bytes": v, "Share": f"{v / tb * 100:.1f}%"}
                for k, v in sorted(languages.items(), key=lambda x: -x[1])
            ])
            st.dataframe(df_l, width='stretch', hide_index=True)
            fig = px.pie(df_l, values="Bytes", names="Language",
                         color_discrete_sequence=px.colors.qualitative.Pastel)
            fig.update_layout(**_plotly_layout(280))
            st.plotly_chart(fig, width='stretch')
        else:
            st.caption("No language data available.")

    st.markdown("#### File Extension Breakdown")
    top_e = exts.most_common(15)
    if top_e:
        df_e = pd.DataFrame(top_e, columns=["Extension", "Count"])
        fig = px.bar(df_e, x="Extension", y="Count", color_discrete_sequence=["#2070e0"])
        fig.update_layout(**_plotly_layout(240))
        st.plotly_chart(fig, width='stretch')

    st.markdown("#### Complete File Inventory")
    df_f = pd.DataFrame(files)
    df_f["Size"] = df_f["size"].apply(lambda s: f"{s / 1024:.1f} KB" if s >= 1024 else f"{s} B")
    df_f = df_f[["path", "classification", "Size"]].rename(columns={
        "path": "File Path", "classification": "Classification"})
    st.dataframe(df_f, width='stretch', hide_index=True, height=420)


# ═══════════════════════════════════════════════════════════════
# SECTION: Change Ledger
# ═══════════════════════════════════════════════════════════════

def page_change_ledger(D):
    _section_hdr("Change Ledger",
                 "Complete audit trail of all code changes on the branch",
                 iso="A.12 / A.14")

    commits = D["commits"]
    if not commits:
        st.info("No commits found on this branch.")
        return

    dated = [c for c in commits if c["date"]]
    first = min(dated, key=lambda c: c["date"]) if dated else None
    last = max(dated, key=lambda c: c["date"]) if dated else None
    day_counts = Counter(c["date_day"] for c in commits if c["date_day"])
    busiest = day_counts.most_common(1)[0] if day_counts else ("\u2014", 0)

    _metric_row([
        ("Total Changes", str(len(commits))),
        ("Contributors", str(len(set(c["author_id"] for c in commits)))),
        ("First Change", first["date_str"] if first else "\u2014"),
        ("Latest Change", last["date_str"] if last else "\u2014"),
        ("Busiest Day", f"{busiest[0]} ({busiest[1]})" if busiest[0] != "\u2014" else "\u2014"),
    ])

    st.markdown("#### Change Frequency")
    if day_counts:
        df = pd.DataFrame(sorted(day_counts.items()), columns=["Date", "Changes"])
        fig = px.bar(df, x="Date", y="Changes", color_discrete_sequence=["#7c5cfc"])
        fig.update_layout(**_plotly_layout(250))
        st.plotly_chart(fig, width='stretch')

    st.markdown("#### Changes by Author")
    ac = Counter(c["author_id"] for c in commits)
    if ac:
        df = pd.DataFrame(ac.most_common(), columns=["Author", "Commits"])
        fig = px.bar(df, x="Author", y="Commits", color_discrete_sequence=["#2070e0"])
        fig.update_layout(**_plotly_layout(250))
        st.plotly_chart(fig, width='stretch')

    st.markdown("#### Complete Change Log")
    df = pd.DataFrame(commits)[["sha", "message", "author_id", "date_str"]]
    df.columns = ["SHA", "Description", "Author", "Timestamp"]
    st.dataframe(df, width='stretch', hide_index=True, height=500)


# ═══════════════════════════════════════════════════════════════
# SECTION: Access Registry
# ═══════════════════════════════════════════════════════════════

def page_access_registry(D):
    _section_hdr("Access Registry",
                 "Personnel with repository access and their activity on the branch",
                 iso="A.9")

    astats = D["author_stats"]

    st.markdown("#### Branch Contributors")
    if astats:
        rows = []
        for aid, s in sorted(astats.items(), key=lambda x: -x[1]["commits"]):
            f, l = s["first"], s["last"]
            days = (l.date() - f.date()).days + 1 if f and l else 0
            inactive = l and (dt.datetime.now(dt.UTC) - l).days > 30
            rows.append({
                "Identifier": aid, "Name": s["name"] or "\u2014",
                "Commits": s["commits"],
                "First Active": _fmt(f, "%Y-%m-%d"),
                "Last Active": _fmt(l, "%Y-%m-%d"),
                "Days Active": days,
                "Status": "Inactive" if inactive else "Active",
            })

        _metric_row([
            ("Total Contributors", str(len(rows))),
            ("Active (30d)", str(sum(1 for r in rows if r["Status"] == "Active"))),
            ("Inactive", str(sum(1 for r in rows if r["Status"] == "Inactive"))),
        ])
        st.dataframe(pd.DataFrame(rows), width='stretch', hide_index=True)
    else:
        st.caption("No contributor data for this branch.")

    st.markdown("")
    st.markdown("#### Repository-Level Access (All Branches)")
    if D["contributors"]:
        df = pd.DataFrame(D["contributors"])[["login", "contributions", "type"]]
        df.columns = ["Login", "Total Contributions", "Type"]
        st.dataframe(df, width='stretch', hide_index=True)
    else:
        st.caption("No contributor data available.")

    st.markdown("#### Activity Pattern by Day of Week")
    commits = D["commits"]
    if commits:
        ad = defaultdict(lambda: Counter())
        for c in commits:
            if c["date"]:
                ad[c["author_id"]][c["date"].strftime("%A")] += 1
        days_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        rows = []
        for author, dc in ad.items():
            for day in days_order:
                cnt = dc.get(day, 0)
                if cnt > 0:
                    rows.append({"Author": author, "Day": day, "Commits": cnt})
        if rows:
            df = pd.DataFrame(rows)
            fig = px.bar(df, x="Day", y="Commits", color="Author", barmode="group",
                         category_orders={"Day": days_order})
            fig.update_layout(**_plotly_layout(300))
            st.plotly_chart(fig, width='stretch')


# ═══════════════════════════════════════════════════════════════
# SECTION: Incident Log
# ═══════════════════════════════════════════════════════════════

def page_incident_log(D):
    _section_hdr("Incident Log",
                 "Issue tracking and resolution metrics", iso="A.16")

    issues = D["issues"]
    if not issues:
        st.info("No issues found in this repository.")
        return

    oi = [i for i in issues if i["state"] == "open"]
    ci = [i for i in issues if i["state"] == "closed"]
    rts = [i["resolution_days"] for i in ci if i["resolution_days"] is not None]
    avg = sum(rts) / len(rts) if rts else None

    _metric_row([
        ("Total Issues", str(len(issues))),
        ("Open", str(len(oi))),
        ("Closed", str(len(ci))),
        ("Resolution Rate", f"{len(ci) / len(issues) * 100:.0f}%" if issues else "\u2014"),
        ("Avg Resolution", f"{avg:.0f} days" if avg else "\u2014"),
    ])

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("#### Open Issues")
        if oi:
            df = pd.DataFrame(oi)[["number", "title", "author", "assignee", "labels_str", "created_str"]]
            df.columns = ["#", "Title", "Reporter", "Assignee", "Labels", "Created"]
            st.dataframe(df, width='stretch', hide_index=True)
        else:
            st.success("No open issues!")

    with c2:
        st.markdown("#### Recently Closed")
        if ci:
            df = pd.DataFrame(ci[:20])[["number", "title", "assignee", "resolution_days", "closed_str"]]
            df.columns = ["#", "Title", "Assignee", "Days to Close", "Closed"]
            st.dataframe(df, width='stretch', hide_index=True)
        else:
            st.caption("No closed issues.")

    st.markdown("")
    st.markdown("#### Issue Categories")
    all_labels = []
    for i in issues:
        all_labels.extend(i["labels"])
    if all_labels:
        lc = Counter(all_labels)
        df = pd.DataFrame(lc.most_common(15), columns=["Label", "Count"])
        fig = px.bar(df, x="Label", y="Count", color_discrete_sequence=["#eab308"])
        fig.update_layout(**_plotly_layout(240))
        st.plotly_chart(fig, width='stretch')

    if rts:
        st.markdown("#### Resolution Time Distribution")
        fig = px.histogram(pd.DataFrame({"Days": rts}), x="Days", nbins=20,
                           color_discrete_sequence=["#06b6d4"])
        fig.update_layout(**_plotly_layout(240,
                          xaxis=dict(gridcolor="#f0eeff", title="Days to Resolution",
                                     title_font=dict(color="#1a1040"), tickfont=dict(color="#374151")),
                          yaxis=dict(gridcolor="#f0eeff", title="Count",
                                     title_font=dict(color="#1a1040"), tickfont=dict(color="#374151"))))
        st.plotly_chart(fig, width='stretch')


# ═══════════════════════════════════════════════════════════════
# SECTION: Pull Requests
# ═══════════════════════════════════════════════════════════════

def page_pull_requests(D):
    _section_hdr("Pull Requests",
                 "Code review and merge lifecycle for the branch", iso="A.14")

    bp = D["branch_pulls"]
    ap = D["pulls"]

    st.markdown(f"#### Branch-Related PRs (`{D['branch']}`)")
    if bp:
        op = [p for p in bp if p["state"] == "open"]
        mg = [p for p in bp if p["state"] == "merged"]
        cl = [p for p in bp if p["state"] == "closed" and p["state"] != "merged"]
        mts = [p["merge_days"] for p in mg if p["merge_days"] is not None]
        am = sum(mts) / len(mts) if mts else None

        _metric_row([
            ("Branch PRs", str(len(bp))),
            ("Open", str(len(op))),
            ("Merged", str(len(mg))),
            ("Closed (unmerged)", str(len(cl))),
            ("Avg Merge Time", f"{am:.0f} days" if am else "\u2014"),
        ])
        df = pd.DataFrame(bp)[["number", "title", "state", "author", "head", "base", "created_str", "merged_str"]]
        df.columns = ["#", "Title", "Status", "Author", "Head", "Base", "Created", "Merged"]
        st.dataframe(df, width='stretch', hide_index=True)
    else:
        st.info("No pull requests associated with this branch.")

    st.markdown("")
    st.markdown("#### All Repository PRs")
    if ap:
        df = pd.DataFrame(ap)[["number", "title", "state", "author", "head", "base", "created_str"]]
        df.columns = ["#", "Title", "Status", "Author", "Head", "Base", "Created"]
        st.dataframe(df, width='stretch', hide_index=True, height=400)
    else:
        st.caption("No pull requests found.")


# ═══════════════════════════════════════════════════════════════
# SECTION: Author Intelligence
# ═══════════════════════════════════════════════════════════════

def _build_author_file_analysis(enriched):
    """Analyze per-file statistics from enriched commit data."""
    file_stats = defaultdict(lambda: {"additions": 0, "deletions": 0, "commits": 0})
    for c in enriched:
        for fn in c.get("_file_details", []):
            name = fn.get("filename", "")
            if not name:
                continue
            fs = file_stats[name]
            fs["additions"] += fn.get("additions", 0)
            fs["deletions"] += fn.get("deletions", 0)
            fs["commits"] += 1

    # Classification
    for name, fs in file_stats.items():
        fs["classification"] = _classify_file(name)
        ext = "." + name.rsplit(".", 1)[-1] if "." in name else "(none)"
        fs["extension"] = ext.lower()
        fs["net"] = fs["additions"] - fs["deletions"]
        fs["filename"] = name

    return dict(file_stats)


def page_author_intelligence(D):
    _section_hdr("Author Intelligence",
                 "Deep analysis of individual contributor activity on the branch")

    astats = D["author_stats"]
    if not astats:
        st.info("No author data available.")
        return

    selected = st.selectbox("Select Contributor", list(astats.keys()))

    if st.button("Analyze Contributor", type="primary"):
        owner, repo = D["owner"], D["repo"]
        # Get ALL commits for this author — no limit
        ac = sorted(
            [c for c in D["commits"] if c["author_id"] == selected and c["date"]],
            key=lambda x: x["date"],
        )
        if not ac:
            st.warning("No commits found for this author.")
            return

        ta, td, tf = 0, 0, 0
        enriched = []
        with st.spinner(f"Fetching details for {len(ac)} commits (this may take a moment)..."):
            for c in ac:
                det = _fetch_commit_detail(owner, repo, c["sha_full"])
                s = det.get("stats", {})
                fs = det.get("files", [])
                a_val, d_val = s.get("additions", 0), s.get("deletions", 0)
                ta += a_val
                td += d_val
                tf += len(fs)
                enriched.append({
                    **c, "additions": a_val, "deletions": d_val,
                    "files_changed": len(fs),
                    "file_names": ", ".join(f.get("filename", "") for f in fs),
                    "_file_details": fs,
                })

        # Author info
        si = astats[selected]
        f, l = si["first"], si["last"]
        days = (l.date() - f.date()).days + 1 if f and l else 0
        avg_per_day = len(ac) / max(days, 1)

        # File analysis
        file_analysis = _build_author_file_analysis(enriched)
        unique_files = len(file_analysis)
        cls_counter = Counter(fs["classification"] for fs in file_analysis.values())
        ext_counter = Counter(fs["extension"] for fs in file_analysis.values())
        # Top files by commits
        top_files = sorted(file_analysis.values(), key=lambda x: -x["commits"])[:20]
        # Top files by churn (additions + deletions)
        top_churn = sorted(file_analysis.values(), key=lambda x: -(x["additions"] + x["deletions"]))[:15]

        # --- KPI Cards ---
        _metric_row([
            ("Total Commits", str(len(ac))),
            ("Lines Added", _fnum(ta)),
            ("Lines Removed", _fnum(td)),
            ("Net Lines", _fnum(ta - td)),
            ("Unique Files", str(unique_files)),
            ("Days Active", str(days)),
            ("Avg Commits/Day", f"{avg_per_day:.1f}"),
            ("Files/Commit", f"{tf / max(len(ac), 1):.1f}"),
        ])

        # --- Row 1: Daily Activity & Code Changes ---
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("#### Daily Commit Activity")
            dc = Counter(c["date_day"] for c in ac)
            if dc:
                df = pd.DataFrame(sorted(dc.items()), columns=["Date", "Commits"])
                fig = px.bar(df, x="Date", y="Commits", color_discrete_sequence=["#7c5cfc"])
                fig.update_layout(**_plotly_layout(280))
                st.plotly_chart(fig, width='stretch', key="ai_daily")

        with c2:
            st.markdown("#### Code Changes per Commit")
            if enriched:
                df = pd.DataFrame(enriched)[["date_str", "additions", "deletions"]]
                df.columns = ["Date", "Additions", "Deletions"]
                df = df.groupby("Date", as_index=False).sum().sort_values("Date")
                fig = go.Figure()
                fig.add_trace(go.Scatter(x=df["Date"], y=df["Additions"], name="Additions",
                                         fill="tozeroy", mode="lines",
                                         line=dict(color="#10b981", width=1.5),
                                         fillcolor="rgba(16,185,129,0.35)"))
                fig.add_trace(go.Scatter(x=df["Date"], y=df["Deletions"], name="Deletions",
                                         fill="tozeroy", mode="lines",
                                         line=dict(color="#ef4444", width=1.5),
                                         fillcolor="rgba(239,68,68,0.35)"))
                fig.update_layout(**_plotly_layout(280))
                st.plotly_chart(fig, width='stretch', key="ai_changes")

        # --- Row 2: File Classification Pie & File Extension Pie ---
        c3, c4 = st.columns(2)
        with c3:
            st.markdown("#### Files by Classification")
            if cls_counter:
                df = pd.DataFrame(cls_counter.items(), columns=["Classification", "Count"])
                fig = px.pie(df, values="Count", names="Classification",
                             color_discrete_sequence=px.colors.qualitative.Set2,
                             hole=0.4)
                fig.update_layout(**_plotly_layout(260, margin=dict(l=5, r=5, t=10, b=5),
                                                    showlegend=True,
                                                    legend=dict(orientation="h", yanchor="top",
                                                                y=-0.05, xanchor="center", x=0.5,
                                                                font=dict(size=9, color="#374151"))))
                fig.update_traces(textinfo="percent", textfont_size=9,
                                  textposition="inside")
                st.plotly_chart(fig, width='stretch', key="ai_cls_pie")

        with c4:
            st.markdown("#### Files by Extension")
            if ext_counter:
                df = pd.DataFrame(ext_counter.most_common(8), columns=["Extension", "Count"])
                fig = px.pie(df, values="Count", names="Extension",
                             color_discrete_sequence=px.colors.qualitative.Pastel,
                             hole=0.4)
                fig.update_layout(**_plotly_layout(260, margin=dict(l=5, r=5, t=10, b=5),
                                                    showlegend=True,
                                                    legend=dict(orientation="h", yanchor="top",
                                                                y=-0.05, xanchor="center", x=0.5,
                                                                font=dict(size=9, color="#374151"))))
                fig.update_traces(textinfo="percent", textfont_size=9,
                                  textposition="inside")
                st.plotly_chart(fig, width='stretch', key="ai_ext_pie")

        # --- Row 3: Top Files by Commits & Churn ---
        c5, c6 = st.columns(2)
        with c5:
            st.markdown("#### Top Files by Commit Frequency")
            if top_files:
                df = pd.DataFrame(top_files)[["filename", "commits", "additions", "deletions"]]
                df.columns = ["File", "Commits", "Lines +", "Lines −"]
                df["File"] = df["File"].apply(lambda x: x.split("/")[-1] if "/" in x else x)
                fig = px.bar(df, x="Commits", y="File", orientation="h",
                             color_discrete_sequence=["#c070e0"])
                fig.update_layout(**_plotly_layout(min(380, 40 + len(top_files) * 22)))
                fig.update_layout(yaxis=dict(autorange="reversed"))
                st.plotly_chart(fig, width='stretch', key="ai_topfiles")

        with c6:
            st.markdown("#### Top Files by Code Churn")
            if top_churn:
                df = pd.DataFrame(top_churn)
                df["churn"] = df["additions"] + df["deletions"]
                df["short"] = df["filename"].apply(lambda x: x.split("/")[-1] if "/" in x else x)
                fig = px.bar(df, x="churn", y="short", orientation="h",
                             color="churn", color_continuous_scale="YlOrRd")
                fig.update_layout(**_plotly_layout(min(380, 40 + len(top_churn) * 22)))
                fig.update_layout(yaxis=dict(autorange="reversed"), coloraxis_showscale=False)
                st.plotly_chart(fig, width='stretch', key="ai_churn")

        # --- Row 4: Cumulative Lines & Weekly Heatmap ---
        c7, c8 = st.columns(2)
        with c7:
            st.markdown("#### Cumulative Lines Over Time")
            if enriched:
                cum_add, cum_del = 0, 0
                cum_data = []
                for c_item in enriched:
                    cum_add += c_item["additions"]
                    cum_del += c_item["deletions"]
                    cum_data.append({"Date": c_item["date_str"], "Added": cum_add,
                                     "Removed": cum_del, "Net": cum_add - cum_del})
                df = pd.DataFrame(cum_data)
                fig = go.Figure()
                fig.add_trace(go.Scatter(x=df["Date"], y=df["Added"], mode="lines",
                                         name="Cumulative +", line=dict(color="#10b981", width=2)))
                fig.add_trace(go.Scatter(x=df["Date"], y=df["Removed"], mode="lines",
                                         name="Cumulative −", line=dict(color="#ef4444", width=2)))
                fig.add_trace(go.Scatter(x=df["Date"], y=df["Net"], mode="lines",
                                         name="Net", line=dict(color="#7c5cfc", width=2, dash="dot")))
                fig.update_layout(**_plotly_layout(280))
                st.plotly_chart(fig, width='stretch', key="ai_cumulative")

        with c8:
            st.markdown("#### Commits by Day of Week")
            if ac:
                days_of_week = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
                dow_counter = Counter(c["date"].strftime("%a") for c in ac if c["date"])
                df = pd.DataFrame([(d, dow_counter.get(d, 0)) for d in days_of_week],
                                  columns=["Day", "Commits"])
                fig = px.bar(df, x="Day", y="Commits", color_discrete_sequence=["#f0a080"],
                             category_orders={"Day": days_of_week})
                fig.update_layout(**_plotly_layout(280))
                st.plotly_chart(fig, width='stretch', key="ai_dow")

        # --- Row 5: Commit Size Distribution ---
        st.markdown("#### Commit Size Distribution")
        if enriched:
            sizes = [e["additions"] + e["deletions"] for e in enriched]
            fig = px.histogram(pd.DataFrame({"Lines Changed": sizes}),
                               x="Lines Changed", nbins=30,
                               color_discrete_sequence=["#7c5cfc"])
            fig.update_layout(**_plotly_layout(250))
            st.plotly_chart(fig, width='stretch', key="ai_sizedist")

        # --- Full Commit Details Table ---
        st.markdown("#### Full Commit History")
        if enriched:
            df = pd.DataFrame(enriched)[
                ["sha", "message", "date_str", "additions", "deletions", "files_changed", "file_names"]]
            df.columns = ["SHA", "Message", "Date", "Lines +", "Lines −", "Files", "File Names"]
            st.dataframe(df, width='stretch', hide_index=True,
                         height=min(600, 60 + len(enriched) * 35))

        # --- Detailed File Table ---
        st.markdown("#### All Files Touched")
        if file_analysis:
            fa_list = sorted(file_analysis.values(), key=lambda x: -x["commits"])
            df = pd.DataFrame(fa_list)[["filename", "classification", "extension",
                                        "commits", "additions", "deletions", "net"]]
            df.columns = ["File Path", "Category", "Extension", "Commits", "Lines +", "Lines −", "Net"]
            st.dataframe(df, width='stretch', hide_index=True,
                         height=min(500, 60 + len(fa_list) * 35))

        # --- Export as PDF ---
        st.markdown("#### Export")
        rd = {
            "author": selected, "name": si["name"],
            "owner": owner, "repo": repo, "branch": D["branch"],
            "total_commits": len(ac), "total_additions": ta,
            "total_deletions": td, "net_lines": ta - td,
            "files_changed": tf, "unique_files": unique_files,
            "days_active": days, "avg_per_day": f"{avg_per_day:.2f}",
            "first_date": _fmt(f), "last_date": _fmt(l),
        }
        # Build chart images for PDF
        with st.spinner("Rendering charts for PDF (this may take 30-60 seconds)..."):
            chart_images = _build_author_chart_images(
                enriched, ac, cls_counter, ext_counter, top_files, top_churn)
        if chart_images:
            st.success(f"{len(chart_images)} of 9 charts rendered for PDF.")
        else:
            st.warning("Chart rendering failed (kaleido/Chromium may not be available). "
                       "PDF will be generated without charts.")
        with st.spinner("Generating PDF report..."):
            pdf_bytes = _gen_author_pdf(rd, enriched, file_analysis, chart_images)
        st.download_button(
            "Download Author Report (PDF)", pdf_bytes,
            f"{repo}_{D['branch']}_{selected}_report.pdf",
            "application/pdf",
        )


# ═══════════════════════════════════════════════════════════════
# SECTION: Project Timeline
# ═══════════════════════════════════════════════════════════════

def page_project_timeline(D):
    _section_hdr("Project Timeline",
                 "Gantt chart, milestone tracking and activity management")

    owner, repo, branch = D["owner"], D["repo"], D["branch"]
    rk = _rk(owner, repo, branch)
    saved = _load_pm(rk)

    # Dates
    c1, c2 = st.columns(2)
    with c1:
        sd = saved.get("project_start")
        try:
            sd = dt.date.fromisoformat(sd)
        except Exception:
            sd = dt.date.today() - dt.timedelta(days=30)
        pstart = st.date_input("Project Start Date", value=sd)
    with c2:
        ed = saved.get("project_end")
        try:
            ed = dt.date.fromisoformat(ed)
        except Exception:
            ed = dt.date.today() + dt.timedelta(days=30)
        pend = st.date_input("Project End Date", value=ed)

    # Extensions
    st.markdown("#### Deadline Extensions")
    if "pm_ext" not in st.session_state:
        st.session_state.pm_ext = {}
    if rk not in st.session_state.pm_ext:
        pe = []
        for x in saved.get("extensions", []):
            try:
                pe.append(dt.date.fromisoformat(x))
            except Exception:
                pass
        st.session_state.pm_ext[rk] = pe

    ec1, ec2, ec3 = st.columns([1, 1, 2])
    with ec1:
        ne = st.date_input("New Extension", value=dt.date.today(), key="ext_new")
    with ec2:
        st.markdown("")
        st.markdown("")
        if st.button("Add Extension"):
            st.session_state.pm_ext[rk].append(ne)
    with ec3:
        if st.session_state.pm_ext[rk]:
            st.info("Extensions: " + ", ".join(d.isoformat() for d in st.session_state.pm_ext[rk]))
            if st.button("Clear Extensions"):
                st.session_state.pm_ext[rk] = []

    st.markdown("")

    # Activity table
    st.markdown("#### Activity Log")
    rows = []
    for c in D["commits"]:
        rows.append({
            "SHA": c.get("sha", ""), "Message": c.get("message", ""),
            "Author": c.get("author_id", ""), "Date": c.get("date_str", ""),
            "Activity Tag": "", "Description": "", "sha_full": c.get("sha_full", ""),
        })

    base_df = pd.DataFrame(rows) if rows else pd.DataFrame(
        columns=["SHA", "Message", "Author", "Date", "Activity Tag", "Description", "sha_full"])

    si = saved.get("commit_inputs", {})
    if not base_df.empty and si:
        tags, descs = [], []
        for _, r in base_df.iterrows():
            item = si.get(r.get("sha_full", ""), {})
            tags.append(item.get("tag", ""))
            descs.append(item.get("desc", ""))
        base_df["Activity Tag"] = tags
        base_df["Description"] = descs

    edited = st.data_editor(
        base_df, width='stretch', height=450, hide_index=True,
        column_config={
            "Activity Tag": st.column_config.SelectboxColumn(
                "Activity Tag", options=[""] + ACTIVITY_TAGS, required=False),
            "Description": st.column_config.TextColumn("Description", required=False),
            "sha_full": st.column_config.TextColumn("sha_full", disabled=True),
        },
        disabled=["SHA", "Message", "Author", "Date", "sha_full"],
    )

    sc1, sc2, sc3 = st.columns([1, 1, 2])
    with sc1:
        if st.button("Save Changes", type="primary"):
            inp = {}
            for _, r in edited.iterrows():
                sf = r.get("sha_full", "")
                if sf:
                    inp[sf] = {
                        "tag": (r.get("Activity Tag") or "").strip(),
                        "desc": (r.get("Description") or "").strip(),
                    }
            pm = {
                "project_start": pstart.isoformat(),
                "project_end": pend.isoformat(),
                "extensions": [d.isoformat() for d in st.session_state.pm_ext.get(rk, [])],
                "commit_inputs": inp,
                "updated_at": dt.datetime.utcnow().isoformat(),
            }
            _save_pm(rk, pm)
            st.success("Saved.")

    with sc2:
        if st.button("Delete Project Data"):
            _del_pm(rk)
            st.session_state.pm_ext[rk] = []
            st.success("Deleted. Refresh to see clean state.")

    st.markdown("#### Gantt Chart")
    if st.button("Generate Gantt Chart", type="primary", key="gantt_btn"):
        ext = st.session_state.pm_ext.get(rk, [])
        tasks = _build_gantt(edited, pstart, pend, ext)
        _render_gantt(tasks, pstart, pend, ext)

    st.markdown("#### Milestones")
    if D["milestones"]:
        df = pd.DataFrame(D["milestones"])[["title", "state", "open_issues", "closed_issues", "due_str"]]
        df.columns = ["Milestone", "State", "Open", "Closed", "Due"]
        st.dataframe(df, width='stretch', hide_index=True)
    else:
        st.caption("No milestones defined for this repository.")


def _build_gantt(df, start, end, extensions, gap=2):
    ws = dt.datetime.combine(start, dt.time(0))
    re_date = max(extensions) if extensions else end
    we = dt.datetime.combine(re_date, dt.time(23, 59))

    rows = []
    for _, r in df.iterrows():
        author = (r.get("Author") or "").strip()
        tag = (r.get("Activity Tag") or "").strip()
        sha = (r.get("SHA") or "").strip()
        desc = (r.get("Description") or "").strip()
        ds = (r.get("Date") or "").strip()
        if not author or not ds:
            continue
        try:
            ts = dt.datetime.strptime(ds[:16], "%Y-%m-%d %H:%M")
        except Exception:
            continue
        rows.append({"Author": author, "Tag": tag or "Uncategorized",
                     "SHA": sha, "Desc": desc, "Start": ts})

    if not rows:
        return pd.DataFrame(columns=["Author", "Tag", "Start", "End", "SHA", "Desc"])

    df0 = pd.DataFrame(rows).sort_values(["Author", "Start"])
    tasks = []

    for author, g in df0.groupby("Author", sort=False):
        g = g.reset_index(drop=True)
        last_e = None
        for i in range(len(g)):
            s = g.loc[i, "Start"]
            e = g.loc[i + 1, "Start"] if i < len(g) - 1 else s + dt.timedelta(days=gap)
            if e <= s:
                e = s + dt.timedelta(days=gap)
            s = max(s, ws)
            e = min(e, we)
            if e <= s:
                e = s + dt.timedelta(hours=4)
            tasks.append({"Author": author, "Start": s, "End": e,
                         "Tag": g.loc[i, "Tag"], "SHA": g.loc[i, "SHA"],
                         "Desc": g.loc[i, "Desc"]})
            last_e = e
        if last_e and last_e < we:
            tasks.append({"Author": author, "Start": last_e, "End": we,
                         "Tag": "Idle", "SHA": "", "Desc": "No activity"})

    return pd.DataFrame(tasks)


def _render_gantt(df, start, end, extensions):
    if df.empty:
        st.info("Fill in Activity Tags and Descriptions, then generate the chart.")
        return

    df = df.copy()
    df["Tag"] = df["Tag"].fillna("Uncategorized")

    fig = px.timeline(df, x_start="Start", x_end="End", y="Author", color="Tag",
                      color_discrete_map={"Idle": "rgba(148,163,184,0.25)"},
                      hover_data={"Author": False, "Tag": True, "SHA": True, "Desc": True})

    fig.update_traces(marker_line_width=0, width=0.08)
    fig.update_yaxes(autorange="reversed")

    x0 = dt.datetime.combine(start, dt.time(0))
    re_date = max(extensions) if extensions else end
    x1 = max(dt.datetime.combine(re_date, dt.time(23, 59)), df["End"].max())
    fig.update_xaxes(range=[x0, x1])

    fig.update_layout(
        height=min(900, 140 + 28 * len(df)),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#1f2937"),
        xaxis=dict(tickfont=dict(color="#374151"), title_font=dict(color="#1a1040")),
        yaxis=dict(tickfont=dict(color="#374151"), title_font=dict(color="#1a1040")),
        legend=dict(font=dict(color="#1f2937")),
        margin=dict(l=10, r=10, t=40, b=10),
    )

    end_dt = dt.datetime.combine(end + dt.timedelta(days=1), dt.time(0))
    fig.add_vline(x=end_dt, line_width=2, line_dash="dot", line_color="#ef4444")

    for d in sorted({d for d in extensions if isinstance(d, dt.date)}):
        fig.add_vline(
            x=dt.datetime.combine(d + dt.timedelta(days=1), dt.time(0)),
            line_width=1, line_dash="dot", line_color="#f0a080",
        )

    fig.add_vrect(x0=end_dt, x1=x1, fillcolor="rgba(239,68,68,0.08)",
                  line_width=0, layer="below")

    st.plotly_chart(fig, width='stretch')
    st.caption("Red line = deadline \u00b7 Yellow = extensions \u00b7 Shaded = extension zone")


# ═══════════════════════════════════════════════════════════════
# SECTION: Compliance Hub
# ═══════════════════════════════════════════════════════════════

def page_compliance_hub(D):
    _section_hdr("Compliance Hub",
                 "ISO 27001 evidence collection and report generation",
                 iso="Full Annex A")

    st.markdown("""
    This section generates structured documentation that maps directly to **ISO 27001 Annex A** controls.
    Each report section provides evidence for specific control areas required during audits.
    """)

    # Control mapping
    st.markdown("#### ISO 27001 Control Mapping")
    controls = [
        {"Control": "A.8 \u2014 Asset Management",
         "Evidence": "File inventory, language distribution, asset classification",
         "Status": "\u2705 Available" if D["files"] else "\u26a0\ufe0f No data",
         "Source": "Asset Inventory"},
        {"Control": "A.9 \u2014 Access Control",
         "Evidence": "Contributor registry, activity patterns, access levels",
         "Status": "\u2705 Available" if D["author_stats"] else "\u26a0\ufe0f No data",
         "Source": "Access Registry"},
        {"Control": "A.12 \u2014 Operations Security",
         "Evidence": "Complete change log, change frequency, author attribution",
         "Status": "\u2705 Available" if D["commits"] else "\u26a0\ufe0f No data",
         "Source": "Change Ledger"},
        {"Control": "A.14 \u2014 System Development Security",
         "Evidence": "PR lifecycle, code review coverage, merge history",
         "Status": "\u2705 Available" if D["pulls"] else "\u26a0\ufe0f No data",
         "Source": "Pull Requests"},
        {"Control": "A.16 \u2014 Incident Management",
         "Evidence": "Issue tracking, resolution times, severity categorization",
         "Status": "\u2705 Available" if D["issues"] else "\u26a0\ufe0f No data",
         "Source": "Incident Log"},
    ]
    st.dataframe(pd.DataFrame(controls), width='stretch', hide_index=True)

    st.markdown("---")

    st.markdown("#### Generate Compliance Report")
    st.markdown("Export a comprehensive HTML document covering all ISO 27001 control evidence from this branch.")

    scope = st.multiselect(
        "Report Sections",
        ["Executive Summary", "Asset Inventory (A.8)", "Access Control (A.9)",
         "Change Management (A.12)", "Development Security (A.14)",
         "Incident Management (A.16)", "Full Audit Trail"],
        default=["Executive Summary", "Asset Inventory (A.8)", "Access Control (A.9)",
                 "Change Management (A.12)", "Development Security (A.14)",
                 "Incident Management (A.16)"],
    )

    if st.button("Generate Compliance Report", type="primary"):
        with st.spinner("Generating compliance report..."):
            html = _gen_compliance_report(D, scope)
            st.download_button(
                "Download Compliance Report (HTML)", html,
                f"ISO27001_{D['repo']}_{D['branch']}_{dt.date.today().isoformat()}.html",
                "text/html",
            )
            st.success("Report generated successfully.")

    st.markdown("")
    st.markdown("#### Compliance Readiness Summary")

    avail = sum(1 for c in controls if "\u2705" in c["Status"])
    pct = avail / len(controls) * 100 if controls else 0
    _metric_row([
        ("Controls Covered", f"{avail}/{len(controls)}"),
        ("Readiness", f"{pct:.0f}%"),
        ("Branch Scope", D["branch"]),
        ("Report Date", dt.date.today().isoformat()),
    ])


# ═══════════════════════════════════════════════════════════════
# Report Templates
# ═══════════════════════════════════════════════════════════════


def _gen_compliance_report(D, sections):
    clsf = Counter(f["classification"] for f in D["files"])
    classifications = sorted(clsf.items(), key=lambda x: -x[1])
    languages = sorted(D["languages"].items(), key=lambda x: -x[1])

    authors = []
    for aid, s in D["author_stats"].items():
        f, l = s["first"], s["last"]
        days = (l.date() - f.date()).days + 1 if f and l else 0
        authors.append({"id": aid, "name": s["name"], "commits": s["commits"],
                        "first": _fmt(f, "%Y-%m-%d"), "last": _fmt(l, "%Y-%m-%d"), "days": days})

    dated = [c for c in D["commits"] if c["date"]]
    fd = _fmt(min(c["date"] for c in dated), "%Y-%m-%d") if dated else "\u2014"
    ld = _fmt(max(c["date"] for c in dated), "%Y-%m-%d") if dated else "\u2014"

    oi = [i for i in D["issues"] if i["state"] == "open"]
    ci = [i for i in D["issues"] if i["state"] == "closed"]
    rts = [i["resolution_days"] for i in ci if i["resolution_days"] is not None]
    ar = f"{sum(rts) / len(rts):.0f} days" if rts else "\u2014"

    audit = []
    for c in D["commits"]:
        audit.append({"date": c["date_str"], "type": "Commit",
                      "author": c["author_id"], "ref": c["sha"], "desc": c["message"]})
    for i in D["issues"]:
        audit.append({"date": i["created_str"], "type": "Issue",
                      "author": i["author"] or "\u2014", "ref": f"#{i['number']}", "desc": i["title"]})
    for p in D["branch_pulls"]:
        audit.append({"date": p["created_str"], "type": "PR",
                      "author": p["author"] or "\u2014", "ref": f"#{p['number']}", "desc": p["title"]})
    audit.sort(key=lambda x: x["date"], reverse=True)

    return _COMPLIANCE_TPL.render(
        owner=D["owner"], repo=D["repo"], branch=D["branch"],
        now=dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        secs=sections, health=_health_score(D),
        n_commits=len(D["commits"]), n_authors=len(D["author_stats"]),
        n_files=len(D["files"]), n_files_safe=max(len(D["files"]), 1),
        n_issues=len(D["issues"]), n_prs=len(D["branch_pulls"]),
        classifications=classifications,
        languages=languages, lang_total_safe=max(sum(D["languages"].values()), 1),
        authors=authors, first_date=fd, last_date=ld,
        commits_list=D["commits"][:200],
        prs=D["branch_pulls"], issues_list=D["issues"],
        n_open_issues=len(oi), n_closed_issues=len(ci),
        avg_resolution=ar, audit=audit[:500],
    )


_COMPLIANCE_TPL = Template(r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>ISO 27001 Compliance Report</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Segoe UI',system-ui,sans-serif;background:#ffffff;color:#374151;line-height:1.7}
.hdr{background:linear-gradient(135deg,#1a1040,#7c5cfc);padding:40px;border-bottom:2px solid #b0a0f0}
.hdr h1{font-size:1.8rem;color:#ffffff;margin-bottom:8px}
.hdr .m{color:#d4d0f8;font-size:.9rem}
.hdr .b{display:inline-block;background:rgba(176,160,240,0.25);color:#ffffff;padding:4px 12px;border-radius:4px;font-size:.8rem;font-weight:600;margin-top:8px}
.ct{max-width:1100px;margin:0 auto;padding:32px 24px}
.sec{margin-bottom:40px;page-break-inside:avoid}
.sec h2{font-size:1.3rem;color:#1a1040;border-bottom:1px solid #e4e0f0;padding-bottom:8px;margin-bottom:16px}
.sec h3{font-size:1rem;color:#374151;margin:16px 0 8px}
.it{background:rgba(124,92,252,0.1);color:#7c5cfc;padding:2px 8px;border-radius:4px;font-size:.75rem;font-weight:600;margin-left:8px}
.gr{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin-bottom:16px}
.cd{background:#faf9ff;border:1px solid #e4e0f0;border-radius:8px;padding:14px}
.cd .l{font-size:.75rem;text-transform:uppercase;color:#7c5cfc;letter-spacing:.05em}
.cd .v{font-size:1.2rem;font-weight:700;color:#1a1040;margin-top:4px}
table{width:100%;border-collapse:collapse;margin-top:8px;font-size:.85rem}
th{background:#faf9ff;color:#7c5cfc;padding:8px 10px;text-align:left;font-weight:600;border-bottom:1px solid #e4e0f0}
td{padding:6px 10px;border-bottom:1px solid #f0eeff;color:#374151}
tr:nth-child(even) td{background:#faf9ff}
.ft{text-align:center;padding:24px;color:#9ca3af;font-size:.8rem;border-top:1px solid #e4e0f0;margin-top:40px}
@media print{body{background:#fff;color:#1e293b}.hdr{background:linear-gradient(135deg,#1a1040,#7c5cfc);border-color:#b0a0f0}.hdr h1{color:#fff}.cd{border-color:#e4e0f0}th{background:#faf9ff;color:#7c5cfc}td{color:#374151;border-color:#e4e0f0}}
</style>
</head>
<body>
<div class="hdr">
<h1>ISO 27001 Compliance Evidence Report</h1>
<div class="m">Repository: <strong>{{ owner }}/{{ repo }}</strong> &middot; Branch: <strong>{{ branch }}</strong><br>
Generated: {{ now }} &middot; Scope: Branch-level software development audit</div>
<div class="b">ISO/IEC 27001:2022 &mdash; Annex A</div>
</div>
<div class="ct">

{% if "Executive Summary" in secs %}
<div class="sec">
<h2>Executive Summary</h2>
<p>This report provides structured evidence for ISO 27001 compliance covering the software development activities on the <strong>{{ branch }}</strong> branch of the <strong>{{ repo }}</strong> repository. The data covers {{ n_commits }} tracked changes by {{ n_authors }} contributors across {{ n_files }} tracked files.</p>
<div class="gr">
<div class="cd"><div class="l">Total Changes</div><div class="v">{{ n_commits }}</div></div>
<div class="cd"><div class="l">Contributors</div><div class="v">{{ n_authors }}</div></div>
<div class="cd"><div class="l">Files Tracked</div><div class="v">{{ n_files }}</div></div>
<div class="cd"><div class="l">Issues</div><div class="v">{{ n_issues }}</div></div>
<div class="cd"><div class="l">Pull Requests</div><div class="v">{{ n_prs }}</div></div>
<div class="cd"><div class="l">Health Score</div><div class="v">{{ health }}/100</div></div>
</div>
</div>
{% endif %}

{% if "Asset Inventory (A.8)" in secs %}
<div class="sec">
<h2>Asset Inventory <span class="it">A.8</span></h2>
<p>Information asset register detailing all tracked files, their classification, and size.</p>
<h3>Asset Classification Summary</h3>
<table><thead><tr><th>Classification</th><th>Count</th><th>Percentage</th></tr></thead><tbody>
{% for cls, cnt in classifications %}
<tr><td>{{ cls }}</td><td>{{ cnt }}</td><td>{{ "%.1f"|format(cnt / n_files_safe * 100) }}%</td></tr>
{% endfor %}
</tbody></table>
<h3>Language Distribution</h3>
<table><thead><tr><th>Language</th><th>Bytes</th><th>Share</th></tr></thead><tbody>
{% for lang, bts in languages %}
<tr><td>{{ lang }}</td><td>{{ bts }}</td><td>{{ "%.1f"|format(bts / lang_total_safe * 100) }}%</td></tr>
{% endfor %}
</tbody></table>
</div>
{% endif %}

{% if "Access Control (A.9)" in secs %}
<div class="sec">
<h2>Access Control <span class="it">A.9</span></h2>
<p>Personnel with access to the branch and their recorded activity.</p>
<table><thead><tr><th>Identifier</th><th>Name</th><th>Commits</th><th>First Active</th><th>Last Active</th><th>Days</th></tr></thead><tbody>
{% for a in authors %}
<tr><td>{{ a.id }}</td><td>{{ a.name }}</td><td>{{ a.commits }}</td><td>{{ a.first }}</td><td>{{ a.last }}</td><td>{{ a.days }}</td></tr>
{% endfor %}
</tbody></table>
</div>
{% endif %}

{% if "Change Management (A.12)" in secs %}
<div class="sec">
<h2>Change Management <span class="it">A.12 / A.14</span></h2>
<p>Complete audit trail of all code changes on the branch.</p>
<div class="gr">
<div class="cd"><div class="l">Total Changes</div><div class="v">{{ n_commits }}</div></div>
<div class="cd"><div class="l">First Change</div><div class="v">{{ first_date }}</div></div>
<div class="cd"><div class="l">Last Change</div><div class="v">{{ last_date }}</div></div>
</div>
<table><thead><tr><th>SHA</th><th>Date</th><th>Author</th><th>Description</th></tr></thead><tbody>
{% for c in commits_list %}
<tr><td><code>{{ c.sha }}</code></td><td>{{ c.date_str }}</td><td>{{ c.author_id }}</td><td>{{ c.message }}</td></tr>
{% endfor %}
</tbody></table>
{% if n_commits > 200 %}<p style="color:#9ca3af;margin-top:8px;">Showing first 200 of {{ n_commits }} changes.</p>{% endif %}
</div>
{% endif %}

{% if "Development Security (A.14)" in secs %}
<div class="sec">
<h2>Development Security <span class="it">A.14</span></h2>
<p>Pull request lifecycle and code review process documentation.</p>
{% if prs %}
<table><thead><tr><th>#</th><th>Title</th><th>Status</th><th>Author</th><th>Head</th><th>Base</th><th>Created</th><th>Merged</th></tr></thead><tbody>
{% for p in prs %}
<tr><td>{{ p.number }}</td><td>{{ p.title }}</td><td>{{ p.state }}</td><td>{{ p.author }}</td><td>{{ p.head }}</td><td>{{ p.base }}</td><td>{{ p.created_str }}</td><td>{{ p.merged_str }}</td></tr>
{% endfor %}
</tbody></table>
{% else %}<p style="color:#9ca3af;">No branch-related pull requests found.</p>{% endif %}
</div>
{% endif %}

{% if "Incident Management (A.16)" in secs %}
<div class="sec">
<h2>Incident Management <span class="it">A.16</span></h2>
<p>Issue tracking and resolution metrics.</p>
<div class="gr">
<div class="cd"><div class="l">Total Issues</div><div class="v">{{ n_issues }}</div></div>
<div class="cd"><div class="l">Open</div><div class="v">{{ n_open_issues }}</div></div>
<div class="cd"><div class="l">Closed</div><div class="v">{{ n_closed_issues }}</div></div>
<div class="cd"><div class="l">Avg Resolution</div><div class="v">{{ avg_resolution }}</div></div>
</div>
{% if issues_list %}
<table><thead><tr><th>#</th><th>Title</th><th>State</th><th>Reporter</th><th>Assignee</th><th>Labels</th><th>Created</th><th>Closed</th><th>Days</th></tr></thead><tbody>
{% for i in issues_list %}
<tr><td>{{ i.number }}</td><td>{{ i.title }}</td><td>{{ i.state }}</td><td>{{ i.author or '&mdash;' }}</td><td>{{ i.assignee or '&mdash;' }}</td><td>{{ i.labels_str }}</td><td>{{ i.created_str }}</td><td>{{ i.closed_str }}</td><td>{{ i.resolution_days if i.resolution_days is not none else '&mdash;' }}</td></tr>
{% endfor %}
</tbody></table>
{% else %}<p style="color:#9ca3af;">No issues found.</p>{% endif %}
</div>
{% endif %}

{% if "Full Audit Trail" in secs %}
<div class="sec">
<h2>Full Audit Trail</h2>
<p>Chronological record of all tracked events.</p>
<table><thead><tr><th>Date</th><th>Type</th><th>Author</th><th>Ref</th><th>Description</th></tr></thead><tbody>
{% for e in audit %}
<tr><td>{{ e.date }}</td><td>{{ e.type }}</td><td>{{ e.author }}</td><td>{{ e.ref }}</td><td>{{ e.desc }}</td></tr>
{% endfor %}
</tbody></table>
</div>
{% endif %}

</div>
<div class="ft">ISO 27001 Compliance Report &middot; Generated by GAM Software PM &middot; {{ now }}<br>
Repository: {{ owner }}/{{ repo }} &middot; Branch: {{ branch }}</div>
</body></html>""")


_AUTHOR_TPL = None  # PDF-based now; kept as placeholder

def _fig_to_png_bytes(fig, width=800, height=400):
    """Convert a Plotly figure to PNG bytes for PDF embedding."""
    try:
        img_bytes = fig.to_image(format="png", width=width, height=height, scale=2)
        if img_bytes and len(img_bytes) > 100:
            return img_bytes
        return None
    except Exception as exc:
        import traceback
        print(f"[PDF-CHART] to_image failed: {exc}")
        traceback.print_exc()
        return None


def _chart_layout(title="", height=400):
    """Consistent light chart layout for PDF export."""
    return dict(
        paper_bgcolor="#ffffff", plot_bgcolor="#faf9ff",
        font=dict(family="Helvetica, Arial, sans-serif", color="#1f2937", size=13),
        xaxis=dict(gridcolor="#e4e0f0", linecolor="#d1cde0",
                   title_font=dict(color="#1a1040", size=13),
                   tickfont=dict(color="#374151", size=12)),
        yaxis=dict(gridcolor="#e4e0f0", linecolor="#d1cde0",
                   title_font=dict(color="#1a1040", size=13),
                   tickfont=dict(color="#374151", size=12)),
        margin=dict(l=65, r=30, t=50, b=65),
        title=dict(text=title, font=dict(size=16, color="#1a1040"), x=0.5, xanchor="center"),
        height=height,
        legend=dict(font=dict(size=12, color="#1f2937")),
        colorway=["#7c5cfc", "#2070e0", "#c070e0", "#f0a080", "#70d0f0",
                  "#10b981", "#f59e0b", "#ef4444"],
    )


def _build_author_chart_images(enriched, ac, cls_counter, ext_counter, top_files, top_churn):
    """Build chart PNG images for PDF embedding. Returns dict of name->bytes."""
    charts = {}
    _errors = []

    def _try_chart(name, build_fn):
        """Wrapper with error capture for each chart."""
        try:
            img = build_fn()
            if img:
                charts[name] = img
            else:
                _errors.append(f"{name}: to_image returned None")
        except Exception as exc:
            _errors.append(f"{name}: {exc}")
            import traceback
            traceback.print_exc()

    # 1) Daily Activity
    def _c1():
        dc = Counter(c["date_day"] for c in ac)
        if not dc:
            return None
        df = pd.DataFrame(sorted(dc.items()), columns=["Date", "Commits"])
        fig = px.bar(df, x="Date", y="Commits", color_discrete_sequence=["#7c5cfc"])
        fig.update_layout(**_chart_layout("Daily Commit Activity", 400))
        return _fig_to_png_bytes(fig, 900, 400)
    _try_chart("daily_activity", _c1)

    # 2) Code changes per commit (area chart for reliable PDF rendering)
    def _c2():
        if not enriched:
            return None
        df = pd.DataFrame(enriched)[["date_str", "additions", "deletions"]]
        df.columns = ["Date", "Additions", "Deletions"]
        df = df.groupby("Date", as_index=False).sum().sort_values("Date")
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=df["Date"], y=df["Additions"], name="Additions",
                                 fill="tozeroy", mode="lines",
                                 line=dict(color="#10b981", width=2),
                                 fillcolor="rgba(16,185,129,0.35)"))
        fig.add_trace(go.Scatter(x=df["Date"], y=df["Deletions"], name="Deletions",
                                 fill="tozeroy", mode="lines",
                                 line=dict(color="#ef4444", width=2),
                                 fillcolor="rgba(239,68,68,0.35)"))
        fig.update_layout(**_chart_layout("Code Changes per Commit", 400))
        return _fig_to_png_bytes(fig, 900, 400)
    _try_chart("code_changes", _c2)

    # 3) File classification pie
    def _c3():
        if not cls_counter:
            return None
        df = pd.DataFrame(cls_counter.items(), columns=["Classification", "Count"])
        fig = px.pie(df, values="Count", names="Classification",
                     color_discrete_sequence=px.colors.qualitative.Set2, hole=0.4)
        fig.update_layout(**_chart_layout("Files by Classification", 450))
        fig.update_traces(textinfo="label+percent", textfont_size=13)
        return _fig_to_png_bytes(fig, 750, 450)
    _try_chart("file_class_pie", _c3)

    # 4) File extension pie
    def _c4():
        if not ext_counter:
            return None
        df = pd.DataFrame(ext_counter.most_common(12), columns=["Extension", "Count"])
        fig = px.pie(df, values="Count", names="Extension",
                     color_discrete_sequence=px.colors.qualitative.Pastel, hole=0.4)
        fig.update_layout(**_chart_layout("Files by Extension", 450))
        fig.update_traces(textinfo="label+percent", textfont_size=13)
        return _fig_to_png_bytes(fig, 750, 450)
    _try_chart("file_ext_pie", _c4)

    # 5) Top files by commits
    def _c5():
        if not top_files:
            return None
        df = pd.DataFrame(top_files)[["filename", "commits"]]
        df.columns = ["File", "Commits"]
        df["File"] = df["File"].apply(lambda x: x.split("/")[-1] if "/" in x else x)
        fig = px.bar(df, x="Commits", y="File", orientation="h",
                     color_discrete_sequence=["#c070e0"])
        h = max(400, 60 + len(top_files) * 28)
        fig.update_layout(**_chart_layout("Top Files by Commit Frequency", h))
        fig.update_layout(yaxis=dict(autorange="reversed"))
        return _fig_to_png_bytes(fig, 900, h)
    _try_chart("top_files", _c5)

    # 6) Top files by churn
    def _c6():
        if not top_churn:
            return None
        df = pd.DataFrame(top_churn)
        df["churn"] = df["additions"] + df["deletions"]
        df["short"] = df["filename"].apply(lambda x: x.split("/")[-1] if "/" in x else x)
        fig = px.bar(df, x="churn", y="short", orientation="h",
                     color="churn", color_continuous_scale="YlOrRd")
        h = max(400, 60 + len(top_churn) * 28)
        fig.update_layout(**_chart_layout("Top Files by Code Churn", h))
        fig.update_layout(yaxis=dict(autorange="reversed"), coloraxis_showscale=False)
        return _fig_to_png_bytes(fig, 900, h)
    _try_chart("top_churn", _c6)

    # 7) Cumulative lines
    def _c7():
        if not enriched:
            return None
        cum_add, cum_del = 0, 0
        cum_data = []
        for c_item in enriched:
            cum_add += c_item["additions"]
            cum_del += c_item["deletions"]
            cum_data.append({"Date": c_item["date_str"], "Added": cum_add,
                             "Removed": cum_del, "Net": cum_add - cum_del})
        df = pd.DataFrame(cum_data)
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=df["Date"], y=df["Added"], mode="lines",
                                 name="Cumulative +", line=dict(color="#10b981", width=2.5)))
        fig.add_trace(go.Scatter(x=df["Date"], y=df["Removed"], mode="lines",
                                 name="Cumulative −", line=dict(color="#ef4444", width=2.5)))
        fig.add_trace(go.Scatter(x=df["Date"], y=df["Net"], mode="lines",
                                 name="Net", line=dict(color="#7c5cfc", width=2.5, dash="dot")))
        fig.update_layout(**_chart_layout("Cumulative Lines Over Time", 400))
        return _fig_to_png_bytes(fig, 900, 400)
    _try_chart("cumulative", _c7)

    # 8) Commits by day of week
    def _c8():
        if not ac:
            return None
        days_of_week = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        dow_counter = Counter(c["date"].strftime("%a") for c in ac if c["date"])
        df = pd.DataFrame([(d, dow_counter.get(d, 0)) for d in days_of_week],
                          columns=["Day", "Commits"])
        fig = px.bar(df, x="Day", y="Commits", color_discrete_sequence=["#f0a080"],
                     category_orders={"Day": days_of_week})
        fig.update_layout(**_chart_layout("Commits by Day of Week", 380))
        return _fig_to_png_bytes(fig, 750, 380)
    _try_chart("day_of_week", _c8)

    # 9) Commit size distribution
    def _c9():
        if not enriched:
            return None
        sizes = [e["additions"] + e["deletions"] for e in enriched]
        fig = px.histogram(pd.DataFrame({"Lines Changed": sizes}),
                           x="Lines Changed", nbins=30,
                           color_discrete_sequence=["#7c5cfc"])
        fig.update_layout(**_chart_layout("Commit Size Distribution", 380))
        return _fig_to_png_bytes(fig, 900, 380)
    _try_chart("size_dist", _c9)

    if _errors:
        print(f"[PDF-CHART] {len(_errors)} chart(s) failed: {_errors}")

    return charts


def _gen_author_pdf(rd, enriched, file_analysis, chart_images):
    """Generate a comprehensive, professional author report as PDF bytes."""
    buf = io.BytesIO()

    # Colors
    BG = HexColor("#ffffff")
    CARD_BG = HexColor("#faf9ff")
    BORDER = HexColor("#e4e0f0")
    TEXT = HexColor("#374151")
    MUTED = HexColor("#6b7280")
    ACCENT = HexColor("#7c5cfc")
    WHITE = HexColor("#1a1040")
    HEADER_BG = HexColor("#7c5cfc")

    # Page dimensions
    PW, PH = A4
    L_MARGIN = 20 * mm
    R_MARGIN = 20 * mm
    T_MARGIN = 22 * mm
    B_MARGIN = 22 * mm
    W = PW - L_MARGIN - R_MARGIN

    # ── Page template with background, header line & page numbers ──
    _page_count = [0]

    def _on_page(canvas, doc):
        _page_count[0] += 1
        canvas.saveState()
        # Dark background
        canvas.setFillColor(BG)
        canvas.rect(0, 0, PW, PH, fill=1, stroke=0)
        # Top accent bar
        canvas.setFillColor(ACCENT)
        canvas.rect(0, PH - 3 * mm, PW, 3 * mm, fill=1, stroke=0)
        # Footer line
        canvas.setStrokeColor(BORDER)
        canvas.setLineWidth(0.5)
        canvas.line(L_MARGIN, B_MARGIN - 6 * mm, PW - R_MARGIN, B_MARGIN - 6 * mm)
        # Footer text
        canvas.setFillColor(MUTED)
        canvas.setFont("Helvetica", 7)
        footer_txt = (f"GAM Software PM \u2014 ISO 27001 Compliance Platform  \u00b7  "
                      f"{rd['owner']}/{rd['repo']} \u00b7 {rd['branch']}  \u00b7  "
                      f"Page {_page_count[0]}")
        canvas.drawCentredString(PW / 2, B_MARGIN - 10 * mm, footer_txt)
        canvas.restoreState()

    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=L_MARGIN, rightMargin=R_MARGIN,
        topMargin=T_MARGIN, bottomMargin=B_MARGIN,
    )

    # ── Paragraph Styles (generous spacing) ──
    sTitle = ParagraphStyle("Title", fontName="Helvetica-Bold", fontSize=22,
                            textColor=WHITE, leading=28, spaceAfter=6)
    sSub = ParagraphStyle("Sub", fontName="Helvetica", fontSize=10,
                          textColor=MUTED, leading=15, spaceAfter=20)
    sH2 = ParagraphStyle("H2", fontName="Helvetica-Bold", fontSize=14,
                         textColor=WHITE, leading=20, spaceBefore=24, spaceAfter=12)
    sH3 = ParagraphStyle("H3", fontName="Helvetica-Bold", fontSize=10.5,
                         textColor=HexColor("#a5b4fc"), leading=15,
                         spaceBefore=14, spaceAfter=8)
    sBody = ParagraphStyle("Body", fontName="Helvetica", fontSize=9,
                           textColor=TEXT, leading=14, spaceAfter=6)
    sCell = ParagraphStyle("Cell", fontName="Helvetica", fontSize=8,
                           textColor=TEXT, leading=12)
    sCellSmall = ParagraphStyle("CellSmall", fontName="Helvetica", fontSize=7.5,
                                textColor=MUTED, leading=11)
    sFooter = ParagraphStyle("Footer", fontName="Helvetica", fontSize=7.5,
                             textColor=MUTED, alignment=TA_CENTER, leading=11)
    sKpiLabel = ParagraphStyle("KpiLabel", fontName="Helvetica", fontSize=8,
                               textColor=MUTED, leading=12, alignment=TA_CENTER)
    sKpiValue = ParagraphStyle("KpiValue", fontName="Helvetica-Bold", fontSize=14,
                               textColor=WHITE, leading=19, alignment=TA_CENTER)

    elements = []

    # ═══ TITLE PAGE ═══
    elements.append(Spacer(1, 30))
    elements.append(Paragraph(f"Contributor Report", sTitle))
    elements.append(Paragraph(f"{rd['author']}", ParagraphStyle(
        "AuthorName", fontName="Helvetica-Bold", fontSize=18,
        textColor=ACCENT, leading=24, spaceAfter=12)))
    elements.append(Paragraph(
        f"Repository: {rd['owner']}/{rd['repo']}<br/>"
        f"Branch: {rd['branch']}<br/>"
        f"Report Date: {dt.datetime.now().strftime('%Y-%m-%d %H:%M UTC')}<br/>"
        f"Period: {rd['first_date']} — {rd['last_date']}", sSub))
    elements.append(Spacer(1, 8))

    # ═══ SUMMARY METRICS ═══
    elements.append(Paragraph("Summary Metrics", sH2))

    def _kpi_cell(label, value):
        return [Paragraph(label, sKpiLabel), Paragraph(str(value), sKpiValue)]

    kpi_grid = [
        [_kpi_cell("Total Commits", rd["total_commits"]),
         _kpi_cell("Lines Added", _fnum(rd["total_additions"])),
         _kpi_cell("Lines Removed", _fnum(rd["total_deletions"])),
         _kpi_cell("Net Lines", _fnum(rd["net_lines"]))],
        [_kpi_cell("Unique Files", rd["unique_files"]),
         _kpi_cell("Days Active", rd["days_active"]),
         _kpi_cell("Avg Commits/Day", rd["avg_per_day"]),
         _kpi_cell("Files/Commit", f"{rd['files_changed'] / max(rd['total_commits'], 1):.1f}")],
    ]
    # Flatten into table rows (label row + value row per kpi row)
    kpi_rows = []
    for row in kpi_grid:
        label_row = [cells[0] for cells in row]
        value_row = [cells[1] for cells in row]
        kpi_rows.append(label_row)
        kpi_rows.append(value_row)

    kpi_col_w = W / 4
    kpi_table = Table(kpi_rows, colWidths=[kpi_col_w] * 4)
    kpi_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), CARD_BG),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    elements.append(kpi_table)
    elements.append(Spacer(1, 16))

    # ═══ CHARTS ═══
    chart_order = [
        ("daily_activity", "Daily Commit Activity"),
        ("code_changes", "Code Changes per Commit"),
        ("file_class_pie", "Files by Classification"),
        ("file_ext_pie", "Files by Extension"),
        ("top_files", "Top Files by Commit Frequency"),
        ("top_churn", "Top Files by Code Churn"),
        ("cumulative", "Cumulative Lines Over Time"),
        ("day_of_week", "Commits by Day of Week"),
        ("size_dist", "Commit Size Distribution"),
    ]

    charts_added = 0
    for chart_key, chart_title in chart_order:
        img_bytes = chart_images.get(chart_key)
        if not img_bytes:
            continue
        # Start a new page for every 2 charts (each chart gets good space)
        if charts_added > 0 and charts_added % 2 == 0:
            elements.append(PageBreak())
        elements.append(Paragraph(chart_title, sH2))
        img_stream = io.BytesIO(img_bytes)
        # Use fixed dimensions that fit well on A4
        chart_w = W
        chart_h = W * 0.52
        img = RLImage(img_stream, width=chart_w, height=chart_h)
        img.hAlign = "CENTER"
        elements.append(img)
        elements.append(Spacer(1, 14))
        charts_added += 1

    # ═══ FILES TOUCHED TABLE ═══
    if file_analysis:
        elements.append(PageBreak())
        elements.append(Paragraph("All Files Touched by Author", sH2))
        elements.append(Paragraph(
            f"{len(file_analysis)} unique files modified across {rd['total_commits']} commits",
            sBody))
        fa_sorted = sorted(file_analysis.values(), key=lambda x: -x["commits"])
        file_header = [
            Paragraph("<b>File Path</b>", sCell),
            Paragraph("<b>Category</b>", sCell),
            Paragraph("<b>Ext</b>", sCell),
            Paragraph("<b>Commits</b>", sCell),
            Paragraph("<b>Lines +</b>", sCell),
            Paragraph("<b>Lines −</b>", sCell),
            Paragraph("<b>Net</b>", sCell),
        ]
        file_rows = [file_header]
        for fa in fa_sorted:
            file_rows.append([
                Paragraph(fa["filename"], sCellSmall),
                Paragraph(fa["classification"], sCellSmall),
                Paragraph(fa["extension"], sCellSmall),
                Paragraph(str(fa["commits"]), sCellSmall),
                Paragraph(str(fa["additions"]), sCellSmall),
                Paragraph(str(fa["deletions"]), sCellSmall),
                Paragraph(str(fa["net"]), sCellSmall),
            ])

        col_widths = [W * 0.34, W * 0.14, W * 0.08, W * 0.1, W * 0.1, W * 0.1, W * 0.1]
        ft = Table(file_rows, colWidths=col_widths, repeatRows=1)
        ft.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), HEADER_BG),
            ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("BACKGROUND", (0, 1), (-1, -1), CARD_BG),
            ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
            ("ALIGN", (3, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, 0), 8),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
            ("TOPPADDING", (0, 1), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 1), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [CARD_BG, BG]),
        ]))
        elements.append(ft)

    # ═══ FULL COMMIT LOG ═══
    elements.append(PageBreak())
    elements.append(Paragraph("Complete Commit History", sH2))
    elements.append(Paragraph(
        f"{len(enriched)} commits from {rd['first_date']} to {rd['last_date']}  ·  "
        f"Branch: {rd['branch']}", sBody))

    commit_header = [
        Paragraph("<b>SHA</b>", sCell),
        Paragraph("<b>Date</b>", sCell),
        Paragraph("<b>Message</b>", sCell),
        Paragraph("<b>+</b>", sCell),
        Paragraph("<b>−</b>", sCell),
        Paragraph("<b>Files</b>", sCell),
    ]
    commit_rows = [commit_header]
    for c in enriched:
        msg = c["message"]
        if len(msg) > 90:
            msg = msg[:87] + "..."
        commit_rows.append([
            Paragraph(c["sha"], sCellSmall),
            Paragraph(c["date_str"], sCellSmall),
            Paragraph(msg, sCellSmall),
            Paragraph(str(c["additions"]), sCellSmall),
            Paragraph(str(c["deletions"]), sCellSmall),
            Paragraph(str(c["files_changed"]), sCellSmall),
        ])

    cc_widths = [W * 0.08, W * 0.13, W * 0.49, W * 0.08, W * 0.08, W * 0.08]
    ct = Table(commit_rows, colWidths=cc_widths, repeatRows=1)
    ct.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("BACKGROUND", (0, 1), (-1, -1), CARD_BG),
        ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
        ("ALIGN", (3, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, 0), 8),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
        ("TOPPADDING", (0, 1), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [CARD_BG, BG]),
    ]))
    elements.append(ct)

    # ═══ PER-COMMIT FILE DETAILS ═══
    elements.append(PageBreak())
    elements.append(Paragraph("Detailed File Changes per Commit", sH2))
    elements.append(Paragraph(
        "Each commit with its individual file-level additions, deletions and change status.",
        sBody))

    for c in enriched:
        file_detail = c.get("_file_details", [])
        if not file_detail:
            continue
        msg_short = c["message"][:65] + ("..." if len(c["message"]) > 65 else "")
        heading = f'<b>{c["sha"]}</b>  ·  {c["date_str"]}  ·  {msg_short}'
        elements.append(Paragraph(heading, sH3))

        rows = [[
            Paragraph("<b>File</b>", sCell),
            Paragraph("<b>Status</b>", sCell),
            Paragraph("<b>+</b>", sCell),
            Paragraph("<b>−</b>", sCell),
            Paragraph("<b>Total</b>", sCell),
        ]]
        for fd in file_detail:
            rows.append([
                Paragraph(fd.get("filename", ""), sCellSmall),
                Paragraph(fd.get("status", ""), sCellSmall),
                Paragraph(str(fd.get("additions", 0)), sCellSmall),
                Paragraph(str(fd.get("deletions", 0)), sCellSmall),
                Paragraph(str(fd.get("changes", 0)), sCellSmall),
            ])
        fd_widths = [W * 0.46, W * 0.12, W * 0.1, W * 0.1, W * 0.1]
        fdt = Table(rows, colWidths=fd_widths, repeatRows=1)
        fdt.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), HEADER_BG),
            ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
            ("BACKGROUND", (0, 1), (-1, -1), CARD_BG),
            ("GRID", (0, 0), (-1, -1), 0.3, BORDER),
            ("ALIGN", (2, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, 0), 7),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 7),
            ("TOPPADDING", (0, 1), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 1), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ]))
        elements.append(fdt)
        elements.append(Spacer(1, 10))

    # ── End-of-report marker ──
    elements.append(Spacer(1, 30))
    elements.append(Paragraph("— End of Report —", ParagraphStyle(
        "EndMark", fontName="Helvetica-Bold", fontSize=10,
        textColor=MUTED, alignment=TA_CENTER, leading=14)))
    elements.append(Spacer(1, 8))
    elements.append(Paragraph(
        f"Generated by GAM Software PM · ISO 27001 Compliance Platform · "
        f"{dt.datetime.now().strftime('%Y-%m-%d %H:%M UTC')}", sFooter))

    doc.build(elements, onFirstPage=_on_page, onLaterPages=_on_page)
    return buf.getvalue()


def _gen_author_report(rd, commits):
    """Legacy HTML fallback — no longer primary."""
    return ""


# ═══════════════════════════════════════════════════════════════
# Main Application
# ═══════════════════════════════════════════════════════════════

def main():
    st.set_page_config(
        page_title="GAM Software PM \u00b7 ISO 27001",
        page_icon="\U0001f6e1\ufe0f",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

    # ── Sidebar ──
    with st.sidebar:
        logo = _inline_logo()
        if logo:
            st.markdown(f'''
            <div class="sidebar-brand">
                <img src="data:image/png;base64,{logo}" alt="">
                <div><div class="n">GAM Software PM</div>
                <div class="t">ISO 27001 Compliance Platform</div></div>
            </div>''', unsafe_allow_html=True)
        else:
            st.markdown("### GAM Software PM")
            st.caption("ISO 27001 Compliance Platform")

        st.markdown("")

        repo_url = st.text_input(
            "Repository URL",
            value=st.session_state.get("repo_url", ""),
            placeholder="https://github.com/owner/repo/tree/branch",
            help="Paste a GitHub URL. Include /tree/branch to target a specific branch.",
        )

        lc, rc = st.columns(2)
        with lc:
            load_btn = st.button("Load", type="primary", width='stretch')
        with rc:
            refresh_btn = st.button("Refresh", width='stretch')

        st.markdown("---")

        section = st.radio("Navigation", NAV_SECTIONS, index=0)

        st.markdown("---")

        # Token status indicator
        if GITHUB_TOKEN:
            _tok_preview = GITHUB_TOKEN[:8] + "..." + GITHUB_TOKEN[-4:]
            st.caption(f"🟢 API Token loaded (`{_tok_preview}`)")
        else:
            st.caption("🔴 No API token — unauthenticated (60 req/hr limit)")

        if "branch_data" in st.session_state and st.session_state.branch_data:
            d = st.session_state.branch_data
            st.caption(f"**{d['owner']}/{d['repo']}**")
            st.caption(f"Branch: `{d['branch']}`")
            st.caption(f"Commits: {len(d['commits'])} \u00b7 Files: {len(d['files'])}")
            st.caption(f"Updated: {_fmt(d['fetched_at'], '%H:%M:%S')}")

    # ── Load / Refresh ──
    if load_btn or refresh_btn:
        try:
            owner, repo, branch_hint = _parse_url(repo_url)
            st.session_state.repo_url = repo_url
            if not branch_hint:
                info = _fetch_repo(owner, repo)
                if not info or not info.get("default_branch"):
                    raise RuntimeError(
                        f"Repository '{owner}/{repo}' not found or not accessible. "
                        "Check the URL and ensure your token has access."
                    )
                branch_hint = info.get("default_branch", "main")
            with st.spinner(f"Loading {owner}/{repo} @ {branch_hint}..."):
                if refresh_btn:
                    st.cache_data.clear()
                data = collect_branch_data(owner, repo, branch_hint)
                st.session_state.branch_data = data
                st.session_state.last_error = None
        except Exception as e:
            st.session_state.branch_data = None
            st.session_state.last_error = str(e)

    if st.session_state.get("last_error"):
        st.error(st.session_state.last_error)

    # ── Content ──
    D = st.session_state.get("branch_data")
    if not D:
        st.markdown("""
        <div class="hero-welcome">
            <div class="hw-icon">\U0001f6e1\ufe0f</div>
            <div class="hw-title">GAM Software PM</div>
            <div class="hw-sub">
                ISO 27001 Compliance & Project Management Platform<br>
                Paste a GitHub repository URL in the sidebar and click <b>Load</b> to begin.
            </div>
            <div class="hw-tags">
                <b>Branch-level intelligence</b> &middot;
                <b>Asset inventory</b> &middot;
                <b>Change management</b> &middot;
                <b>Audit documentation</b>
            </div>
        </div>""", unsafe_allow_html=True)
        return

    st.markdown(
        f'<div class="ts-bar">Data fetched {_fmt(D["fetched_at"], "%Y-%m-%d %H:%M:%S UTC")} \u00b7 '
        f'Auto-refresh: {CACHE_TTL}s \u00b7 '
        f'<a href="{D["repo_url"]}" target="_blank">Open on GitHub \u2197</a></div>',
        unsafe_allow_html=True,
    )

    routes = {
        "\U0001f4ca Command Center": page_command_center,
        "\U0001f4e6 Asset Inventory": page_asset_inventory,
        "\U0001f4dc Change Ledger": page_change_ledger,
        "\U0001f510 Access Registry": page_access_registry,
        "\U0001f6a8 Incident Log": page_incident_log,
        "\U0001f500 Pull Requests": page_pull_requests,
        "\U0001f9e0 Author Intelligence": page_author_intelligence,
        "\U0001f4c5 Project Timeline": page_project_timeline,
        "\U0001f6e1\ufe0f Compliance Hub": page_compliance_hub,
    }

    handler = routes.get(section)
    if handler:
        handler(D)


if __name__ == "__main__":
    main()
