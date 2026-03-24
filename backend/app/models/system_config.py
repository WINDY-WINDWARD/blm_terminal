"""SQLAlchemy ORM model for system configuration and sync state."""

from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SystemConfig(Base):
    """Key-value store for system state.
    
    Used to track:
    - last_full_fairvalue_sync: Timestamp of last full universe sync
    - last_watchlist_fairvalue_sync: Timestamp of last watchlist sync
    """

    __tablename__ = "system_config"

    key: Mapped[str] = mapped_column(String(64), primary_key=True, index=True)
    value: Mapped[str] = mapped_column(String(512), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
