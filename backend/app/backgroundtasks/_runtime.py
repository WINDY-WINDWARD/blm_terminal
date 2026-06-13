"""Cross-cutting runtime helpers (audit C.1, A.10).

Extracted from ``app/backgroundtasks/_impl.py``.  These are the
shared primitives used by **every** worker daemon and cycle
function in the background-tasks package:

- **Thread shutdown event** + async mirror (``_shutdown_event``,
  ``get/set/reset_async_shutdown_event``).
- **Startup sequencing events** (one per pipeline stage) — the
  orchestrator uses these to gate workers that depend on upstream
  data being populated.
- **Pipeline lock + idle event** — mutual exclusion between pipeline
  *producers* (daily_update / indicators / scores) and a wait signal
  for *consumers* (global_scan / watchlist_notification).
- **First-run flag management** — per-worker SystemConfig keys with
  an in-process cache.
- **Sleep / cron math / job-status helpers** (``_sleep_interruptible``,
  ``_seconds_until_next_cron``, ``_report_job_waiting``,
  ``_is_job_enabled``).
- **Async coroutine runner** — ``_run_async`` uses a persistent
  per-thread event loop (reused across calls); ``_cleanup_run_async_loops``
  closes all loops during shutdown.  news_fetcher / market_data_fetcher
  carry Semaphore/Event objects created at module load in the main thread,
  so we can't reuse the main loop without "bound to a different
  event loop" errors.

Moved here in A.10 to shrink ``_impl.py`` toward its target size
before the A.11/A.12 cycle-function split and ``_impl`` deletion.
"""
from __future__ import annotations

import asyncio
import logging
import threading
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.database import _SyncSessionLocal
from app.jobs.runner import update_job_status_sync
from app.models.job import Job
from app.models.system_config import SystemConfig


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Worker thread state — do not access from async code
# ---------------------------------------------------------------------------
_shutdown_event = threading.Event()
_worker_threads: list[threading.Thread] = []


# ---------------------------------------------------------------------------
# Startup sequencing events
# Set by each worker after its first-run sync completes (or is skipped).
# Downstream workers poll these before starting their own first-run work.
# ---------------------------------------------------------------------------
_startup_stock_universe_done = threading.Event()
_startup_ticker_backfill_done = threading.Event()
_startup_ticker_indicators_done = threading.Event()
_startup_ticker_scores_done = threading.Event()
_startup_ticker_hourly_done = threading.Event()
_startup_market_data_done = threading.Event()
_startup_pipeline_done = threading.Event()


# ---------------------------------------------------------------------------
# Cron-cycle pipeline coordination
#
# _pipeline_lock   — mutual exclusion between pipeline *producers*
#                    (ticker_daily_update, ticker_indicators, ticker_scores).
#                    Only one producer runs its pipeline at a time.
#
# _pipeline_idle   — event that is SET when no pipeline is active.
#                    Pipeline consumers (global_scan, watchlist_notification)
#                    wait on this before each cycle so they never run on
#                    stale data while a refresh is in progress.
# ---------------------------------------------------------------------------
_pipeline_lock = threading.Lock()
_pipeline_idle = threading.Event()
_pipeline_idle.set()   # initially idle


# ---------------------------------------------------------------------------
# Async task shutdown event — for asyncio tasks
# ---------------------------------------------------------------------------
_async_shutdown_event: asyncio.Event | None = None


# ---------------------------------------------------------------------------
# First run detection — per-worker flags in SystemConfig
# ---------------------------------------------------------------------------
# Each worker owns its own key: "first_run.<worker_name>"
# Workers never share a flag, so a fast-starting worker cannot steal the
# first-run opportunity from a slower one.
# ---------------------------------------------------------------------------
_first_run_completed_cache: dict[str, bool] = {}
_first_run_lock = threading.Lock()


def _is_job_enabled(job_key: str) -> bool:
    """Check if a job is enabled in the database."""
    try:
        with _SyncSessionLocal() as db:
            stmt = select(Job).where(Job.job_key == job_key)
            result = db.execute(stmt)
            job = result.scalar_one_or_none()
            return job.is_enabled if job else True
    except Exception as e:
        logger.warning(f"Failed to check is_enabled for {job_key}, defaulting to enabled: {e}")
        return True


def _wait_for_startup_event(event: threading.Event, name: str, job_key: str) -> bool:
    """Block until *event* is set, polling every 5 s with a status update.

    Returns True if shutdown was requested before the event fired (caller
    should return immediately), False if the event is now set.
    """
    while not event.is_set():
        if _shutdown_event.is_set():
            return True
        update_job_status_sync(
            job_key, "waiting", progress=0,
            message=f"Waiting for {name} to complete...",
        )
        _shutdown_event.wait(timeout=5)
    return False


def _wait_for_pipeline(job_key: str, job_name: str) -> bool:
    """Block until the data pipeline is idle (no producer is running).

    Returns True if shutdown was requested, False when pipeline is idle.
    """
    while not _pipeline_idle.is_set():
        if _shutdown_event.is_set():
            return True
        update_job_status_sync(
            job_key, "waiting", progress=0,
            message="Waiting for data pipeline to complete...",
        )
        # Wait on _shutdown_event (not _pipeline_idle) so a shutdown signal
        # wakes this loop immediately rather than blocking the full 5 s timeout.
        _shutdown_event.wait(timeout=5)
    return False


def get_async_shutdown_event() -> asyncio.Event:
    """Get or create the async shutdown event."""
    global _async_shutdown_event
    if _async_shutdown_event is None:
        _async_shutdown_event = asyncio.Event()
        _async_shutdown_event.set()
    return _async_shutdown_event


def reset_async_shutdown_event() -> None:
    """Reset the async shutdown event (clear it) to allow async tasks to run."""
    global _async_shutdown_event
    if _async_shutdown_event is not None:
        _async_shutdown_event.clear()


def set_async_shutdown_event() -> None:
    """Set the async shutdown event to signal async tasks to stop."""
    global _async_shutdown_event
    if _async_shutdown_event is None:
        _async_shutdown_event = asyncio.Event()
    _async_shutdown_event.set()


def _is_first_run(worker: str) -> bool:
    """Return True if this worker has not yet completed its first-run sync.

    Uses key ``first_run.<worker>`` in SystemConfig.  If the key is absent it
    is created (value ``"True"``) and True is returned.  Thread-safe: a lock
    prevents two threads from both seeing the key as absent simultaneously.
    """
    if _first_run_completed_cache.get(worker):
        return False

    key = f"first_run.{worker}"
    with _first_run_lock:
        # Re-check inside lock in case another thread just set it.
        if _first_run_completed_cache.get(worker):
            return False
        try:
            with _SyncSessionLocal() as db:
                stmt = select(SystemConfig).where(SystemConfig.key == key)
                config = db.execute(stmt).scalar_one_or_none()
                if config is None:
                    db.add(SystemConfig(key=key, value="True"))
                    db.commit()
                    return True
                return config.value == "True"
        except Exception as e:
            logger.warning(f"Failed to check first_run for {worker}, defaulting to True: {e}")
            return True


def _set_first_run_complete(worker: str) -> None:
    """Mark this worker's first-run as complete.

    Sets ``first_run.<worker>`` to ``"False"`` in SystemConfig and caches the
    result in-process so subsequent calls are free.
    """
    if _first_run_completed_cache.get(worker):
        return

    key = f"first_run.{worker}"
    try:
        with _SyncSessionLocal() as db:
            stmt = select(SystemConfig).where(SystemConfig.key == key)
            config = db.execute(stmt).scalar_one_or_none()
            if config:
                config.value = "False"
            else:
                db.add(SystemConfig(key=key, value="False"))
            db.commit()
            _first_run_completed_cache[worker] = True
            logger.info(f"first_run flag set to False for worker: {worker}")
    except Exception as e:
        logger.warning(f"Failed to set first_run to False for {worker}: {e}")


def _sleep_interruptible(seconds: float) -> bool:
    """Sleep for up to `seconds`, returning True if interrupted by shutdown."""
    return _shutdown_event.wait(timeout=seconds)


_run_async_lock = threading.Lock()
_run_async_loops: dict[int, asyncio.AbstractEventLoop] = {}


def _run_async(coro):
    """
    Run an async coroutine using a persistent per-thread event loop.

    Reuses the same event loop across calls within the same worker thread,
    avoiding the overhead of creating + closing a fresh loop on every call.
    The Semaphore/Event objects in news_fetcher / market_data_fetcher are
    created at module load in the main thread and carried into the worker
    thread — using a per-thread loop ensures "bound to a different event
    loop" errors do not occur.

    NEVER call this from the main async event loop.
    """
    tid = threading.get_ident()
    with _run_async_lock:
        loop = _run_async_loops.get(tid)
        if loop is None or loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            _run_async_loops[tid] = loop
    return loop.run_until_complete(coro)


def _cleanup_run_async_loops() -> None:
    with _run_async_lock:
        for loop in _run_async_loops.values():
            try: loop.close()
            except Exception: pass
        _run_async_loops.clear()


def _seconds_until_next_cron(cron_expr: str) -> float:
    """Return seconds from now until the next fire time for the given cron expression.
    
    Evaluated strictly in Asia/Kolkata (IST) time to avoid timezone drift 
    when running on cloud/test servers set to UTC.

    Returns a large sentinel (24 hours) for @startup — that expression means
    'run once at startup then idle forever', so callers that mistakenly reach
    this helper should simply sleep a long time rather than crash.
    """
    if cron_expr == "@startup":
        return 86400.0  # 24 hours — effectively idle
    
    from croniter import croniter
    try:
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("Asia/Kolkata")).replace(tzinfo=None)
    except Exception:
        now = datetime.now()
        
    return (croniter(cron_expr, now).get_next(datetime) - now).total_seconds()


def _report_job_waiting(job_key: str, cron_expr: str | None, message: str | None = None) -> float:
    """Set job status to 'waiting' with a computed next_trigger_at, then return the
    number of seconds until the next cron fire for the caller to sleep.

    For ``@startup`` or ``None`` cron expressions, next_trigger_at is left NULL
    (manual-only / one-shot behaviour).
    """
    if cron_expr is None or cron_expr == "@startup":
        update_job_status_sync(job_key, "waiting", progress=100,
                               message=message or "Manual only")
        return 86400.0  # long idle

    wait_secs = _seconds_until_next_cron(cron_expr)
    next_trigger = datetime.now(timezone.utc) + timedelta(seconds=wait_secs)
    update_job_status_sync(
        job_key, "waiting", progress=100,
        message=message or f"Next run in {wait_secs / 3600:.1f}h",
        next_trigger=next_trigger,
    )
    return wait_secs
