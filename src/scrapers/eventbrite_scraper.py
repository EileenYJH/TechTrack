"""
Scraper for Eventbrite and MLH public event pages (no API key required).
"""
from __future__ import annotations

import re
from urllib.parse import urljoin
from bs4 import BeautifulSoup

from ..models import Event
from ..utils.http import get_html, polite_sleep
from ..utils.date_parser import extract_dates, classify_event, CATEGORY_KEYWORDS


class EventbriteScraper:
    def __init__(self, sources: list[dict], keywords: list[str]):
        self.sources = sources
        self.keywords = keywords

    def scrape(self) -> list[Event]:
        events: list[Event] = []
        for source in self.sources:
            polite_sleep(1, 3)
            scraped = self._scrape_source(source)
            events.extend(scraped)
        return events

    def _scrape_source(self, source: dict) -> list[Event]:
        html = get_html(source["url"])
        if not html:
            return []

        soup = BeautifulSoup(html, "lxml")
        name = source["name"]
        country = source.get("country", "International")

        # Eventbrite card structure
        events: list[Event] = []
        cards = soup.select(
            ".eds-event-card__content, article, .event-card, [data-testid*='event']"
        )

        if not cards:
            # Fallback: generic link extraction
            return self._generic_extract(soup, source)

        for card in cards[:25]:
            title_el = card.select_one("h2, h3, .eds-event-card__formatted-name")
            link_el = card.select_one("a[href]")
            date_el = card.select_one(
                "time, .eds-event-card__sub-content, [class*='date']"
            )
            desc_el = card.select_one("p, .eds-event-card__description")

            if not title_el or not link_el:
                continue

            title = title_el.get_text(strip=True)
            if not self._is_relevant(title):
                continue

            event_url = link_el.get("href", "")
            if not event_url.startswith("http"):
                event_url = urljoin(source["url"], event_url)

            date_text = date_el.get_text(strip=True) if date_el else ""
            description = desc_el.get_text(strip=True) if desc_el else ""
            start_date, end_date, deadline = extract_dates(date_text + " " + description)
            category = classify_event(title, description, CATEGORY_KEYWORDS)

            events.append(Event(
                title=title,
                source_name=name,
                source_url=source["url"],
                event_url=event_url,
                category=category,
                country=country,
                description=description[:400],
                start_date=start_date,
                end_date=end_date,
                deadline=deadline,
                location="",
                organizer=name,
            ))

        return events

    def _generic_extract(self, soup: BeautifulSoup, source: dict) -> list[Event]:
        events: list[Event] = []
        for a in soup.select("a[href]")[:40]:
            title = a.get_text(strip=True)
            if len(title) < 10 or not self._is_relevant(title):
                continue
            href = a.get("href", "")
            if not href.startswith("http"):
                href = urljoin(source["url"], href)
            ctx = a.find_parent().get_text(separator=" ", strip=True) if a.find_parent() else title
            start_date, end_date, deadline = extract_dates(ctx)
            category = classify_event(title, ctx, CATEGORY_KEYWORDS)
            events.append(Event(
                title=title[:200],
                source_name=source["name"],
                source_url=source["url"],
                event_url=href,
                category=category,
                country=source.get("country", "International"),
                description=ctx[:400],
                start_date=start_date,
                end_date=end_date,
                deadline=deadline,
                location="",
                organizer=source["name"],
            ))
        return events[:15]

    def _is_relevant(self, text: str) -> bool:
        text_lower = text.lower()
        return any(kw.lower() in text_lower for kw in self.keywords)
