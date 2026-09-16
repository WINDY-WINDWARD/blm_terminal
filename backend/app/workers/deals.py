"""Watchlist deals worker — periodically warms deals data during market hours."""

import logging

from app.backgroundtasks._runtime import (
    _is_job_enabled,
    _report_job_waiting,
    _shutdown_event,
    _sleep_interruptible,
    _wait_for_startup_event,
)
from app.jobs.runner import update_job_status_sync
from app.services.data_sync.deals import _watchlist_deals_sync
from app.workers.lifecycle import _startup_stock_universe_done

logger = logging.getLogger(__name__)


def watchlist_deals_worker() -> None:
    """Worker loop for syncing deals and large trades for watchlist items."""
    logger.info("watchlist_deals_worker: started")

    if not _is_job_enabled("job.watchlist_deals"):
        logger.info("watchlist_deals_worker: disabled, waiting...")
        update_job_status_sync("job.watchlist_deals", "waiting", progress=0, message="Disabled")
        while not _shutdown_event.is_set():
            _sleep_interruptible(60)
        update_job_status_sync("job.watchlist_deals", "idle", progress=0, message="Stopped")
        logger.info("watchlist_deals_worker: stopped")
        return

    # Wait for stock universe before initial run
    if _wait_for_startup_event(_startup_stock_universe_done, "stock_universe", "job.watchlist_deals"):
        update_job_status_sync("job.watchlist_deals", "idle", progress=0, message="Stopped")
        logger.info("watchlist_deals_worker: stopped")
        return

    update_job_status_sync("job.watchlist_deals", "waiting", progress=0, message="Waiting for schedule")

    while not _shutdown_event.is_set():
        wait_secs = _report_job_waiting("job.watchlist_deals", "*/30 * * * *")
        if _sleep_interruptible(wait_secs):
            break
        if not _shutdown_event.is_set():
            if not _is_job_enabled("job.watchlist_deals"):
                update_job_status_sync("job.watchlist_deals", "waiting", progress=0, message="Disabled")
                _sleep_interruptible(60)
                continue
            update_job_status_sync("job.watchlist_deals", "running", progress=50, message="Fetching watchlist deals...")
            try:
                _watchlist_deals_sync()
            except Exception as e:
                logger.exception("watchlist_deals_worker failed: %s", e)
            update_job_status_sync("job.watchlist_deals", "waiting", progress=100, message="Deals refreshed")

    update_job_status_sync("job.watchlist_deals", "idle", progress=0, message="Stopped")
    logger.info("watchlist_deals_worker: stopped")
