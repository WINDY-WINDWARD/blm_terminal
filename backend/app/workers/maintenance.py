"""Maintenance workers (audit C.1, A.9, A.13).

Extracted from ``app/backgroundtasks/_impl.py`` so the heavy
``_impl.py`` shrinks toward its target size.

Public worker:
- ``vacuum_worker()`` — daemon thread: runs VACUUM on the SQLite
  warehouse every Sunday 04:00 (low-traffic window).  Skipped if
  disabled via system_config; waits for ``ticker_scores`` to
  complete on the first launch to avoid racing with the nightly
  pipeline.

A.13: migrated ``_bg_impl`` references to canonical imports.
"""
from __future__ import annotations

import logging
import sqlite3
import time
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)


VACUUM_CRON = "0 4 * * 0"   # Every Sunday 04:00 (low-traffic window)


def _purge_ai_traces(con: sqlite3.Connection) -> None:
    """Purge AI Pick traces older than 90 days."""
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
        # SQLite uses string comparison for ISO8601 datetimes.
        cutoff_date = cutoff.replace("+00:00", "")
        con.execute("DELETE FROM ai_pick_traces WHERE created_at < ?", (cutoff_date,))
        logger.info("vacuum: purged old AI pick traces")
    except sqlite3.OperationalError as e:
        logger.warning(f"vacuum: failed to purge ai_pick_traces: {e}")


def _purge_api_cache(con: sqlite3.Connection) -> None:
    """Delete expired api_cache rows."""
    try:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        con.execute("DELETE FROM api_cache WHERE expires_at < ?", (now,))
        logger.info("vacuum: purged expired api_cache rows")
    except sqlite3.OperationalError as e:
        logger.warning(f"vacuum: failed to purge api_cache: {e}")


def _run_vacuum() -> None:
    """Run VACUUM on the SQLite warehouse to reclaim space from deleted rows.

    Uses a dedicated short-lived connection because VACUUM cannot run inside
    an open transaction.  Disables WAL briefly to allow the rebuild.
    """
    from app.config import settings
    from app.jobs.runner import update_job_status_sync

    db_path = settings.db_path
    logger.info("vacuum: starting VACUUM on %s", db_path)
    update_job_status_sync("job.vacuum", "running", progress=10, message="Starting VACUUM...")
    t0 = time.time()
    try:
        # VACUUM cannot be executed inside a transaction.  Use a fresh
        # connection with isolation_level=None (autocommit) so each
        # statement is its own transaction.
        with sqlite3.connect(db_path, timeout=15, check_same_thread=False, isolation_level=None) as con:
            from app.database import _apply_sqlite_pragmas
            _cur = con.cursor()
            _apply_sqlite_pragmas(_cur)
            _cur.close()
            _purge_ai_traces(con)
            _purge_api_cache(con)

            # 1. checkpoint WAL to fold pending writes into the main DB
            update_job_status_sync("job.vacuum", "running", progress=20,
                                            message="Checkpointing WAL...")
            try:
                con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except sqlite3.OperationalError as e:
                logger.warning("vacuum: wal_checkpoint failed (continuing): %s", e)

            # 2. rebuild the database file in place
            update_job_status_sync("job.vacuum", "running", progress=50,
                                            message="VACUUM in progress (may take 5-15 min)...")
            con.execute("VACUUM")

            # 3. update query planner stats
            update_job_status_sync("job.vacuum", "running", progress=90,
                                            message="Running ANALYZE...")
            con.execute("ANALYZE")

        elapsed = time.time() - t0
        logger.info("vacuum: complete in %.1fs", elapsed)
        update_job_status_sync("job.vacuum", "waiting", progress=100,
                                        message=f"Complete in {elapsed:.0f}s")
    except Exception:
        logger.exception("vacuum: failed")
        update_job_status_sync("job.vacuum", "waiting", progress=0,
                                        message="Failed (will retry next week)")


def vacuum_worker() -> None:
    """Daemon thread: runs VACUUM weekly on Sunday 04:00.

    Skips if disabled via system_config.  On first launch (first_run=True)
    waits for ticker_scores to complete before triggering (we don't want to
    race with the nightly pipeline).  Subsequent cycles use the cron schedule.
    """
    from app.backgroundtasks._runtime import (
        _is_first_run,
        _is_job_enabled,
        _report_job_waiting,
        _set_first_run_complete,
        _shutdown_event,
        _sleep_interruptible,
        _startup_ticker_scores_done,
        _wait_for_startup_event,
    )
    from app.jobs.runner import update_job_status_sync

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
            from app.jobs.runner import mark_job_success_sync
            mark_job_success_sync("job.vacuum")

    update_job_status_sync("job.vacuum", "idle", progress=0, message="Stopped")
    logger.info("vacuum_worker: stopped")
