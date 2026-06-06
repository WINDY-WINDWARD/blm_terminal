"""Maintenance workers (audit C.1, A.9).

Extracted from ``app/backgroundtasks/_impl.py`` so the heavy
``_impl.py`` shrinks toward its target size.

Public worker:
- ``vacuum_worker()`` — daemon thread: runs VACUUM on the SQLite
  warehouse every Sunday 04:00 (low-traffic window).  Skipped if
  disabled via system_config; waits for ``ticker_scores`` to
  complete on the first launch to avoid racing with the nightly
  pipeline.

NOTE: We import ``logger``, ``settings``, ``_is_job_enabled``,
``_is_first_run``, ``_set_first_run_complete``, ``_shutdown_event``,
``_sleep_interruptible``, ``_wait_for_startup_event``,
``_startup_ticker_scores_done``, ``update_job_status_sync``, and
``_report_job_waiting`` lazily inside the worker body to avoid a
circular import: ``app.backgroundtasks._impl`` re-exports us at
the bottom of its own module, so a top-level import from
``_impl`` here would deadlock the import machinery.
"""
from __future__ import annotations

import sqlite3
import time

VACUUM_CRON = "0 4 * * 0"   # Every Sunday 04:00 (low-traffic window)


def _run_vacuum() -> None:
    """Run VACUUM on the SQLite warehouse to reclaim space from deleted rows.

    Uses a dedicated short-lived connection because VACUUM cannot run inside
    an open transaction.  Disables WAL briefly to allow the rebuild.
    """
    from app.backgroundtasks import _impl as _bg_impl

    db_path = _bg_impl.settings.db_path
    _bg_impl.logger.info("vacuum: starting VACUUM on %s", db_path)
    _bg_impl.update_job_status_sync("job.vacuum", "running", progress=10, message="Starting VACUUM...")
    t0 = time.time()
    try:
        # VACUUM cannot be executed inside a transaction.  Use a fresh
        # connection with isolation_level=None (autocommit) so each
        # statement is its own transaction.
        with sqlite3.connect(db_path, timeout=600, isolation_level=None) as con:
            # 1. checkpoint WAL to fold pending writes into the main DB
            _bg_impl.update_job_status_sync("job.vacuum", "running", progress=20,
                                            message="Checkpointing WAL...")
            try:
                con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except sqlite3.OperationalError as e:
                _bg_impl.logger.warning("vacuum: wal_checkpoint failed (continuing): %s", e)

            # 2. rebuild the database file in place
            _bg_impl.update_job_status_sync("job.vacuum", "running", progress=50,
                                            message="VACUUM in progress (may take 5-15 min)...")
            con.execute("VACUUM")

            # 3. update query planner stats
            _bg_impl.update_job_status_sync("job.vacuum", "running", progress=90,
                                            message="Running ANALYZE...")
            con.execute("ANALYZE")

        elapsed = time.time() - t0
        _bg_impl.logger.info("vacuum: complete in %.1fs", elapsed)
        _bg_impl.update_job_status_sync("job.vacuum", "waiting", progress=100,
                                        message=f"Complete in {elapsed:.0f}s")
    except Exception:
        _bg_impl.logger.exception("vacuum: failed")
        _bg_impl.update_job_status_sync("job.vacuum", "waiting", progress=0,
                                        message="Failed (will retry next week)")


def vacuum_worker() -> None:
    """Daemon thread: runs VACUUM weekly on Sunday 04:00.

    Skips if disabled via system_config.  On first launch (first_run=True)
    waits for ticker_scores to complete before triggering (we don't want to
    race with the nightly pipeline).  Subsequent cycles use the cron schedule.
    """
    from app.backgroundtasks import _impl as _bg_impl

    logger = _bg_impl.logger
    _is_job_enabled = _bg_impl._is_job_enabled
    _is_first_run = _bg_impl._is_first_run
    _set_first_run_complete = _bg_impl._set_first_run_complete
    _shutdown_event = _bg_impl._shutdown_event
    _sleep_interruptible = _bg_impl._sleep_interruptible
    _wait_for_startup_event = _bg_impl._wait_for_startup_event
    _startup_ticker_scores_done = _bg_impl._startup_ticker_scores_done
    update_job_status_sync = _bg_impl.update_job_status_sync
    _report_job_waiting = _bg_impl._report_job_waiting

    logger.info("vacuum_worker: started")

    if not _is_job_enabled("job.vacuum"):
        logger.info("vacuum_worker: disabled, waiting...")
        update_job_status_sync("job.vacuum", "waiting", progress=0, message="Disabled")
        while not _shutdown_event.is_set():
            _sleep_interruptible(60)
        update_job_status_sync("job.vacuum", "idle", progress=0, message="Stopped")
        logger.info("vacuum_worker: stopped")
        return

    # Wait for ticker_scores to finish its first run so we don't fight for the
    # DB lock during startup.  This is a soft check — if the worker hasn't
    # started, just proceed.
    if _is_first_run("vacuum") and _wait_for_startup_event(
        _startup_ticker_scores_done, "ticker_scores", "job.vacuum"
    ):
        update_job_status_sync("job.vacuum", "idle", progress=0, message="Stopped")
        return
    if _is_first_run("vacuum"):
        _set_first_run_complete("vacuum")

    while not _shutdown_event.is_set():
        wait_secs = _report_job_waiting("job.vacuum", VACUUM_CRON,
                                        message="Weekly maintenance")
        logger.info("vacuum_worker: sleeping %.0fs until next cron (%s)",
                    wait_secs, VACUUM_CRON)
        if _sleep_interruptible(wait_secs):
            break
        if not _shutdown_event.is_set():
            if not _is_job_enabled("job.vacuum"):
                update_job_status_sync("job.vacuum", "waiting", progress=0, message="Disabled")
                _sleep_interruptible(60)
                continue
            _run_vacuum()

    update_job_status_sync("job.vacuum", "idle", progress=0, message="Stopped")
    logger.info("vacuum_worker: stopped")
