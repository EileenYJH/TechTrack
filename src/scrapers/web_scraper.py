"""
General-purpose scraper for university, organisation, and company event pages.
Works on static HTML; Playwright fallback for JS-heavy sites.
"""
from __future__ import annotations

import re
from typing import Optional
from bs4 import BeautifulSoup

from ..models import Event
from ..utils.http import get_html, polite_sleep
from ..utils.date_parser import extract_dates, classify_event, CATEGORY_KEYWORDS


_BLOCKLIST = [
    # Non-events
    "cuti umum", "public holiday", "hari kelepasan", "hari cuti",
    "tutup", "closed", "inaccessible", "maintenance", "convocation",
    "graduation", "commencement", "semester break", "cuti semester",
    "exam timetable", "jadual peperiksaan",
    "press release", "media release", "newsletter", "staff announcement",
    "minutes of meeting", "job vacancy", "jawatan kosong",
    # Secondary school / pre-university — not our audience
    "secondary school", "high school", "sekolah menengah", "sekolah rendah",
    "primary school", "spm students", "form 4", "form 5", "form 6",
    "spm level", "stpm", "pt3", "upsr", "lower secondary", "upper secondary",
    "school students only", "open to school", "for schools",
]

# Patterns that indicate the "title" is actually code/markup, not an event name
_CODE_PATTERNS = re.compile(
    r'[{}\[\]<>]|=>|\bfunction\b|\bimport\b|\bconst\b|\blet\b|\bvar\b'
    r'|\bdef\b|\bclass\b|npm |pip |\.js\b|\.py\b|</|/>|<!--',
    re.IGNORECASE
)


def _is_code_title(text: str) -> bool:
    """Return True if the text looks like scraped code rather than an event title."""
    text = text.strip()
    if not text or len(text) < 6 or len(text) > 250:
        return True
    if _CODE_PATTERNS.search(text):
        return True
    # Reject if more than 2 non-word chars in a row (e.g. `==`, `&&`, `::`)
    if re.search(r'[^a-zA-Z0-9\s\-–,.()/\'\":!?]{2,}', text):
        return True
    return False

# CSS selectors commonly used for event listings
_LINK_SELECTORS = [
    "a[href*='event']",
    "a[href*='Event']",
    "a[href*='news']",
    "a[href*='activity']",
    "a[href*='programme']",
    ".event-title a",
    ".event-link",
    "article a",
    ".card a",
    "h2 a",
    "h3 a",
]

_TITLE_SELECTORS = ["h1", "h2.event-title", ".event-title", ".page-title", "title"]
_DESC_SELECTORS  = [".event-description", ".event-detail", "article p", ".content p", "main p"]
_DATE_SELECTORS  = [".event-date", ".date", "time", "[class*='date']", "[class*='Date']"]


class WebScraper:
    def __init__(self, source: dict, keywords: list[str]):
        self.source = source
        self.keywords = keywords

    def scrape(self) -> list[Event]:
        html = get_html(self.source["url"])
        if not html:
            return []

        soup = BeautifulSoup(html, "lxml")
        page_text = soup.get_text(separator="\n", strip=True)

        # Try Claude extraction first — smarter and faster (1 API call vs 30 HTTP requests)
        from ..utils.claude_extractor import extract_events, parse_date
        claude_results = extract_events(page_text, self.source["url"], self.source["name"])
        if claude_results:
            return [self._result_to_event(r, parse_date) for r in claude_results]

        # Fallback: traditional BeautifulSoup + link-following
        events: list[Event] = []
        event_links = self._find_event_links(soup, self.source["url"])
        for url, title in event_links[:8]:  # cap at 8 to keep runtime short
            polite_sleep(0.5, 1.5)
            event = self._scrape_event_page(url, title)
            if event:
                events.append(event)
        if not events:
            events = self._parse_listing_page(soup, self.source["url"])
        return events

    def _result_to_event(self, r: dict, parse_date) -> Event:
        return Event(
            title=(r.get("title") or "")[:200],
            source_name=self.source["name"],
            source_url=self.source["url"],
            event_url=r.get("event_url") or self.source["url"],
            category=r.get("category") or "Other",
            country=self.source.get("country", "Unknown"),
            description=(r.get("description") or "")[:500],
            start_date=parse_date(r.get("start_date")),
            end_date=parse_date(r.get("end_date")),
            deadline=parse_date(r.get("deadline")),
            location=r.get("location") or "",
            organizer=r.get("organizer") or self.source["name"],
            image_url=r.get("image_url") or "",
        )

    def _find_event_links(self, soup: BeautifulSoup, base_url: str) -> list[tuple[str, str]]:
        seen: set[str] = set()
        results: list[tuple[str, str]] = []

        for selector in _LINK_SELECTORS:
            for a in soup.select(selector):
                href = a.get("href", "")
                text = a.get_text(strip=True)
                if not href or not text:
                    continue
                full_url = _resolve_url(href, base_url)
                if full_url in seen:
                    continue
                if self._is_relevant(text):
                    seen.add(full_url)
                    results.append((full_url, text))

        return results

    def _scrape_event_page(self, url: str, fallback_title: str) -> Optional[Event]:
        html = get_html(url)
        if not html:
            return None

        soup = BeautifulSoup(html, "lxml")
        title = self._extract_text(soup, _TITLE_SELECTORS) or fallback_title
        description = self._extract_text(soup, _DESC_SELECTORS)
        date_text = self._extract_text(soup, _DATE_SELECTORS) or soup.get_text()
        location = self._extract_location(soup.get_text())
        image_url = self._extract_og_image(soup)

        start_date, end_date, deadline = extract_dates(date_text)
        category = classify_event(title, description or "", CATEGORY_KEYWORDS)

        if not self._is_relevant(title + " " + (description or "")):
            return None

        return Event(
            title=title.strip(),
            source_name=self.source["name"],
            source_url=self.source["url"],
            event_url=url,
            category=category,
            country=self.source.get("country", "Unknown"),
            description=(description or "")[:500],
            start_date=start_date,
            end_date=end_date,
            deadline=deadline,
            location=location,
            organizer=self.source["name"],
            image_url=image_url,
        )

    @staticmethod
    def _extract_og_image(soup: BeautifulSoup) -> str:
        for attr in ("og:image", "twitter:image"):
            tag = soup.find("meta", property=attr) or soup.find("meta", attrs={"name": attr})
            if tag and tag.get("content"):
                return tag["content"].strip()
        return ""

    def _parse_listing_page(self, soup: BeautifulSoup, base_url: str) -> list[Event]:
        """Extract events directly from a listing page (no sub-pages)."""
        events: list[Event] = []
        text = soup.get_text(separator="\n")
        lines = [l.strip() for l in text.splitlines() if len(l.strip()) > 10]

        for i, line in enumerate(lines):
            if not self._is_relevant(line) or _is_code_title(line):
                continue
            ctx = "\n".join(lines[max(0, i-2): i+5])
            start_date, end_date, deadline = extract_dates(ctx)
            category = classify_event(line, ctx, CATEGORY_KEYWORDS)
            events.append(Event(
                title=line[:200],
                source_name=self.source["name"],
                source_url=base_url,
                event_url=base_url,
                category=category,
                country=self.source.get("country", "Unknown"),
                description=ctx[:400],
                start_date=start_date,
                end_date=end_date,
                deadline=deadline,
                location=self._extract_location(ctx),
                organizer=self.source["name"],
            ))

        return events[:20]

    def _is_relevant(self, text: str) -> bool:
        text_lower = text.lower()
        if any(block in text_lower for block in _BLOCKLIST):
            return False
        return any(kw.lower() in text_lower for kw in self.keywords)

    @staticmethod
    def _extract_text(soup: BeautifulSoup, selectors: list[str]) -> Optional[str]:
        for sel in selectors:
            el = soup.select_one(sel)
            if el:
                return el.get_text(separator=" ", strip=True)
        return None

    @staticmethod
    def _extract_location(text: str) -> str:
        patterns = [
            r"(?:venue|location|place|held at|at)\s*[:\-]?\s*([^\n,]+)",
            r"(?:kuala lumpur|petaling jaya|penang|johor bahru|cyberjaya|putrajaya|selangor)",
        ]
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                return m.group(0)[:100]
        return ""


def _resolve_url(href: str, base: str) -> str:
    if href.startswith("http"):
        return href
    from urllib.parse import urljoin
    return urljoin(base, href)
