"""
Database layer. Uses PostgreSQL (via DATABASE_URL) when available, SQLite locally.
Set DATABASE_URL in .streamlit/secrets.toml or as an environment variable.
"""
import os
import hashlib
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

from .models import Event

_SQLITE_PATH = Path(__file__).parent.parent / "data" / "events.db"


def _db_url() -> str | None:
    """Return DATABASE_URL from Streamlit secrets or env, else None (→ SQLite)."""
    try:
        import streamlit as st
        url = st.secrets.get("DATABASE_URL")
        if url:
            return url
    except Exception:
        pass
    return os.environ.get("DATABASE_URL")


@contextmanager
def _db():
    url = _db_url()
    if url:
        import psycopg2
        import psycopg2.extras
        con = psycopg2.connect(url, cursor_factory=psycopg2.extras.RealDictCursor)
    else:
        import sqlite3
        _SQLITE_PATH.parent.mkdir(exist_ok=True)
        con = sqlite3.connect(_SQLITE_PATH)
        con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def _ph() -> str:
    return "%s" if _db_url() else "?"


def init_db() -> None:
    pg = bool(_db_url())
    id_col = "id SERIAL PRIMARY KEY" if pg else "id INTEGER PRIMARY KEY AUTOINCREMENT"

    with _db() as con:
        cur = con.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id          TEXT PRIMARY KEY,
                title       TEXT NOT NULL,
                source_name TEXT,
                source_url  TEXT,
                event_url   TEXT,
                category    TEXT,
                country     TEXT,
                description TEXT,
                start_date  TEXT,
                end_date    TEXT,
                deadline    TEXT,
                location    TEXT,
                organizer   TEXT,
                tags        TEXT,
                scraped_at  TEXT
            )
        """)
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS run_log (
                {id_col},
                ran_at TEXT,
                source TEXT,
                found  INTEGER,
                added  INTEGER,
                error  TEXT
            )
        """)
        if pg:
            cur.execute(
                "ALTER TABLE events ADD COLUMN IF NOT EXISTS bookmarked INTEGER DEFAULT 0"
            )
        else:
            try:
                cur.execute("ALTER TABLE events ADD COLUMN bookmarked INTEGER DEFAULT 0")
            except Exception:
                pass  # column already exists


def _event_id(event: Event) -> str:
    key = f"{event.title.lower().strip()}|{event.source_name}|{event.start_date}"
    return hashlib.sha1(key.encode()).hexdigest()


def upsert_event(event: Event) -> bool:
    """Insert event if new. Returns True if newly inserted."""
    ph  = _ph()
    eid = _event_id(event)
    d   = event.to_dict()
    with _db() as con:
        cur = con.cursor()
        cur.execute(f"SELECT id FROM events WHERE id={ph}", (eid,))
        if cur.fetchone():
            return False
        cur.execute(f"""
            INSERT INTO events
                (id,title,source_name,source_url,event_url,category,country,
                 description,start_date,end_date,deadline,location,organizer,
                 tags,scraped_at,bookmarked)
            VALUES
                ({ph},{ph},{ph},{ph},{ph},{ph},{ph},
                 {ph},{ph},{ph},{ph},{ph},{ph},
                 {ph},{ph},0)
        """, (eid, d["title"], d["source_name"], d["source_url"], d["event_url"],
              d["category"], d["country"], d["description"], d["start_date"],
              d["end_date"], d["deadline"], d["location"], d["organizer"],
              d["tags"], d["scraped_at"]))
    return True


def toggle_bookmark(event_id: str) -> bool:
    """Toggle bookmark state. Returns new bookmarked value (True = saved)."""
    ph = _ph()
    with _db() as con:
        cur = con.cursor()
        cur.execute(f"SELECT bookmarked FROM events WHERE id={ph}", (event_id,))
        row = cur.fetchone()
        if not row:
            return False
        new_val = 0 if row["bookmarked"] else 1
        cur.execute(f"UPDATE events SET bookmarked={ph} WHERE id={ph}", (new_val, event_id))
        return bool(new_val)


def log_run(source: str, found: int, added: int, error: str = "") -> None:
    ph = _ph()
    with _db() as con:
        cur = con.cursor()
        cur.execute(
            f"INSERT INTO run_log (ran_at,source,found,added,error) VALUES ({ph},{ph},{ph},{ph},{ph})",
            (datetime.now().isoformat(), source, found, added, error),
        )


def get_all_events(
    upcoming_only: bool = True,
    category: Optional[str] = None,
    country: Optional[str] = None,
    search: Optional[str] = None,
    bookmarked_only: bool = False,
) -> list[dict]:
    ph     = _ph()
    query  = "SELECT * FROM events WHERE 1=1"
    params: list = []

    if upcoming_only:
        query += f" AND (start_date IS NULL OR start_date >= {ph})"
        params.append(datetime.now().isoformat())

    if category and category != "All":
        query += f" AND category = {ph}"
        params.append(category)

    if country and country != "All":
        query += f" AND country = {ph}"
        params.append(country)

    if search:
        query += f" AND (title LIKE {ph} OR description LIKE {ph} OR organizer LIKE {ph})"
        like = f"%{search}%"
        params.extend([like, like, like])

    if bookmarked_only:
        query += " AND bookmarked = 1"

    query += " ORDER BY bookmarked DESC, COALESCE(start_date, '9999') ASC"

    with _db() as con:
        cur = con.cursor()
        cur.execute(query, params)
        return [dict(r) for r in cur.fetchall()]


def get_run_logs(limit: int = 50) -> list[dict]:
    ph = _ph()
    with _db() as con:
        cur = con.cursor()
        cur.execute(f"SELECT * FROM run_log ORDER BY ran_at DESC LIMIT {ph}", (limit,))
        return [dict(r) for r in cur.fetchall()]


def get_stats() -> dict:
    ph = _ph()
    with _db() as con:
        cur = con.cursor()
        cur.execute("SELECT COUNT(*) FROM events")
        total = cur.fetchone()
        total = list(total.values())[0] if hasattr(total, "values") else total[0]

        cur.execute(
            f"SELECT COUNT(*) FROM events WHERE start_date IS NULL OR start_date >= {ph}",
            (datetime.now().isoformat(),),
        )
        upcoming = cur.fetchone()
        upcoming = list(upcoming.values())[0] if hasattr(upcoming, "values") else upcoming[0]

        cur.execute("SELECT COUNT(*) FROM events WHERE bookmarked = 1")
        bookmarked = cur.fetchone()
        bookmarked = list(bookmarked.values())[0] if hasattr(bookmarked, "values") else bookmarked[0]

        cur.execute("SELECT category, COUNT(*) as n FROM events GROUP BY category")
        by_cat = {r["category"]: r["n"] for r in cur.fetchall()}

        cur.execute("SELECT ran_at FROM run_log ORDER BY ran_at DESC LIMIT 1")
        last_run = cur.fetchone()
        last_run = (list(last_run.values())[0] if hasattr(last_run, "values") else last_run[0]) if last_run else "Never"

    return {
        "total":       total,
        "upcoming":    upcoming,
        "bookmarked":  bookmarked,
        "by_category": by_cat,
        "last_run":    last_run,
    }
