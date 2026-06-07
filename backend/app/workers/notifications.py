"""Notification workers (audit C.1, A.9 step 3).

Extracted from ``app/backgroundtasks/_impl.py`` so the heavy
``_impl.py`` shrinks toward its target size.  These are the
**daemon thread loops** that own the cron schedule for the
notification cycles (watchlist-specific + global NSE scan).
The actual cycle functions (``_notification_cycle_full``,
``_notification_cycle_reduced``, ``_global_scan_cycle``) stay
in ``_impl.py`` for now and will move in A.11/A.12.

Public workers:
- ``watchlist_notification_worker()`` — cron ``*/5`` during market
  hours, ``*/30`` after hours; waits for the data pipeline lock so
  it never races daily_update/indicators/scores.
- ``global_scan_worker()`` — cron ``*/30 * * * *``; same pipeline
  lock wait.  Scans all NSE stocks (not just watchlist) for
  technical & market alerts.

NOTE: We import all `_impl` helpers (logger, settings, sync cycle
functions, shutdown state, etc.) lazily inside the worker body to
avoid a circular import: ``app.backgroundtasks._impl`` re-exports
us at the bottom of its own module, so a top-level import from
``_impl`` here would deadlock the import machinery.
"""
from __future__ import annotations


def watchlist_notification_worker() -> None:
    """Daemon thread: monitors watchlist stocks for significant market events.

    Cron: */5 * * * * during market hours; */30 * * * * after hours.
    """
    from app.backgroundtasks import _impl as _bg_impl
    from app.workers.notification_cycles import (
        _notification_cycle_full,
        _notification_cycle_reduced,
    )

    logger = _bg_impl.logger
    _is_job_enabled = _bg_impl._is_job_enabled
    _shutdown_event = _bg_impl._shutdown_event
    _sleep_interruptible = _bg_impl._sleep_interruptible
    _is_market_open = _bg_impl._is_market_open
    _wait_for_startup_event = _bg_impl._wait_for_startup_event
    _wait_for_pipeline = _bg_impl._wait_for_pipeline
    _startup_ticker_scores_done = _bg_impl._startup_ticker_scores_done
    update_job_status_sync = _bg_impl.update_job_status_sync
    _report_job_waiting = _bg_impl._report_job_waiting

    logger.info("watchlist_notification_worker: started")

    if not _is_job_enabled("job.notifications"):
        logger.info("watchlist_notification_worker: disabled, waiting...")
        update_job_status_sync("job.notifications", "waiting", progress=0, message="Disabled")
        while not _shutdown_event.is_set():
            _sleep_interruptible(60)
        update_job_status_sync("job.notifications", "idle", progress=0, message="Stopped")
        logger.info("watchlist_notification_worker: stopped")
        return

    # Wait for ticker scores to be ready before first notification cycle
    update_job_status_sync("job.notifications", "waiting", progress=0, message="Waiting for startup pipeline...")
    if _wait_for_startup_event(_startup_ticker_scores_done, "ticker_scores", "job.notifications"):
        update_job_status_sync("job.notifications", "idle", progress=0, message="Stopped")
        logger.info("watchlist_notification_worker: stopped")
        return

    while not _shutdown_event.is_set():
        if not _is_job_enabled("job.notifications"):
            update_job_status_sync("job.notifications", "waiting", progress=0, message="Disabled")
            _sleep_interruptible(60)
            continue
        # Wait for any active data pipeline (daily_update/indicators/scores) to finish
        if _wait_for_pipeline("job.notifications", "watchlist_notification"):
            break
        if _is_market_open():
            update_job_status_sync("job.notifications", "running", progress=50, message="Checking market events...")
            _notification_cycle_full()
            wait = _report_job_waiting("job.notifications", "*/5 * * * *")
            _sleep_interruptible(wait)
        else:
            update_job_status_sync("job.notifications", "waiting", progress=0, message="Market closed, checking after-hours...")
            _notification_cycle_reduced()
            wait = _report_job_waiting("job.notifications", "*/30 * * * *")
            _sleep_interruptible(wait)

    update_job_status_sync("job.notifications", "idle", progress=0, message="Stopped")
    logger.info("watchlist_notification_worker: stopped")


def global_scan_worker() -> None:
    """Daemon thread: scans all NSE stocks on cron */30 * * * *."""
    from app.backgroundtasks import _impl as _bg_impl
    from app.workers.global_scan_cycle import _global_scan_cycle

    logger = _bg_impl.logger
    _is_job_enabled = _bg_impl._is_job_enabled
    _shutdown_event = _bg_impl._shutdown_event
    _sleep_interruptible = _bg_impl._sleep_interruptible
    _wait_for_startup_event = _bg_impl._wait_for_startup_event
    _wait_for_pipeline = _bg_impl._wait_for_pipeline
    _startup_ticker_scores_done = _bg_impl._startup_ticker_scores_done
    update_job_status_sync = _bg_impl.update_job_status_sync
    _report_job_waiting = _bg_impl._report_job_waiting

    logger.info("global_scan_worker: started")

    if not _is_job_enabled("job.global_scan"):
        logger.info("global_scan_worker: disabled, waiting...")
        update_job_status_sync("job.global_scan", "waiting", progress=0, message="Disabled")
        while not _shutdown_event.is_set():
            _sleep_interruptible(60)
        update_job_status_sync("job.global_scan", "idle", progress=0, message="Stopped")
        logger.info("global_scan_worker: stopped")
        return

    # Wait for ticker scores to be ready before first scan
    update_job_status_sync("job.global_scan", "waiting", progress=0, message="Waiting for startup pipeline...")
    if _wait_for_startup_event(_startup_ticker_scores_done, "ticker_scores", "job.global_scan"):
        update_job_status_sync("job.global_scan", "idle", progress=0, message="Stopped")
        logger.info("global_scan_worker: stopped")
        return

    while not _shutdown_event.is_set():
        if not _is_job_enabled("job.global_scan"):
            update_job_status_sync("job.global_scan", "waiting", progress=0, message="Disabled")
            _sleep_interruptible(60)
            continue
        # Wait for any active data pipeline (daily_update/indicators/scores) to finish
        if _wait_for_pipeline("job.global_scan", "global_scan"):
            break
        update_job_status_sync("job.global_scan", "running", progress=50, message="Scanning all NSE stocks...")
        _global_scan_cycle()
        wait = _report_job_waiting("job.global_scan", "*/30 * * * *")
        if _sleep_interruptible(wait):
            break

    update_job_status_sync("job.global_scan", "idle", progress=0, message="Stopped")
    logger.info("global_scan_worker: stopped")
