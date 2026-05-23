"""
scheduler.py
------------
APScheduler background jobs for the Whale Strike Navigator.

Jobs:
  1. check_for_new_ais_data  — every AIS_REFRESH_INTERVAL_MINUTES
     Checks data/raw/ais/ for new Parquet files. If any are newer than
     the last reload, triggers data reload + cache clear.

  2. build_live_risk_grid    — every AIS_REFRESH_INTERVAL_MINUTES
     Runs build_live_risk.py to compute a fresh live risk grid from
     today's aisstream.io vessel positions.
"""

import sys
from datetime import datetime
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from loguru import logger

from app.config import settings
from app.services.data_loader import load_all_data
from app.utils.cache import clear_all_caches

# ── Paths ─────────────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parents[4]
AIS_DIR   = REPO_ROOT / "data" / "raw" / "ais"

# Add scripts dir to path so we can import build_live_risk
SCRIPTS_DIR = REPO_ROOT / "scripts" / "processing"
sys.path.insert(0, str(SCRIPTS_DIR))

# ── State ─────────────────────────────────────────────────────────────────────
_scheduler:    AsyncIOScheduler | None = None
_last_reload:  datetime = datetime.min


# ── Jobs ──────────────────────────────────────────────────────────────────────

async def check_for_new_ais_data() -> None:
    """Reload all data if new AIS files have appeared."""
    global _last_reload

    parquet_files = list(AIS_DIR.glob("*.parquet"))
    if not parquet_files:
        return

    newest_mtime = max(
        datetime.fromtimestamp(f.stat().st_mtime)
        for f in parquet_files
    )

    if newest_mtime > _last_reload:
        logger.info(f"New AIS data detected — reloading...")
        load_all_data()
        clear_all_caches()
        _last_reload = datetime.now()
        logger.success("Data reload complete")
    else:
        logger.debug(f"AIS check: no new data since {_last_reload:%H:%M:%S}")


async def build_live_risk_grid() -> None:
    """Recompute live risk grid from today's aisstream positions."""
    try:
        from build_live_risk import build_live_risk
        build_live_risk()
        # Clear risk cache so next request picks up fresh live grid
        clear_all_caches()
    except Exception as e:
        logger.warning(f"Live risk build failed: {e}")


# ── Lifecycle ─────────────────────────────────────────────────────────────────

def start_scheduler() -> None:
    global _scheduler, _last_reload
    _last_reload = datetime.now()
    _scheduler   = AsyncIOScheduler()

    _scheduler.add_job(
        check_for_new_ais_data,
        trigger=IntervalTrigger(minutes=settings.ais_refresh_interval_minutes),
        id="check_ais",
        name="Check for new AIS data",
        replace_existing=True,
        max_instances=1,
    )

    _scheduler.add_job(
        build_live_risk_grid,
        trigger=IntervalTrigger(minutes=settings.ais_refresh_interval_minutes),
        id="live_risk",
        name="Build live risk grid",
        replace_existing=True,
        max_instances=1,
    )

    _scheduler.start()
    logger.success(
        f"Scheduler started — AIS check + live risk build every "
        f"{settings.ais_refresh_interval_minutes} minutes"
    )


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")