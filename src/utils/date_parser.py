import re
from datetime import datetime
from typing import Optional
from dateutil import parser as dateutil_parser

# Common date patterns found in event pages
_DATE_PATTERNS = [
    r"\b(\d{1,2}[\s\-/]\w+[\s\-/]\d{4})\b",
    r"\b(\w+\s+\d{1,2},?\s+\d{4})\b",
    r"\b(\d{4}[\-/]\d{2}[\-/]\d{2})\b",
    r"\b(\d{1,2}\s+\w+\s+\d{4})\b",
    r"\b(\d{1,2}/\d{1,2}/\d{4})\b",
]

# "14–16 June 2025"  or  "14 - 16 June 2025"  or  "14 to 16 June 2025"
_RANGE_PATTERN = re.compile(
    r"\b(\d{1,2})\s*(?:[–\-]|to)\s*(\d{1,2})\s+(\w+)\s+(\d{4})\b",
    re.IGNORECASE,
)

_DEADLINE_KEYWORDS = [
    "deadline", "registration closes", "apply by", "submit by",
    "applications due", "closing date", "register before", "register by",
    "registration deadline", "submission deadline",
]

_START_KEYWORDS = [
    "date:", "event date", "starts", "start date", "held on",
    "taking place", "when:", "schedule", "on ", "from ",
]


def _expand_ranges(text: str) -> str:
    """Replace 'DD-DD Month YYYY' with 'DD Month YYYY - DD Month YYYY' so both
    boundary dates are picked up by the standard patterns."""
    def _replace(m: re.Match) -> str:
        d1, d2, month, year = m.group(1), m.group(2), m.group(3), m.group(4)
        return f"{d1} {month} {year} - {d2} {month} {year}"
    return _RANGE_PATTERN.sub(_replace, text)


def extract_dates(text: str) -> tuple[Optional[datetime], Optional[datetime], Optional[datetime]]:
    """Returns (start_date, end_date, deadline) extracted from raw text."""
    start_date = end_date = deadline = None
    expanded = _expand_ranges(text)
    lines = expanded.lower().split("\n")

    for line in lines:
        dates_in_line = _find_dates_in_text(line)
        if not dates_in_line:
            continue

        # Check if this line mentions a deadline
        if any(kw in line for kw in _DEADLINE_KEYWORDS):
            if deadline is None:
                deadline = dates_in_line[0]
        # Check if this line mentions start/event date
        elif any(kw in line for kw in _START_KEYWORDS):
            if start_date is None:
                start_date = dates_in_line[0]
            if len(dates_in_line) > 1 and end_date is None:
                end_date = dates_in_line[1]
        else:
            # Fallback: first date found → start_date, second → end_date
            if start_date is None:
                start_date = dates_in_line[0]
            if len(dates_in_line) > 1 and end_date is None:
                end_date = dates_in_line[1]

    return start_date, end_date, deadline


def _find_dates_in_text(text: str) -> list[datetime]:
    found = []
    seen_strs: set[str] = set()
    for pattern in _DATE_PATTERNS:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            raw = match.group(1)
            if raw in seen_strs:
                continue
            seen_strs.add(raw)
            try:
                dt = dateutil_parser.parse(raw, dayfirst=True)
                # Sanity-check: only accept dates between 2024 and 2030
                if 2024 <= dt.year <= 2030:
                    found.append(dt)
            except Exception:
                pass
    return found


def classify_event(title: str, description: str, keywords_map: dict[str, list[str]]) -> str:
    text = (title + " " + description).lower()
    for category, kws in keywords_map.items():
        if any(kw.lower() in text for kw in kws):
            return category
    return "Other"


CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "Hackathon": ["hackathon", "hack", "datathon", "buildathon"],
    "Competition": [
        "competition", "challenge", "contest", "olympiad", "award",
        "robotics", "coding challenge", "case competition",
    ],
    "Career Fair": ["career fair", "job fair", "internship fair", "recruitment fair", "hiring fair"],
    "Conference": ["conference", "symposium", "summit", "congress", "colloquium", "forum"],
    "Workshop / Bootcamp": ["workshop", "bootcamp", "boot camp", "training", "course", "masterclass"],
    "Seminar / Talk": ["seminar", "talk", "lecture", "webinar", "tech talk", "speaker"],
    "Company Visit": ["company visit", "industry visit", "factory visit", "site visit", "plant visit"],
}
