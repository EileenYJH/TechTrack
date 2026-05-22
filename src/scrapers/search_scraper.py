"""
Discovery scraper: uses DuckDuckGo search to find event pages not in the fixed source list.
Uses DDG snippets + regex only — no Ollama, so it stays fast.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

from ..models import Event
from ..utils.http import polite_sleep
from ..utils.date_parser import extract_dates, classify_event, CATEGORY_KEYWORDS

_SKIP_DOMAINS = {
    "facebook.com", "twitter.com", "x.com", "youtube.com",
    "wikipedia.org", "reddit.com", "quora.com", "linkedin.com",
    "instagram.com", "tiktok.com", "threads.net",
}


class SearchScraper:
    def __init__(self, queries: list[str], keywords: list[str]):
        self.queries = queries
        self.keywords = keywords

    def scrape(self) -> list[Event]:
        events: list[Event] = []
        seen_urls: set[str] = set()

        for query in self.queries:
            polite_sleep(1, 2)
            results = self._ddg_search(query, max_results=5)
            for result in results:
                url = result["url"]
                if url in seen_urls or self._is_skip_domain(url):
                    continue
                seen_urls.add(url)
                event = self._result_to_event(result)
                if event:
                    events.append(event)

        return events

    def _ddg_search(self, query: str, max_results: int = 5) -> list[dict]:
        try:
            from ddgs import DDGS
            results = []
            with DDGS() as ddgs:
                for r in ddgs.text(query, max_results=max_results):
                    results.append({
                        "title":   r.get("title", ""),
                        "url":     r.get("href", ""),
                        "snippet": r.get("body", ""),
                    })
            return results
        except Exception as e:
            print(f"[Search] DDG error for '{query}': {e}")
            return []

    def _result_to_event(self, result: dict) -> Event | None:
        title   = result["title"]
        snippet = result["snippet"]
        url     = result["url"]

        combined = title + " " + snippet
        if not any(kw.lower() in combined.lower() for kw in self.keywords):
            return None

        start_date, end_date, deadline = extract_dates(combined)
        category = classify_event(title, snippet, CATEGORY_KEYWORDS)
        country  = self._guess_country(combined)

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
            location=self._guess_location(combined),
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
        if any(kw in text_lower for kw in ["malaysia", "kuala lumpur", " kl ", "penang", "johor", "cyberjaya"]):
            return "Malaysia"
        if "singapore" in text_lower:
            return "Singapore"
        if "indonesia" in text_lower:
            return "Indonesia"
        return "International"

    @staticmethod
    def _guess_location(text: str) -> str:
        for pat in [
            r"(?:kuala lumpur|petaling jaya|penang|johor bahru|cyberjaya|putrajaya|selangor)",
            r"(?:venue|location|held at|at)\s*[:\-]?\s*([^\n,]{5,60})",
        ]:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                return m.group(0)[:80]
        return ""
