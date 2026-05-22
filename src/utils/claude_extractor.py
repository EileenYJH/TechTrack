"""
Claude-powered event extraction. Uses Claude Haiku to read page text and
return structured event data — far more accurate than regex/CSS selectors.
Falls back gracefully (returns []) if ANTHROPIC_API_KEY is not configured.
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime
from typing import Optional

_client = None


def _get_api_key() -> Optional[str]:
    try:
        import streamlit as st
        key = st.secrets.get("ANTHROPIC_API_KEY")
        if key:
            return key
    except Exception:
        pass
    return os.environ.get("ANTHROPIC_API_KEY")


def _get_client():
    global _client
    if _client is not None:
        return _client
    api_key = _get_api_key()
    if not api_key:
        return None
    try:
        from anthropic import Anthropic
        _client = Anthropic(api_key=api_key)
    except ImportError:
        print("[Claude] anthropic package not installed — run: pip install anthropic")
    return _client


_SYSTEM_PROMPT = """You are an event extraction assistant for a Malaysian engineering and CS student tracker.

Given text scraped from a webpage, extract all relevant upcoming events and return a JSON array.

Include only events related to: competitions, hackathons, career fairs, conferences, workshops, bootcamps, seminars, tech talks, company visits, robotics, embedded systems, AI/ML, cybersecurity, coding challenges, datathons, internship fairs.

Skip: past events, general news, unrelated content, staff announcements.

For each event return a JSON object with these exact keys:
- "title": event name (string, required)
- "start_date": "YYYY-MM-DD" or null
- "end_date": "YYYY-MM-DD" or null
- "deadline": registration/submission deadline "YYYY-MM-DD" or null
- "category": one of "Competition", "Career Fair", "Conference", "Workshop / Bootcamp", "Seminar / Talk", "Company Visit", "Hackathon", "Other"
- "location": venue or city (string or null)
- "organizer": organizing body (string or null)
- "description": 1-2 sentence summary (string)
- "event_url": direct URL to the event if found in the text (string or null)

Return ONLY a valid JSON array. No explanation, no markdown fences. If no relevant events found, return [].
Today is {today}. Do not include events that have already ended."""


def extract_events(page_text: str, source_url: str, source_name: str) -> list[dict]:
    """Extract structured events from raw page text using Claude Haiku.

    Returns [] if API key not configured, no events found, or on any error.
    Uses prompt caching so repeated calls within 5 min reuse the cached system prompt.
    """
    client = _get_client()
    if not client:
        return []

    today = date.today().isoformat()
    trimmed = page_text[:8000]

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2048,
            system=[{
                "type": "text",
                "text": _SYSTEM_PROMPT.format(today=today),
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{
                "role": "user",
                "content": f"Source: {source_name}\nURL: {source_url}\n\n{trimmed}",
            }],
        )
        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```", 1)[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.rsplit("```", 1)[0]
        results = json.loads(raw.strip())
        return results if isinstance(results, list) else []
    except Exception as e:
        print(f"[Claude] Extraction error for {source_name}: {e}")
        return []


def parse_date(val: Optional[str]) -> Optional[datetime]:
    """Convert ISO date string from Claude output to datetime."""
    if not val:
        return None
    try:
        return datetime.fromisoformat(val)
    except (ValueError, TypeError):
        return None
