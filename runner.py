"""
Main scraping runner. Loads config, runs all scrapers, stores results.
Run directly: python runner.py
"""
import sys
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

import yaml
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from src.db import init_db, upsert_event, log_run, get_stats
from src.scrapers.web_scraper import WebScraper
from src.scrapers.search_scraper import SearchScraper
from src.scrapers.instagram_scraper import InstagramScraper
from src.scrapers.eventbrite_scraper import EventbriteScraper
from src.notifier import send_digest

console = Console()

_MAX_WORKERS = 5  # parallel source scrapers


def load_config() -> dict:
    with open(ROOT / "config.yaml") as f:
        return yaml.safe_load(f)


def _upsert_collect(events: list, new_events: list) -> int:
    added = 0
    for e in events:
        if upsert_event(e):
            added += 1
            new_events.append(e.to_dict())
    return added


def _scrape_one(source: dict, keywords: list) -> tuple[str, list, str | None]:
    """Scrape a single source — prefers Firecrawl when API key is configured."""
    try:
        try:
            from src.scrapers.firecrawl_scraper import FirecrawlScraper
            if FirecrawlScraper.is_available():
                return source["name"], FirecrawlScraper(source, keywords).scrape(), None
        except ImportError:
            pass
        scraper = WebScraper(source, keywords)
        return source["name"], scraper.scrape(), None
    except Exception as ex:
        return source["name"], [], str(ex)


def _scrape_group(sources: list[dict], keywords: list, label: str, new_events: list) -> tuple[int, int]:
    """Scrape a group of sources in parallel. Returns (found, added)."""
    found = added = 0
    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
        futures = {pool.submit(_scrape_one, src, keywords): src for src in sources}
        for future in as_completed(futures):
            name, events, error = future.result()
            if error:
                log_run(name, 0, 0, error)
                console.print(f"  [red]FAILED[/] {name}: {error}")
            else:
                added_here = _upsert_collect(events, new_events)
                added += added_here
                found += len(events)
                log_run(name, len(events), added_here)
    console.print(f"  [green]{label}[/]: found {found}, added {added} new")
    return found, added


def run_all(verbose: bool = True) -> dict[str, int]:
    console.rule("[bold blue]Event Tracker — Scrape Run")
    console.print(f"  Started at {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")

    init_db()
    cfg = load_config()
    keywords = cfg["keywords"]
    totals: dict[str, int] = {}
    new_events: list[dict] = []

    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), transient=True) as prog:

        # ── Universities (parallel) ───────────────────────────────
        task = prog.add_task("Scraping university sites…", total=None)
        _, uni_added = _scrape_group(
            cfg.get("universities", []), keywords, "Universities", new_events
        )
        totals["Universities"] = uni_added
        prog.remove_task(task)

        # ── Organisations (parallel) ──────────────────────────────
        task = prog.add_task("Scraping organisations…", total=None)
        _, org_added = _scrape_group(
            cfg.get("organizations", []), keywords, "Organisations", new_events
        )
        totals["Organisations"] = org_added
        prog.remove_task(task)

        # ── Companies (parallel) ──────────────────────────────────
        task = prog.add_task("Scraping company sites…", total=None)
        _, co_added = _scrape_group(
            cfg.get("companies", []), keywords, "Companies", new_events
        )
        totals["Companies"] = co_added
        prog.remove_task(task)

        # ── Eventbrite / aggregators ──────────────────────────────
        task = prog.add_task("Scraping aggregators…", total=None)
        try:
            scraper = EventbriteScraper(cfg.get("aggregators", []), keywords)
            events = scraper.scrape()
            agg_added = _upsert_collect(events, new_events)
            log_run("Aggregators", len(events), agg_added)
            totals["Aggregators"] = agg_added
            console.print(f"  [green]Aggregators[/]: found {len(events)}, added {agg_added} new")
        except Exception as ex:
            log_run("Aggregators", 0, 0, str(ex))
            console.print(f"  [red]FAILED Aggregators[/]: {ex}")
        prog.remove_task(task)

        # ── DuckDuckGo search ─────────────────────────────────────
        task = prog.add_task("Running search discovery…", total=None)
        try:
            scraper = SearchScraper(cfg.get("search_queries", []), keywords)
            events = scraper.scrape()
            search_added = _upsert_collect(events, new_events)
            log_run("Search", len(events), search_added)
            totals["Search"] = search_added
            console.print(f"  [green]Search discovery[/]: found {len(events)}, added {search_added} new")
        except Exception as ex:
            log_run("Search", 0, 0, str(ex))
            console.print(f"  [red]FAILED Search[/]: {ex}")
        prog.remove_task(task)

        # ── Instagram ─────────────────────────────────────────────
        accounts = cfg.get("instagram_accounts", [])
        if accounts:
            task = prog.add_task("Scraping Instagram…", total=None)
            try:
                scraper = InstagramScraper(accounts, keywords)
                events = scraper.scrape()
                ig_added = _upsert_collect(events, new_events)
                log_run("Instagram", len(events), ig_added)
                totals["Instagram"] = ig_added
                console.print(f"  [green]Instagram[/]: found {len(events)}, added {ig_added} new")
            except Exception as ex:
                log_run("Instagram", 0, 0, str(ex))
                console.print(f"  [yellow]Instagram skipped[/]: {ex}")
            prog.remove_task(task)

    # ── Summary ────────────────────────────────────────────────────
    console.print()
    console.rule("[bold]Summary")
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Source", style="dim")
    table.add_column("New events added", justify="right")
    for src, count in totals.items():
        table.add_row(src, str(count))
    console.print(table)
    try:
        stats = get_stats()
        console.print(f"\n  Total in DB: [bold]{stats['total']}[/]  |  Upcoming: [bold]{stats['upcoming']}[/]")
    except Exception:
        console.print("\n  (Could not fetch DB stats)")
    console.print(f"  Launch dashboard: [cyan]streamlit run dashboard/app.py[/]\n")

    send_digest(new_events, cfg)
    return totals


if __name__ == "__main__":
    run_all()
