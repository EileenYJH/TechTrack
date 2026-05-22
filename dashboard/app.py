"""
Streamlit dashboard for the EE & CS Event Tracker.
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

_CODE_RE = re.compile(
    r'[{}\[\]]|=>|\bfunction\b|\bimport\b|\bconst\b|\blet\b|\bvar\b'
    r'|\bdef\b|\bclass\b|npm |pip |\.js\b|\.py\b|</|/>|<!--',
    re.IGNORECASE
)

def _is_junk_event(ev: dict) -> bool:
    title = (ev.get("title") or "").strip()
    if not title or len(title) < 6 or len(title) > 250:
        return True
    if _CODE_RE.search(title):
        return True
    if re.search(r'[^a-zA-Z0-9\s\-–,.()/\'\":!?]{2,}', title):
        return True
    return False

def _safe_text(text: str) -> str:
    """Escape for HTML and strip backticks so Streamlit markdown doesn't create code blocks."""
    return _html.escape(text).replace("`", "'")

st.set_page_config(
    page_title="TechTrack — EE & CS Events",
    page_icon="T",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap');

html, body, [class*="css"] {
    font-family: 'Inter', sans-serif;
    background-color: #f7fafd;
    color: #181c1e;
}

#MainMenu, footer, header { visibility: hidden; }

/* Parallax grid background */
body::after {
    content: "";
    position: fixed;
    inset: 0;
    background-image:
        linear-gradient(to right, rgba(74,62,230,0.04) 1px, transparent 1px),
        linear-gradient(to bottom, rgba(74,62,230,0.04) 1px, transparent 1px);
    background-size: 60px 60px;
    pointer-events: none;
    z-index: 0;
}

/* Scanline overlay */
body::before {
    content: " ";
    display: block;
    position: fixed;
    inset: 0;
    background: linear-gradient(rgba(255,255,255,0) 50%, rgba(0,0,0,0.04) 50%);
    z-index: 9999;
    background-size: 100% 4px;
    pointer-events: none;
    opacity: 0.15;
}

/* Sidebar */
section[data-testid="stSidebar"] {
    background: rgba(255,255,255,0.9) !important;
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
    position: relative;
    overflow: hidden;
    margin-bottom: 1rem;
}
.cyber-card:hover {
    border-color: #4a3ee6;
    transform: translateY(-3px);
    box-shadow: 0 12px 36px rgba(74,62,230,0.10);
}
.cyber-card::before {
    content: "";
    position: absolute;
    top: 0; left: 0;
    width: 100%; height: 3px;
    background: linear-gradient(90deg, #4a3ee6, transparent);
    opacity: 0.5;
}

/* Card image area */
.card-img {
    height: 130px;
    background-size: cover;
    background-position: center;
    background-repeat: no-repeat;
    position: relative;
}
.card-img-overlay {
    position: absolute;
    inset: 0;
    background: linear-gradient(to top, rgba(255,255,255,0.92), rgba(255,255,255,0.1));
}

/* Card body */
.card-body { padding: 0.85rem 1rem 0.9rem 1rem; }
.card-type-badge {
    display: inline-block;
    padding: 2px 10px;
    font-size: 0.68rem;
    font-weight: 800;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    border-radius: 2px;
    margin-bottom: 6px;
}
.badge-hackathon   { background:#ede9fe; color:#4c1d95; border:1px solid #c4b5fd; }
.badge-competition { background:#fee2e2; color:#7f1d1d; border:1px solid #fca5a5; }
.badge-career      { background:#dcfce7; color:#14532d; border:1px solid #86efac; }
.badge-conference  { background:#dbeafe; color:#1e3a8a; border:1px solid #93c5fd; }
.badge-workshop    { background:#ffedd5; color:#7c2d12; border:1px solid #fdba74; }
.badge-seminar     { background:#fef3c7; color:#78350f; border:1px solid #fcd34d; }
.badge-visit       { background:#f1f5f9; color:#334155; border:1px solid #cbd5e1; }
.badge-other       { background:#f1f5f9; color:#334155; border:1px solid #cbd5e1; }

.card-title {
    font-size: 0.92rem;
    font-weight: 800;
    color: #000f22;
    text-transform: uppercase;
    letter-spacing: 0.02em;
    line-height: 1.3;
    margin-bottom: 5px;
    font-style: italic;
}
.card-title a { color: #000f22; text-decoration: none; transition: color .2s; }
.card-title a:hover { color: #4a3ee6; }

.card-meta { font-size: 0.75rem; color: #64748b; line-height: 1.6; }
.card-deadline { font-size: 0.73rem; color: #dc2626; font-weight: 600; margin-top: 3px; }
.card-desc { font-size: 0.78rem; color: #475569; margin-top: 5px; line-height: 1.4; }

/* Days pill */
.days-pill   { display:inline-block; padding:1px 8px; border-radius:2px; font-size:0.68rem;
    font-weight:800; letter-spacing:.08em; text-transform:uppercase;
    background:#dbeafe; color:#1e3a8a; border:1px solid #93c5fd; }
.days-urgent { background:#fee2e2; color:#7f1d1d; border-color:#fca5a5; }
.days-soon   { background:#ffedd5; color:#7c2d12; border-color:#fdba74; }

/* Stat card */
.stat-card {
    background: rgba(255,255,255,0.88);
    border: 1px solid rgba(74,62,230,0.15);
    clip-path: polygon(0 0, 100% 0, 100% calc(100% - 10px), calc(100% - 10px) 100%, 0 100%);
    padding: 1.2rem 1.4rem;
    text-align: center;
    position: relative;
}
.stat-card::before {
    content: "";
    position: absolute; top:0; left:0;
    width:100%; height:3px;
    background: linear-gradient(90deg, #4a3ee6, transparent);
    opacity: 0.4;
}
.stat-val { font-size: 2.2rem; font-weight: 900; color: #000f22; line-height: 1; font-style: italic; }
.stat-lbl { font-size: 0.68rem; color: #64748b; margin-top: 0.3rem;
    text-transform: uppercase; letter-spacing: .14em; font-weight: 700; }

/* Hero */
.hero {
    background: linear-gradient(135deg, #000f22 0%, #1e3a8a 60%, #4a3ee6 100%);
    clip-path: polygon(0 0, 100% 0, 100% calc(100% - 18px), calc(100% - 18px) 100%, 0 100%);
    padding: 2rem 2.5rem;
    margin-bottom: 1.5rem;
    position: relative;
}
.hero-title { color: #ffffff; font-size: 2.2rem; font-weight: 900; margin: 0 0 0.25rem 0;
    text-transform: uppercase; letter-spacing: -0.01em; font-style: italic; }
.hero-sub   { color: rgba(255,255,255,0.65); font-size: 0.85rem; margin: 0;
    text-transform: uppercase; letter-spacing: .1em; font-weight: 600; }

/* Section header */
.section-header {
    font-size: 0.8rem;
    font-weight: 900;
    color: #000f22;
    text-transform: uppercase;
    letter-spacing: 0.15em;
    border-left: 4px solid #4a3ee6;
    padding-left: 0.85rem;
    margin: 2rem 0 1rem 0;
    position: relative;
}
.section-header::after {
    content: "";
    position: absolute;
    bottom: -6px; left: 0;
    width: 40px; height: 2px;
    background: #4a3ee6;
}
.section-count {
    color: #94a3b8;
    font-weight: 600;
    letter-spacing: 0;
    margin-left: 8px;
    font-style: normal;
}

/* Filter bar */
.filter-btn {
    display: inline-block;
    padding: 5px 14px;
    border: 1px solid #c4c6ce;
    background: rgba(255,255,255,0.6);
    color: #43474d;
    font-size: 0.7rem;
    font-weight: 800;
    letter-spacing: .1em;
    text-transform: uppercase;
    border-radius: 2px;
    cursor: pointer;
    transition: .2s;
    margin-right: 6px;
    margin-bottom: 6px;
}
.filter-btn-active {
    background: #4a3ee6;
    color: #ffffff;
    border-color: #4a3ee6;
    box-shadow: 0 4px 14px rgba(74,62,230,0.25);
}

/* Streamlit button override for filter row */
div[data-testid="column"] button[kind="secondary"] {
    background: transparent !important;
    border: 1px solid #c4c6ce !important;
    color: #43474d !important;
    font-size: 0.7rem !important;
    font-weight: 800 !important;
    letter-spacing: .1em !important;
    text-transform: uppercase !important;
    border-radius: 2px !important;
    padding: 4px 12px !important;
}
</style>
""", unsafe_allow_html=True)

# ── Helpers ───────────────────────────────────────────────────────────────────
def _parse_date(val):
    if not val:
        return None
    try:
        return datetime.fromisoformat(str(val))
    except Exception:
        return None

def _fmt_time(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%d %b %H:%M")
    except Exception:
        return iso

def _days_pill(start) -> str:
    if not start:
        return ""
    days = (start.date() - datetime.now().date()).days
    if days < 0:
        return ""
    if days == 0:
        cls, label = "days-urgent", "TODAY"
    elif days <= 7:
        cls, label = "days-urgent", f"{days}D LEFT"
    elif days <= 30:
        cls, label = "days-soon", f"{days}D LEFT"
    else:
        cls, label = "days-pill", f"{days}D LEFT"
    return f'<span class="{cls}">{label}</span>'

CAT_BADGE = {
    "Hackathon":           "badge-hackathon",
    "Competition":         "badge-competition",
    "Career Fair":         "badge-career",
    "Conference":          "badge-conference",
    "Workshop / Bootcamp": "badge-workshop",
    "Seminar / Talk":      "badge-seminar",
    "Company Visit":       "badge-visit",
    "Other":               "badge-other",
}
CAT_GRADIENT = {
    "Hackathon":           "linear-gradient(135deg,#4c1d95,#7c3aed)",
    "Competition":         "linear-gradient(135deg,#7f1d1d,#dc2626)",
    "Career Fair":         "linear-gradient(135deg,#14532d,#16a34a)",
    "Conference":          "linear-gradient(135deg,#1e3a8a,#2563eb)",
    "Workshop / Bootcamp": "linear-gradient(135deg,#7c2d12,#ea580c)",
    "Seminar / Talk":      "linear-gradient(135deg,#78350f,#d97706)",
    "Company Visit":       "linear-gradient(135deg,#1e293b,#475569)",
    "Other":               "linear-gradient(135deg,#1e293b,#475569)",
}

GROUPS = [
    ("Competitions & Hackathons", ["Competition", "Hackathon"]),
    ("Workshops & Seminars",      ["Workshop / Bootcamp", "Seminar / Talk"]),
    ("Conferences",               ["Conference"]),
    ("Career Fairs & Others",     ["Career Fair", "Company Visit", "Other"]),
]

init_db()
with open(ROOT / "config.yaml") as f:
    cfg = yaml.safe_load(f)

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("""
    <div style="padding:1rem 0.5rem 1.5rem 0.5rem">
        <div style="font-size:1.35rem;font-weight:900;letter-spacing:-0.02em;font-style:italic">
            <span style="color:#4a3ee6">TECH</span><span style="color:#000f22">TRACK</span>
        </div>
        <div style="font-size:0.62rem;font-weight:700;letter-spacing:0.18em;text-transform:uppercase;color:#94a3b8;margin-top:2px">
            Sector: Events_Nexus
        </div>
    </div>
    """, unsafe_allow_html=True)

    search = st.text_input("Search", placeholder="IEEE, hackathon, robotics…", label_visibility="collapsed")

    country_options = ["All", "Malaysia", "Singapore", "Indonesia", "International", "Regional"]
    selected_country = st.selectbox("Country", country_options, label_visibility="visible")

    show_past       = st.toggle("Show past events",  value=False)
    bookmarked_only = st.toggle("Bookmarked only",   value=False)

    st.divider()

    if st.button("Run Scraper", use_container_width=True, type="primary"):
        with st.spinner("Scraping — this may take a few minutes…"):
            try:
                from runner import run_all
                run_all(verbose=False)
                st.success("Done. Refresh to see new events.")
                st.rerun()
            except Exception as e:
                st.error(f"Scraper error: {e}")

    with st.expander("Add source"):
        new_name    = st.text_input("Name",    key="new_name")
        new_url     = st.text_input("URL",     key="new_url")
        new_type    = st.selectbox("Type", ["universities","organizations","companies","aggregators"], key="new_type")
        new_country = st.text_input("Country", value="Malaysia", key="new_country")
        if st.button("Add"):
            if new_name and new_url:
                cfg[new_type].append({"name": new_name, "url": new_url, "country": new_country})
                with open(ROOT / "config.yaml", "w") as f:
                    yaml.dump(cfg, f, allow_unicode=True, sort_keys=False)
                st.success(f"Added {new_name}.")
            else:
                st.warning("Fill in name and URL.")

# ── Hero ──────────────────────────────────────────────────────────────────────
stats = get_stats()
last  = _fmt_time(stats["last_run"]) if stats["last_run"] != "Never" else "Never"

st.markdown(f"""
<div class="hero">
    <div class="hero-title">TechTrack</div>
    <div class="hero-sub">Engineering &amp; CS Events &nbsp;//&nbsp; Malaysia &amp; Beyond &nbsp;//&nbsp; Updated: {last}</div>
</div>
""", unsafe_allow_html=True)

# ── Stat cards ────────────────────────────────────────────────────────────────
c1, c2, c3, c4 = st.columns(4)
for col, val, lbl in [
    (c1, stats["total"],      "Total Events"),
    (c2, stats["upcoming"],   "Upcoming"),
    (c3, stats["bookmarked"], "Bookmarked"),
    (c4, len(stats.get("by_category", {})), "Categories"),
]:
    col.markdown(f"""<div class="stat-card">
        <div class="stat-val">{val}</div>
        <div class="stat-lbl">{lbl}</div>
    </div>""", unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# ── Load events ───────────────────────────────────────────────────────────────
all_events = get_all_events(
    upcoming_only=not show_past,
    country=selected_country if selected_country != "All" else None,
    search=search or None,
    bookmarked_only=bookmarked_only,
)

# ── Tabs ──────────────────────────────────────────────────────────────────────
tab_cards, tab_timeline, tab_logs = st.tabs(["Events", "Timeline", "Run Logs"])


def _render_card(ev: dict, card_key: str):
    eid   = ev.get("id", "")
    cat   = ev.get("category") or "Other"
    title = _safe_text(ev.get("title") or "Untitled")
    url   = ev.get("event_url") or ""
    if not url or url in ("null", "None"):
        url = "#"
    else:
        url = _html.escape(url)

    src   = _safe_text(ev.get("source_name") or "")
    start = _parse_date(ev.get("start_date"))
    dead  = _parse_date(ev.get("deadline"))
    loc   = _safe_text(ev.get("location") or "")
    desc  = _safe_text((ev.get("description") or "")[:150])
    img   = ev.get("image_url") or ""
    is_bm = bool(ev.get("bookmarked", 0))

    badge_cls = CAT_BADGE.get(cat, "badge-other")
    gradient  = CAT_GRADIENT.get(cat, CAT_GRADIENT["Other"])
    date_str  = start.strftime("%d %b %Y") if start else "Date TBA"

    if img and img.startswith("http"):
        bg_style = f'background:{gradient}; background-image:url("{_html.escape(img)}")'
    else:
        bg_style = f"background:{gradient}"

    days_html  = _days_pill(start)
    dead_html  = f'<div class="card-deadline">Deadline: {dead.strftime("%d %b %Y")}</div>' if dead else ""
    desc_html  = f'<div class="card-desc">{desc}{"…" if len(ev.get("description","")) > 150 else ""}</div>' if desc else ""
    meta_parts = [date_str, src]
    if loc:
        meta_parts.append(loc)

    card_html = f"""
<div class="cyber-card">
  <div class="card-img" style="{bg_style}">
    <div class="card-img-overlay"></div>
  </div>
  <div class="card-body">
    <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;margin-bottom:5px">
      <span class="card-type-badge {badge_cls}">{_html.escape(cat)}</span>
      {days_html}
    </div>
    <div class="card-title"><a href="{url}" target="_blank">{title}</a></div>
    <div class="card-meta">{" &nbsp;/&nbsp; ".join(meta_parts)}</div>
    {dead_html}
    {desc_html}
  </div>
</div>"""

    col_card, col_btn = st.columns([5, 1])
    with col_card:
        st.markdown(card_html, unsafe_allow_html=True)
    with col_btn:
        st.markdown("<div style='margin-top:22px'>", unsafe_allow_html=True)
        bm_label = "★" if is_bm else "☆"
        if eid and st.button(bm_label, key=f"bm_{card_key}_{eid}",
                             help="Bookmark", use_container_width=True):
            toggle_bookmark(eid)
            st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)


# ── Tab 1: Category sections ─────────────────────────────────────────────────
with tab_cards:
    if not all_events:
        st.info("No events found. Adjust filters or run the scraper.")
    else:
        st.caption(f"**{len(all_events)}** event(s) — filtered by your sidebar settings")

        for group_label, cats in GROUPS:
            group_events = [e for e in all_events
                            if (e.get("category") or "Other") in cats
                            and not _is_junk_event(e)]
            if not group_events:
                continue

            st.markdown(
                f'<div class="section-header">{group_label}'
                f'<span class="section-count">({len(group_events)})</span></div>',
                unsafe_allow_html=True
            )

            cols = st.columns(3)
            for i, ev in enumerate(group_events):
                with cols[i % 3]:
                    _render_card(ev, f"{group_label}_{i}")


# ── Tab 2: Timeline ───────────────────────────────────────────────────────────
with tab_timeline:
    dated = [e for e in all_events if e.get("start_date")]
    if not dated:
        st.info("No events with confirmed dates.")
    else:
        df = pd.DataFrame([{
            "Bm":       "★" if e.get("bookmarked") else "",
            "Title":    e["title"][:60],
            "Date":     pd.to_datetime(e["start_date"]),
            "Deadline": pd.to_datetime(e["deadline"]) if e.get("deadline") else None,
            "Category": e["category"],
            "Country":  e["country"],
            "Source":   e["source_name"],
        } for e in dated]).sort_values("Date")

        st.dataframe(
            df, use_container_width=True, hide_index=True,
            column_config={
                "Date":     st.column_config.DatetimeColumn("Event Date", format="DD MMM YYYY"),
                "Deadline": st.column_config.DatetimeColumn("Deadline",   format="DD MMM YYYY"),
                "Bm":       st.column_config.TextColumn("", width="small"),
            },
        )
        csv = df.to_csv(index=False).encode("utf-8")
        st.download_button("Download CSV", csv, "techtrack_events.csv", "text/csv")


# ── Tab 3: Run Logs ───────────────────────────────────────────────────────────
with tab_logs:
    logs = get_run_logs(limit=100)
    if not logs:
        st.info("No runs yet.")
    else:
        df_logs = pd.DataFrame(logs)
        df_logs["ran_at"] = pd.to_datetime(df_logs["ran_at"])
        st.dataframe(
            df_logs[["ran_at", "source", "found", "added", "error"]],
            use_container_width=True, hide_index=True,
            column_config={
                "ran_at": st.column_config.DatetimeColumn("Time", format="DD MMM YYYY HH:mm"),
                "found":  st.column_config.NumberColumn("Found"),
                "added":  st.column_config.NumberColumn("Added"),
                "error":  st.column_config.TextColumn("Error"),
            },
        )
