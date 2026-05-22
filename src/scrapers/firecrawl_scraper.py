"""
Production-grade Firecrawl event scraper for TechTrack.

Replaces the local Ollama approach with Firecrawl (handles JS, returns clean
markdown) + the same Anthropic Claude API you already have configured.

Architecture
------------
  Firecrawl  →  renders page, removes boilerplate, returns clean markdown
  Claude API →  extracts structured events from the markdown (fast + accurate)

  Falls back to Firecrawl's own LLM if ANTHROPIC_API_KEY is absent.
  Falls back to the existing BS4+Ollama WebScraper if FIRECRAWL_API_KEY absent.

Setup
-----
  pip install firecrawl-py tenacity

  .streamlit/secrets.toml   OR   environment variables:
    FIRECRAWL_API_KEY = "fc-..."           # required for this module
    ANTHROPIC_API_KEY = "sk-ant-..."       # optional — used for richer extraction

Credit cost (Firecrawl)
  Scrape:         1–2 credits per page
  Extract (LLM):  5–10 credits per page
  Free plan:      500 credits/month  (~50 scrape+extract runs)
  Hobby ($16/mo): 3 000 credits/month (~300 runs)
"""
from __future__ import annotations

import os
import re
import json
import hashlib
import logging
import time
from datetime import datetime, date
from enum import Enum
from typing import Optional

import httpx
from pydantic import BaseModel, Field
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)

from ..models import Event

logger = logging.getLogger("techtrack.firecrawl")

# ── Key helpers ───────────────────────────────────────────────────────────────

def _get_secret(name: str) -> str | None:
    """Read from Streamlit secrets → env var → None."""
    try:
        import streamlit as st
        val = st.secrets.get(name)
        if val:
            return str(val)
    except Exception:
        pass
    return os.environ.get(name)


FIRECRAWL_API_KEY: str | None = _get_secret("FIRECRAWL_API_KEY")
ANTHROPIC_API_KEY: str | None = _get_secret("ANTHROPIC_API_KEY")

FIRECRAWL_BASE = "https://api.firecrawl.dev/v1"

# ── Pydantic models ───────────────────────────────────────────────────────────

class EventCategory(str, Enum):
    COMPETITION   = "Competition"
    HACKATHON     = "Hackathon"
    WORKSHOP      = "Workshop / Bootcamp"
    CONFERENCE    = "Conference"
    COMPANY_VISIT = "Company Visit"
    SEMINAR       = "Seminar / Talk"
    CAREER_FAIR   = "Career Fair"
    OTHER         = "Other"


class TechFocus(str, Enum):
    HARDWARE_EE = "Hardware/EE"
    AI_ML       = "AI/ML"
    CODING      = "Coding"
    HYBRID      = "Hybrid"
    OTHER       = "Other"


class RawEvent(BaseModel):
    """Structured event as returned by LLM extraction."""
    title:       str
    start_date:  Optional[str] = None   # YYYY-MM-DD
    end_date:    Optional[str] = None
    deadline:    Optional[str] = None   # registration deadline
    location:    Optional[str] = None
    organizer:   Optional[str] = None
    event_url:   Optional[str] = None
    description: Optional[str] = None
    eligibility: Optional[str] = None
    prize:       Optional[str] = None
    team_size:   Optional[str] = None
    tags:        list[str]     = Field(default_factory=list)


class RawEventList(BaseModel):
    events: list[RawEvent] = Field(default_factory=list)


# ── Relevance scoring for EE + AI + Coding ───────────────────────────────────

_EE_KEYWORDS = {
    "embedded", "fpga", "pcb", "circuit", "power electronics", "motor drive",
    "sensor", "iot", "internet of things", "arduino", "raspberry pi", "esp32",
    "stm32", "arm cortex", "microcontroller", "verilog", "vhdl", "analog",
    "digital design", "semiconductor", "rf", "signal processing", "wireless",
    "electric vehicle", "ev charger", "drone", "uav", "hardware", "robotics",
    "mechatronics", "automation", "plc", "firmware", "low-power", "solar",
    "photovoltaic", "oscilloscope", "soldering", "schematic", "pcb design",
    "keysight", "infineon", "bosch", "nxp", "ti", "renesas", "stmicro",
    "altium", "kicad", "proteus", "multisim", "ltspice",
}

_AI_ML_KEYWORDS = {
    "machine learning", "neural network", "deep learning", "computer vision",
    "nlp", "llm", "large language model", "transformer", "generative ai",
    "data science", "kaggle", "pytorch", "tensorflow", "keras", "scikit",
    "reinforcement learning", "natural language", "diffusion model", "gpt",
    "stable diffusion", "object detection", "image classification", "gan",
    "autonomous", "self-driving", "ai hackathon", "ml challenge", "datathon",
    "hugging face", "mlops", "model training", "ai competition", "llmops",
    "computer vision challenge", "nvidia", "cuda", "ai research",
}

_CODING_KEYWORDS = {
    "algorithm", "competitive programming", "software engineering", "devhacks",
    "app development", "web development", "mobile app", "cloud computing",
    "api", "backend", "frontend", "full stack", "open source", "hackathon",
    "coding challenge", "programming contest", "ctf", "cybersecurity",
    "blockchain", "web3", "smart contract", "devops", "kubernetes", "docker",
    "icpc", "acm", "google codejam", "meta hacker cup", "codeforces",
}

_SECONDARY_SCHOOL = {
    "secondary school", "high school", "spm", "form 4", "form 5", "form 6",
    "sekolah menengah", "stpm", "pt3", "upsr", "lower secondary",
    "only for school", "school students only",
}


def score_relevance(title: str, description: str, tags: list[str]) -> tuple[int, TechFocus]:
    """
    Score event relevance (0–100) for EE + AI + Coding students.
    Returns (score, primary_focus).
    """
    text = (title + " " + description + " " + " ".join(tags)).lower()

    if any(k in text for k in _SECONDARY_SCHOOL):
        return 0, TechFocus.OTHER

    ee_hits     = sum(1 for k in _EE_KEYWORDS     if k in text)
    ai_hits     = sum(1 for k in _AI_ML_KEYWORDS  if k in text)
    code_hits   = sum(1 for k in _CODING_KEYWORDS if k in text)
    total       = ee_hits + ai_hits + code_hits

    if total == 0:
        return 15, TechFocus.OTHER

    # Primary focus
    m = max(ee_hits, ai_hits, code_hits)
    multi = sum(x == m for x in (ee_hits, ai_hits, code_hits))
    if multi > 1 or (ee_hits > 0 and (ai_hits > 0 or code_hits > 0)):
        focus = TechFocus.HYBRID
    elif ai_hits == m:
        focus = TechFocus.AI_ML
    elif code_hits == m:
        focus = TechFocus.CODING
    else:
        focus = TechFocus.HARDWARE_EE

    score = min(100, 35 + total * 7)

    # Bonuses
    if any(w in text for w in ["university", "undergraduate", "postgraduate", "student team"]):
        score = min(100, score + 8)
    if any(w in text for w in ["malaysia", "regional", "asean"]):
        score = min(100, score + 5)

    return score, focus


# ── Extraction schema & prompt ────────────────────────────────────────────────

_EVENT_SCHEMA = {
    "type": "object",
    "properties": {
        "events": {
            "type": "array",
            "description": "All upcoming events found on the page",
            "items": {
                "type": "object",
                "properties": {
                    "title":       {"type": "string",  "description": "Full event name"},
                    "start_date":  {"type": "string",  "description": "YYYY-MM-DD, null if unknown"},
                    "end_date":    {"type": "string",  "description": "YYYY-MM-DD, null if unknown"},
                    "deadline":    {"type": "string",  "description": "Registration deadline YYYY-MM-DD"},
                    "location":    {"type": "string",  "description": "City / country / Online"},
                    "organizer":   {"type": "string",  "description": "Hosting organisation"},
                    "event_url":   {"type": "string",  "description": "Direct event or registration URL"},
                    "description": {"type": "string",  "description": "1–2 sentence summary"},
                    "eligibility": {"type": "string",  "description": "Who can participate"},
                    "prize":       {"type": "string",  "description": "Prize / reward if mentioned"},
                    "team_size":   {"type": "string",  "description": "Allowed team size if mentioned"},
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Topic tags e.g. AI, robotics, hackathon, EE, cybersecurity",
                    },
                },
                "required": ["title"],
            },
        }
    },
    "required": ["events"],
}

_BASE_PROMPT = (
    "You are scanning a webpage for tech events relevant to university students in "
    "Electrical Engineering (EE), AI/ML, and Computer Science.\n\n"
    "Extract ALL upcoming events matching: competitions, hackathons, workshops/bootcamps, "
    "conferences, seminars, company visits, career fairs, coding challenges, robotics "
    "contests, embedded systems events, AI/ML challenges, data science competitions.\n\n"
    "EXCLUDE: past events (today is {today}), news articles, job postings (not fairs), "
    "events only for secondary/high school students, non-technical events.\n\n"
    "Return dates as YYYY-MM-DD. Null for unknown fields."
)

_CLAUDE_SYSTEM = (
    "You extract structured event data from scraped webpage text. "
    "Return only valid JSON matching the provided schema. "
    "Focus on tech events for university students (EE, AI, CS). "
    "Today is {today}. Exclude past events and secondary-school-only events."
)


# ── Low-level Firecrawl API wrapper ───────────────────────────────────────────

class RateLimitError(Exception):
    pass


class FirecrawlClient:
    """
    Thin wrapper around Firecrawl REST API.
    Handles auth, retries, and rate-limit back-off.
    """

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or FIRECRAWL_API_KEY
        if not self.api_key:
            raise ValueError(
                "FIRECRAWL_API_KEY not set. "
                "Get a free key at https://firecrawl.dev"
            )
        self._http = httpx.Client(
            base_url=FIRECRAWL_BASE,
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=60,
        )

    def close(self):
        self._http.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=4, max=30),
        retry=retry_if_exception_type(RateLimitError),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    def scrape_and_extract(self, url: str, prompt: str) -> dict:
        """
        Scrape url with Firecrawl's built-in LLM extract.
        Returns the raw 'extract' dict from the response.
        Uses ~5–10 Firecrawl credits.
        """
        payload = {
            "url": url,
            "formats": ["extract"],
            "extract": {
                "prompt": prompt,
                "schema": _EVENT_SCHEMA,
            },
            "timeout": 30_000,
            "waitFor": 1_000,
        }
        resp = self._http.post("/scrape", json=payload)

        if resp.status_code == 402:
            raise ValueError("[Firecrawl] Out of credits — upgrade at firecrawl.dev")
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("retry-after", 15))
            logger.warning(f"[Firecrawl] Rate limited — waiting {retry_after}s")
            time.sleep(retry_after)
            raise RateLimitError("rate limited")

        resp.raise_for_status()
        return resp.json().get("data", {}).get("extract", {})

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=4, max=30),
        retry=retry_if_exception_type(RateLimitError),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    def scrape_markdown(self, url: str) -> str:
        """
        Scrape url and return clean markdown.
        Uses ~1–2 Firecrawl credits. Used for Claude-based extraction.
        """
        resp = self._http.post(
            "/scrape",
            json={
                "url": url,
                "formats": ["markdown"],
                "timeout": 30_000,
                "waitFor": 1_000,
                "excludeTags": ["nav", "footer", "header", "script", "style", "aside"],
            },
        )

        if resp.status_code == 429:
            raise RateLimitError("rate limited")

        resp.raise_for_status()
        data = resp.json().get("data", {})
        og_img = data.get("metadata", {}).get("ogImage", "")
        md = data.get("markdown", "")
        # Attach og:image as a metadata comment for the scraper to pick up
        if og_img:
            md = f"<!-- ogimage: {og_img} -->\n" + md
        return md

    def map_links(self, url: str, limit: int = 30) -> list[str]:
        """Return all URLs found on a site (uses /map endpoint). ~1 credit."""
        try:
            resp = self._http.post("/map", json={"url": url, "limit": limit})
            resp.raise_for_status()
            return resp.json().get("links", [])
        except Exception as e:
            logger.warning(f"[Firecrawl] map failed for {url}: {e}")
            return []


# ── Claude-based extraction (optional, higher quality) ───────────────────────

def _extract_via_claude(markdown: str, source_name: str) -> list[RawEvent]:
    """Use Anthropic Claude to extract events from Firecrawl markdown."""
    if not ANTHROPIC_API_KEY:
        return []
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        today = date.today().isoformat()

        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",  # fast + cheap
            max_tokens=2048,
            system=_CLAUDE_SYSTEM.format(today=today),
            messages=[{
                "role": "user",
                "content": (
                    f"Source: {source_name}\n\n"
                    f"Extract events from this page content. "
                    f"Return JSON: {{\"events\": [...]}}\n\n"
                    f"Schema for each event:\n"
                    f"title, start_date(YYYY-MM-DD), end_date, deadline, "
                    f"location, organizer, event_url, description, eligibility, "
                    f"prize, team_size, tags(array)\n\n"
                    f"Page content (markdown):\n{markdown[:4000]}"
                ),
            }],
        )

        text = msg.content[0].text.strip()
        # Strip markdown fences if present
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

        parsed = json.loads(text)
        raw_list = parsed.get("events", parsed) if isinstance(parsed, dict) else parsed
        if not isinstance(raw_list, list):
            return []

        return [
            RawEvent(**{k: v for k, v in ev.items() if k in RawEvent.model_fields})
            for ev in raw_list
            if isinstance(ev, dict) and ev.get("title")
        ]
    except Exception as e:
        logger.warning(f"[Claude] Extraction failed for {source_name}: {e}")
        return []


# ── Helpers ───────────────────────────────────────────────────────────────────

_CODE_RE = re.compile(
    r"[{}\[\]]|=>|\bfunction\b|\bimport\b|\bconst\b|\bvar\b|\bdef\b|\bclass\b"
    r"|npm |pip |\.js\b|\.py\b|<\/|/>|<!--",
    re.IGNORECASE,
)


def _looks_like_code(text: str) -> bool:
    text = text.strip()
    if not text or len(text) < 6 or len(text) > 250:
        return True
    if _CODE_RE.search(text):
        return True
    if re.search(r"[^a-zA-Z0-9\s\-–,.()/\'\":!?]{2,}", text):
        return True
    return False


def _parse_date(s: str | None) -> date | None:
    if not s or s in ("null", "None", "none", ""):
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%B %d, %Y", "%d %B %Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(s.strip(), fmt).date()
        except ValueError:
            continue
    # Try partial year extraction
    m = re.search(r"(\d{4}-\d{2}-\d{2})", s)
    if m:
        try:
            return date.fromisoformat(m.group(1))
        except ValueError:
            pass
    return None


def _to_datetime(d: date | None) -> datetime | None:
    return datetime.combine(d, datetime.min.time()) if d else None


def _infer_country(text: str) -> str:
    t = text.lower()
    if any(k in t for k in ["malaysia", "kuala lumpur", " kl ", "penang", "johor", "cyberjaya", "selangor", "putrajaya"]):
        return "Malaysia"
    if "singapore" in t:
        return "Singapore"
    if "indonesia" in t:
        return "Indonesia"
    if "thailand" in t:
        return "Thailand"
    if "regional" in t or "asean" in t or "southeast asia" in t:
        return "Regional"
    return "International"


def _classify_category(title: str, description: str, tags: list[str]) -> EventCategory:
    text = (title + " " + description + " " + " ".join(tags)).lower()
    if any(k in text for k in ["hackathon", " hack "]):
        return EventCategory.HACKATHON
    if any(k in text for k in ["career fair", "job fair", "internship fair", "recruitment drive"]):
        return EventCategory.CAREER_FAIR
    if any(k in text for k in ["competition", "contest", "challenge", "championship", "olympiad"]):
        return EventCategory.COMPETITION
    if any(k in text for k in ["workshop", "bootcamp", "training session", "hands-on lab"]):
        return EventCategory.WORKSHOP
    if any(k in text for k in ["conference", "summit", "symposium", "congress", "expo"]):
        return EventCategory.CONFERENCE
    if any(k in text for k in ["company visit", "site visit", "plant visit", "office visit", "industry trip"]):
        return EventCategory.COMPANY_VISIT
    if any(k in text for k in ["seminar", "talk", "webinar", "lecture", "forum", "panel", "colloquium"]):
        return EventCategory.SEMINAR
    return EventCategory.OTHER


def _og_image_from_markdown(md: str) -> str:
    m = re.search(r"<!-- ogimage: (.+?) -->", md)
    return m.group(1).strip() if m else ""


# ── Main scraper class ────────────────────────────────────────────────────────

class FirecrawlScraper:
    """
    Drop-in replacement for WebScraper.
    Uses Firecrawl for JS rendering + either Claude or Firecrawl's LLM for extraction.

    Interface matches WebScraper:
        scraper = FirecrawlScraper(source_config, keywords)
        events  = scraper.scrape()

    Automatically prefers Claude extraction (higher quality) when
    ANTHROPIC_API_KEY is set; falls back to Firecrawl's built-in LLM.
    """

    def __init__(self, source: dict, keywords: list[str]):
        self.source = source
        self.keywords = keywords
        self._client = FirecrawlClient()

    def scrape(self) -> list[Event]:
        url  = self.source["url"]
        name = self.source["name"]

        raw_events = self._extract_events(url, name)
        if not raw_events:
            logger.info(f"[Firecrawl] No events found at {name}")
            return []

        events = []
        for raw in raw_events:
            if _looks_like_code(raw.title):
                continue

            start = _parse_date(raw.start_date)
            end   = _parse_date(raw.end_date)
            dead  = _parse_date(raw.deadline)

            # Skip already-ended events
            if start and start < date.today():
                continue

            tags  = [t for t in (raw.tags or []) if isinstance(t, str)]
            desc  = (raw.description or "").strip()
            cat   = _classify_category(raw.title, desc, tags)

            relevance, _ = score_relevance(raw.title, desc, tags)
            if relevance < 15:
                continue

            country = _infer_country(
                (raw.location or "") + " " + self.source.get("country", "")
            )

            events.append(Event(
                title     = raw.title[:200],
                source_name = name,
                source_url  = url,
                event_url   = (raw.event_url or url)[:500],
                category    = cat.value,
                country     = country,
                description = desc[:500],
                start_date  = _to_datetime(start),
                end_date    = _to_datetime(end),
                deadline    = _to_datetime(dead),
                location    = (raw.location or "")[:200],
                organizer   = (raw.organizer or name)[:200],
                tags        = tags,
            ))

        logger.info(f"[Firecrawl] {name}: {len(events)} events extracted")
        self._client.close()
        return events

    def _extract_events(self, url: str, name: str) -> list[RawEvent]:
        today = date.today().isoformat()

        # Strategy 1: Firecrawl scrape → Claude extraction (best quality)
        if ANTHROPIC_API_KEY:
            try:
                md = self._client.scrape_markdown(url)
                if md:
                    results = _extract_via_claude(md, name)
                    if results:
                        return results
            except Exception as e:
                logger.warning(f"[Firecrawl+Claude] {name}: {e}")

        # Strategy 2: Firecrawl built-in LLM extraction
        try:
            prompt = _BASE_PROMPT.format(today=today)
            extracted = self._client.scrape_and_extract(url, prompt)
            raw_list = extracted.get("events", [])
            return [
                RawEvent(**{k: v for k, v in ev.items() if k in RawEvent.model_fields})
                for ev in raw_list
                if isinstance(ev, dict) and ev.get("title")
            ]
        except Exception as e:
            logger.error(f"[Firecrawl] Extraction failed for {name}: {e}")
            return []

    @staticmethod
    def is_available() -> bool:
        """True when FIRECRAWL_API_KEY is configured."""
        return bool(FIRECRAWL_API_KEY)


# ── Aggregator scraper (Devpost, MLH, HackerEarth, Unstop, Kaggle) ────────────

class FirecrawlAggregatorScraper:
    """
    Scrapes structured event listings from well-known aggregator sites.
    Each aggregator has a curated list of known event-listing URLs.
    """

    # Curated event-listing URLs for major aggregators.
    # Add new entries here to extend coverage — no other code changes needed.
    AGGREGATOR_URLS: dict[str, list[str]] = {
        "Devpost": [
            "https://devpost.com/hackathons?open-to=public&order_by=recently-added",
        ],
        "MLH": [
            "https://mlh.io/seasons/2026/events",
        ],
        "HackerEarth": [
            "https://www.hackerearth.com/challenges/",
        ],
        "Unstop": [
            "https://unstop.com/hackathons",
            "https://unstop.com/competitions",
        ],
        "Kaggle": [
            "https://www.kaggle.com/competitions?listOption=active",
        ],
        "Hugging Face Events": [
            "https://huggingface.co/events",
        ],
    }

    def __init__(self, keywords: list[str]):
        self.keywords = keywords
        self._client  = FirecrawlClient()

    def scrape_all(self) -> list[Event]:
        events: list[Event] = []
        for agg_name, urls in self.AGGREGATOR_URLS.items():
            for url in urls:
                source = {"name": agg_name, "url": url, "country": "International"}
                scraper = FirecrawlScraper(source, self.keywords)
                scraper._client = self._client  # reuse connection
                events.extend(scraper.scrape())
                time.sleep(1.5)   # polite delay between aggregators
        self._client.close()
        return events

    def scrape_one(self, name: str) -> list[Event]:
        """Scrape a single named aggregator."""
        urls = self.AGGREGATOR_URLS.get(name, [])
        events: list[Event] = []
        for url in urls:
            source = {"name": name, "url": url, "country": "International"}
            events.extend(FirecrawlScraper(source, self.keywords).scrape())
        return events


# ── Instagram via Apify (optional) ───────────────────────────────────────────

class ApifyInstagramScraper:
    """
    Scrapes Instagram hashtags/accounts for event announcements using Apify.
    Requires APIFY_TOKEN in secrets/env.

    Relevant hashtags: #AIHackathon #MalaysiaCodingCompetition
                       #RoboticsAI #EEHackathon #TechEventMY
    """

    APIFY_ACTOR = "apify/instagram-hashtag-scraper"
    HASHTAGS    = [
        "AIHackathon", "MalaysiaCodingCompetition", "RoboticsAI",
        "EEHackathon", "TechEventMY", "HackathonMalaysia",
        "EmbeddedSystems", "MLChallenge", "DataScienceMalaysia",
    ]

    def __init__(self, keywords: list[str]):
        self.keywords  = keywords
        self.api_token = _get_secret("APIFY_TOKEN")

    def scrape(self) -> list[Event]:
        if not self.api_token:
            logger.info("[Apify] APIFY_TOKEN not set — skipping Instagram")
            return []
        try:
            return self._run_actor()
        except Exception as e:
            logger.error(f"[Apify] Instagram scrape failed: {e}")
            return []

    def _run_actor(self) -> list[Event]:
        with httpx.Client(timeout=120) as client:
            # Start actor run
            resp = client.post(
                f"https://api.apify.com/v2/acts/{self.APIFY_ACTOR}/runs",
                headers={"Authorization": f"Bearer {self.api_token}"},
                json={
                    "hashtags": self.HASHTAGS,
                    "resultsLimit": 20,
                    "proxy": {"useApifyProxy": True},
                },
            )
            resp.raise_for_status()
            run_id = resp.json()["data"]["id"]

            # Poll for completion (up to 3 min)
            for _ in range(18):
                time.sleep(10)
                status_resp = client.get(
                    f"https://api.apify.com/v2/actor-runs/{run_id}",
                    headers={"Authorization": f"Bearer {self.api_token}"},
                )
                status = status_resp.json()["data"]["status"]
                if status in ("SUCCEEDED", "FAILED", "ABORTED"):
                    break

            if status != "SUCCEEDED":
                return []

            # Fetch dataset
            dataset_id = status_resp.json()["data"]["defaultDatasetId"]
            items_resp  = client.get(
                f"https://api.apify.com/v2/datasets/{dataset_id}/items",
                headers={"Authorization": f"Bearer {self.api_token}"},
            )
            posts = items_resp.json()

        events = []
        today  = date.today().isoformat()
        for post in posts:
            caption = post.get("caption", "")
            if not any(kw.lower() in caption.lower() for kw in self.keywords):
                continue
            # Quick Claude extraction on caption
            raw = _extract_via_claude(caption[:1500], "Instagram")
            for ev in raw:
                start = _parse_date(ev.start_date)
                if start and start < date.today():
                    continue
                events.append(Event(
                    title       = ev.title[:200],
                    source_name = "Instagram",
                    source_url  = post.get("url", ""),
                    event_url   = post.get("url", ""),
                    category    = _classify_category(ev.title, ev.description or "", ev.tags).value,
                    country     = _infer_country(ev.location or ""),
                    description = (ev.description or "")[:500],
                    start_date  = _to_datetime(start),
                    deadline    = _to_datetime(_parse_date(ev.deadline)),
                    location    = ev.location or "",
                    organizer   = ev.organizer or "",
                    image_url   = post.get("imageUrl", ""),
                    tags        = ev.tags,
                ))
        return events


# ── Convenience function ──────────────────────────────────────────────────────

def scrape_url(url: str, source_name: str = "Manual", keywords: list[str] | None = None) -> list[Event]:
    """
    Convenience function: scrape any URL and return events.

    >>> events = scrape_url("https://devpost.com/hackathons", "Devpost")
    """
    source = {"name": source_name, "url": url, "country": "International"}
    return FirecrawlScraper(source, keywords or []).scrape()
