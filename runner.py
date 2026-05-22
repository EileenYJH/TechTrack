"""
Main scraping runner. Loads config, runs all scrapers, stores results.
Run directly: python runner.py
"""
import sys
from pathlib import Path
from datetime import datetime

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


def load_config() -> dict:
    with open(ROOT / "config.yaml") as f:
        return yaml.safe_load(f)


def _upsert_collect(events: list, new_events: list) -> int:
    """Insert new events, collect them into new_events. Returns count added."""
    added = 0
    for e in events:
        if upsert_event(e):
            added += 1
            new_events.append(e.to_dict())
    return added


def run_all(verbose: bool = True) -> dict[str, int]:
    console.rule("[bold blue]Event Tracker — Scrape Run")
    console.print(f"  Started at {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")

    init_db()
    cfg = load_config()
    keywords = cfg["keywords"]
    totals: dict[str, int] = {}
    new_events: list[dict] = []  # collected for email digest

    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), transient=True) as prog:

        # ── University sites ──────────────────────────────
        task = prog.add_task("Scraping university sites…", total=None)
        uni_found = uni_added = 0
        for uni in cfg.get("universities", []):
            prog.update(task, description=f"University: {uni['name']}")
            try:
                scraper = WebScraper(uni, keywords)
                events = scraper.scrape()
                added_here = _upsert_collect(events, new_events)
                uni_added += added_here
                uni_found += len(events)
                log_run(uni["name"], len(events), added_here)
            except Exception as ex:
                log_run(uni["name"], 0, 0, str(ex))
                if verbose:
                    console.print(f"  [red]FAILED[/] {uni['name']}: {ex}")
        totals["Universities"] = uni_added
        console.print(f"  [green]Universities[/]: found {uni_found}, added {uni_added} new")

        # ── Organisations (IEEE, IEM, etc.) ───────────────
        task = prog.add_task("Scraping organisations…", total=None)
        org_found = org_added = 0
        for org in cfg.get("organizations", []):
            prog.update(task, description=f"Org: {org['name']}")
            try:
                scraper = WebScraper(org, keywords)
                events = scraper.scrape()
                added_here = _upsert_collect(events, new_events)
                org_added += added_here
                org_found += len(events)
                log_run(org["name"], len(events), added_here)
            except Exception as ex:
                log_run(org["name"], 0, 0, str(ex))
        totals["Organisations"] = org_added
        console.print(f"  [green]Organisations[/]: found {org_found}, added {org_added} new")

        # ── Company sites ─────────────────────────────────
        task = prog.add_task("Scraping company sites…", total=None)
        co_found = co_added = 0
        for company in cfg.get("companies", []):
            prog.update(task, description=f"Company: {company['name']}")
            try:
                scraper = WebScraper(company, keywords)
                events = scraper.scrape()
                added_here = _upsert_collect(events, new_events)
                co_added += added_here
                co_found += len(events)
                log_run(company["name"], len(events), added_here)
            except Exception as ex:
                log_run(company["name"], 0, 0, str(ex))
        totals["Companies"] = co_added
        console.print(f"  [green]Companies[/]: found {co_found}, added {co_added} new")

        # ── Eventbrite / aggregators ──────────────────────
        task = prog.add_task("Scraping event aggregators…", total=None)
        try:
            prog.update(task, description="Eventbrite + MLH…")
            scraper = EventbriteScraper(cfg.get("aggregators", []), keywords)
            events = scraper.scrape()
            agg_added = _upsert_collect(events, new_events)
            log_run("Aggregators", len(events), agg_added)
            totals["Aggregators"] = agg_added
            console.print(f"  [green]Aggregators[/]: found {len(events)}, added {agg_added} new")
        except Exception as ex:
            log_run("Aggregators", 0, 0, str(ex))
            console.print(f"  [red]FAILED Aggregators[/]: {ex}")

        # ── DuckDuckGo search discovery ───────────────────
        task = prog.add_task("Running search discovery…", total=None)
        try:
            prog.update(task, description="DuckDuckGo search…")
            scraper = SearchScraper(cfg.get("search_queries", []), keywords)
            events = scraper.scrape()
            search_added = _upsert_collect(events, new_events)
            log_run("Search", len(events), search_added)
            totals["Search"] = search_added
            console.print(f"  [green]Search discovery[/]: found {len(events)}, added {search_added} new")
        except Exception as ex:
            log_run("Search", 0, 0, str(ex))
            console.print(f"  [red]FAILED Search[/]: {ex}")

        # ── Instagram ─────────────────────────────────────
        task = prog.add_task("Scraping Instagram…", total=None)
        accounts = cfg.get("instagram_accounts", [])
        if accounts:
            try:
                prog.update(task, description="Instagram public profiles…")
                scraper = InstagramScraper(accounts, keywords)
                events = scraper.scrape()
                ig_added = _upsert_collect(events, new_events)
                log_run("Instagram", len(events), ig_added)
                totals["Instagram"] = ig_added
                console.print(f"  [green]Instagram[/]: found {len(events)}, added {ig_added} new")
            except Exception as ex:
                log_run("Instagram", 0, 0, str(ex))
                console.print(f"  [yellow]Instagram skipped[/]: {ex}")

    # ── Summary ───────────────────────────────────────────
    stats = get_stats()
    console.print()
    console.rule("[bold]Summary")
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Source", style="dim")
    table.add_column("New events added", justify="right")
    for src, count in totals.items():
        table.add_row(src, str(count))
    console.print(table)
    console.print(f"\n  Total in DB: [bold]{stats['total']}[/]  |  Upcoming: [bold]{stats['upcoming']}[/]")
    console.print(f"  Launch dashboard: [cyan]streamlit run dashboard/app.py[/]\n")

    # ── Email digest ──────────────────────────────────────
    send_digest(new_events, cfg)

    return totals


if __name__ == "__main__":
    run_all()
