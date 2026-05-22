"""
Discovery scraper: uses DuckDuckGo HTML search (no API key required)
to find event pages from universities and companies not in the fixed list.
"""
from __future__ import annotations

import re
from urllib.parse import quote_plus, urlparse
from bs4 import BeautifulSoup

from ..models import Event
from ..utils.http import get_html, polite_sleep
from ..utils.date_parser import extract_dates, classify_event, CATEGORY_KEYWORDS

DDG_URL = "https://html.duckduckgo.com/html/?q={query}"

_SKIP_DOMAINS = {
    "facebook.com", "twitter.com", "x.com", "youtube.com",
    "wikipedia.org", "reddit.com", "quora.com",
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
        url = DDG_URL.format(query=quote_plus(query))
        html = get_html(url)
        if not html:
            return []

        soup = BeautifulSoup(html, "lxml")
        results = []

        for result in soup.select(".result"):
            title_el = result.select_one(".result__title a")
            snippet_el = result.select_one(".result__snippet")
            if not title_el:
                continue
            href = title_el.get("href", "")
            # DDG wraps links — extract the real URL
            real_url = self._extract_real_url(href)
            results.append({
                "title": title_el.get_text(strip=True),
                "url": real_url,
                "snippet": snippet_el.get_text(strip=True) if snippet_el else "",
            })

        return results[:10]

    def _scrape_result(self, result: dict) -> Event | None:
        title = result["title"]
        snippet = result["snippet"]
        url = result["url"]

        combined = title + " " + snippet
        if not any(kw.lower() in combined.lower() for kw in self.keywords):
            return None

        # Try to get more detail from the page
        html = get_html(url)
        full_text = ""
        if html:
            soup = BeautifulSoup(html, "lxml")
            full_text = soup.get_text(separator="\n")[:3000]

        date_text = full_text or snippet
        start_date, end_date, deadline = extract_dates(date_text)
        category = classify_event(title, snippet, CATEGORY_KEYWORDS)
        country = self._guess_country(url + " " + combined)

        return Event(
            title=title[:200],
            source_name="Web Search",
            source_url="https://html.duckduckgo.com",
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
    def _extract_real_url(href: str) -> str:
        # DDG redirect: //duckduckgo.com/l/?uddg=<encoded-url>
        m = re.search(r"uddg=([^&]+)", href)
        if m:
            from urllib.parse import unquote
            return unquote(m.group(1))
        if href.startswith("http"):
            return href
        return ""

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
