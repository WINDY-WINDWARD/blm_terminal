"""Pydantic schemas for job tracking."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class JobBase(BaseModel):
    """Base job schema."""

    job_key: str
    name: str
    description: Optional[str] = None
    category: Optional[str] = None
    schedule_type: Optional[str] = None
    interval_seconds: Optional[int] = None
    cron_expression: Optional[str] = None
    is_enabled: bool = True
    is_manual_only: bool = False


class JobStatus(BaseModel):
    """Job status schema for API responses."""

    job_key: str
    name: str
    description: Optional[str] = None
    category: Optional[str] = None
    cron_expression: Optional[str] = None
    status: str
    progress_percent: int = 0
    progress_message: Optional[str] = None
    last_triggered_at: Optional[datetime] = None
    last_completed_at: Optional[datetime] = None
    next_trigger_at: Optional[datetime] = None
    last_error: Optional[str] = None
    is_enabled: bool = True
    is_manual_only: bool = False

    class Config:
        from_attributes = True


class JobListResponse(BaseModel):
    """Response for listing all jobs."""

    jobs: list[JobStatus]


class JobTriggerResponse(BaseModel):
    """Response for triggering a job."""

    ok: bool
    message: str
    job: Optional[JobStatus] = None
    error: Optional[str] = None


class JobToggleRequest(BaseModel):
    """Request for toggling job enabled state."""

    enabled: bool


class JobToggleResponse(BaseModel):
    """Response for toggling a job."""

    ok: bool
    job: Optional[JobStatus] = None


class JobExecutionResponse(BaseModel):
    """Response schema for a single job execution run."""

    id: int
    job_key: str
    name: str
    category: Optional[str] = None
    triggered_by: str
    status: str
    progress_percent: int = 0
    progress_message: Optional[str] = None
    started_at: datetime
    completed_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    error: Optional[str] = None
    log_lines: list[dict] = []
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class JobExecutionListResponse(BaseModel):
    """Response for paginated list of job executions."""

    total: int
    executions: list[JobExecutionResponse]

