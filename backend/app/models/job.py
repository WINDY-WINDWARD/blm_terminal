"""SQLAlchemy ORM model for background job tracking."""

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Boolean
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
