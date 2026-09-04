"""SQLAlchemy ORM model for user layout preferences."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class UserLayout(Base):
    """Persisted terminal UI layout configuration for a user."""

    __tablename__ = "user_layouts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    active_panels: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    panel_count: Mapped[int] = mapped_column(Integer, nullable=False)
    merged_groups: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    saved_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    deleted_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        default=func.now(),
        onupdate=func.now(),
    )

    user = relationship("User", backref="user_layouts")

    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_user_layout_name"),
    )
