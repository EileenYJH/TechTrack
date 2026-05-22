"""
Instagram scraper using instaloader (scrapes public profiles, no API key needed).
Rate-limited by default; will skip gracefully if blocked.
"""
from __future__ import annotations

import re
import time
from typing import Optional

from ..models import Event
from ..utils.date_parser import extract_dates, classify_event, CATEGORY_KEYWORDS


class InstagramScraper:
    def __init__(self, accounts: list[str], keywords: list[str]):
        self.accounts = accounts
        self.keywords = keywords
        self._loader = None

    def _get_loader(self):
        if self._loader is None:
            try:
                import instaloader
                self._loader = instaloader.Instaloader(
                    download_pictures=False,
                    download_videos=False,
                    download_video_thumbnails=False,
                    download_geotags=False,
                    download_comments=False,
                    save_metadata=False,
                    compress_json=False,
                    quiet=True,
                )
            except ImportError:
                print("[Instagram] instaloader not installed — skipping Instagram scraping")
        return self._loader

    def scrape(self) -> list[Event]:
        loader = self._get_loader()
        if not loader:
            return []

        events: list[Event] = []
        for account in self.accounts:
            try:
                account_events = self._scrape_account(loader, account)
                events.extend(account_events)
                time.sleep(5)  # be polite between accounts
            except Exception as e:
                print(f"[Instagram] Skipping @{account}: {e}")

        return events

    def _scrape_account(self, loader, username: str) -> list[Event]:
        try:
            import instaloader
            profile = instaloader.Profile.from_username(loader.context, username)
        except Exception as e:
            print(f"[Instagram] Cannot load @{username}: {e}")
            return []

        events: list[Event] = []
        post_count = 0

        for post in profile.get_posts():
            if post_count >= 20:  # only check latest 20 posts per account
                break
            post_count += 1

            caption = post.caption or ""
            if not self._is_relevant(caption):
                continue

            start_date, end_date, deadline = extract_dates(caption)
            category = classify_event(caption[:100], caption, CATEGORY_KEYWORDS)
            title = self._extract_title(caption)
            post_url = f"https://www.instagram.com/p/{post.shortcode}/"

            events.append(Event(
                title=title,
                source_name=f"Instagram @{username}",
                source_url=f"https://www.instagram.com/{username}/",
                event_url=post_url,
                category=category,
                country=self._guess_country(caption),
                description=caption[:500],
                start_date=start_date,
                end_date=end_date,
                deadline=deadline,
                location=self._extract_location(caption),
                organizer=username,
                tags=post.hashtags,
            ))

            time.sleep(2)

        return events

    def _is_relevant(self, text: str) -> bool:
        text_lower = text.lower()
        return any(kw.lower() in text_lower for kw in self.keywords)

    @staticmethod
    def _extract_title(caption: str) -> str:
        first_line = caption.split("\n")[0].strip()
        return first_line[:150] if first_line else caption[:150]

    @staticmethod
    def _guess_country(text: str) -> str:
        text_lower = text.lower()
        if any(kw in text_lower for kw in ["malaysia", "kuala lumpur", "kl", "penang", "johor", "cyberjaya"]):
            return "Malaysia"
        return "International"

    @staticmethod
    def _extract_location(text: str) -> str:
        m = re.search(
            r"(?:venue|location|at)\s*[:\-]?\s*([^\n,]{5,60})", text, re.IGNORECASE
        )
        if m:
            return m.group(1).strip()[:80]
        return ""
