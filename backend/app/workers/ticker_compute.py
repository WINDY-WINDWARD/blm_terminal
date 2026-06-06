"""Ticker compute-pipeline workers (audit C.1, A.9 step 2).

Extracted from ``app/backgroundtasks/_impl.py`` so the heavy
``_impl.py`` shrinks toward its target size.  These are the
**daemon thread loops** that own the cron schedule for computing
derived metrics (scores, indicators) on top of the candle data.
The actual sync work functions (``_ticker_scores_sync``,
``_ticker_indicators_sync``, ``_ticker_intraday_indicators_sync``)
live in ``app/services/data_sync/<domain>.py`` — already moved in
A.7-A.8.

Public workers:
- ``ticker_scores_worker()`` — cron ``0 0 * * *``; acquires
  pipeline lock.  Also triggered mid-day by
  ``_ticker_daily_update_sync()`` after bhavcopy lands.
- ``ticker_indicators_worker()`` — cron ``0 11 * * 1-5``; acquires
  pipeline lock.
- ``ticker_intraday_hourly_indicators_worker()`` — cron
  ``30 9,10,11,12,13,14,15 * * 1-5``.

NOTE: We import all `_impl` helpers (logger, settings, sync work
functions, shutdown state, etc.) lazily inside the worker body to
avoid a circular import: ``app.backgroundtasks._impl`` re-exports
us at the bottom of its own module, so a top-level import from
``_impl`` here would deadlock the import machinery.
"""
from __future__ import annotations


def ticker_scores_worker() -> None:
    """Daemon thread: computes ticker scores at startup then on cron 0 0 * * * (midnight).

    Also triggered mid-day by _ticker_daily_update_sync() after bhavcopy lands.
    """
    from app.backgroundtasks import _impl as _bg_impl

    logger = _bg_impl.logger
    _is_job_enabled = _bg_impl._is_job_enabled
    _shutdown_event = _bg_impl._shutdown_event
    _sleep_interruptible = _bg_impl._sleep_interruptible
    update_job_status_sync = _bg_impl.update_job_status_sync
    _report_job_waiting = _bg_impl._report_job_waiting
    _pipeline_lock = _bg_impl._pipeline_lock
    _pipeline_idle = _bg_impl._pipeline_idle
    _ticker_scores_sync = _bg_impl._ticker_scores_sync

    logger.info("ticker_scores_worker: started")

    if not _is_job_enabled("job.ticker_scores"):
        logger.info("ticker_scores_worker: disabled, waiting...")
        update_job_status_sync("job.ticker_scores", "waiting", progress=0, message="Disabled")
        while not _shutdown_event.is_set():
            _sleep_interruptible(60)
        update_job_status_sync("job.ticker_scores", "idle", progress=0, message="Stopped")
        logger.info("ticker_scores_worker: stopped")
        return

    update_job_status_sync("job.ticker_scores", "waiting", progress=0, message="Waiting for orchestrator / cron schedule")

    while not _shutdown_event.is_set():
        wait_secs = _report_job_waiting("job.ticker_scores", "0 0 * * *")
        logger.info("ticker_scores_worker: sleeping %.0fs until next cron (0 0 * * *)", wait_secs)
        if _sleep_interruptible(wait_secs):
            break
        if not _shutdown_event.is_set():
            if not _is_job_enabled("job.ticker_scores"):
                update_job_status_sync("job.ticker_scores", "waiting", progress=0, message="Disabled")
                _sleep_interruptible(60)
                continue
            with _pipeline_lock:
                _pipeline_idle.clear()
                try:
                    update_job_status_sync("job.ticker_scores", "running", progress=0, message="Computing ticker scores...")
                    _ticker_scores_sync()
                finally:
                    _pipeline_idle.set()

    update_job_status_sync("job.ticker_scores", "idle", progress=0, message="Stopped")
    logger.info("ticker_scores_worker: stopped")


def ticker_indicators_worker() -> None:
    """Daemon thread target for computing technical indicators (cron: 0 11 * * 1-5)."""
    from app.backgroundtasks import _impl as _bg_impl

    logger = _bg_impl.logger
    _is_job_enabled = _bg_impl._is_job_enabled
    _shutdown_event = _bg_impl._shutdown_event
    _sleep_interruptible = _bg_impl._sleep_interruptible
    update_job_status_sync = _bg_impl.update_job_status_sync
    _report_job_waiting = _bg_impl._report_job_waiting
    _pipeline_lock = _bg_impl._pipeline_lock
    _pipeline_idle = _bg_impl._pipeline_idle
    _ticker_indicators_sync = _bg_impl._ticker_indicators_sync

    logger.info("ticker_indicators_worker: started")

    if not _is_job_enabled("job.ticker_indicators"):
        logger.info("ticker_indicators_worker: disabled, waiting...")
        update_job_status_sync("job.ticker_indicators", "waiting", progress=0, message="Disabled")
        while not _shutdown_event.is_set():
            _sleep_interruptible(60)
        update_job_status_sync("job.ticker_indicators", "idle", progress=0, message="Stopped")
        logger.info("ticker_indicators_worker: stopped")
        return

    update_job_status_sync("job.ticker_indicators", "waiting", progress=0, message="Waiting for orchestrator / cron schedule")

    while not _shutdown_event.is_set():
        wait_secs = _report_job_waiting("job.ticker_indicators", "0 11 * * 1-5")
        logger.info("ticker_indicators_worker: sleeping %.0fs until next cron (0 11 * * 1-5)", wait_secs)
        if _sleep_interruptible(wait_secs):
            break
        if not _shutdown_event.is_set():
            if not _is_job_enabled("job.ticker_indicators"):
                update_job_status_sync("job.ticker_indicators", "waiting", progress=0, message="Disabled")
                _sleep_interruptible(60)
                continue
            with _pipeline_lock:
                _pipeline_idle.clear()
                try:
                    update_job_status_sync("job.ticker_indicators", "running", progress=0, message="Computing indicators...")
                    _ticker_indicators_sync()
                finally:
                    _pipeline_idle.set()

    update_job_status_sync("job.ticker_indicators", "idle", progress=0, message="Stopped")
    logger.info("ticker_indicators_worker: stopped")


def ticker_intraday_hourly_indicators_worker() -> None:
    """Daemon thread target for computing hourly (1h) intraday technical indicators.

    Cron: at :30 past each trading hour 09:30-15:30 IST on weekdays.
    """
    from app.backgroundtasks import _impl as _bg_impl

    logger = _bg_impl.logger
    _is_job_enabled = _bg_impl._is_job_enabled
    _is_first_run = _bg_impl._is_first_run
    _set_first_run_complete = _bg_impl._set_first_run_complete
    _shutdown_event = _bg_impl._shutdown_event
    _sleep_interruptible = _bg_impl._sleep_interruptible
    update_job_status_sync = _bg_impl.update_job_status_sync
    _report_job_waiting = _bg_impl._report_job_waiting
    _startup_ticker_hourly_done = _bg_impl._startup_ticker_hourly_done
    _ticker_intraday_indicators_sync = _bg_impl._ticker_intraday_indicators_sync

    logger.info("ticker_intraday_hourly_indicators_worker: started")

    if not _is_job_enabled("job.ticker_intraday_hourly_indicators"):
        logger.info("ticker_intraday_hourly_indicators_worker: disabled, waiting...")
        update_job_status_sync("job.ticker_intraday_hourly_indicators", "waiting", progress=0, message="Disabled")
        while not _shutdown_event.is_set():
            _sleep_interruptible(60)
        update_job_status_sync("job.ticker_intraday_hourly_indicators", "idle", progress=0, message="Stopped")
        logger.info("ticker_intraday_hourly_indicators_worker: stopped")
        return

    if _is_first_run("ticker_intraday_hourly_indicators"):
        if _bg_impl._wait_for_startup_event(_startup_ticker_hourly_done, "ticker_intraday_hourly_update", "job.ticker_intraday_hourly_indicators"):
            update_job_status_sync("job.ticker_intraday_hourly_indicators", "idle", progress=0, message="Stopped")
            logger.info("ticker_intraday_hourly_indicators_worker: stopped")
            return
        update_job_status_sync("job.ticker_intraday_hourly_indicators", "running", progress=0, message="Starting initial computation...")
        _ticker_intraday_indicators_sync(["1h"])
        _set_first_run_complete("ticker_intraday_hourly_indicators")
    else:
        logger.info("ticker_intraday_hourly_indicators_worker: first_run=False, skipping startup computation")
        update_job_status_sync("job.ticker_intraday_hourly_indicators", "waiting", progress=0, message="Waiting for cron schedule")

    while not _shutdown_event.is_set():
        wait_secs = _report_job_waiting("job.ticker_intraday_hourly_indicators", "30 9,10,11,12,13,14,15 * * 1-5")
        logger.info("ticker_intraday_hourly_indicators_worker: sleeping %.0fs until next cron (30 9,10,11,12,13,14,15 * * 1-5)", wait_secs)
        if _sleep_interruptible(wait_secs):
            break
        if not _shutdown_event.is_set():
            if not _is_job_enabled("job.ticker_intraday_hourly_indicators"):
                update_job_status_sync("job.ticker_intraday_hourly_indicators", "waiting", progress=0, message="Disabled")
                _sleep_interruptible(60)
                continue
            update_job_status_sync("job.ticker_intraday_hourly_indicators", "running", progress=0, message="Computing hourly indicators...")
            _ticker_intraday_indicators_sync(["1h"])

    update_job_status_sync("job.ticker_intraday_hourly_indicators", "idle", progress=0, message="Stopped")
    logger.info("ticker_intraday_hourly_indicators_worker: stopped")
