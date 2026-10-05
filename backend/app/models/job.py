"""SQLAlchemy ORM model for background job tracking."""

from datetime import datetime, timezone

from sqlalchemy import DateTime, Index, Integer, String, Boolean, Float, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Job(Base):
    """Tracks background job status, progress, and scheduling."""

    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(String(256))
    category: Mapped[str] = mapped_column(String(32))
    schedule_type: Mapped[str] = mapped_column(String(16))
    interval_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cron_expression: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Written ONLY on successful work completion (pipeline stages, triggered
    # runs, daemon syncs) — never by waiting/idle bookkeeping. Drives the
    # missed-schedule catch-up. last_completed_at cannot serve this: daemons
    # stamp it on every waiting/idle transition.
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_trigger_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="idle")
    progress_percent: Mapped[int] = mapped_column(Integer, default=0)
    progress_message: Mapped[str | None] = mapped_column(String(128), nullable=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    is_manual_only: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(), onupdate=lambda: datetime.now())

    __table_args__ = (
        Index("ix_jobs_name", "name"),
        Index("ix_jobs_status", "status"),
        Index("ix_jobs_next_trigger_at", "next_trigger_at"),
    )


class JobExecution(Base):
    """Tracks a single run/execution of a background job with logs and timings."""

    __tablename__ = "job_executions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_key: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    category: Mapped[str | None] = mapped_column(String(32), nullable=True)
    triggered_by: Mapped[str] = mapped_column(String(32), default="manual")  # manual | scheduled
    status: Mapped[str] = mapped_column(String(32), default="running")  # running | completed | failed
    progress_percent: Mapped[int] = mapped_column(Integer, default=0)
    progress_message: Mapped[str | None] = mapped_column(String(256), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    error: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    log_lines: Mapped[str] = mapped_column(Text, default="[]")  # JSON string of [{"timestamp": "...", "message": "...", "level": "..."}]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index("ix_job_executions_job_key", "job_key"),
        Index("ix_job_executions_status", "status"),
        Index("ix_job_executions_started_at", "started_at"),
    )
