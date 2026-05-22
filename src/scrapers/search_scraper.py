"""
Discovery scraper: uses DuckDuckGo search (via duckduckgo-search package)
to find event pages from universities and companies not in the fixed list.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse
from bs4 import BeautifulSoup

from ..models import Event
from ..utils.http import get_html, polite_sleep
from ..utils.date_parser import extract_dates, classify_event, CATEGORY_KEYWORDS

_SKIP_DOMAINS = {
    "facebook.com", "twitter.com", "x.com", "youtube.com",
    "wikipedia.org", "reddit.com", "quora.com", "linkedin.com",
}


class SearchScraper:
    def __init__(self, queries: list[str], keywords: list[str]):
        self.queries = queries
        self.keywords = keywords

    def scrape(self) -> list[Event]:
        events: list[Event] = []
        seen_urls: set[str] = set()

        for query in self.queries:
            polite_sleep(2, 4)
            results = self._ddg_search(query)
            for result in results:
                url = result["url"]
                if url in seen_urls or self._is_skip_domain(url):
                    continue
                seen_urls.add(url)
                polite_sleep(1, 2)
                event = self._scrape_result(result)
                if event:
                    events.append(event)

        return events

    def _ddg_search(self, query: str) -> list[dict]:
        try:
            from ddgs import DDGS
            results = []
            with DDGS() as ddgs:
                for r in ddgs.text(query, max_results=10):
                    results.append({
                        "title": r.get("title", ""),
                        "url": r.get("href", ""),
                        "snippet": r.get("body", ""),
                    })
            return results
        except Exception as e:
            print(f"[Search] DDG error for '{query}': {e}")
            return []

    def _scrape_result(self, result: dict) -> Event | None:
        title = result["title"]
        snippet = result["snippet"]
        url = result["url"]

        combined = title + " " + snippet
        if not any(kw.lower() in combined.lower() for kw in self.keywords):
            return None

        # Try Claude extraction on the actual page for richer data
        from ..utils.claude_extractor import extract_events, parse_date
        html = get_html(url)
        if html:
            soup = BeautifulSoup(html, "lxml")
            page_text = soup.get_text(separator="\n", strip=True)
            claude_results = extract_events(page_text, url, title)
            if claude_results:
                r = claude_results[0]
                return Event(
                    title=(r.get("title") or title)[:200],
                    source_name="Web Search",
                    source_url=url,
                    event_url=r.get("event_url") or url,
                    category=r.get("category") or "Other",
                    country=self._guess_country(url + " " + combined),
                    description=(r.get("description") or snippet)[:500],
                    start_date=parse_date(r.get("start_date")),
                    end_date=parse_date(r.get("end_date")),
                    deadline=parse_date(r.get("deadline")),
                    location=r.get("location") or "",
                    organizer=r.get("organizer") or "",
                )
            full_text = page_text[:3000]
        else:
            full_text = ""

        # Fallback: regex-based extraction from snippet/page text
        date_text = full_text or snippet
        start_date, end_date, deadline = extract_dates(date_text)
        category = classify_event(title, snippet, CATEGORY_KEYWORDS)
        country = self._guess_country(url + " " + combined)

        return Event(
            title=title[:200],
            source_name="Web Search",
            source_url=url,
            event_url=url,
            category=category,
            country=country,
            description=snippet[:500],
            start_date=start_date,
            end_date=end_date,
            deadline=deadline,
            location=self._guess_location(combined + full_text[:500]),
            organizer="",
        )

    @staticmethod
    def _is_skip_domain(url: str) -> bool:
        try:
            domain = urlparse(url).netloc.lstrip("www.")
            return any(skip in domain for skip in _SKIP_DOMAINS)
        except Exception:
            return False

    @staticmethod
    def _guess_country(text: str) -> str:
        text_lower = text.lower()
        if any(kw in text_lower for kw in ["malaysia", "kuala lumpur", "kl", "penang", "johor", "cyberjaya"]):
            return "Malaysia"
        if "singapore" in text_lower:
            return "Singapore"
        if "indonesia" in text_lower:
            return "Indonesia"
        return "International"

    @staticmethod
    def _guess_location(text: str) -> str:
        patterns = [
            r"(?:kuala lumpur|petaling jaya|penang|johor bahru|cyberjaya|putrajaya|selangor|kl)",
            r"(?:venue|location|held at|at)\s*[:\-]?\s*([^\n,]{5,60})",
        ]
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                return m.group(0)[:80]
        return ""
