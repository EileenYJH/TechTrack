import sqlite3
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Optional
from .models import Event

DB_PATH = Path(__file__).parent.parent / "data" / "events.db"


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init_db() -> None:
    with _conn() as con:
        con.execute("""
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
        con.execute("""
            CREATE TABLE IF NOT EXISTS run_log (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                ran_at     TEXT,
                source     TEXT,
                found      INTEGER,
                added      INTEGER,
                error      TEXT
            )
        """)
        # Migration: add bookmarked column if it doesn't exist yet
        try:
            con.execute("ALTER TABLE events ADD COLUMN bookmarked INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass  # column already exists


def _event_id(event: Event) -> str:
    key = f"{event.title.lower().strip()}|{event.source_name}|{event.start_date}"
    return hashlib.sha1(key.encode()).hexdigest()


def upsert_event(event: Event) -> bool:
    """Insert event if new. Returns True if newly inserted."""
    eid = _event_id(event)
    d = event.to_dict()
    with _conn() as con:
        existing = con.execute("SELECT id FROM events WHERE id=?", (eid,)).fetchone()
        if existing:
            return False
        con.execute("""
            INSERT INTO events (id,title,source_name,source_url,event_url,category,country,
                                description,start_date,end_date,deadline,location,organizer,
                                tags,scraped_at,bookmarked)
            VALUES (:id,:title,:source_name,:source_url,:event_url,:category,:country,
                    :description,:start_date,:end_date,:deadline,:location,:organizer,
                    :tags,:scraped_at,0)
        """, {"id": eid, **d})
    return True


def toggle_bookmark(event_id: str) -> bool:
    """Toggle bookmark state. Returns the new bookmarked value (True = bookmarked)."""
    with _conn() as con:
        row = con.execute("SELECT bookmarked FROM events WHERE id=?", (event_id,)).fetchone()
        if not row:
            return False
        new_val = 0 if row["bookmarked"] else 1
        con.execute("UPDATE events SET bookmarked=? WHERE id=?", (new_val, event_id))
        return bool(new_val)


def log_run(source: str, found: int, added: int, error: str = "") -> None:
    with _conn() as con:
        con.execute(
            "INSERT INTO run_log (ran_at,source,found,added,error) VALUES (?,?,?,?,?)",
            (datetime.now().isoformat(), source, found, added, error),
        )


def get_all_events(
    upcoming_only: bool = True,
    category: Optional[str] = None,
    country: Optional[str] = None,
    search: Optional[str] = None,
    bookmarked_only: bool = False,
) -> list[dict]:
    query = "SELECT * FROM events WHERE 1=1"
    params: list = []

    if upcoming_only:
        query += " AND (start_date IS NULL OR start_date >= ?)"
        params.append(datetime.now().isoformat())

    if category and category != "All":
        query += " AND category = ?"
        params.append(category)

    if country and country != "All":
        query += " AND country = ?"
        params.append(country)

    if search:
        query += " AND (title LIKE ? OR description LIKE ? OR organizer LIKE ?)"
        like = f"%{search}%"
        params.extend([like, like, like])

    if bookmarked_only:
        query += " AND bookmarked = 1"

    query += " ORDER BY bookmarked DESC, COALESCE(start_date, '9999') ASC"

    with _conn() as con:
        rows = con.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def get_run_logs(limit: int = 50) -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM run_log ORDER BY ran_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_stats() -> dict:
    with _conn() as con:
        total = con.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        upcoming = con.execute(
            "SELECT COUNT(*) FROM events WHERE start_date IS NULL OR start_date >= ?",
            (datetime.now().isoformat(),),
        ).fetchone()[0]
        bookmarked = con.execute(
            "SELECT COUNT(*) FROM events WHERE bookmarked = 1"
        ).fetchone()[0]
        by_cat = con.execute(
            "SELECT category, COUNT(*) as n FROM events GROUP BY category"
        ).fetchall()
        last_run = con.execute(
            "SELECT ran_at FROM run_log ORDER BY ran_at DESC LIMIT 1"
        ).fetchone()
    return {
        "total": total,
        "upcoming": upcoming,
        "bookmarked": bookmarked,
        "by_category": {r["category"]: r["n"] for r in by_cat},
        "last_run": last_run[0] if last_run else "Never",
    }
