"""
Daily scheduler. Runs the scraper automatically every day at the time
configured in config.yaml (default 08:00 KL time).

Usage:
    python scheduler.py          # run in foreground (keep terminal open)
    python scheduler.py --now    # run immediately, then schedule
"""
import sys
import argparse
from pathlib import Path
from datetime import datetime

import yaml
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from rich.console import Console

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

console = Console()


def job():
    from runner import run_all
    console.print(f"\n[dim]{datetime.now().isoformat()}[/] — Starting scheduled scrape…")
    run_all(verbose=False)


def main():
    parser = argparse.ArgumentParser(description="Event Tracker Scheduler")
    parser.add_argument("--now", action="store_true", help="Run a scrape immediately before scheduling")
    args = parser.parse_args()

    with open(ROOT / "config.yaml") as f:
        cfg = yaml.safe_load(f)

    sched_cfg = cfg.get("scheduler", {})
    run_time = sched_cfg.get("run_time", "08:00")
    timezone = sched_cfg.get("timezone", "Asia/Kuala_Lumpur")
    hour, minute = run_time.split(":")

    if args.now:
        console.print("[cyan]Running immediate scrape…[/]")
        job()

    scheduler = BlockingScheduler(timezone=timezone)
    scheduler.add_job(
        job,
        CronTrigger(hour=int(hour), minute=int(minute), timezone=timezone),
        id="daily_scrape",
        replace_existing=True,
    )

    console.print(f"\n[green]Scheduler started.[/] Daily run at [bold]{run_time}[/] ({timezone})")
    console.print("Press Ctrl+C to stop.\n")

    try:
        scheduler.start()
    except KeyboardInterrupt:
        console.print("\n[yellow]Scheduler stopped.[/]")


if __name__ == "__main__":
    main()
