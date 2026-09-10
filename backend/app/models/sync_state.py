"""SQLAlchemy ORM model for sync checkpoints and state resumability."""

from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SyncState(Base):
    """Tracks background sync progress cursors.

    Enables resumability: If a task or the entire process is aborted
    mid-way, background tasks read the last_symbol or cursor for the given
    task_name and resume from there.
    """

    __tablename__ = "sync_state"

    task_name: Mapped[str] = mapped_column(String(64), primary_key=True, index=True)
    last_symbol: Mapped[str] = mapped_column(String(50), nullable=True)
    cursor_info: Mapped[str] = mapped_column(String(256), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        default=func.now(),
        onupdate=func.now(),
    )
