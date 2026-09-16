"""FastAPI router for jobs API."""

import asyncio
import os
from pathlib import Path
from typing import AsyncGenerator, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_admin_user
from app.config import settings
from app.database import get_db
from app.models.job import Job
from app.schemas.job import (
    JobStatus,
    JobListResponse,
    JobTriggerResponse,
    JobToggleRequest,
    JobToggleResponse,
)
from app.jobs.runner import trigger_job, sync_all_jobs_to_db
from app.jobs.registry import JobRegistry, JobDefinition

router = APIRouter(dependencies=[Depends(get_admin_user)])


@router.get("/jobs", response_model=JobListResponse, tags=["jobs"])
async def list_jobs(db: AsyncSession = Depends(get_db)) -> JobListResponse:
    """List all registered jobs with their current status."""
    await sync_all_jobs_to_db()

    stmt = select(Job).order_by(Job.name)
    result = await db.execute(stmt)
    jobs = result.scalars().all()

    return JobListResponse(jobs=[JobStatus.model_validate(j) for j in jobs])


@router.get("/jobs/{job_key}", response_model=JobStatus, tags=["jobs"])
async def get_job(job_key: str, db: AsyncSession = Depends(get_db)) -> JobStatus:
    """Get a specific job by job_key."""
    stmt = select(Job).where(Job.job_key == job_key)
    result = await db.execute(stmt)
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_key}")

    return JobStatus.model_validate(job)


@router.post("/jobs/{job_key}/trigger", response_model=JobTriggerResponse, tags=["jobs"])
async def trigger_job_endpoint(
    job_key: str,
    force: bool = Query(False, description="Force restart if job is running"),
    db: AsyncSession = Depends(get_db),
) -> JobTriggerResponse:
    """Manually trigger a job to run immediately."""
    job = await db.execute(select(Job).where(Job.job_key == job_key))
    job = job.scalar_one_or_none()

    if not job:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_key}")

    result = await trigger_job(job_key, force=force)

    if not result.get("ok"):
        return JobTriggerResponse(
            ok=False,
            message=result.get("error", "Unknown error"),
            error=result.get("error"),
        )

    updated_job = await db.execute(select(Job).where(Job.job_key == job_key))
    updated_job = updated_job.scalar_one_or_none()

    return JobTriggerResponse(
        ok=True,
        message=result.get("message", "Job triggered"),
        job=JobStatus.model_validate(updated_job) if updated_job else None,
    )


@router.post("/jobs/{job_key}/toggle", response_model=JobToggleResponse, tags=["jobs"])
async def toggle_job(
    job_key: str,
    request: JobToggleRequest,
    db: AsyncSession = Depends(get_db),
) -> JobToggleResponse:
    """Enable or disable a job."""
    stmt = select(Job).where(Job.job_key == job_key)
    result = await db.execute(stmt)
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_key}")

    stmt = (
        update(Job)
        .where(Job.job_key == job_key)
        .values(is_enabled=request.enabled)
    )
    await db.execute(stmt)
    await db.commit()

    stmt = select(Job).where(Job.job_key == job_key)
    result = await db.execute(stmt)
    updated_job = result.scalar_one_or_none()

    return JobToggleResponse(
        ok=True,
        job=JobStatus.model_validate(updated_job) if updated_job else None,
    )


@router.post("/jobs/sync", tags=["jobs"])
async def sync_jobs() -> dict:
    """Manually sync jobs to database."""
    await sync_all_jobs_to_db()
    return {"ok": True, "message": "Jobs synced"}


def _resolve_log_file() -> Path:
    """Resolve the backend log file path using the same logic as _configure_logging()."""
    if settings.log_dir:
        log_dir = Path(settings.log_dir)
    else:
        log_dir = Path(__file__).resolve().parent.parent.parent / "logs"
    return log_dir / "backend.log"


@router.get("/jobs/logs/stream", tags=["jobs"])
async def stream_logs(
    request: Request,
    lines: int = Query(200, description="Number of tail lines to send on connect", ge=1, le=2000),
) -> StreamingResponse:
    """Stream backend log file as Server-Sent Events.

    Sends the last `lines` lines on connect, then tails the file live.
    Each SSE event is a single log line: ``data: <line>\\n\\n``.
    The stream ends when the client disconnects.
    """
    log_file = _resolve_log_file()

    async def event_generator() -> AsyncGenerator[str, None]:
        # Send initial tail lines if the file exists
        if log_file.exists():
            try:
                with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                    all_lines = f.readlines()
                for line in all_lines[-lines:]:
                    stripped = line.rstrip("\n\r")
                    if stripped:
                        yield f"data: {stripped}\n\n"
                # Seek to end for live tail
                file_pos = log_file.stat().st_size
            except OSError:
                file_pos = 0
        else:
            yield "data: [log file not found — backend may not have written any logs yet]\n\n"
            file_pos = 0

        # Live tail: poll for new content every 0.5 s
        while not await request.is_disconnected():
            try:
                current_size = log_file.stat().st_size if log_file.exists() else 0
                if current_size > file_pos:
                    with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                        f.seek(file_pos)
                        new_content = f.read()
                    file_pos = current_size
                    for line in new_content.splitlines():
                        if line.strip():
                            yield f"data: {line}\n\n"
                elif current_size < file_pos:
                    # File was rotated — reset to start of new file
                    file_pos = 0
                    yield "data: [log rotated]\n\n"
            except OSError:
                pass
            await asyncio.sleep(0.5)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/jobs/write-queue/stats", tags=["jobs"])
async def write_queue_stats() -> dict:
    """Return write queue health stats for the jobs health tab."""
    from app.services.write_queue import get_stats
    return get_stats()


@router.get("/jobs/db-stats/live", tags=["jobs"])
async def db_stats_live() -> dict:
    """Live DB-stats snapshot for the Jobs → DB Stats tab.

    Cheap and non-blocking: all queue metrics are in-memory, DB size comes
    from file stat() — no SQL is executed, so polling this every 2s never
    contends with real DB operations.
    """
    from app.services.write_queue import get_db_stats
    return get_db_stats()


@router.get("/jobs/db-stats/alerts", tags=["jobs"])
async def db_stats_alerts(
    limit: int = Query(100, ge=1, le=500, description="Max alerts to return"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Persisted silent DB alert events (newest first) with frozen snapshots."""
    import json as _json

    from app.models.db_alert import DbAlert

    stmt = (
        select(DbAlert)
        .order_by(DbAlert.ts.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    alerts = []
    for row in rows:
        try:
            snapshot = _json.loads(row.snapshot_json) if row.snapshot_json else {}
        except Exception:
            snapshot = {}
        alerts.append({
            "id": row.id,
            "ts": row.ts,
            "type": row.type,
            "severity": row.severity,
            "message": row.message,
            "snapshot": snapshot,
        })
    return {"alerts": alerts, "total": len(alerts)}
