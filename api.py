"""
TechTrack FastAPI Server
========================
Provides a JSON API + web UI for triggering scrapes and querying events.

Run locally:
    uvicorn api:app --reload --port 8000

Endpoints:
    POST /api/scrape          — trigger a full scrape run (background)
    POST /api/scrape/url      — scrape a single URL
    GET  /api/events          — list events (filters: category, country, search, limit)
    GET  /api/stats           — DB statistics
    GET  /api/sources         — list configured sources
    GET  /api/scrape/status   — status of the last background scrape
    GET  /health              — health check
    GET  /                    — simple HTML dashboard (no Streamlit dependency)
"""
from __future__ import annotations

import sys
import asyncio
from pathlib import Path
from datetime import datetime
from typing import Optional

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, BackgroundTasks, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
import yaml

from src.db import init_db, get_all_events, get_stats, get_run_logs, upsert_event, log_run
from src.scrapers.firecrawl_scraper import FirecrawlScraper, scrape_url, FirecrawlAggregatorScraper

# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="TechTrack Event API",
    description="EE & CS event aggregator for Malaysian university students",
    version="2.0.0",
)

# In-memory scrape job tracker
_scrape_status: dict = {"running": False, "last_run": None, "last_result": None}


# ── Request / response models ─────────────────────────────────────────────────

class ScrapeURLRequest(BaseModel):
    url: str
    source_name: str = "Manual"


class ScrapeResponse(BaseModel):
    status: str
    message: str
    events_added: Optional[int] = None


# ── Background scrape task ────────────────────────────────────────────────────

def _run_scrape_job():
    _scrape_status["running"] = True
    _scrape_status["last_run"] = datetime.now().isoformat()
    try:
        with open(ROOT / "config.yaml") as f:
            cfg = yaml.safe_load(f)
        keywords = cfg.get("keywords", [])

        init_db()
        added_total = 0

        all_sources = (
            cfg.get("universities", []) +
            cfg.get("organizations", []) +
            cfg.get("companies", [])
        )

        if FirecrawlScraper.is_available():
            from concurrent.futures import ThreadPoolExecutor, as_completed
            import threading
            results = []
            with ThreadPoolExecutor(max_workers=5) as pool:
                futures = {
                    pool.submit(
                        lambda s: (s["name"], FirecrawlScraper(s, keywords).scrape()),
                        src
                    ): src
                    for src in all_sources
                }
                for future in as_completed(futures):
                    name, events = future.result()
                    added = sum(1 for e in events if upsert_event(e))
                    log_run(name, len(events), added)
                    added_total += added
        else:
            # Fall back to existing runner
            import runner
            result = runner.run_all(verbose=False)
            added_total = sum(result.values())

        _scrape_status["last_result"] = {
            "added": added_total,
            "finished_at": datetime.now().isoformat(),
        }
    except Exception as e:
        _scrape_status["last_result"] = {"error": str(e)}
    finally:
        _scrape_status["running"] = False


# ── Startup ───────────────────────────────────────────────────────────────────

@app.on_event("startup")
def on_startup():
    init_db()


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "firecrawl": FirecrawlScraper.is_available()}


@app.post("/api/scrape", response_model=ScrapeResponse)
def trigger_scrape(background_tasks: BackgroundTasks):
    """Start a full scrape run in the background."""
    if _scrape_status["running"]:
        return ScrapeResponse(status="running", message="A scrape is already in progress.")
    background_tasks.add_task(_run_scrape_job)
    return ScrapeResponse(status="started", message="Scrape job started in background.")


@app.get("/api/scrape/status")
def scrape_status():
    return _scrape_status


@app.post("/api/scrape/url", response_model=ScrapeResponse)
def scrape_single_url(req: ScrapeURLRequest):
    """Scrape a single URL immediately and store new events."""
    if not FirecrawlScraper.is_available():
        raise HTTPException(503, "FIRECRAWL_API_KEY not configured")
    try:
        with open(ROOT / "config.yaml") as f:
            cfg = yaml.safe_load(f)
        events = scrape_url(req.url, req.source_name, cfg.get("keywords", []))
        added  = sum(1 for e in events if upsert_event(e))
        log_run(req.source_name, len(events), added)
        return ScrapeResponse(
            status="ok",
            message=f"Found {len(events)} events, added {added} new.",
            events_added=added,
        )
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/api/events")
def list_events(
    category:        Optional[str]  = Query(None),
    country:         Optional[str]  = Query(None),
    search:          Optional[str]  = Query(None),
    upcoming_only:   bool           = Query(True),
    bookmarked_only: bool           = Query(False),
    limit:           int            = Query(100, le=500),
):
    """Return events with optional filters."""
    events = get_all_events(
        upcoming_only   = upcoming_only,
        category        = category,
        country         = country,
        search          = search,
        bookmarked_only = bookmarked_only,
    )
    return {"count": len(events[:limit]), "events": events[:limit]}


@app.get("/api/stats")
def stats():
    return get_stats()


@app.get("/api/sources")
def list_sources():
    with open(ROOT / "config.yaml") as f:
        cfg = yaml.safe_load(f)
    return {
        "universities":  cfg.get("universities", []),
        "organizations": cfg.get("organizations", []),
        "companies":     cfg.get("companies", []),
        "aggregators":   cfg.get("aggregators", []),
    }


@app.get("/api/logs")
def run_logs(limit: int = Query(50, le=200)):
    return get_run_logs(limit=limit)


# ── Simple HTML dashboard (no Streamlit) ─────────────────────────────────────

_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>TechTrack API</title>
<style>
  body{font-family:Inter,sans-serif;background:#f7fafd;color:#181c1e;margin:0;padding:2rem}
  h1{font-weight:900;font-style:italic;color:#4a3ee6;margin:0 0 .5rem}
  p{color:#64748b;margin:0 0 2rem}
  .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:1rem;margin-bottom:2rem}
  .card{background:#fff;border:1px solid rgba(74,62,230,.15);padding:1.25rem;
        clip-path:polygon(0 0,100% 0,100% calc(100% - 12px),calc(100% - 12px) 100%,0 100%)}
  .card h3{margin:0 0 .5rem;font-size:.8rem;text-transform:uppercase;letter-spacing:.1em;color:#94a3b8}
  .card .val{font-size:2rem;font-weight:900;font-style:italic;color:#000f22}
  .endpoints{background:#fff;border:1px solid rgba(74,62,230,.15);padding:1.5rem}
  .endpoints h2{margin:0 0 1rem;font-size:.8rem;text-transform:uppercase;letter-spacing:.1em;color:#4a3ee6}
  .ep{display:flex;gap:.75rem;align-items:baseline;padding:.4rem 0;border-bottom:1px solid #f1f5f9}
  .method{font-size:.68rem;font-weight:800;letter-spacing:.08em;padding:2px 8px;border-radius:2px}
  .get{background:#dbeafe;color:#1e3a8a}.post{background:#dcfce7;color:#14532d}
  .path{font-family:monospace;font-size:.85rem;color:#000f22}
  .desc{font-size:.8rem;color:#64748b;margin-left:auto}
  .btn{display:inline-block;margin-top:1.5rem;padding:.6rem 1.5rem;background:#4a3ee6;color:#fff;
       border:none;cursor:pointer;font-weight:800;letter-spacing:.08em;text-transform:uppercase;
       font-size:.75rem;clip-path:polygon(0 0,100% 0,100% calc(100% - 8px),calc(100% - 8px) 100%,0 100%)}
  #out{margin-top:1rem;background:#f8fafc;border:1px solid #e2e8f0;padding:1rem;
       font-family:monospace;font-size:.8rem;white-space:pre-wrap;max-height:400px;overflow:auto;display:none}
</style>
</head>
<body>
<h1>TECHTRACK</h1>
<p>EE &amp; CS Event API &nbsp;//&nbsp; Malaysian University Students</p>

<div class="grid" id="stats">
  <div class="card"><h3>Total Events</h3><div class="val" id="total">—</div></div>
  <div class="card"><h3>Upcoming</h3><div class="val" id="upcoming">—</div></div>
  <div class="card"><h3>Bookmarked</h3><div class="val" id="bookmarked">—</div></div>
  <div class="card"><h3>Firecrawl</h3><div class="val" id="fc">—</div></div>
</div>

<div class="endpoints">
  <h2>Endpoints</h2>
  <div class="ep"><span class="method get">GET</span><span class="path">/api/events</span><span class="desc">List all events</span></div>
  <div class="ep"><span class="method get">GET</span><span class="path">/api/stats</span><span class="desc">Database statistics</span></div>
  <div class="ep"><span class="method get">GET</span><span class="path">/api/sources</span><span class="desc">Configured sources</span></div>
  <div class="ep"><span class="method get">GET</span><span class="path">/api/logs</span><span class="desc">Scrape run logs</span></div>
  <div class="ep"><span class="method post">POST</span><span class="path">/api/scrape</span><span class="desc">Trigger full scrape</span></div>
  <div class="ep"><span class="method post">POST</span><span class="path">/api/scrape/url</span><span class="desc">Scrape single URL</span></div>
  <div class="ep"><span class="method get">GET</span><span class="path">/docs</span><span class="desc">Interactive Swagger UI</span></div>
</div>

<button class="btn" onclick="triggerScrape()">Trigger Scrape</button>
<div id="out"></div>

<script>
async function load(){
  const r=await fetch('/api/stats'); const s=await r.json();
  document.getElementById('total').textContent=s.total||'0';
  document.getElementById('upcoming').textContent=s.upcoming||'0';
  document.getElementById('bookmarked').textContent=s.bookmarked||'0';
  const h=await fetch('/health'); const hj=await h.json();
  document.getElementById('fc').textContent=hj.firecrawl?'Active':'No Key';
}
async function triggerScrape(){
  const out=document.getElementById('out');
  out.style.display='block'; out.textContent='Starting scrape…';
  const r=await fetch('/api/scrape',{method:'POST'});
  const j=await r.json(); out.textContent=JSON.stringify(j,null,2);
  // poll status
  for(let i=0;i<30;i++){
    await new Promise(r=>setTimeout(r,3000));
    const s=await(await fetch('/api/scrape/status')).json();
    out.textContent=JSON.stringify(s,null,2);
    if(!s.running) break;
  }
}
load();
</script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
def dashboard():
    return _HTML


# ── APScheduler for daily automated runs ─────────────────────────────────────
# Uncomment to enable the in-process daily scheduler.
# Alternatively use GitHub Actions (already configured in .github/workflows/scrape.yml).

# from apscheduler.schedulers.background import BackgroundScheduler
# import yaml as _yaml
#
# def _start_scheduler():
#     with open(ROOT / "config.yaml") as f:
#         sched_cfg = _yaml.safe_load(f).get("scheduler", {})
#     run_time = sched_cfg.get("run_time", "08:00")
#     tz       = sched_cfg.get("timezone", "Asia/Kuala_Lumpur")
#     hour, minute = map(int, run_time.split(":"))
#
#     scheduler = BackgroundScheduler(timezone=tz)
#     scheduler.add_job(_run_scrape_job, "cron", hour=hour, minute=minute,
#                       id="daily_scrape", replace_existing=True)
#     scheduler.start()
#     print(f"[Scheduler] Daily scrape scheduled at {run_time} {tz}")
#
# _start_scheduler()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=True)
