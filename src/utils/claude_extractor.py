"""
AI-powered event extraction using Ollama (local LLM).
Reads page text and returns structured event data — far more accurate than regex/CSS selectors.
Falls back gracefully (returns []) if Ollama is not running.

Setup:
  1. Install Ollama: https://ollama.com/download/windows
  2. Pull a model: ollama pull llama3.2
  3. Ollama runs automatically in the background after install.
"""
from __future__ import annotations

import json
import re
import requests as _requests
from datetime import date, datetime
from typing import Optional

OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
OLLAMA_MODEL = "llama3.2"

_CODE_RE = re.compile(
    r'[{}\[\]]|=>|\bfunction\b|\bimport\b|\bconst\b|\blet\b|\bvar\b'
    r'|\bdef\b|\bclass\b|npm |pip |\.js\b|\.py\b|</|/>|<!--',
    re.IGNORECASE
)


def _looks_like_code(text: str) -> bool:
    """Return True if the text is a code snippet, not an event title."""
    text = text.strip()
    if not text or len(text) < 6 or len(text) > 250:
        return True
    if _CODE_RE.search(text):
        return True
    if re.search(r'[^a-zA-Z0-9\s\-–,.()/\'\":!?]{2,}', text):
        return True
    return False

_SYSTEM_PROMPT = """You are an event extraction assistant for a Malaysian engineering and CS student tracker.

Given text scraped from a webpage, extract all relevant upcoming events.

ONLY include events that are one of: competitions, hackathons, career fairs, conferences, workshops, bootcamps, seminars, tech talks, company visits, robotics, embedded systems, AI/ML, cybersecurity, coding challenges, datathons, internship fairs.

STRICTLY SKIP all of the following — do NOT include them as events:
- News articles, press releases, blog posts, announcements, newsletters
- Public holidays, cuti umum, semester breaks, exam timetables
- Convocations, graduations, general university notices
- Job postings, internship listings (only include internship FAIRS)
- Staff/faculty meetings, board meetings
- Anything that is not a student-facing event students can register for or attend

An event must have: a specific name, a date or registration deadline, and be open for student participation.

Respond with a JSON object containing an "events" array. Each event must have these exact keys:
{{
  "events": [
    {{
      "title": "event name here",
      "start_date": "YYYY-MM-DD or null",
      "end_date": "YYYY-MM-DD or null",
      "deadline": "YYYY-MM-DD or null",
      "category": "one of: Competition, Career Fair, Conference, Workshop / Bootcamp, Seminar / Talk, Company Visit, Hackathon, Other",
      "location": "venue or city or null",
      "organizer": "organizing body or null",
      "description": "1-2 sentence summary",
      "event_url": "direct URL if found in text or null"
    }}
  ]
}}

If no relevant events found, return {{"events": []}}.
Today is {today}. Do not include events that have already ended."""

# Field name aliases the model might use instead of our canonical names
_FIELD_ALIASES = {
    "title": ["name", "event_name", "event_title"],
    "start_date": ["date", "event_date", "start", "from"],
    "end_date": ["end", "to", "until"],
    "deadline": ["registration_deadline", "reg_deadline", "apply_by", "due_date"],
    "event_url": ["url", "link", "href"],
    "organizer": ["organisation", "organization", "hosted_by", "host"],
}


def _normalise(event: dict) -> dict:
    """Map any alias field names to our canonical names."""
    out = dict(event)
    for canonical, aliases in _FIELD_ALIASES.items():
        if canonical not in out:
            for alias in aliases:
                if alias in out:
                    out[canonical] = out.pop(alias)
                    break
    return out


def extract_events(page_text: str, source_url: str, source_name: str) -> list[dict]:
    """Extract structured events from raw page text using a local Ollama model.

    Returns [] if Ollama is not running, no events found, or on any error.
    """
    today = date.today().isoformat()
    trimmed = page_text[:1200]

    try:
        resp = _requests.post(
            OLLAMA_URL,
            json={
                "model": OLLAMA_MODEL,
                "messages": [
                    {"role": "system", "content": _SYSTEM_PROMPT.format(today=today)},
                    {"role": "user", "content": f"Source: {source_name}\nURL: {source_url}\n\n{trimmed}"},
                ],
                "stream": False,
                "format": "json",
            },
            timeout=120,
        )
        resp.raise_for_status()
        raw = resp.json()["message"]["content"].strip()

        parsed = json.loads(raw)
        # Unwrap {"events": [...]} or any dict wrapping a list
        if isinstance(parsed, dict):
            for key in ("events", "results", "data", "items"):
                if key in parsed and isinstance(parsed[key], list):
                    parsed = parsed[key]
                    break
            else:
                # Take first list value
                for v in parsed.values():
                    if isinstance(v, list):
                        parsed = v
                        break
                else:
                    parsed = []

        if not isinstance(parsed, list):
            return []

        results = [_normalise(e) for e in parsed
                   if isinstance(e, dict)
                   and (e.get("title") or e.get("name"))
                   and not _looks_like_code(str(e.get("title") or e.get("name", "")))]
        # Strip any "null" strings the model may have written
        for r in results:
            for k, v in r.items():
                if v in ("null", "None", "none", ""):
                    r[k] = None
        return results

    except _requests.exceptions.ConnectionError:
        print("[Ollama] Not running — start Ollama from the system tray or run: ollama serve")
        return []
    except Exception as e:
        print(f"[Ollama] Extraction error for {source_name}: {e}")
        return []


def parse_date(val: Optional[str]) -> Optional[datetime]:
    """Convert ISO date string from model output to datetime."""
    if not val:
        return None
    try:
        return datetime.fromisoformat(val)
    except (ValueError, TypeError):
        return None
