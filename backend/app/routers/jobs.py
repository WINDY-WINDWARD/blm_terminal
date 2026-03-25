"""FastAPI router for jobs API."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

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

router = APIRouter()


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
