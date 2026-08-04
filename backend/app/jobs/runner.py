"""Job runner for background task execution and tracking."""

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal, _SyncSessionLocal
from app.models.job import Job
from app.jobs.registry import JobRegistry

logger = logging.getLogger(__name__)


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
) -> None:
    """Update job status in database. Uses timezone-aware UTC datetime.
    
    Automatically sets last_triggered_at when status is 'running'
    and last_completed_at when status is 'idle' or 'waiting'.
    Automatically calculates next_trigger_at for interval-based jobs.
    """
    async with AsyncSessionLocal() as db:
        values: dict = {
            "status": status,
            "updated_at": datetime.now(timezone.utc),
        }
        
        # Auto-set timestamps based on status
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

        stmt = update(Job).where(Job.job_key == job_key).values(**values)
        await db.execute(stmt)
        await db.commit()


def update_job_status_sync(
    job_key: str,
    status: str,
    progress: int | None = None,
    message: str | None = None,
    error: str | None = None,
    last_completed: datetime | None = None,
    last_triggered: datetime | None = None,
    next_trigger: datetime | None = None,
) -> None:
    """Synchronous version of update_job_status for use in worker threads.
    
    Automatically sets last_triggered_at when status is 'running'
    and last_completed_at when status is 'idle' or 'waiting'.
    Automatically calculates next_trigger_at for interval-based jobs.

    Retries up to 3 times with brief exponential back-off on SQLite
    "database is locked" errors that can occur during the startup write-storm
    when many workers try to persist their initial status simultaneously.
    """
    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        try:
            with _SyncSessionLocal() as db:
                values: dict = {
                    "status": status,
                    "updated_at": datetime.now(timezone.utc),
                }

                # Auto-set timestamps based on status
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

                stmt = update(Job).where(Job.job_key == job_key).values(**values)
                db.execute(stmt)
                db.commit()
            return  # success — exit the retry loop
        except Exception as e:
            if attempt < max_attempts:
                wait = 0.5 * attempt  # 0.5 s, 1.0 s back-off
                logger.debug(
                    "update_job_status_sync: DB busy for %s (attempt %d/%d), retrying in %.1fs: %s",
                    job_key, attempt, max_attempts, wait, e,
                )
                time.sleep(wait)
            else:
                logger.warning("Failed to update job status for %s: %s", job_key, e)


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
            job.cron_expression = job_def.cron_expression
            job.is_manual_only = job_def.is_manual_only

        await db.commit()


async def sync_all_jobs_to_db() -> None:
    """Sync all registered jobs to database."""
    for job_def in JobRegistry.list_all():
        await sync_job_to_db(job_def.job_key)


def report_progress(job_key: str, percent: int, message: str) -> None:
    """Thread-safe progress update. Called from worker threads."""
    try:
        loop = asyncio.get_running_loop()
        loop.call_soon_threadsafe(
            lambda: update_job_status(job_key, "running", progress=percent, message=message)
        )
    except RuntimeError:
        pass


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
        )
        logger.info(f"Job {job_key} completed successfully")

    except Exception as e:
        logger.exception(f"Job {job_key} failed")
        await update_job_status(job_key, "failed", error=str(e)[:512])

    finally:
        JobRegistry.set_running(job_key, False)


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
        )
        logger.info(f"Job {job_key} completed successfully")

    except Exception as e:
        logger.exception(f"Job {job_key} failed")
        await update_job_status(job_key, "failed", error=str(e)[:512])
