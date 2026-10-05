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
from app.models.job import Job, JobExecution
from app.schemas.job import (
    JobStatus,
    JobListResponse,
    JobTriggerResponse,
    JobToggleRequest,
    JobToggleResponse,
    JobExecutionResponse,
    JobExecutionListResponse,
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


def _format_execution(exc: JobExecution) -> JobExecutionResponse:
    import json
    logs = []
    if exc.log_lines:
        try:
            logs = json.loads(exc.log_lines) if isinstance(exc.log_lines, str) else exc.log_lines
        except Exception:
            logs = []
    return JobExecutionResponse(
        id=exc.id,
        job_key=exc.job_key,
        name=exc.name,
        category=exc.category,
        triggered_by=exc.triggered_by,
        status=exc.status,
        progress_percent=exc.progress_percent,
        progress_message=exc.progress_message,
        started_at=exc.started_at,
        completed_at=exc.completed_at,
        duration_seconds=exc.duration_seconds,
        error=exc.error,
        log_lines=logs,
        created_at=exc.created_at,
    )


@router.get("/jobs/executions", response_model=JobExecutionListResponse, tags=["jobs"])
async def list_job_executions(
    job_key: Optional[str] = Query(None, description="Filter by job_key"),
    limit: int = Query(50, ge=1, le=200, description="Max records to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    db: AsyncSession = Depends(get_db),
) -> JobExecutionListResponse:
    """List historical and active job executions, sorted newest first."""
    from sqlalchemy import func

    count_stmt = select(func.count(JobExecution.id))
    if job_key:
        count_stmt = count_stmt.where(JobExecution.job_key == job_key)
    total = (await db.execute(count_stmt)).scalar() or 0

    stmt = select(JobExecution).order_by(JobExecution.started_at.desc())
    if job_key:
        stmt = stmt.where(JobExecution.job_key == job_key)
    stmt = stmt.offset(offset).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()

    return JobExecutionListResponse(
        total=total,
        executions=[_format_execution(r) for r in rows],
    )


@router.get("/jobs/executions/{execution_id}", response_model=JobExecutionResponse, tags=["jobs"])
async def get_job_execution(
    execution_id: int,
    db: AsyncSession = Depends(get_db),
) -> JobExecutionResponse:
    """Get single job execution details including log lines."""
    stmt = select(JobExecution).where(JobExecution.id == execution_id)
    exc = (await db.execute(stmt)).scalar_one_or_none()
    if not exc:
        raise HTTPException(status_code=404, detail="Execution not found")

    return _format_execution(exc)


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
