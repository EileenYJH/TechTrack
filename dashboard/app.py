"""
TechTrack Dashboard — full AI Studio redesign.
Run: streamlit run dashboard/app.py
"""
import sys
import re
import html as _html
from pathlib import Path
from datetime import datetime

import streamlit as st
import pandas as pd
import yaml

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from src.db import init_db, get_all_events, get_stats, get_run_logs, toggle_bookmark

# ── Junk/HTML filters ─────────────────────────────────────────────────────────
_CODE_RE = re.compile(
    r'[{}\[\]]|=>|\bfunction\b|\bimport\b|\bconst\b|\blet\b|\bvar\b'
    r'|\bdef\b|\bclass\b|npm |pip |\.js\b|\.py\b|</|/>|<!--', re.IGNORECASE
)
_HTML_TAG_RE = re.compile(r'<[^>]+>')

def _strip_html(text: str) -> str:
    t = _HTML_TAG_RE.sub(' ', text or '')
    return _html.unescape(re.sub(r'\s{2,}', ' ', t)).strip()

def _safe(text: str) -> str:
    return _html.escape(_strip_html(text)).replace('`', "'")

def _is_junk(ev: dict) -> bool:
    title = (ev.get('title') or '').strip()
    if not title or len(title) < 6 or len(title) > 250:
        return True
    if _CODE_RE.search(title):
        return True
    if re.search(r'[^a-zA-Z0-9\s\-–,.()/\'\\":!?]{2,}', title):
        return True
    return False

# ── Category normalisation ────────────────────────────────────────────────────
_CAT_MAP = {
    "bootcamp":                            "Workshop / Bootcamp",
    "webinar":                             "Seminar / Talk",
    "seminar":                             "Seminar / Talk",
    "talk":                                "Seminar / Talk",
    "workshop":                            "Workshop / Bootcamp",
    "event":                               "Other",
    "exhibition":                          "Other",
    "tour/visit":                          "Company Visit",
    "company visit / kemasukan":           "Company Visit",
    "distance learning / pengajian asasi": "Other",
    "prasiswazah / entry scholarship":     "Other",
    "open day":                            "Other",
    "makerthon":                           "Hackathon",
    "university event":                    "Other",
}

def _cat(ev_or_str) -> str:
    raw = ev_or_str if isinstance(ev_or_str, str) else (ev_or_str.get('category') or 'Other')
    return _CAT_MAP.get(raw.strip().lower(), raw.strip() or 'Other')

# ── Derived fields ────────────────────────────────────────────────────────────
def _origin(ev: dict) -> str:
    c = (ev.get('country') or '').lower()
    return 'Malaysia' if 'malaysia' in c else 'International'

def _platform(ev: dict) -> str:
    src = (ev.get('source_name') or '').lower()
    if 'instagram' in src:
        return 'Instagram'
    if any(k in src for k in ['utm', 'um ', 'utp', 'mmu', 'upm', 'utar', 'sunway', 'apu', 'taylor', 'univ']):
        return 'University'
    return 'Web'

def _interest(ev: dict) -> str:
    title = (ev.get('title') or '').lower()
    ee_kw = ['ee', 'electrical', 'electronic', 'circuit', 'embedded', 'robotics',
             'semiconductor', 'hardware', 'mechatronics', 'ieee', 'pcb', 'fpga',
             'microcontroller', 'power', 'signal', 'analog', 'digital design']
    return 'EE Related' if any(k in title for k in ee_kw) else 'Technology Related'

def _parse_dt(val):
    if not val:
        return None
    try:
        return datetime.fromisoformat(str(val))
    except Exception:
        return None

def _days_badge(start) -> str:
    if not start:
        return ''
    days = (start.date() - datetime.now().date()).days
    if days < 0:
        return ''
    if days == 0:
        cls, lbl = 'badge-urgent', 'TODAY'
    elif days <= 7:
        cls, lbl = 'badge-urgent', f'{days}D LEFT'
    elif days <= 30:
        cls, lbl = 'badge-soon', f'{days}D LEFT'
    else:
        cls, lbl = 'badge-ok', f'{days}D LEFT'
    return f'<span class="days-badge {cls}">{lbl}</span>'

def _timeline_html(ev: dict) -> str:
    start = _parse_dt(ev.get('start_date'))
    dead  = _parse_dt(ev.get('deadline'))
    now   = datetime.now()
    items = []
    # Scraped
    scraped = _parse_dt(ev.get('scraped_at'))
    if scraped:
        items.append(('Discovery Pipeline', scraped.strftime('%d %b %Y'), 'completed'))
    # Deadline
    if dead:
        st_dl = 'active' if dead >= now else 'completed'
        items.append(('Registration Deadline', dead.strftime('%d %b %Y'), st_dl))
    # Event date
    if start:
        st_ev = 'upcoming' if start > now else 'active' if start.date() == now.date() else 'completed'
        items.append(('Event Date', start.strftime('%d %b %Y'), st_ev))

    next_item = next((i for i in items if i[2] in ('active', 'upcoming')), items[-1] if items else None)
    if not next_item:
        return ''

    status_cls = {'completed': 'tl-done', 'active': 'tl-active', 'upcoming': 'tl-soon'}.get(next_item[2], 'tl-soon')
    return (
        '<div class="card-timeline">'
        '<span class="tl-label">Next Stage:</span>'
        f'<span class="tl-name">{next_item[0]}</span>'
        f'<span class="tl-date {status_cls}">{next_item[1]}</span>'
        '</div>'
    )

# ── Card colour config ────────────────────────────────────────────────────────
CAT_GRADIENT = {
    "Hackathon":           "linear-gradient(160deg,#2d1b69,#4c1d95,#7c3aed)",
    "Competition":         "linear-gradient(160deg,#450a0a,#7f1d1d,#dc2626)",
    "Career Fair":         "linear-gradient(160deg,#052e16,#14532d,#16a34a)",
    "Conference":          "linear-gradient(160deg,#0c1445,#1e3a8a,#2563eb)",
    "Workshop / Bootcamp": "linear-gradient(160deg,#431407,#7c2d12,#ea580c)",
    "Seminar / Talk":      "linear-gradient(160deg,#3f1f07,#78350f,#d97706)",
    "Company Visit":       "linear-gradient(160deg,#0f172a,#1e293b,#475569)",
    "Other":               "linear-gradient(160deg,#0f172a,#1e293b,#475569)",
}
CAT_BADGE_CLS = {
    "Hackathon":           "cat-hackathon",
    "Competition":         "cat-competition",
    "Career Fair":         "cat-career",
    "Conference":          "cat-conference",
    "Workshop / Bootcamp": "cat-workshop",
    "Seminar / Talk":      "cat-seminar",
    "Company Visit":       "cat-visit",
    "Other":               "cat-other",
}
CAT_TAG = {
    "Hackathon":           "HACK_EX",
    "Competition":         "COMP_SG",
    "Career Fair":         "CAREER",
    "Conference":          "CONF_NX",
    "Workshop / Bootcamp": "WRKSHP",
    "Seminar / Talk":      "TALK_EV",
    "Company Visit":       "VISIT",
    "Other":               "GEN_EV",
}

GROUPS = [
    ("Competitions & Hackathons", ["Competition", "Hackathon"]),
    ("Workshops & Seminars",      ["Workshop / Bootcamp", "Seminar / Talk"]),
    ("Conferences",               ["Conference"]),
    ("Career Fairs & Others",     ["Career Fair", "Company Visit", "Other"]),
]

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="TechTrack | Events Nexus",
    page_icon="T",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── CSS ───────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap');
@import url('https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:opsz,wght,FILL,GRAD@20..48,100..700,0..1,-50..200&display=swap');

html, body, [class*="css"] {
    font-family: 'Inter', sans-serif !important;
    background-color: #f7fafd !important;
    color: #181c1e !important;
}
#MainMenu, footer, header { visibility: hidden; }

/* Scanline */
body::before {
    content: " "; display: block; position: fixed; inset: 0;
    background: linear-gradient(rgba(255,255,255,0) 50%, rgba(0,0,0,0.03) 50%),
                linear-gradient(90deg, rgba(74,62,230,0.02), rgba(0,255,0,0.005), rgba(0,0,255,0.02));
    z-index: 9999; background-size: 100% 4px, 3px 100%;
    pointer-events: none; opacity: 0.15;
}
/* Grid bg */
body::after {
    content: ""; position: fixed; inset: 0;
    background-image:
        linear-gradient(to right, rgba(74,62,230,0.04) 1px, transparent 1px),
        linear-gradient(to bottom, rgba(74,62,230,0.04) 1px, transparent 1px);
    background-size: 60px 60px; pointer-events: none; z-index: 0;
}

/* Sidebar */
section[data-testid="stSidebar"] {
    background: rgba(255,255,255,0.92) !important;
    backdrop-filter: blur(12px);
    border-right: 1px solid rgba(74,62,230,0.15) !important;
}
section[data-testid="stSidebar"] > div { background: transparent !important; }

/* Cyber card */
.cyber-card {
    background: rgba(255,255,255,0.88);
    backdrop-filter: blur(10px);
    border: 1px solid rgba(74,62,230,0.15);
    clip-path: polygon(0 0, 100% 0, 100% calc(100% - 14px), calc(100% - 14px) 100%, 0 100%);
    transition: border-color .3s, transform .3s, box-shadow .3s;
    position: relative; overflow: hidden; margin-bottom: 1rem;
}
.cyber-card:hover {
    border-color: #4a3ee6;
    transform: translateY(-3px);
    box-shadow: 0 12px 36px rgba(74,62,230,0.12);
}
.cyber-card::after {
    content: ""; position: absolute; top: 0; left: 0;
    width: 100%; height: 3px;
    background: linear-gradient(90deg, #3cd7ff, transparent);
    opacity: 0.6;
}

/* Card image */
.card-img-wrap {
    height: 160px; position: relative; overflow: hidden;
    background: #ebeef1;
}
.card-img-wrap img {
    width: 100%; height: 100%; object-fit: cover;
    transition: transform .7s ease;
}
.cyber-card:hover .card-img-wrap img { transform: scale(1.07); }
.card-img-gradient {
    position: absolute; inset: 0;
    background: linear-gradient(to top, rgba(255,255,255,0.95) 0%, rgba(255,255,255,0.3) 50%, rgba(0,0,0,0.2) 100%);
}
.card-img-fallback {
    width: 100%; height: 100%; display: block;
}
.cat-pin {
    position: absolute; bottom: 10px; right: 12px;
    padding: 3px 10px; background: rgba(255,255,255,0.92);
    backdrop-filter: blur(6px); border: 1px solid rgba(74,62,230,0.25);
    font-size: .68rem; font-weight: 800; letter-spacing: .1em;
    text-transform: uppercase; color: #4a3ee6; font-family: monospace;
    clip-path: polygon(0 0,100% 0,100% calc(100% - 5px),calc(100% - 5px) 100%,0 100%);
}
.bm-badge {
    position: absolute; top: 10px; right: 12px;
    padding: 3px 10px; background: #4a3ee6;
    color: white; font-size: .65rem; font-weight: 800;
    letter-spacing: .1em; text-transform: uppercase;
    font-family: monospace; animation: pulse-glow 2s infinite;
}
@keyframes pulse-glow {
    0%,100% { box-shadow: 0 0 5px rgba(74,62,230,0.3); }
    50% { box-shadow: 0 0 12px rgba(74,62,230,0.6); }
}

/* Card body */
.card-body { padding: .85rem 1rem .75rem; }

.badge-row { display: flex; flex-wrap: wrap; gap: 5px; margin-bottom: 7px; }
.badge-pill {
    padding: 2px 8px; font-size: .68rem; font-weight: 800;
    letter-spacing: .08em; text-transform: uppercase;
    font-family: monospace; border-radius: 2px;
}
.badge-my  { background:#fef9c3; color:#854d0e; border:1px solid #fde047; }
.badge-int { background:#ede9fe; color:#4338ca; border:1px solid #a5b4fc; }
.badge-ee  { background:#dcfce7; color:#166534; border:1px solid #86efac; }
.badge-tech{ background:#e0f2fe; color:#075985; border:1px solid #7dd3fc; }
.badge-web { background:#f1f5f9; color:#475569; border:1px solid #cbd5e1; }
.badge-uni { background:#faf5ff; color:#7c3aed; border:1px solid #d8b4fe; }
.badge-ig  { background:#fce7f3; color:#9d174d; border:1px solid #f9a8d4; }

.tag-row { display:flex; align-items:center; gap:6px; margin-bottom:5px; flex-wrap:wrap; }
.tag-pill {
    padding: 2px 8px; border: 1px solid rgba(74,62,230,0.3);
    color: #4a3ee6; font-size: .67rem; font-weight: 800;
    letter-spacing: .08em; text-transform: uppercase; font-family: monospace;
    border-radius: 2px;
}
.tag-date { font-size:.72rem; font-weight:700; color:#43474d; font-family:monospace; text-transform:uppercase; }
.days-badge {
    font-size:.65rem; font-weight:800; letter-spacing:.08em; padding:2px 7px;
    text-transform:uppercase; font-family:monospace; border-radius:2px;
}
.badge-urgent { background:#fee2e2; color:#7f1d1d; border:1px solid #fca5a5; }
.badge-soon   { background:#ffedd5; color:#7c2d12; border:1px solid #fdba74; }
.badge-ok     { background:#dbeafe; color:#1e3a8a; border:1px solid #93c5fd; }

.card-title {
    font-size:.88rem; font-weight:900; color:#000f22;
    text-transform:uppercase; letter-spacing:.02em; font-style:italic;
    line-height:1.3; margin-bottom:5px;
}
.card-title a { color:#000f22; text-decoration:none; transition:color .2s; }
.card-title a:hover { color:#4a3ee6; }

.card-meta { font-size:.72rem; color:#64748b; margin-bottom:4px; }
.card-deadline { font-size:.7rem; color:#dc2626; font-weight:700; margin-bottom:4px; }

/* Timeline snapshot */
.card-timeline {
    background:#f8fafc; border:1px dashed rgba(74,62,230,0.2);
    padding: 5px 8px; margin-bottom:6px; font-family:monospace;
    display:flex; align-items:center; gap:6px; flex-wrap:wrap;
}
.tl-label { font-size:.62rem; font-weight:900; text-transform:uppercase; color:#94a3b8; letter-spacing:.1em; }
.tl-name  { font-size:.72rem; font-weight:800; color:#000f22; text-transform:uppercase; }
.tl-date  { font-size:.65rem; font-weight:800; padding:1px 6px; border-radius:2px; margin-left:auto; }
.tl-done  { background:#dcfce7; color:#14532d; }
.tl-active{ background:#fef3c7; color:#78350f; }
.tl-soon  { background:#dbeafe; color:#1e3a8a; }

/* Cat-specific badges */
.cat-hackathon   { background:#ede9fe; color:#4c1d95; border:1px solid #c4b5fd; }
.cat-competition { background:#fee2e2; color:#7f1d1d; border:1px solid #fca5a5; }
.cat-career      { background:#dcfce7; color:#14532d; border:1px solid #86efac; }
.cat-conference  { background:#dbeafe; color:#1e3a8a; border:1px solid #93c5fd; }
.cat-workshop    { background:#ffedd5; color:#7c2d12; border:1px solid #fdba74; }
.cat-seminar     { background:#fef3c7; color:#78350f; border:1px solid #fcd34d; }
.cat-visit       { background:#f1f5f9; color:#334155; border:1px solid #cbd5e1; }
.cat-other       { background:#f1f5f9; color:#334155; border:1px solid #cbd5e1; }

/* Stat card */
.stat-card {
    background:rgba(255,255,255,0.88); border:1px solid rgba(74,62,230,0.15);
    clip-path:polygon(0 0,100% 0,100% calc(100% - 10px),calc(100% - 10px) 100%,0 100%);
    padding:1.2rem 1.4rem; position:relative; text-align:center;
}
.stat-card::after {
    content:""; position:absolute; top:0; left:0;
    width:100%; height:3px;
    background:linear-gradient(90deg,#4a3ee6,transparent); opacity:.4;
}
.stat-val { font-size:2.4rem; font-weight:900; color:#000f22; font-style:italic; font-family:monospace; line-height:1; }
.stat-lbl { font-size:.65rem; color:#64748b; margin-top:.3rem; text-transform:uppercase; letter-spacing:.14em; font-weight:700; }
.stat-card-hi { border-color:rgba(74,62,230,0.35) !important; background:rgba(74,62,230,0.04) !important; }
.stat-card-hi .stat-val { color:#4a3ee6; }
.stat-card-hi .stat-lbl { color:#4a3ee6; }

/* Section header */
.section-hdr {
    font-size:.78rem; font-weight:900; color:#000f22;
    text-transform:uppercase; letter-spacing:.15em;
    border-left:4px solid #4a3ee6; padding-left:.85rem;
    margin: 1.5rem 0 1rem 0; position:relative;
}
.section-hdr::after {
    content:""; position:absolute; bottom:-6px; left:0;
    width:40px; height:2px; background:#4a3ee6;
}
.section-count { color:#94a3b8; font-weight:600; margin-left:8px; font-style:normal; }

/* Cyber button */
.cyber-btn {
    background:transparent; border:1px solid #4a3ee6; color:#4a3ee6;
    text-transform:uppercase; letter-spacing:.08em; position:relative;
    overflow:hidden; transition:.3s; font-weight:700; font-family:monospace;
    font-size:.72rem; padding:4px 12px; cursor:pointer;
    clip-path:polygon(0 0,100% 0,100% calc(100% - 6px),calc(100% - 6px) 100%,0 100%);
}
.cyber-btn:hover { background:#4a3ee6; color:#fff; box-shadow:0 4px 14px rgba(74,62,230,0.25); }

/* Auto-renew panel */
.pipeline-panel {
    background:#0f172a; border:2px solid #1e293b; padding:1.25rem 1.5rem;
    margin-bottom:1.5rem; position:relative; overflow:hidden;
}
.pipeline-panel::before {
    content:""; position:absolute; top:0; left:0;
    width:100%; height:2px;
    background:linear-gradient(90deg,#4a3ee6,#3cd7ff,#4a3ee6);
}
.pipeline-dot {
    width:10px; height:10px; border-radius:50%; display:inline-block;
    margin-right:6px; vertical-align:middle;
    animation:ping 1.5s cubic-bezier(0,0,.2,1) infinite;
}
@keyframes ping { 75%,100% { transform:scale(2); opacity:0; } }
.pipeline-log {
    background:rgba(15,23,42,0.9); padding:8px 12px;
    font-family:monospace; font-size:.72rem; color:#3cd7ff;
    border:1px solid #1e293b; margin-top:8px;
}

/* Filter desk */
.filter-panel {
    background:#fff; border:1px solid rgba(196,198,206,0.75);
    padding:1rem 1.25rem; margin-bottom:1.5rem;
}
.filter-label {
    font-size:.65rem; font-weight:900; text-transform:uppercase;
    letter-spacing:.15em; color:#74777e; font-family:monospace;
    margin-bottom:5px; display:block;
}

/* Streamlit overrides */
div[data-testid="stButton"] > button {
    border-radius:2px !important; font-weight:700 !important;
    letter-spacing:.06em !important; text-transform:uppercase !important;
    font-family:monospace !important; font-size:.72rem !important;
}
div[data-testid="stTextInput"] input {
    border-radius:4px !important; font-family:monospace !important;
    background: #f1f5f9 !important; font-size:.85rem !important;
}
</style>
""", unsafe_allow_html=True)

# ── Session state ─────────────────────────────────────────────────────────────
if 'tab'            not in st.session_state: st.session_state.tab             = 'discovery'
if 'search'         not in st.session_state: st.session_state.search          = ''
if 'cat_filter'     not in st.session_state: st.session_state.cat_filter      = 'All Events'
if 'origin_filter'  not in st.session_state: st.session_state.origin_filter   = 'All'
if 'platform_filter'not in st.session_state: st.session_state.platform_filter = 'All'
if 'interest_filter'not in st.session_state: st.session_state.interest_filter = 'All'
if 'show_past'      not in st.session_state: st.session_state.show_past       = False
if 'renew_running'  not in st.session_state: st.session_state.renew_running   = False
if 'renew_log'      not in st.session_state: st.session_state.renew_log       = 'Ingestion engine idle.'

# ── DB + config ───────────────────────────────────────────────────────────────
init_db()
with open(ROOT / 'config.yaml') as f:
    cfg = yaml.safe_load(f)

stats = get_stats()

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("""
    <div style="padding:1rem .5rem 1.5rem .5rem">
        <div style="font-size:1.5rem;font-weight:900;letter-spacing:-.02em;font-style:italic">
            <span style="color:#4a3ee6">TECH</span><span style="color:#000f22">TRACK</span>
        </div>
        <div style="font-size:.6rem;font-weight:700;letter-spacing:.18em;text-transform:uppercase;color:#94a3b8;margin-top:2px">
            Sector: Events_Nexus_01
        </div>
    </div>
    """, unsafe_allow_html=True)

    def _nav(label: str, key: str, icon: str):
        active = st.session_state.tab == key
        style = (
            "background:linear-gradient(90deg,rgba(74,62,230,.1),transparent);"
            "border-left:3px solid #4a3ee6;color:#4a3ee6;font-weight:800;"
            if active else "color:#43474d;"
        )
        if st.button(
            f"{icon}  {label}",
            key=f"nav_{key}",
            use_container_width=True,
            type="secondary",
        ):
            st.session_state.tab = key
            st.session_state.cat_filter = 'All Events'
            st.rerun()

    _nav("CORE_DASH",  "dashboard",  "▣")
    _nav("DISCOVERY",  "discovery",  "◈")
    _nav("MY_EVENTS",  "my-events",  "★")
    _nav("RUN_LOGS",   "logs",       "≡")

    st.divider()

    st.session_state.search = st.text_input(
        "Search", placeholder="IEEE, hackathon, robotics…",
        value=st.session_state.search, label_visibility="collapsed"
    )
    st.session_state.show_past = st.toggle("Show past events", value=st.session_state.show_past)

    st.divider()

    if st.button("LAUNCH_AUTO_RENEW", use_container_width=True, type="primary"):
        with st.spinner("Running scraper pipeline…"):
            try:
                from runner import run_all
                run_all(verbose=False)
                st.success("Pipeline complete. Refresh to see new events.")
                st.rerun()
            except Exception as e:
                st.error(f"Pipeline error: {e}")

    with st.expander("Add source"):
        new_name    = st.text_input("Name",    key="new_name")
        new_url     = st.text_input("URL",     key="new_url")
        new_type    = st.selectbox("Type", ["universities","organizations","companies","aggregators"], key="new_type")
        new_country = st.text_input("Country", value="Malaysia", key="new_country")
        if st.button("Add"):
            if new_name and new_url:
                cfg[new_type].append({"name": new_name, "url": new_url, "country": new_country})
                with open(ROOT / 'config.yaml', 'w') as f:
                    yaml.dump(cfg, f, allow_unicode=True, sort_keys=False)
                st.success(f"Added {new_name}.")
            else:
                st.warning("Fill in name and URL.")

# ── Event card renderer ───────────────────────────────────────────────────────
def _render_card(ev: dict, key_prefix: str):
    eid   = ev.get('id', '')
    cat   = _cat(ev)
    title = _safe(ev.get('title') or 'Untitled')
    url   = ev.get('event_url') or ''
    if not url or url in ('null', 'None', ''):
        url = '#'
    else:
        url = _html.escape(url)

    img     = ev.get('image_url') or ''
    is_bm   = bool(ev.get('bookmarked', 0))
    start   = _parse_dt(ev.get('start_date'))
    dead    = _parse_dt(ev.get('deadline'))
    src     = _safe(ev.get('source_name') or '')
    date_str= start.strftime('%d %b %Y') if start else 'Date TBA'
    grad    = CAT_GRADIENT.get(cat, CAT_GRADIENT['Other'])
    cat_cls = CAT_BADGE_CLS.get(cat, 'cat-other')
    tag_lbl = CAT_TAG.get(cat, 'EVENT')
    origin  = _origin(ev)
    plat    = _platform(ev)
    interest= _interest(ev)

    # Image block
    if img and img.startswith('http'):
        img_html = (
            f'<img src="{_html.escape(img)}" alt="" '
            'referrerpolicy="no-referrer" '
            'onerror="this.style.display=\'none\';this.nextSibling.style.display=\'block\'" '
            f'style="width:100%;height:100%;object-fit:cover;display:block">'
            f'<div style="width:100%;height:100%;{grad};display:none"></div>'
        )
    else:
        img_html = f'<div style="width:100%;height:100%;background:{grad}"></div>'

    bm_html = '<span class="bm-badge">REGISTERED</span>' if is_bm else ''
    days_html = _days_badge(start)
    dead_html = f'<div class="card-deadline">Deadline: {dead.strftime("%d %b %Y")}</div>' if dead else ''
    tl_html   = _timeline_html(ev)

    origin_cls = 'badge-my' if origin == 'Malaysia' else 'badge-int'
    origin_lbl = 'MALAYSIA' if origin == 'Malaysia' else 'INT_NEXUS'
    int_cls    = 'badge-ee' if interest == 'EE Related' else 'badge-tech'
    plat_cls   = {'Instagram': 'badge-ig', 'University': 'badge-uni'}.get(plat, 'badge-web')

    # Validate location
    raw_loc = _strip_html(ev.get('location') or '')
    loc_display = ''
    if raw_loc and len(raw_loc) >= 3:
        fc = raw_loc[0]
        if fc.isupper() and len(raw_loc) <= 60 and not raw_loc.lower().startswith(('ation', 'ion ', 'ng ', 'ed ', 'ing ')):
            loc_display = raw_loc

    meta_parts = [date_str, src]
    if loc_display:
        meta_parts.append(_html.escape(loc_display))
    meta_str = ' &nbsp;/&nbsp; '.join(p for p in meta_parts if p)

    # Raw clean description for separate rendering
    raw_desc = _strip_html((ev.get('description') or '')[:300]).strip()
    desc_display = raw_desc[:150] + ('…' if len(raw_desc) > 150 else '') if raw_desc else ''

    card_html = (
        '<div class="cyber-card">'
        f'<div class="card-img-wrap">{img_html}'
        '<div class="card-img-gradient"></div>'
        f'{bm_html}'
        f'<span class="cat-pin {cat_cls}">{_html.escape(cat)}</span>'
        '</div>'
        '<div class="card-body">'
        f'<div class="badge-row">'
        f'<span class="badge-pill {origin_cls}">{origin_lbl}</span>'
        f'<span class="badge-pill {int_cls}">{_html.escape(interest)}</span>'
        f'<span class="badge-pill {plat_cls}">{_html.escape(plat)}</span>'
        '</div>'
        f'<div class="tag-row">'
        f'<span class="tag-pill">{_html.escape(tag_lbl)}</span>'
        f'<span class="tag-date">{_html.escape(date_str)}</span>'
        f'{days_html}'
        '</div>'
        f'<div class="card-title"><a href="{url}" target="_blank">{title}</a></div>'
        f'<div class="card-meta">{meta_str}</div>'
        f'{dead_html}'
        f'{tl_html}'
        '</div></div>'
    )

    col_card, col_btn = st.columns([5, 1])
    with col_card:
        st.markdown(card_html, unsafe_allow_html=True)
        if desc_display:
            st.markdown(
                f'<p style="font-size:.76rem;color:#475569;margin:-8px 0 10px 0;line-height:1.45;padding:0 2px">'
                f'{_html.escape(desc_display)}</p>',
                unsafe_allow_html=True,
            )
    with col_btn:
        st.markdown('<div style="margin-top:20px">', unsafe_allow_html=True)
        if eid and st.button('★' if is_bm else '☆', key=f'bm_{key_prefix}_{eid}',
                             help='Toggle bookmark', use_container_width=True):
            toggle_bookmark(eid)
            st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)


# ── Load events ───────────────────────────────────────────────────────────────
all_events = get_all_events(
    upcoming_only=not st.session_state.show_past,
    search=st.session_state.search or None,
)

def _apply_filters(events):
    out = []
    for e in events:
        if _is_junk(e):
            continue
        if st.session_state.cat_filter not in ('All Events', ''):
            if _cat(e) != st.session_state.cat_filter:
                # Also check loose mapping
                cats_map = {
                    'Hackathon': ['Hackathon', 'Makerthon'],
                    'Workshop': ['Workshop / Bootcamp'],
                    'Talk': ['Seminar / Talk'],
                    'Company Visit': ['Company Visit'],
                }
                mapped = cats_map.get(st.session_state.cat_filter, [st.session_state.cat_filter])
                if _cat(e) not in mapped:
                    continue
        if st.session_state.origin_filter != 'All':
            if _origin(e) != st.session_state.origin_filter:
                continue
        if st.session_state.platform_filter != 'All':
            if _platform(e) != st.session_state.platform_filter:
                continue
        if st.session_state.interest_filter != 'All':
            if _interest(e) != st.session_state.interest_filter:
                continue
        out.append(e)
    return out

filtered_events = _apply_filters(all_events)
bookmarked_events = [e for e in all_events if e.get('bookmarked')]


# ══════════════════════════════════════════════════════════════════════════════
# TAB: DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════
if st.session_state.tab == 'dashboard':

    last = stats.get('last_run', 'Never')
    if last != 'Never':
        try:
            last = datetime.fromisoformat(last).strftime('%d %b %H:%M')
        except Exception:
            pass

    st.markdown(f"""
    <div style="background:linear-gradient(135deg,#000f22 0%,#1e3a8a 60%,#4a3ee6 100%);
                clip-path:polygon(0 0,100% 0,100% calc(100% - 18px),calc(100% - 18px) 100%,0 100%);
                padding:1.75rem 2rem;margin-bottom:1.5rem">
        <div style="color:#fff;font-size:2rem;font-weight:900;font-style:italic;text-transform:uppercase;letter-spacing:-.01em">
            TechTrack
        </div>
        <div style="color:rgba(255,255,255,.65);font-size:.78rem;text-transform:uppercase;letter-spacing:.1em;font-weight:600;margin-top:2px">
            Engineering & CS Events &nbsp;//&nbsp; Malaysia & Beyond &nbsp;//&nbsp; Updated: {last}
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Stats
    c1, c2, c3, c4 = st.columns(4)
    for col, val, lbl, hi in [
        (c1, stats['total'],    'Total Events',   False),
        (c2, stats['upcoming'], 'Upcoming',        True),
        (c3, stats['bookmarked'],'Bookmarked',     False),
        (c4, len(stats.get('by_category', {})), 'Categories', False),
    ]:
        hi_cls = 'stat-card-hi' if hi else ''
        col.markdown(
            f'<div class="stat-card {hi_cls}">'
            f'<div class="stat-val">{val:02d}</div>'
            f'<div class="stat-lbl">{lbl}</div>'
            '</div>',
            unsafe_allow_html=True
        )

    st.markdown('<br>', unsafe_allow_html=True)

    # Upcoming / Bookmarked
    st.markdown(
        '<div class="section-hdr">Upcoming Registered Events'
        f'<span class="section-count">({len(bookmarked_events)})</span></div>',
        unsafe_allow_html=True
    )
    if not bookmarked_events:
        st.info("No bookmarked events yet. Use ☆ on any event card to register interest.")
        if st.button("BROWSE_DISCOVERY", type="primary"):
            st.session_state.tab = 'discovery'
            st.rerun()
    else:
        cols = st.columns(2)
        for i, ev in enumerate(bookmarked_events[:4]):
            with cols[i % 2]:
                _render_card(ev, f'dash_{i}')

    # Category breakdown
    st.markdown(
        '<div class="section-hdr">Events by Category</div>',
        unsafe_allow_html=True
    )
    cat_counts = {}
    for ev in all_events:
        c_norm = _cat(ev)
        cat_counts[c_norm] = cat_counts.get(c_norm, 0) + 1
    if cat_counts:
        df_cats = pd.DataFrame(
            [(k, v) for k, v in sorted(cat_counts.items(), key=lambda x: -x[1])],
            columns=['Category', 'Count']
        )
        st.bar_chart(df_cats.set_index('Category'), use_container_width=True, height=250)


# ══════════════════════════════════════════════════════════════════════════════
# TAB: DISCOVERY
# ══════════════════════════════════════════════════════════════════════════════
elif st.session_state.tab == 'discovery':

    # Hero
    st.markdown("""
    <div style="background:rgba(255,255,255,0.4);border:1px solid rgba(74,62,230,0.15);
                padding:1.25rem 1.5rem;margin-bottom:1.25rem;
                clip-path:polygon(0 0,100% 0,100% calc(100% - 14px),calc(100% - 14px) 100%,0 100%)">
        <div style="font-size:1.9rem;font-weight:900;color:#000f22;font-style:italic;text-transform:uppercase;letter-spacing:-.01em">
            Discover <span style="color:#0098b7;text-shadow:0 0 8px rgba(60,215,255,.3)">Tech Events</span>
        </div>
        <div style="font-size:.85rem;color:#43474d;font-weight:600;margin-top:.25rem">
            Competitions, hackathons, conferences, workshops &amp; career fairs across Malaysia and beyond.
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Pipeline panel
    last_run = stats.get('last_run', 'Never')
    if last_run != 'Never':
        try:
            last_run = datetime.fromisoformat(last_run).strftime('%Y-%m-%d %H:%M')
        except Exception:
            pass

    st.markdown(f"""
    <div class="pipeline-panel">
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
            <span class="pipeline-dot" style="background:#3cd7ff;box-shadow:0 0 0 0 rgba(60,215,255,.5)"></span>
            <span style="font-size:.68rem;font-weight:900;letter-spacing:.18em;text-transform:uppercase;color:#3cd7ff;font-family:monospace">
                MALAYSIAN BROADCAST INGESTION PIPELINE (AUTO-RENEW)
            </span>
        </div>
        <div style="font-size:1.1rem;font-weight:800;font-style:italic;color:#fff;text-transform:uppercase;margin-bottom:4px">
            Social & University Channel Crawler
        </div>
        <div style="font-size:.78rem;color:#94a3b8;max-width:600px">
            Indexes EE &amp; tech events from Malaysian university portals, IEEE chapters,
            tech company sites, and aggregators. Click <strong style="color:#fff">LAUNCH_AUTO_RENEW</strong> in the sidebar.
        </div>
        <div class="pipeline-log">
            <span style="color:#475569">SYSTEM_LOG &gt;&gt;</span>
            <span style="margin-left:6px">{_html.escape(str(st.session_state.renew_log))}</span>
        </div>
        <div style="margin-top:10px;font-family:monospace;font-size:.68rem;color:#475569">
            LAST DISCOVERY CLOCK: <span style="color:#fff;font-weight:700">{last_run}</span>
            &nbsp;&nbsp;|&nbsp;&nbsp;TOTAL IN DB: <span style="color:#3cd7ff;font-weight:700">{stats['total']}</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Filter desk
    st.markdown("""
    <div class="filter-panel">
        <span style="font-size:.65rem;font-weight:900;text-transform:uppercase;letter-spacing:.2em;color:#4a3ee6;font-family:monospace">
            METRIC SEGMENT CLASSIFIERS
        </span>
        <div style="font-size:.8rem;font-weight:800;color:#000f22;text-transform:uppercase;font-family:monospace;margin-top:2px">
            Interactive Filter Desk
        </div>
    </div>
    """, unsafe_allow_html=True)

    cat_options = ['All Events','Conference','Competition','Hackathon','Workshop / Bootcamp','Seminar / Talk','Career Fair','Company Visit','Other']
    cat_cols = st.columns(len(cat_options))
    for i, c in enumerate(cat_options):
        with cat_cols[i]:
            active = st.session_state.cat_filter == c
            if st.button(c.replace(' / ', '/'), key=f'cf_{c}',
                         type='primary' if active else 'secondary',
                         use_container_width=True):
                st.session_state.cat_filter = c
                st.rerun()

    f1, f2, f3 = st.columns(3)
    with f1:
        st.markdown('<span class="filter-label">Origin Region</span>', unsafe_allow_html=True)
        for opt, lbl in [('All','ALL_ORIGINS'),('Malaysia','MALAYSIA'),('International','INT_NEXUS')]:
            if st.button(lbl, key=f'ori_{opt}',
                         type='primary' if st.session_state.origin_filter == opt else 'secondary',
                         use_container_width=True):
                st.session_state.origin_filter = opt
                st.rerun()

    with f2:
        st.markdown('<span class="filter-label">Discovery Platform</span>', unsafe_allow_html=True)
        for opt, lbl in [('All','ALL_CHANNELS'),('University','UNI'),('Web','WEB'),('Instagram','INSTA')]:
            if st.button(lbl, key=f'plt_{opt}',
                         type='primary' if st.session_state.platform_filter == opt else 'secondary',
                         use_container_width=True):
                st.session_state.platform_filter = opt
                st.rerun()

    with f3:
        st.markdown('<span class="filter-label">Interest Field</span>', unsafe_allow_html=True)
        for opt, lbl in [('All','ALL_FOCUS'),('EE Related','EE_ENG'),('Technology Related','GEN_TECH')]:
            if st.button(lbl, key=f'int_{opt}',
                         type='primary' if st.session_state.interest_filter == opt else 'secondary',
                         use_container_width=True):
                st.session_state.interest_filter = opt
                st.rerun()

    st.markdown('<br>', unsafe_allow_html=True)

    # Active filter banner
    if st.session_state.search:
        st.markdown(
            f'<div style="padding:.75rem 1rem;background:rgba(74,62,230,.05);border:1px solid rgba(74,62,230,.15);margin-bottom:1rem">'
            f'<span style="font-size:.68rem;font-weight:900;text-transform:uppercase;letter-spacing:.15em;color:#4a3ee6;font-family:monospace">Filter Active</span>'
            f'<span style="display:block;font-size:.78rem;font-weight:800;color:#000f22;text-transform:uppercase;margin-top:2px">'
            f'Showing: "{_safe(st.session_state.search)}" — {len(filtered_events)} records</span></div>',
            unsafe_allow_html=True
        )

    # Events grid by category sections
    if not filtered_events:
        st.markdown(
            '<div style="text-align:center;padding:3rem;font-family:monospace">'
            '<div style="font-size:2rem;margin-bottom:.5rem">◌</div>'
            '<div style="font-weight:900;text-transform:uppercase;font-size:.8rem">NO EVENTS DETECTED</div>'
            '<div style="color:#64748b;font-size:.75rem;margin-top:.25rem">Adjust filters or run the scraper pipeline</div>'
            '</div>',
            unsafe_allow_html=True
        )
        if st.button('RESET_FILTERS'):
            st.session_state.cat_filter = 'All Events'
            st.session_state.origin_filter = 'All'
            st.session_state.platform_filter = 'All'
            st.session_state.interest_filter = 'All'
            st.session_state.search = ''
            st.rerun()
    else:
        for group_label, cats in GROUPS:
            grp = [e for e in filtered_events if _cat(e) in cats]
            if not grp:
                continue
            st.markdown(
                f'<div class="section-hdr">{group_label}'
                f'<span class="section-count">({len(grp)})</span></div>',
                unsafe_allow_html=True
            )
            cols = st.columns(3)
            for i, ev in enumerate(grp):
                with cols[i % 3]:
                    _render_card(ev, f'disc_{group_label}_{i}')


# ══════════════════════════════════════════════════════════════════════════════
# TAB: MY EVENTS
# ══════════════════════════════════════════════════════════════════════════════
elif st.session_state.tab == 'my-events':

    st.markdown("""
    <div style="background:rgba(74,62,230,.05);border:1px solid rgba(74,62,230,.2);padding:1.25rem 1.5rem;margin-bottom:1.5rem;
                clip-path:polygon(0 0,100% 0,100% calc(100% - 14px),calc(100% - 14px) 100%,0 100%)">
        <div style="font-size:1.5rem;font-weight:900;color:#000f22;font-style:italic;text-transform:uppercase">
            My Secure Passes
        </div>
        <div style="font-size:.82rem;color:#43474d;font-weight:600;margin-top:.25rem">
            Events you have bookmarked. Click ★ on any card to secure your pass.
        </div>
    </div>
    """, unsafe_allow_html=True)

    bm = [e for e in get_all_events(upcoming_only=False) if e.get('bookmarked')]
    if not bm:
        st.info("No bookmarked events. Browse Discovery and click ☆ to bookmark.")
        if st.button("LAUNCH_DISCOVERY_MATRIX", type="primary"):
            st.session_state.tab = 'discovery'
            st.rerun()
    else:
        cols = st.columns(2)
        for i, ev in enumerate(bm):
            with cols[i % 2]:
                _render_card(ev, f'my_{i}')


# ══════════════════════════════════════════════════════════════════════════════
# TAB: RUN LOGS
# ══════════════════════════════════════════════════════════════════════════════
elif st.session_state.tab == 'logs':

    st.markdown('<div class="section-hdr">Scraper Run Logs</div>', unsafe_allow_html=True)

    # Quick stat strip
    lc1, lc2, lc3 = st.columns(3)
    lc1.markdown(f'<div class="stat-card"><div class="stat-val">{stats["total"]:02d}</div><div class="stat-lbl">Total Events</div></div>', unsafe_allow_html=True)
    lc2.markdown(f'<div class="stat-card stat-card-hi"><div class="stat-val">{stats["upcoming"]:02d}</div><div class="stat-lbl">Upcoming</div></div>', unsafe_allow_html=True)
    lc3.markdown(f'<div class="stat-card"><div class="stat-val">{stats["bookmarked"]:02d}</div><div class="stat-lbl">Bookmarked</div></div>', unsafe_allow_html=True)

    st.markdown('<br>', unsafe_allow_html=True)

    logs = get_run_logs(limit=200)
    if not logs:
        st.info("No run logs yet. Launch the scraper pipeline to generate logs.")
    else:
        df = pd.DataFrame(logs)
        df['ran_at'] = pd.to_datetime(df['ran_at'])
        st.dataframe(
            df[['ran_at','source','found','added','error']],
            use_container_width=True, hide_index=True,
            column_config={
                'ran_at':  st.column_config.DatetimeColumn('Time',   format='DD MMM YYYY HH:mm'),
                'found':   st.column_config.NumberColumn('Found'),
                'added':   st.column_config.NumberColumn('Added'),
                'error':   st.column_config.TextColumn('Error'),
            },
        )
        # Timeline view
        st.markdown('<div class="section-hdr">Events Timeline</div>', unsafe_allow_html=True)
        dated = [e for e in all_events if e.get('start_date') and not _is_junk(e)]
        if dated:
            df_tl = pd.DataFrame([{
                'Bm':       '★' if e.get('bookmarked') else '',
                'Title':    (_strip_html(e['title'] or ''))[:55],
                'Date':     pd.to_datetime(e['start_date']),
                'Deadline': pd.to_datetime(e['deadline']) if e.get('deadline') else None,
                'Category': _cat(e),
                'Origin':   _origin(e),
                'Source':   e['source_name'],
            } for e in dated]).sort_values('Date')
            st.dataframe(
                df_tl, use_container_width=True, hide_index=True,
                column_config={
                    'Date':     st.column_config.DatetimeColumn('Event Date', format='DD MMM YYYY'),
                    'Deadline': st.column_config.DatetimeColumn('Deadline',   format='DD MMM YYYY'),
                    'Bm':       st.column_config.TextColumn('', width='small'),
                },
            )
            csv = df_tl.to_csv(index=False).encode('utf-8')
            st.download_button('Download CSV', csv, 'techtrack_events.csv', 'text/csv')
