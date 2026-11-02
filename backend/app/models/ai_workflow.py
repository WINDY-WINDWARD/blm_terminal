"""SQLAlchemy ORM models for scheduled AI workflows, runs, and custom prompts."""

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class AiWorkflow(Base):
    """A scheduled automated AI workflow task."""

    __tablename__ = "ai_workflows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(String(240), nullable=True)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    schedule_type: Mapped[str] = mapped_column(String(16), nullable=False, default="daily")
    cron_expression: Mapped[str] = mapped_column(String(64), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Kolkata")
    time_of_day: Mapped[str | None] = mapped_column(String(5), nullable=True)
    days_of_week: Mapped[str | None] = mapped_column(String(32), nullable=True)
    once_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    symbols_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    watchlist_id: Mapped[int | None] = mapped_column(ForeignKey("watchlists.id", ondelete="SET NULL"), nullable=True)
    model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    persona: Mapped[str | None] = mapped_column(String(16), nullable=True)
    mode: Mapped[str] = mapped_column(String(16), nullable=False, default="research")
    allow_write_tools: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    catch_up_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    catch_up_window_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=12)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    last_slot_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utcnow, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utcnow, onupdate=utcnow, server_default=func.now(), nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)

    __table_args__ = (
        Index("ix_ai_workflows_user_enabled_next", "user_id", "is_enabled", "next_run_at"),
    )

    runs: Mapped[list["AiWorkflowRun"]] = relationship(
        "AiWorkflowRun",
        back_populates="workflow",
        cascade="all, delete-orphan",
    )


class AiWorkflowRun(Base):
    """An execution run of an AI workflow."""

    __tablename__ = "ai_workflow_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workflow_id: Mapped[int] = mapped_column(
        ForeignKey("ai_workflows.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    trigger: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")
    skip_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    slot_key: Mapped[str] = mapped_column(String(80), nullable=False)
    prompt_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)
    name_snapshot: Mapped[str | None] = mapped_column(String(120), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    session_id: Mapped[int | None] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="SET NULL"), nullable=True
    )
    output_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_summary: Mapped[str | None] = mapped_column(String(512), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_silent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utcnow, server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("workflow_id", "slot_key", name="uq_ai_workflow_run_slot"),
        Index("ix_ai_workflow_runs_user_unread", "user_id", "is_read", "created_at"),
        Index("ix_ai_workflow_runs_workflow_created", "workflow_id", "created_at"),
    )

    workflow: Mapped[AiWorkflow] = relationship("AiWorkflow", back_populates="runs")


class AiCustomPrompt(Base):
    """User-authored prompt template for AI workflows and chat."""

    __tablename__ = "ai_custom_prompts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(80), nullable=False)
    tag: Mapped[str] = mapped_column(String(48), nullable=False)
    description: Mapped[str | None] = mapped_column(String(240), nullable=True)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    icon: Mapped[str | None] = mapped_column(String(8), nullable=True)
    mode: Mapped[str] = mapped_column(String(16), nullable=False, default="research")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    use_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utcnow, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=utcnow, onupdate=utcnow, server_default=func.now(), nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)

    __table_args__ = (
        Index("ix_ai_custom_prompts_user_mode_order", "user_id", "mode", "sort_order"),
    )
