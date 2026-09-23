"""Ticker data-pipeline sync workers (audit C.1, A.9 step 2, A.13).

Extracted from ``app/backgroundtasks/_impl.py`` so the heavy
``_impl.py`` shrinks toward its target size.  These are the
**daemon thread loops** that own the cron schedule for pulling
fresh candle data into the warehouse.  The actual sync work
functions (e.g. ``_ticker_backfill_sync``,
``_ticker_daily_update_sync``, ``_ticker_intraday_update_sync``)
live in ``app/services/data_sync/<domain>.py`` — already moved
in A.4-A.6.

Public workers:
- ``ticker_backfill_worker()`` — runs at startup (orchestrator owns
  the work; this thread just idles until shutdown).
- ``ticker_daily_update_worker()`` — cron
  ``*/30 15,16,17,18,19,20 * * 1-5``; acquires the pipeline lock
  so scan/notif workers wait.
- ``ticker_intraday_hourly_update_worker()`` — cron
  ``15 9,10,11,12,13,14,15 * * 1-5``; first-run triggers the initial
  hourly backfill.

A.13: migrated ``_bg_impl`` references to canonical imports.
"""
from __future__ import annotations

import logging


logger = logging.getLogger(__name__)


def ticker_backfill_worker() -> None:
    """Daemon thread target for ticker backfill.

    Runs on every server startup (after stock universe is ready).
    get_symbols_needing_backfill() now checks both row count and staleness, so
    when data is current this completes near-instantly with no symbols to process.
    """
    from app.backgroundtasks._runtime import (
        _is_job_enabled,
        _shutdown_event,
        _sleep_interruptible,
    )
    from app.jobs.runner import update_job_status_sync

    logger.info("ticker_backfill_worker: started")

    if not _is_job_enabled("job.ticker_backfill"):
        logger.info("ticker_backfill_worker: disabled, waiting...")
        update_job_status_sync("job.ticker_backfill", "waiting", progress=0, message="Disabled")
        while not _shutdown_event.is_set():
            _sleep_interruptible(60)
        update_job_status_sync("job.ticker_backfill", "idle", progress=0, message="Stopped")
        logger.info("ticker_backfill_worker: stopped")
        return

    update_job_status_sync("job.ticker_backfill", "waiting", progress=0, message="Waiting for orchestrator startup / idle")
    logger.info("ticker_backfill_worker: startup work delegated to orchestrator, idling until shutdown")

    while not _shutdown_event.is_set():
        _sleep_interruptible(3600)

    update_job_status_sync("job.ticker_backfill", "idle", progress=0, message="Stopped")
    logger.info("ticker_backfill_worker: stopped")


def ticker_daily_update_worker() -> None:
    """Daemon thread target for ticker daily updates (cron: */30 15,16,17,18,19,20 * * 1-5)."""
    from app.backgroundtasks._runtime import (
        _is_job_enabled,
        _pipeline_idle,
        _pipeline_lock,
        _report_job_waiting,
        _shutdown_event,
        _sleep_interruptible,
        _startup_pipeline_done,
        _wait_for_startup_event,
    )
    from app.jobs.runner import update_job_status_sync
    from app.services.data_sync.daily import _ticker_daily_update_sync

    logger.info("ticker_daily_update_worker: started")

    # 30-second delay at startup on cold boot for desktop responsiveness
    _sleep_interruptible(30.0)

    if not _is_job_enabled("job.ticker_daily_update"):
        logger.info("ticker_daily_update_worker: disabled, waiting...")
        update_job_status_sync("job.ticker_daily_update", "waiting", progress=0, message="Disabled")
        while not _shutdown_event.is_set():
            _sleep_interruptible(60)
        update_job_status_sync("job.ticker_daily_update", "idle", progress=0, message="Stopped")
        logger.info("ticker_daily_update_worker: stopped")
        return

    update_job_status_sync("job.ticker_daily_update", "waiting", progress=0, message="Waiting for cron schedule")

    if _wait_for_startup_event(_startup_pipeline_done, "startup pipeline", "job.ticker_daily_update"):
        return

    while not _shutdown_event.is_set():
        wait_secs = _report_job_waiting("job.ticker_daily_update", "*/30 15,16,17,18,19,20 * * 1-5")
        logger.info("ticker_daily_update_worker: sleeping %.0fs until next cron (*/30 15,16,17,18,19,20 * * 1-5)", wait_secs)
        if _sleep_interruptible(wait_secs):
            break
        if not _shutdown_event.is_set():
            if not _is_job_enabled("job.ticker_daily_update"):
                update_job_status_sync("job.ticker_daily_update", "waiting", progress=0, message="Disabled")
                _sleep_interruptible(60)
                continue
            with _pipeline_lock:
                _pipeline_idle.clear()
                try:
                    update_job_status_sync("job.ticker_daily_update", "running", progress=0, message="Running daily update...")
                    _ticker_daily_update_sync()
                    from app.jobs.runner import mark_job_success_sync
                    mark_job_success_sync("job.ticker_daily_update")
                finally:
                    _pipeline_idle.set()

    update_job_status_sync("job.ticker_daily_update", "idle", progress=0, message="Stopped")
    logger.info("ticker_daily_update_worker: stopped")


def ticker_intraday_hourly_update_worker() -> None:
    """Daemon thread target for hourly (1h) intraday candle updates.

    Cron: at :15 past each trading hour 09:15-15:15 IST on weekdays.
    Also executes once at startup (first_run pattern).
    """
    from app.backgroundtasks._runtime import (
        _is_first_run,
        _is_job_enabled,
        _report_job_waiting,
        _set_first_run_complete,
        _shutdown_event,
        _sleep_interruptible,
        _startup_ticker_hourly_done,
    )
    from app.jobs.runner import update_job_status_sync
    from app.services.data_sync.intraday import _ticker_intraday_update_sync

    logger.info("ticker_intraday_hourly_update_worker: started")

    if not _is_job_enabled("job.ticker_intraday_hourly_update"):
        logger.info("ticker_intraday_hourly_update_worker: disabled, waiting...")
        update_job_status_sync("job.ticker_intraday_hourly_update", "waiting", progress=0, message="Disabled")
        while not _shutdown_event.is_set():
            _sleep_interruptible(60)
        update_job_status_sync("job.ticker_intraday_hourly_update", "idle", progress=0, message="Stopped")
        logger.info("ticker_intraday_hourly_update_worker: stopped")
        return

    if _is_first_run("ticker_intraday_hourly_update"):
        from app.backgroundtasks._runtime import _wait_for_startup_event
        _wait_for_startup_event()
        update_job_status_sync("job.ticker_intraday_hourly_update", "running", progress=0, message="Starting hourly backfill...")
        try:
            _ticker_intraday_update_sync(["1h"])
        except Exception as exc:
            logger.error("[hourly_worker] startup run failed: %s", exc)
        _set_first_run_complete("ticker_intraday_hourly_update")
        _startup_ticker_hourly_done.set()
        logger.info("ticker_intraday_hourly_update_worker: startup gate released (_startup_ticker_hourly_done)")
        update_job_status_sync("job.ticker_intraday_hourly_update", "waiting", progress=0, message="Waiting for cron schedule")
    else:
        logger.info("ticker_intraday_hourly_update_worker: first_run=False, skipping startup execution")
        _startup_ticker_hourly_done.set()
        logger.info("ticker_intraday_hourly_update_worker: startup gate released (first_run=False)")
        update_job_status_sync("job.ticker_intraday_hourly_update", "waiting", progress=0, message="Waiting for cron schedule")

    while not _shutdown_event.is_set():
        wait_secs = _report_job_waiting("job.ticker_intraday_hourly_update", "15 9,10,11,12,13,14,15 * * 1-5")
        logger.info("ticker_intraday_hourly_update_worker: sleeping %.0fs until next cron (15 9,10,11,12,13,14,15 * * 1-5)", wait_secs)
        if _sleep_interruptible(wait_secs):
            break
        if not _shutdown_event.is_set():
            if not _is_job_enabled("job.ticker_intraday_hourly_update"):
                update_job_status_sync("job.ticker_intraday_hourly_update", "waiting", progress=0, message="Disabled")
                _sleep_interruptible(60)
                continue
            update_job_status_sync("job.ticker_intraday_hourly_update", "running", progress=0, message="Running hourly update...")
            try:
                _ticker_intraday_update_sync(["1h"])
            except Exception as exc:
                logger.error("[hourly_worker] cron run failed: %s", exc)
            update_job_status_sync("job.ticker_intraday_hourly_update", "waiting", progress=0, message="Waiting for cron schedule")

    update_job_status_sync("job.ticker_intraday_hourly_update", "idle", progress=0, message="Stopped")
    logger.info("ticker_intraday_hourly_update_worker: stopped")
