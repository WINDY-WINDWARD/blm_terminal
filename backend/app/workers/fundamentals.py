"""Screener fundamentals backfill worker (market cap + net-profit YoY).

Daemon thread target that owns the cron schedule for enriching the universe
with screener.in fundamentals. The actual sync work function
(``_fundamentals_sync``) lives in ``app.services.data_sync.fundamentals``.

Public worker:
- ``fundamentals_worker()`` — daily cron at 01:30 IST. Startup execution is
  skipped (first full pass takes hours); progress is made by the nightly
  run, the missed-schedule catch-up after boot, plus any manual trigger
  from the Jobs UI.
"""
from __future__ import annotations

FUNDAMENTALS_CRON = "30 1 * * *"


def fundamentals_worker() -> None:
    """Daemon thread target for screener fundamentals backfill."""
    import logging

    from app.backgroundtasks._runtime import (_is_first_run,
        _is_job_enabled, _report_job_waiting, _set_first_run_complete,
        _shutdown_event, _sleep_interruptible)
    from app.jobs.runner import update_job_status_sync
    from app.services.data_sync.fundamentals import _fundamentals_sync

    logger = logging.getLogger(__name__)
    logger.info("fundamentals_worker: started")

    if not _is_job_enabled("job.fundamentals"):
        logger.info("fundamentals_worker: disabled, waiting...")
        update_job_status_sync("job.fundamentals", "waiting", progress=0, message="Disabled")
        while not _shutdown_event.is_set():
            _sleep_interruptible(60)
        update_job_status_sync("job.fundamentals", "idle", progress=0, message="Stopped")
        logger.info("fundamentals_worker: stopped")
        return

    if _is_first_run("fundamentals"):
        logger.info("fundamentals_worker: first run — deferring to nightly cron (full pass takes hours)")
        _set_first_run_complete("fundamentals")
    else:
        logger.info("fundamentals_worker: first_run=False, skipping startup execution")
    update_job_status_sync("job.fundamentals", "waiting", progress=0, message="Waiting for cron schedule")

    while not _shutdown_event.is_set():
        wait_secs = _report_job_waiting("job.fundamentals", FUNDAMENTALS_CRON)
        logger.info("fundamentals_worker: sleeping %.0fs until next cron (%s)", wait_secs, FUNDAMENTALS_CRON)
        if _sleep_interruptible(wait_secs):
            break
        if not _shutdown_event.is_set():
            if not _is_job_enabled("job.fundamentals"):
                update_job_status_sync("job.fundamentals", "waiting", progress=0, message="Disabled")
                _sleep_interruptible(60)
                continue
            update_job_status_sync("job.fundamentals", "running", progress=0, message="Enriching fundamentals...")
            _fundamentals_sync()
            from app.jobs.runner import mark_job_success_sync
            mark_job_success_sync("job.fundamentals")

    update_job_status_sync("job.fundamentals", "idle", progress=0, message="Stopped")
    logger.info("fundamentals_worker: stopped")
