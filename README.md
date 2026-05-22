# EE & CS Event Tracker

Automated system that discovers competitions, career fairs, conferences, workshops, hackathons, company visits, and other tech events — primarily in Malaysia but globally too.

## Quick Start

```bat
:: 1. Run setup (first time only)
setup.bat

:: 2. Activate the virtual environment
venv\Scripts\activate

:: 3. Scrape now
python runner.py

:: 4. Open the dashboard
streamlit run dashboard/app.py

:: 5. (Optional) Start daily auto-scheduler
python scheduler.py
```

## What it scrapes

| Source type | Examples |
|-------------|----------|
| University event pages | UTM, UM, UTP, MMU, UPM, Sunway, Monash MY … |
| Professional bodies | IEEE Malaysia, IEM, MDEC, CyberSecurity Malaysia |
| Company event pages | Intel, Grab, Petronas, TM, Google, Microsoft, AWS |
| Event aggregators | Eventbrite, MLH, Devfolio, Hackathon.io |
| Instagram (public) | @ieee_malaysia, @mdec_malaysia, university accounts … |
| Search discovery | DuckDuckGo searches for new events not in the fixed list |

## Adding sources

**Option A — Dashboard UI**: Click "➕ Add a new source" or "📸 Add Instagram account" in the sidebar.

**Option B — Edit `config.yaml` directly**:

```yaml
universities:
  - name: "My New University"
    url: "https://example.edu.my/events"
    country: Malaysia

instagram_accounts:
  - new_account_handle

search_queries:
  - "new search query 2025"
```

Changes take effect on the next scraper run.

## Scheduler

`scheduler.py` uses APScheduler to run the scraper every day at 08:00 KL time (configurable in `config.yaml`).

To run it on Windows startup automatically, add a Task Scheduler entry pointing to:
```
venv\Scripts\python.exe scheduler.py
```

## Data

All events are stored in `data/events.db` (SQLite). You can open it with DB Browser for SQLite or export to CSV from the dashboard.

## Limitations

- **Instagram**: uses `instaloader` to scrape public profiles — may be rate-limited if too many accounts are added. Stays polite with 5-second delays between accounts.
- **JavaScript-heavy sites**: uses `playwright` (Chromium headless) as fallback — first run requires `playwright install chromium`.
- **Date parsing**: best-effort from unstructured text — always verify event details on the official page.
