"""SQLAlchemy ORM models for BLM Script Lab (user chart scripts)."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class SavedScript(Base):
    """Named user/builtin chart script; head_rev_id points at the live revision."""

    __tablename__ = "saved_scripts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(String(280), nullable=False, default="")
    is_builtin: Mapped[bool] = mapped_column(nullable=False, default=False)
    head_rev_id: Mapped[int | None] = mapped_column(
        ForeignKey("script_revisions.id", ondelete="SET NULL", use_alter=True, name="fk_saved_scripts_head_rev"),
        nullable=True,
        default=None,
    )
    deleted_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False, default=func.now(), onupdate=func.now()
    )

    user = relationship("User", backref="saved_scripts")
    revisions = relationship(
        "ScriptRevision",
        back_populates="script",
        cascade="all, delete-orphan",
        foreign_keys="ScriptRevision.script_id",
        order_by="ScriptRevision.rev_no",
    )

    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_saved_scripts_user_name"),
    )


class ScriptRevision(Base):
    """Immutable snapshot of one script version (manifest + code)."""

    __tablename__ = "script_revisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    script_id: Mapped[int] = mapped_column(ForeignKey("saved_scripts.id", ondelete="CASCADE"), nullable=False)
    rev_no: Mapped[int] = mapped_column(Integer, nullable=False)
    manifest: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str] = mapped_column(String(280), nullable=False, default="")
    chat_session_id: Mapped[int | None] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="SET NULL"), nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, default=func.now())

    script = relationship(
        "SavedScript", back_populates="revisions", foreign_keys=[script_id]
    )

    __table_args__ = (
        UniqueConstraint("script_id", "rev_no", name="uq_script_revisions_script_rev"),
    )


class ScriptChartState(Base):
    """Per-user, per-panel enablement + param overrides for a script."""

    __tablename__ = "script_chart_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    panel_id: Mapped[str] = mapped_column(String(64), nullable=False)
    script_id: Mapped[int] = mapped_column(ForeignKey("saved_scripts.id", ondelete="CASCADE"), nullable=False)
    enabled: Mapped[bool] = mapped_column(nullable=False, default=True)
    param_values: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    added_at: Mapped[int] = mapped_column(BigInteger, nullable=False)

    user = relationship("User", backref="script_chart_states")
    script = relationship("SavedScript")

    __table_args__ = (
        UniqueConstraint("user_id", "panel_id", "script_id", name="uq_script_chart_state_slot"),
    )
