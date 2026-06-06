"""Market data + results calendar worker daemons (audit C.1, A.9 step 4).

Extracted from ``app/backgroundtasks/_impl.py``.  The actual sync
functions stay in ``_impl.py`` for now and move in A.11.

Public workers:
- ``market_data_worker()`` — cron ``*/5 * * * *`` during market hours.
- ``results_calendar_worker()`` — cron ``0 8,14 * * 1-5``.

NOTE: Lazy imports from ``_impl`` to avoid circular import deadlock.
"""
from __future__ import annotations


def market_data_worker() -> None:
    """Daemon thread target for market data fetching (cron: */5 * * * *, market-hours only)."""
    from app.backgroundtasks import _impl as _bg_impl

    logger = _bg_impl.logger
    _is_job_enabled = _bg_impl._is_job_enabled
    _is_first_run = _bg_impl._is_first_run
    _set_first_run_complete = _bg_impl._set_first_run_complete
    _shutdown_event = _bg_impl._shutdown_event
    _sleep_interruptible = _bg_impl._sleep_interruptible
    _is_market_open = _bg_impl._is_market_open
    _seconds_until_market_open = _bg_impl._seconds_until_market_open
    _wait_for_startup_event = _bg_impl._wait_for_startup_event
    _startup_stock_universe_done = _bg_impl._startup_stock_universe_done
    _report_job_waiting = _bg_impl._report_job_waiting
    _market_data_sync = _bg_impl._market_data_sync
    _run_async = _bg_impl._run_async
    market_data_fetcher = _bg_impl.market_data_fetcher
    update_job_status_sync = _bg_impl.update_job_status_sync

    logger.info("market_data_worker: started")

    if not _is_job_enabled("job.market_data"):
        logger.info("market_data_worker: disabled, waiting...")
        update_job_status_sync("job.market_data", "waiting", progress=0, message="Disabled")
        while not _shutdown_event.is_set():
            _sleep_interruptible(60)
        update_job_status_sync("job.market_data", "idle", progress=0, message="Stopped")
        logger.info("market_data_worker: stopped")
        return

    # Check first_run for startup execution
    if _is_first_run("market_data"):
        # Wait for stock universe before fetching market data
        if _wait_for_startup_event(_startup_stock_universe_done, "stock_universe", "job.market_data"):
            update_job_status_sync("job.market_data", "idle", progress=0, message="Stopped")
            logger.info("market_data_worker: stopped")
            return
        update_job_status_sync("job.market_data", "running", progress=0, message="Starting initial sync...")
        _market_data_sync()
        _set_first_run_complete("market_data")
    else:
        logger.info("market_data_worker: first_run=False, skipping startup execution")
        update_job_status_sync("job.market_data", "waiting", progress=0, message="Waiting for cron schedule")

    while not _shutdown_event.is_set():
        if _is_market_open():
            wait = _report_job_waiting("job.market_data", "*/5 * * * *", f"Market open, next run soon")
            logger.info("market_data_worker: market is open, next run in %.0f s", wait)
            if _sleep_interruptible(wait):
                break
            if not _shutdown_event.is_set() and _is_market_open():
                if not _is_job_enabled("job.market_data"):
                    update_job_status_sync("job.market_data", "waiting", progress=0, message="Disabled")
                    _sleep_interruptible(60)
                    continue
                update_job_status_sync("job.market_data", "running", progress=50, message="Fetching market data...")
                _market_data_sync()
        else:
            wait = _seconds_until_market_open()
            logger.info("market_data_worker: market is closed, next run in %.0f s (%.1f hours)", wait, wait / 3600)
            update_job_status_sync("job.market_data", "waiting", progress=0, message=f"Market closed, opens in {wait/3600:.1f}h")
            if _sleep_interruptible(wait):
                break

    update_job_status_sync("job.market_data", "idle", progress=0, message="Stopped")
    try:
        _run_async(market_data_fetcher.close())
    except Exception:
        logger.debug("market_data_worker: close() raised, ignoring (client may already be closed)")
    logger.info("market_data_worker: stopped")


def results_calendar_worker() -> None:
    """Daemon thread: syncs upcoming results notifications twice daily (8am + 2pm IST)."""
    from app.backgroundtasks import _impl as _bg_impl

    logger = _bg_impl.logger
    _is_job_enabled = _bg_impl._is_job_enabled
    _is_first_run = _bg_impl._is_first_run
    _set_first_run_complete = _bg_impl._set_first_run_complete
    _shutdown_event = _bg_impl._shutdown_event
    _sleep_interruptible = _bg_impl._sleep_interruptible
    _wait_for_startup_event = _bg_impl._wait_for_startup_event
    _startup_stock_universe_done = _bg_impl._startup_stock_universe_done
    _report_job_waiting = _bg_impl._report_job_waiting
    _results_calendar_sync = _bg_impl._results_calendar_sync
    _RESULTS_CALENDAR_CRON = _bg_impl._RESULTS_CALENDAR_CRON
    update_job_status_sync = _bg_impl.update_job_status_sync

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
