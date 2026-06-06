"""Ticker universe refresh worker (audit C.1, A.9 step 2).

Extracted from ``app/backgroundtasks/_impl.py`` so the heavy
``_impl.py`` shrinks toward its target size.  This is the **daemon
thread loop** that owns the cron schedule for refreshing the
NSE stock universe metadata table.  The actual sync work function
(``_stock_universe_sync``) lives in ``app/services/data_sync/universe.py``
— already moved in A.3.

Public workers:
- ``stock_universe_worker()`` — daily cron at 00:00 IST refreshes
  the universe metadata.  Startup is owned by the orchestrator.

NOTE: We import all `_impl` helpers (logger, settings, sync work
functions, shutdown state, etc.) lazily inside the worker body to
avoid a circular import: ``app.backgroundtasks._impl`` re-exports
us at the bottom of its own module, so a top-level import from
``_impl`` here would deadlock the import machinery.
"""
from __future__ import annotations


def stock_universe_worker() -> None:
    """Daemon thread target for stock universe refresh."""
    from app.backgroundtasks import _impl as _bg_impl

    logger = _bg_impl.logger
    _is_job_enabled = _bg_impl._is_job_enabled
    _is_first_run = _bg_impl._is_first_run
    _set_first_run_complete = _bg_impl._set_first_run_complete
    _shutdown_event = _bg_impl._shutdown_event
    _sleep_interruptible = _bg_impl._sleep_interruptible
    update_job_status_sync = _bg_impl.update_job_status_sync
    _report_job_waiting = _bg_impl._report_job_waiting
    _stock_universe_sync = _bg_impl._stock_universe_sync

    logger.info("stock_universe_worker: started")

    if not _is_job_enabled("job.stock_universe"):
        logger.info("stock_universe_worker: disabled, waiting...")
        update_job_status_sync("job.stock_universe", "waiting", progress=0, message="Disabled")
        while not _shutdown_event.is_set():
            _sleep_interruptible(60)
        update_job_status_sync("job.stock_universe", "idle", progress=0, message="Stopped")
        logger.info("stock_universe_worker: stopped")
        return

    if _is_first_run("stock_universe"):
        logger.info("stock_universe_worker: orchestrator owns startup sync, skipping worker first-run execution")
        _set_first_run_complete("stock_universe")
    else:
        logger.info("stock_universe_worker: first_run=False, skipping startup execution")
    update_job_status_sync("job.stock_universe", "waiting", progress=0, message="Waiting for orchestrator / cron schedule")

    while not _shutdown_event.is_set():
        wait_secs = _report_job_waiting("job.stock_universe", "0 0 * * *")
        logger.info("stock_universe_worker: sleeping %.0fs until next cron (0 0 * * *)", wait_secs)
        if _sleep_interruptible(wait_secs):
            break
        if not _shutdown_event.is_set():
            if not _is_job_enabled("job.stock_universe"):
                update_job_status_sync("job.stock_universe", "waiting", progress=0, message="Disabled")
                _sleep_interruptible(60)
                continue
            update_job_status_sync("job.stock_universe", "running", progress=0, message="Syncing stock universe...")
            _stock_universe_sync()

    update_job_status_sync("job.stock_universe", "idle", progress=0, message="Stopped")
    logger.info("stock_universe_worker: stopped")
