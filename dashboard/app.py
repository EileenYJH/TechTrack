"""
Streamlit dashboard for the EE & CS Event Tracker.
Run: streamlit run dashboard/app.py
"""
import sys
from pathlib import Path
from datetime import datetime

import streamlit as st
import pandas as pd
import yaml

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from src.db import init_db, get_all_events, get_stats, get_run_logs, toggle_bookmark

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
        dt = datetime.fromisoformat(iso)
        return dt.strftime("%d %b %H:%M")
    except Exception:
        return iso


# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="EE & CS Event Tracker",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded",
)

init_db()

with open(ROOT / "config.yaml") as f:
    cfg = yaml.safe_load(f)

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("🎯 EE & CS Events")
    st.caption("Malaysia & beyond")
    st.divider()

    search = st.text_input("🔍 Search", placeholder="e.g. hackathon, IEEE, robotics…")

    categories = ["All"] + cfg.get("categories", [])
    selected_cat = st.selectbox("Category", categories)

    country_options = ["All", "Malaysia", "Singapore", "Indonesia", "International", "Regional"]
    selected_country = st.selectbox("Country / Region", country_options)

    show_past       = st.toggle("Show past events",    value=False)
    bookmarked_only = st.toggle("⭐ Bookmarked only",  value=False)

    st.divider()

    st.subheader("🔄 Update Events")
    if st.button("Run Scraper Now", use_container_width=True, type="primary"):
        with st.spinner("Scraping… this may take a few minutes"):
            try:
                from runner import run_all
                run_all(verbose=False)
                st.success("Done! Refresh to see new events.")
                st.rerun()
            except Exception as e:
                st.error(f"Scraper error: {e}")

    st.divider()

    with st.expander("➕ Add a new source"):
        new_name    = st.text_input("Name", key="new_name")
        new_url     = st.text_input("URL",  key="new_url")
        new_type    = st.selectbox("Type", ["universities", "organizations", "companies", "aggregators"], key="new_type")
        new_country = st.text_input("Country", value="Malaysia", key="new_country")
        if st.button("Add Source"):
            if new_name and new_url:
                cfg[new_type].append({"name": new_name, "url": new_url, "country": new_country})
                with open(ROOT / "config.yaml", "w") as f:
                    yaml.dump(cfg, f, allow_unicode=True, sort_keys=False)
                st.success(f"Added {new_name}. It will be scraped on next run.")
            else:
                st.warning("Please fill in both name and URL.")

    with st.expander("📸 Add Instagram account"):
        ig_account = st.text_input("Username (without @)", key="ig_account")
        if st.button("Add Account"):
            if ig_account:
                if ig_account not in cfg.get("instagram_accounts", []):
                    cfg.setdefault("instagram_accounts", []).append(ig_account)
                    with open(ROOT / "config.yaml", "w") as f:
                        yaml.dump(cfg, f, allow_unicode=True, sort_keys=False)
                    st.success(f"Added @{ig_account}")
                else:
                    st.info("Already in the list.")

# ── Stats bar ─────────────────────────────────────────────────────────────────
stats = get_stats()
col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("Total Events",  stats["total"])
col2.metric("Upcoming",      stats["upcoming"])
col3.metric("Bookmarked",    stats["bookmarked"])
col4.metric(
    "Last Updated",
    _fmt_time(stats["last_run"]) if stats["last_run"] != "Never" else "Never",
)
col5.metric("Categories", len(stats.get("by_category", {})))

st.divider()

# ── Load events ───────────────────────────────────────────────────────────────
events = get_all_events(
    upcoming_only=not show_past,
    category=selected_cat if selected_cat != "All" else None,
    country=selected_country if selected_country != "All" else None,
    search=search or None,
    bookmarked_only=bookmarked_only,
)

# ── Tabs ──────────────────────────────────────────────────────────────────────
tab_list, tab_timeline, tab_logs = st.tabs(["📋 Event List", "📅 Timeline", "📊 Run Logs"])

CAT_COLORS = {
    "Hackathon":           "🟣",
    "Competition":         "🔴",
    "Career Fair":         "🟢",
    "Conference":          "🔵",
    "Workshop / Bootcamp": "🟠",
    "Seminar / Talk":      "🟡",
    "Company Visit":       "⚪",
    "Other":               "⬜",
}

# ── Tab 1: Event List ─────────────────────────────────────────────────────────
with tab_list:
    if not events:
        st.info("No events found. Try running the scraper or adjusting your filters.")
    else:
        st.caption(f"Showing **{len(events)}** event(s)")
        for ev in events:
            eid     = ev.get("id", "")
            icon    = CAT_COLORS.get(ev.get("category", ""), "⬜")
            title   = ev.get("title", "Untitled")
            cat     = ev.get("category", "Other")
            src     = ev.get("source_name", "")
            url     = ev.get("event_url", "#")
            start   = _parse_date(ev.get("start_date"))
            dead    = _parse_date(ev.get("deadline"))
            loc     = ev.get("location", "")
            country = ev.get("country", "")
            desc    = ev.get("description", "")
            is_bm   = bool(ev.get("bookmarked", 0))

            date_str = start.strftime("%d %b %Y") if start else "Date TBA"
            dead_str = f"  •  Deadline: {dead.strftime('%d %b %Y')}" if dead else ""
            bm_label = "⭐ Saved" if is_bm else "☆ Save"

            with st.container(border=True):
                c1, c2 = st.columns([5, 1])
                with c1:
                    st.markdown(f"**{icon} [{title}]({url})**")
                    st.caption(
                        f"{cat}  •  {date_str}{dead_str}  •  {src}"
                        + (f"  •  📍 {loc}" if loc else "")
                        + (f"  •  🌏 {country}" if country else "")
                    )
                    if desc:
                        with st.expander("Details"):
                            st.write(desc[:400])
                with c2:
                    if start:
                        days_left = (start.date() - datetime.now().date()).days
                        if days_left >= 0:
                            st.metric("Days left", days_left)
                        else:
                            st.caption("Past")
                    if eid and st.button(bm_label, key=f"bm_{eid}", use_container_width=True):
                        toggle_bookmark(eid)
                        st.rerun()

# ── Tab 2: Timeline ───────────────────────────────────────────────────────────
with tab_timeline:
    dated = [e for e in events if e.get("start_date")]
    if not dated:
        st.info("No events with confirmed dates to display.")
    else:
        df = pd.DataFrame([{
            "Title":      e["title"][:60],
            "Date":       pd.to_datetime(e["start_date"]),
            "Deadline":   pd.to_datetime(e["deadline"]) if e.get("deadline") else None,
            "Category":   e["category"],
            "Country":    e["country"],
            "Source":     e["source_name"],
            "Bookmarked": "⭐" if e.get("bookmarked") else "",
            "URL":        e["event_url"],
        } for e in dated]).sort_values("Date")

        st.dataframe(
            df[["Bookmarked", "Title", "Date", "Deadline", "Category", "Country", "Source"]],
            use_container_width=True,
            hide_index=True,
            column_config={
                "Date":       st.column_config.DatetimeColumn("Event Date",             format="DD MMM YYYY"),
                "Deadline":   st.column_config.DatetimeColumn("Registration Deadline",  format="DD MMM YYYY"),
                "Bookmarked": st.column_config.TextColumn(""),
            },
        )

        csv = df.drop(columns=["URL"]).to_csv(index=False).encode("utf-8")
        st.download_button("⬇ Download CSV", csv, "events.csv", "text/csv")

# ── Tab 3: Run Logs ───────────────────────────────────────────────────────────
with tab_logs:
    logs = get_run_logs(limit=100)
    if not logs:
        st.info("No runs yet. Click 'Run Scraper Now' in the sidebar to start.")
    else:
        df_logs = pd.DataFrame(logs)
        df_logs["ran_at"] = pd.to_datetime(df_logs["ran_at"])
        st.dataframe(
            df_logs[["ran_at", "source", "found", "added", "error"]],
            use_container_width=True,
            hide_index=True,
            column_config={
                "ran_at": st.column_config.DatetimeColumn("Run Time", format="DD MMM YYYY HH:mm"),
                "found":  st.column_config.NumberColumn("Found"),
                "added":  st.column_config.NumberColumn("Added"),
            },
        )
