"""
Streamlit dashboard for the EE & CS Event Tracker.
Run: streamlit run dashboard/app.py
"""
import sys
import html as _html
from pathlib import Path
from datetime import datetime

import streamlit as st
import pandas as pd
import yaml

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from src.db import init_db, get_all_events, get_stats, get_run_logs, toggle_bookmark

st.set_page_config(
    page_title="TechTrack — EE & CS Events",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
#MainMenu, footer, header { visibility: hidden; }

/* Hero */
.hero {
    background: linear-gradient(135deg, #0f172a 0%, #1e3a5f 50%, #0f172a 100%);
    border-radius: 16px; padding: 2rem 2.5rem; margin-bottom: 1.5rem;
    border: 1px solid #1e40af33;
}
.hero h1 { color: #f8fafc; font-size: 2rem; font-weight: 700; margin: 0 0 0.3rem 0; }
.hero p  { color: #94a3b8; font-size: 1rem; margin: 0; }

/* Stat cards */
.stat-card { background: #1e293b; border: 1px solid #334155; border-radius: 12px;
    padding: 1.1rem 1.4rem; text-align: center; }
.stat-card .val { font-size: 2rem; font-weight: 700; color: #f1f5f9; line-height: 1; }
.stat-card .lbl { font-size: 0.78rem; color: #64748b; margin-top: 0.3rem;
    text-transform: uppercase; letter-spacing: .06em; }

/* Section header */
.section-header {
    font-size: 1.15rem; font-weight: 700; color: #f1f5f9;
    margin: 1.8rem 0 1rem 0; padding-bottom: 0.5rem;
    border-bottom: 2px solid #1e40af44;
}

/* Event card */
.ev-card {
    background: #1e293b; border: 1px solid #334155; border-radius: 12px;
    overflow: hidden; margin-bottom: 1rem; transition: border-color .2s, transform .15s;
    height: 100%;
}
.ev-card:hover { border-color: #3b82f6; transform: translateY(-2px); }
.ev-img {
    height: 110px; background-size: cover; background-position: center;
    background-repeat: no-repeat; position: relative;
}
.ev-img-overlay {
    position: absolute; inset: 0; background: rgba(15,23,42,0.45);
}
.ev-body { padding: 0.85rem 1rem 0.9rem 1rem; }
.ev-badges { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; margin-bottom: 6px; }
.ev-title { font-size: 0.95rem; font-weight: 600; color: #f1f5f9; margin-bottom: 5px;
    line-height: 1.35; }
.ev-title a { color: #60a5fa; text-decoration: none; }
.ev-title a:hover { text-decoration: underline; }
.ev-meta { font-size: 0.78rem; color: #64748b; line-height: 1.5; }
.ev-desc { font-size: 0.8rem; color: #94a3b8; margin-top: 5px; line-height: 1.4; }

/* Badges */
.badge { display:inline-block; padding:2px 9px; border-radius:999px;
    font-size:0.7rem; font-weight:600; letter-spacing:.04em; }
.badge-hackathon   { background:#7c3aed22; color:#a78bfa; border:1px solid #7c3aed55; }
.badge-competition { background:#dc262622; color:#f87171; border:1px solid #dc262655; }
.badge-career      { background:#05966922; color:#34d399; border:1px solid #05966955; }
.badge-conference  { background:#1d4ed822; color:#60a5fa; border:1px solid #1d4ed855; }
.badge-workshop    { background:#d9770622; color:#fb923c; border:1px solid #d9770655; }
.badge-seminar     { background:#b4580622; color:#fbbf24; border:1px solid #b4580655; }
.badge-visit       { background:#37415122; color:#94a3b8; border:1px solid #37415155; }
.badge-other       { background:#37415122; color:#94a3b8; border:1px solid #37415155; }

/* Days pill */
.days-pill   { background:#1d4ed822; border:1px solid #1d4ed855; color:#60a5fa;
    border-radius:8px; padding:2px 8px; font-size:0.7rem; font-weight:600; }
.days-urgent { background:#dc262622; border-color:#dc262655; color:#f87171; }
.days-soon   { background:#d9770622; border-color:#d9770655; color:#fb923c; }

/* Sidebar */
section[data-testid="stSidebar"] { background:#0f172a; border-right:1px solid #1e293b; }
</style>
""", unsafe_allow_html=True)

# ── Helpers ──────────────────────────────────────────────────────────────────
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
    cls = "days-urgent" if days <= 7 else ("days-soon" if days <= 30 else "days-pill")
    label = "Today" if days == 0 else f"{days}d left"
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
CAT_ICON = {
    "Hackathon": "💻", "Competition": "🏆", "Career Fair": "💼",
    "Conference": "🎤", "Workshop / Bootcamp": "🛠️", "Seminar / Talk": "🎙️",
    "Company Visit": "🏢", "Other": "📌",
}
CAT_GRADIENT = {
    "Hackathon":           "linear-gradient(135deg,#4c1d95,#7c3aed)",
    "Competition":         "linear-gradient(135deg,#7f1d1d,#dc2626)",
    "Career Fair":         "linear-gradient(135deg,#064e3b,#059669)",
    "Conference":          "linear-gradient(135deg,#1e3a8a,#2563eb)",
    "Workshop / Bootcamp": "linear-gradient(135deg,#7c2d12,#ea580c)",
    "Seminar / Talk":      "linear-gradient(135deg,#713f12,#d97706)",
    "Company Visit":       "linear-gradient(135deg,#1e293b,#475569)",
    "Other":               "linear-gradient(135deg,#1e293b,#475569)",
}

# Priority groups for category sections
GROUPS = [
    ("🏆  Competitions & Hackathons", ["Competition", "Hackathon"]),
    ("🛠️  Workshops & Seminars",      ["Workshop / Bootcamp", "Seminar / Talk"]),
    ("🎤  Conferences",               ["Conference"]),
    ("💼  Career Fairs & Others",     ["Career Fair", "Company Visit", "Other"]),
]

init_db()
with open(ROOT / "config.yaml") as f:
    cfg = yaml.safe_load(f)

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### ⚡ TechTrack")
    st.caption("EE & CS events for Malaysian students")
    st.divider()

    search = st.text_input("🔍 Search", placeholder="hackathon, IEEE, robotics…")
    country_options = ["All", "Malaysia", "Singapore", "Indonesia", "International", "Regional"]
    selected_country = st.selectbox("Country", country_options)
    show_past        = st.toggle("Show past events",   value=False)
    bookmarked_only  = st.toggle("⭐ Bookmarked only", value=False)

    st.divider()
    if st.button("🔄 Run Scraper", use_container_width=True, type="primary"):
        with st.spinner("Scraping… this may take a few minutes"):
            try:
                from runner import run_all
                run_all(verbose=False)
                st.success("Done! Refresh to see new events.")
                st.rerun()
            except Exception as e:
                st.error(f"Scraper error: {e}")

    with st.expander("➕ Add source"):
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
                st.warning("Fill in both name and URL.")

# ── Hero ──────────────────────────────────────────────────────────────────────
stats = get_stats()
last  = _fmt_time(stats["last_run"]) if stats["last_run"] != "Never" else "Never"
st.markdown(f"""
<div class="hero">
    <h1>⚡ TechTrack</h1>
    <p>Engineering &amp; CS events across Malaysia and beyond &nbsp;·&nbsp; Last updated: {last}</p>
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
    col.markdown(f"""
    <div class="stat-card">
        <div class="val">{val}</div>
        <div class="lbl">{lbl}</div>
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
tab_cards, tab_timeline, tab_logs = st.tabs(["📋 Events", "📅 Timeline", "📊 Run Logs"])


def _render_card(ev: dict, col_key: str):
    """Render a single event card inside a Streamlit column."""
    eid   = ev.get("id", "")
    cat   = ev.get("category") or "Other"
    title = _html.escape(ev.get("title") or "Untitled")
    url   = ev.get("event_url") or ""
    if url in ("null", "None", "", None):
        url = "#"
    else:
        url = _html.escape(url)

    src   = _html.escape(ev.get("source_name") or "")
    start = _parse_date(ev.get("start_date"))
    dead  = _parse_date(ev.get("deadline"))
    loc   = _html.escape(ev.get("location") or "")
    desc  = _html.escape((ev.get("description") or "")[:160])
    img   = ev.get("image_url") or ""
    is_bm = bool(ev.get("bookmarked", 0))

    badge_cls = CAT_BADGE.get(cat, "badge-other")
    icon      = CAT_ICON.get(cat, "📌")
    gradient  = CAT_GRADIENT.get(cat, CAT_GRADIENT["Other"])
    date_str  = start.strftime("%d %b %Y") if start else "Date TBA"
    dead_str  = f"Deadline: {dead.strftime('%d %b %Y')}" if dead else ""

    # Image area
    if img and img.startswith("http"):
        img_style = f'background-image:url("{_html.escape(img)}"); {gradient.replace("linear-gradient","linear-gradient")}'
        img_bg = f'background:{gradient}; background-image:url("{_html.escape(img)}")'
    else:
        img_bg = f"background:{gradient}"

    days_html  = _days_pill(start)
    meta_parts = [f"📅 {date_str}", src]
    if loc:
        meta_parts.append(f"📍 {loc}")
    meta = " &nbsp;·&nbsp; ".join(meta_parts)

    card_html = f"""
<div class="ev-card">
  <div class="ev-img" style="{img_bg}">
    <div class="ev-img-overlay"></div>
  </div>
  <div class="ev-body">
    <div class="ev-badges">
      <span class="badge {badge_cls}">{icon} {_html.escape(cat)}</span>
      {days_html}
    </div>
    <div class="ev-title"><a href="{url}" target="_blank">{title}</a></div>
    <div class="ev-meta">{meta}</div>
    {"<div class='ev-meta' style='color:#f87171'>" + dead_str + "</div>" if dead_str else ""}
    {"<div class='ev-desc'>" + desc + ("…" if len(ev.get("description","")) > 160 else "") + "</div>" if desc else ""}
  </div>
</div>"""

    card_col, btn_col = st.columns([5, 1])
    with card_col:
        st.markdown(card_html, unsafe_allow_html=True)
    with btn_col:
        st.markdown("<div style='margin-top:20px'>", unsafe_allow_html=True)
        bm_label = "⭐" if is_bm else "☆"
        if eid and st.button(bm_label, key=f"bm_{col_key}_{eid}", help="Bookmark", use_container_width=True):
            toggle_bookmark(eid)
            st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)


# ── Tab 1: Category sections ──────────────────────────────────────────────────
with tab_cards:
    if not all_events:
        st.info("No events found. Try adjusting your filters or running the scraper.")
    else:
        st.caption(f"**{len(all_events)}** event(s) found")

        for group_label, cats in GROUPS:
            group_events = [e for e in all_events if (e.get("category") or "Other") in cats]
            if not group_events:
                continue

            st.markdown(f'<div class="section-header">{group_label} <span style="color:#475569;font-size:0.85rem;font-weight:400">({len(group_events)})</span></div>', unsafe_allow_html=True)

            cols = st.columns(3)
            for i, ev in enumerate(group_events):
                with cols[i % 3]:
                    _render_card(ev, f"{group_label}_{i}")


# ── Tab 2: Timeline ───────────────────────────────────────────────────────────
with tab_timeline:
    dated = [e for e in all_events if e.get("start_date")]
    if not dated:
        st.info("No events with confirmed dates to display.")
    else:
        df = pd.DataFrame([{
            "⭐":       "⭐" if e.get("bookmarked") else "",
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
                "⭐":       st.column_config.TextColumn("", width="small"),
            },
        )
        csv = df.to_csv(index=False).encode("utf-8")
        st.download_button("⬇ Download CSV", csv, "techtrack_events.csv", "text/csv")


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
