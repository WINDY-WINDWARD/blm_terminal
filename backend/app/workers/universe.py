"""Ticker universe refresh worker (audit C.1, A.9 step 2, A.13).

Extracted from ``app/backgroundtasks/_impl.py`` so the heavy
``_impl.py`` shrinks toward its target size.  This is the **daemon
thread loop** that owns the cron schedule for refreshing the
NSE stock universe metadata table.  The actual sync work function
(``_stock_universe_sync``) lives in ``app/services/data_sync/universe.py``
— already moved in A.3.

Public workers:
- ``stock_universe_worker()`` — daily cron at 00:00 IST refreshes
  the universe metadata.  Startup is owned by the orchestrator.

A.13: ``_bg_impl.<X>`` references migrated to direct canonical
homes (``app.backgroundtasks._runtime`` for shared state/helpers,
``app.services.data_sync.universe`` for ``_stock_universe_sync``,
``app.jobs.runner`` for ``update_job_status_sync``).  All imports
remain **lazy** (inside function bodies) to avoid the
``app.backgroundtasks`` ⇄ ``app.workers`` circular import.
"""
from __future__ import annotations


def stock_universe_worker() -> None:
    """Daemon thread target for stock universe refresh."""
    import logging

    from app.backgroundtasks._runtime import (_is_first_run,
        _is_job_enabled, _report_job_waiting, _set_first_run_complete,
        _shutdown_event, _sleep_interruptible)
    from app.jobs.runner import update_job_status_sync
    from app.services.data_sync.universe import _stock_universe_sync

    logger = logging.getLogger(__name__)
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
            from app.jobs.runner import mark_job_success_sync
            mark_job_success_sync("job.stock_universe")

    update_job_status_sync("job.stock_universe", "idle", progress=0, message="Stopped")
    logger.info("stock_universe_worker: stopped")
