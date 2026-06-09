"""Results calendar worker daemon (audit C.1, A.9 step 4, A.13).

Extracted from ``app/backgroundtasks/_impl.py``.  The actual sync
functions live in ``app/services/data_sync/calendar.py``.

``market_data`` is no longer a standalone daemon — it runs as Stage 7
of the orchestrator pipeline (both startup and nightly) and on a
``*/5 * * * *`` cron scheduler managed by ``Orchestrator._run_market_data_scheduler``.

Public workers:
- ``results_calendar_worker()`` — cron ``0 8,14 * * 1-5``.

A.13: migrated ``_bg_impl`` references to canonical imports.
"""
from __future__ import annotations

import logging


logger = logging.getLogger(__name__)


def results_calendar_worker() -> None:
    """Daemon thread: syncs upcoming results notifications twice daily (8am + 2pm IST)."""
    from app.backgroundtasks._runtime import (
        _is_first_run,
        _is_job_enabled,
        _report_job_waiting,
        _set_first_run_complete,
        _shutdown_event,
        _sleep_interruptible,
        _startup_stock_universe_done,
        _wait_for_startup_event,
    )
    from app.jobs.runner import update_job_status_sync
    from app.services.data_sync.calendar import (
        _RESULTS_CALENDAR_CRON,
        _results_calendar_sync,
    )

    logger.info("results_calendar_worker: started")

    if not _is_job_enabled("job.results_calendar"):
        logger.info("results_calendar_worker: disabled, waiting...")
        update_job_status_sync("job.results_calendar", "waiting", progress=0, message="Disabled")
        while not _shutdown_event.is_set():
            _sleep_interruptible(60)
        update_job_status_sync("job.results_calendar", "idle", progress=0, message="Stopped")
        logger.info("results_calendar_worker: stopped")
        return

    # Wait for stock universe to be ready (replaces the old fixed 15s delay)
    if _wait_for_startup_event(_startup_stock_universe_done, "stock_universe", "job.results_calendar"):
        update_job_status_sync("job.results_calendar", "idle", progress=0, message="Stopped")
        logger.info("results_calendar_worker: stopped")
        return

    # Check first_run for startup execution
    if _is_first_run("results_calendar"):
        update_job_status_sync("job.results_calendar", "running", progress=0, message="Starting initial sync...")
        _results_calendar_sync()
        _set_first_run_complete("results_calendar")
    else:
        logger.info("results_calendar_worker: first_run=False, skipping startup execution")
        update_job_status_sync("job.results_calendar", "waiting", progress=0, message="Waiting for cron schedule")

    while not _shutdown_event.is_set():
        wait_secs = _report_job_waiting("job.results_calendar", _RESULTS_CALENDAR_CRON)
        logger.info(
            "results_calendar_worker: sleeping %.0f s until next cron (%s)",
            wait_secs, _RESULTS_CALENDAR_CRON,
        )
        if _sleep_interruptible(wait_secs):
            break
        if not _shutdown_event.is_set():
            if not _is_job_enabled("job.results_calendar"):
                update_job_status_sync("job.results_calendar", "waiting", progress=0, message="Disabled")
                _sleep_interruptible(60)
                continue
            _results_calendar_sync()

    update_job_status_sync("job.results_calendar", "idle", progress=0, message="Stopped")
    logger.info("results_calendar_worker: stopped")
