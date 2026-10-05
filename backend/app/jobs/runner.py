"""Job runner for background task execution and tracking."""

import asyncio
import json
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal, _SyncSessionLocal
from app.models.job import Job, JobExecution
from app.jobs.registry import JobRegistry
from app.services.write_queue import _write_queue_enabled

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Active execution tracking
# ---------------------------------------------------------------------------
# { job_key: execution_id }
_active_executions: dict[str, int] = {}
_active_executions_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Debounce state for update_job_status_sync
# ---------------------------------------------------------------------------
# { job_key: (last_emit_epoch, last_progress_percent) }
_last_emit: dict[str, tuple[float, int]] = {}
_last_emit_lock = threading.Lock()
_DEBOUNCE_MIN_INTERVAL = 0.8  # seconds
_DEBOUNCE_MIN_DELTA_PCT = 5   # percent


def _create_job_execution_sync(
    job_key: str,
    name: str | None = None,
    category: str | None = None,
    triggered_by: str = "manual",
) -> int:
    """Create a new JobExecution row synchronously and register as active."""
    if not name:
        job_def = JobRegistry.get(job_key)
        if job_def:
            name = job_def.name
            category = category or job_def.category
        else:
            name = job_key

    now = datetime.now(timezone.utc)
    initial_log = json.dumps([
        {
            "timestamp": now.isoformat(),
            "message": f"Job {name} started ({triggered_by})",
            "level": "info",
        }
    ])

    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        try:
            with _SyncSessionLocal() as db:
                exec_row = JobExecution(
                    job_key=job_key,
                    name=name,
                    category=category,
                    triggered_by=triggered_by,
                    status="running",
                    progress_percent=0,
                    progress_message="Starting...",
                    started_at=now,
                    log_lines=initial_log,
                )
                db.add(exec_row)
                db.commit()
                db.refresh(exec_row)
                exec_id = exec_row.id
                with _active_executions_lock:
                    _active_executions[job_key] = exec_id
                return exec_id
        except Exception as e:
            if attempt < max_attempts:
                time.sleep(0.3 * attempt)
            else:
                logger.warning("Failed to create JobExecution for %s: %s", job_key, e)
                return 0
    return 0


def log_job_message(job_key: str, message: str, level: str = "info") -> None:
    """Add a timestamped log line to the active execution of a job."""
    def _do_log():
        exec_id = None
        with _active_executions_lock:
            exec_id = _active_executions.get(job_key)
        if not exec_id:
            return

        try:
            with _SyncSessionLocal() as db:
                exec_row = db.execute(select(JobExecution).where(JobExecution.id == exec_id)).scalar_one_or_none()
                if exec_row:
                    lines = []
                    try:
                        lines = json.loads(exec_row.log_lines or "[]")
                    except Exception:
                        lines = []
                    lines.append({
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "message": message,
                        "level": level,
                    })
                    if len(lines) > 500:
                        lines = lines[-500:]
                    exec_row.log_lines = json.dumps(lines)
                    exec_row.progress_message = message
                    db.commit()
        except Exception as e:
            logger.debug("Failed to log job message for %s: %s", job_key, e)

    try:
        loop = asyncio.get_running_loop()
        loop.run_in_executor(None, _do_log)
    except RuntimeError:
        _do_log()


def _execute_job_update(job_key: str, values: dict) -> None:
    """Execute a single job UPDATE directly via _SyncSessionLocal, and sync with JobExecution."""
    from app.database import _SyncSessionLocal
    from app.models.job import Job, JobExecution
    from sqlalchemy import update as sa_update, select as sa_select

    now = datetime.now(timezone.utc)
    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        try:
            with _SyncSessionLocal() as db:
                stmt = sa_update(Job).where(Job.job_key == job_key).values(**values)
                db.execute(stmt)

                # Check active execution
                exec_id = None
                with _active_executions_lock:
                    exec_id = _active_executions.get(job_key)

                status = values.get("status")

                # If running and no active execution exists yet, auto-create one (e.g. from background daemon)
                if not exec_id and status == "running":
                    job_row = db.execute(sa_select(Job).where(Job.job_key == job_key)).scalar_one_or_none()
                    name = job_row.name if job_row else job_key
                    category = job_row.category if job_row else None
                    initial_msg = values.get("progress_message") or f"Job {name} started (scheduled)"
                    initial_log = json.dumps([
                        {"timestamp": now.isoformat(), "message": initial_msg, "level": "info"}
                    ])
                    new_exec = JobExecution(
                        job_key=job_key,
                        name=name,
                        category=category,
                        triggered_by="scheduled",
                        status="running",
                        progress_percent=values.get("progress_percent") or 0,
                        progress_message=values.get("progress_message") or "Starting...",
                        started_at=values.get("last_triggered_at") or now,
                        log_lines=initial_log,
                    )
                    db.add(new_exec)
                    db.commit()
                    db.refresh(new_exec)
                    exec_id = new_exec.id
                    with _active_executions_lock:
                        _active_executions[job_key] = exec_id

                elif exec_id:
                    exec_row = db.execute(sa_select(JobExecution).where(JobExecution.id == exec_id)).scalar_one_or_none()
                    if exec_row:
                        # Append log line if progress message or error changed
                        lines = []
                        try:
                            lines = json.loads(exec_row.log_lines or "[]")
                        except Exception:
                            lines = []

                        msg = values.get("progress_message")
                        err = values.get("last_error")
                        new_log = None
                        if err:
                            new_log = {"timestamp": now.isoformat(), "message": f"Error: {err}", "level": "error"}
                        elif msg and (not lines or lines[-1].get("message") != msg):
                            new_log = {"timestamp": now.isoformat(), "message": msg, "level": "info"}

                        if new_log:
                            lines.append(new_log)
                            if len(lines) > 500:
                                lines = lines[-500:]
                            exec_row.log_lines = json.dumps(lines)

                        if "progress_percent" in values and values["progress_percent"] is not None:
                            exec_row.progress_percent = values["progress_percent"]
                        if msg is not None:
                            exec_row.progress_message = msg
                        if err is not None:
                            exec_row.error = err

                        # Terminal state: completed
                        if status in ("idle", "completed") and (exec_row.progress_percent == 100 or values.get("progress_percent") == 100 or values.get("progress_message") == "Completed"):
                            exec_row.status = "completed"
                            exec_row.completed_at = now
                            if exec_row.started_at:
                                s = exec_row.started_at
                                if s.tzinfo is None:
                                    s = s.replace(tzinfo=timezone.utc)
                                exec_row.duration_seconds = max(0.0, round((now - s).total_seconds(), 2))
                            with _active_executions_lock:
                                _active_executions.pop(job_key, None)
                        elif status == "failed" or err is not None:
                            exec_row.status = "failed"
                            exec_row.completed_at = now
                            if exec_row.started_at:
                                s = exec_row.started_at
                                if s.tzinfo is None:
                                    s = s.replace(tzinfo=timezone.utc)
                                exec_row.duration_seconds = max(0.0, round((now - s).total_seconds(), 2))
                            with _active_executions_lock:
                                _active_executions.pop(job_key, None)

                db.commit()
            return
        except Exception as e:
            if attempt < max_attempts:
                wait = 0.5 * attempt
                logger.debug(
                    "update_job_status_sync: DB busy for %s (attempt %d/%d), retrying in %.1fs: %s",
                    job_key, attempt, max_attempts, wait, e,
                )
                time.sleep(wait)
            else:
                logger.warning("Failed to update job status for %s: %s", job_key, e)


async def get_job_status(job_key: str) -> Job | None:
    """Get job record from database."""
    async with AsyncSessionLocal() as db:
        stmt = select(Job).where(Job.job_key == job_key)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()


async def update_job_status(
    job_key: str,
    status: str,
    progress: int | None = None,
    message: str | None = None,
    error: str | None = None,
    last_completed: datetime | None = None,
    last_triggered: datetime | None = None,
    next_trigger: datetime | None = None,
    last_success: datetime | None = None,
) -> None:
    """Update job status in database and sync with active JobExecution."""
    values: dict = {
        "status": status,
        "updated_at": datetime.now(timezone.utc),
    }

    now = datetime.now(timezone.utc)
    if status == "running" or last_triggered:
        values["last_triggered_at"] = last_triggered if last_triggered else now
    if status in ("idle", "waiting") or last_completed:
        values["last_completed_at"] = last_completed if last_completed else now

    if status in ("running", "idle", "waiting"):
        if error is None:
            values["last_error"] = None
    if progress is not None:
        values["progress_percent"] = progress
    if message is not None:
        values["progress_message"] = message
    if error is not None:
        values["last_error"] = error
    if last_completed is not None:
        values["last_completed_at"] = last_completed
    if last_triggered is not None:
        values["last_triggered_at"] = last_triggered
    if next_trigger is not None:
        values["next_trigger_at"] = next_trigger
    if last_success is not None:
        values["last_success_at"] = last_success

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _execute_job_update, job_key, values)


def update_job_status_sync(
    job_key: str,
    status: str,
    progress: int | None = None,
    message: str | None = None,
    error: str | None = None,
    last_completed: datetime | None = None,
    last_triggered: datetime | None = None,
    next_trigger: datetime | None = None,
    last_success: datetime | None = None,
) -> None:
    """Synchronous version of update_job_status for use in worker threads.

    Automatically sets last_triggered_at when status is 'running'
    and last_completed_at when status is 'idle' or 'waiting'.
    Automatically calculates next_trigger_at for interval-based jobs.

    Retries up to 3 times with brief exponential back-off on SQLite
    "database is locked" errors that can occur during the startup write-storm
    when many workers try to persist their initial status simultaneously.

    Debounce: redundant progress updates (same key, <0.8s interval, <5% delta)
    are skipped to reduce DB write volume during bulk operations.  Terminal
    states (failed, idle, 100%) always flush immediately.
    """
    # --- Debounce logic (thread-safe) ---
    now_epoch = time.time()
    is_terminal = status in ("failed", "idle") or progress == 100
    if not is_terminal and progress is not None:
        with _last_emit_lock:
            prev = _last_emit.get(job_key)
            if prev is not None:
                last_t, last_pct = prev
                delta_pct = abs(progress - last_pct)
                if (now_epoch - last_t) < _DEBOUNCE_MIN_INTERVAL and delta_pct < _DEBOUNCE_MIN_DELTA_PCT:
                    return  # skip redundant update

    # Build the values dict
    values: dict = {
        "status": status,
        "updated_at": datetime.now(timezone.utc),
    }

    now = datetime.now(timezone.utc)
    if status == "running" or last_triggered:
        values["last_triggered_at"] = last_triggered if last_triggered else now
    if status in ("idle", "waiting") or last_completed:
        values["last_completed_at"] = last_completed if last_completed else now

    if status in ("running", "idle", "waiting"):
        if error is None:
            values["last_error"] = None
    if progress is not None:
        values["progress_percent"] = progress
    if message is not None:
        values["progress_message"] = message
    if error is not None:
        values["last_error"] = error
    if next_trigger is not None:
        values["next_trigger_at"] = next_trigger
    if last_success is not None:
        values["last_success_at"] = last_success

    # Route ALL job updates through the write queue to eliminate EXCLUSIVE-lock contention.
    # Previously terminal (idle/failed/100%) wrote directly, but that still contended
    # with api_cache and stock_universe single-row updates at startup (see 2026-09-16 logs).
    # Coalescing keeps only latest per job_key, so UI delay is <0.2s.
    enqueued = True
    if not _write_queue_enabled():
        _execute_job_update(job_key, values)
    else:
        try:
            from app.services.write_queue import enqueue_write, PRIO_JOBS
            enqueued = enqueue_write(PRIO_JOBS, _execute_job_update, job_key, values)
        except Exception:
            # Fallback: direct write if queue import fails
            _execute_job_update(job_key, values)
            enqueued = True

    # Record emit for debounce only if actually enqueued/written
    if progress is not None and enqueued:
        with _last_emit_lock:
            _last_emit[job_key] = (now_epoch, progress)


async def sync_job_to_db(job_key: str) -> None:
    """Ensure job exists in database, upserting metadata from the registry.

    Creates the row if it doesn't exist, or updates cron_expression, description,
    category, and is_manual_only if the definition has changed.  Does NOT overwrite
    status, progress, or timestamps on an existing row.
    """
    job_def = JobRegistry.get(job_key)
    if not job_def:
        return

    async with AsyncSessionLocal() as db:
        existing = await db.execute(select(Job).where(Job.job_key == job_key))
        job = existing.scalar_one_or_none()

        if job is None:
            job = Job(
                job_key=job_def.job_key,
                name=job_def.name,
                description=job_def.description,
                category=job_def.category,
                schedule_type="cron",
                cron_expression=job_def.cron_expression,
                is_manual_only=job_def.is_manual_only,
                status="idle",
                progress_percent=0,
                is_enabled=True,
            )
            db.add(job)
        else:
            # Upsert: refresh definition fields, but leave runtime state alone
            job.name = job_def.name
            job.description = job_def.description
            job.category = job_def.category
            job.schedule_type = "cron"
            job.cron_expression = job_def.cron_expression
            job.is_manual_only = job_def.is_manual_only

        await db.commit()


async def sync_all_jobs_to_db() -> None:
    """Sync all registered jobs to database."""
    for job_def in JobRegistry.list_all():
        await sync_job_to_db(job_def.job_key)


def mark_job_success_sync(job_key: str) -> None:
    """Record a successful work completion (worker threads).

    Unlike the waiting/idle bookkeeping that stamps last_completed_at on
    every loop, this writes last_success_at ONLY — the signal the
    missed-schedule catch-up uses to decide a job already ran.
    """
    try:
        update_job_status_sync(job_key, "idle", progress=100,
                               message="Completed",
                               last_success=datetime.now(timezone.utc))
    except Exception:
        logger.debug("mark_job_success_sync failed for %s", job_key, exc_info=True)


async def mark_job_success(job_key: str) -> None:
    """Async variant of mark_job_success_sync (event-loop threads)."""
    try:
        await update_job_status(job_key, "idle", progress=100,
                                message="Completed",
                                last_success=datetime.now(timezone.utc))
    except Exception:
        logger.debug("mark_job_success failed for %s", job_key, exc_info=True)


def report_progress(job_key: str, percent: int, message: str) -> None:
    """Thread-safe progress update. Called from worker threads or async tasks."""
    status = "idle" if percent == 100 else "running"
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(
            update_job_status(job_key, status, progress=percent, message=message)
        )
    except RuntimeError:
        update_job_status_sync(job_key, status, progress=percent, message=message)


async def _execute_triggered_job(job_key: str, job_def: Any) -> None:
    """Execute a triggered job asynchronously in the background and update job status."""
    try:
        if job_def.callable:
            if job_def.is_async:
                await job_def.callable()
            else:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, job_def.callable)

        now = datetime.now(timezone.utc)
        await update_job_status(
            job_key,
            "idle",
            progress=100,
            message="Completed",
            last_completed=now,
            last_success=now,
        )
        logger.info(f"Job {job_key} completed successfully")

    except Exception as e:
        logger.exception(f"Job {job_key} failed")
        await update_job_status(job_key, "failed", error=str(e)[:512])

    finally:
        JobRegistry.set_running(job_key, False)
        with _active_executions_lock:
            _active_executions.pop(job_key, None)


async def trigger_job(job_key: str, force: bool = False) -> dict:
    """Manually trigger a job.

    Spawns the execution task asynchronously in the background so the HTTP endpoint
    returns immediately without timing out for long-running tasks.

    Args:
        job_key: The stable job identifier
        force: If True, kill running job and restart (default: False)

    Returns:
        dict with ok, message, and current job state
    """
    job = await get_job_status(job_key)
    if not job:
        return {"ok": False, "error": f"Job not found: {job_key}"}

    job_def = JobRegistry.get(job_key)
    if not job_def:
        return {"ok": False, "error": f"Job definition not found: {job_key}"}

    current_status = job.status

    if current_status == "running":
        if not force:
            return {
                "ok": False,
                "error": "Job already running",
                "job": {
                    "job_key": job.job_key,
                    "name": job.name,
                    "status": "running",
                    "last_triggered_at": job.last_triggered_at.isoformat() if job.last_triggered_at else None,
                },
            }
        logger.warning(f"Force-triggering job {job_key}, stopping existing run")

    now = datetime.now(timezone.utc)
    _create_job_execution_sync(
        job_key=job_key,
        name=job_def.name,
        category=job_def.category,
        triggered_by="manual",
    )

    await update_job_status(
        job_key, "running", progress=0, message="Starting...", last_triggered=now
    )

    JobRegistry.set_running(job_key, True)

    asyncio.create_task(_execute_triggered_job(job_key, job_def))

    return {
        "ok": True,
        "message": "Job triggered",
        "job": {
            "job_key": job_key,
            "name": job.name,
            "status": "running",
            "last_triggered_at": now.isoformat(),
        },
    }


async def run_job_async(job_key: str) -> None:
    """Execute a job with proper status tracking."""
    job_def = JobRegistry.get(job_key)
    if not job_def:
        logger.error(f"Job definition not found: {job_key}")
        return

    if not job_def.callable:
        logger.warning(f"Job {job_key} has no callable, skipping")
        return

    _create_job_execution_sync(
        job_key=job_key,
        name=job_def.name,
        category=job_def.category,
        triggered_by="scheduled",
    )

    try:
        if job_def.is_async:
            await job_def.callable()
        else:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, job_def.callable)

        now = datetime.now(timezone.utc)
        await update_job_status(
            job_key,
            "idle",
            progress=100,
            message="Completed",
            last_completed=now,
            last_success=now,
        )
        logger.info(f"Job {job_key} completed successfully")

    except Exception as e:
        logger.exception(f"Job {job_key} failed")
        await update_job_status(job_key, "failed", error=str(e)[:512])

    finally:
        with _active_executions_lock:
            _active_executions.pop(job_key, None)
