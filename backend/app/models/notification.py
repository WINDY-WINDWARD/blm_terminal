"""SQLAlchemy ORM model for watchlist stock notifications."""

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Notification(Base):
    """Persisted notification for a watchlist stock triggering a market event."""

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    watchlist_id: Mapped[int] = mapped_column(
        ForeignKey("watchlists.id", ondelete="CASCADE"), nullable=False
    )
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    exchange: Mapped[str] = mapped_column(String(16), default="NSE")
    trigger_type: Mapped[str] = mapped_column(String(32), nullable=False)
    message: Mapped[str] = mapped_column(String(256), nullable=False)
    triggered_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    triggered_date: Mapped[date] = mapped_column(Date, nullable=False)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "watchlist_id",
            "symbol",
            "trigger_type",
            "triggered_date",
            name="uq_notification_daily",
        ),
        Index("ix_notifications_watchlist_unread", "watchlist_id", "is_read"),
        Index("ix_notifications_triggered_date", "triggered_date"),
    )


class GlobalNotification(Base):
    """Persisted notification for global scan alerts (all NSE stocks)."""

    __tablename__ = "global_notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    exchange: Mapped[str] = mapped_column(String(16), default="NSE")
    trigger_type: Mapped[str] = mapped_column(String(32), nullable=False)
    message: Mapped[str] = mapped_column(String(256), nullable=False)
    triggered_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    triggered_date: Mapped[date] = mapped_column(Date, nullable=False)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "symbol",
            "trigger_type",
            "triggered_date",
            name="uq_global_notification_daily",
        ),
        Index("ix_global_notifications_unread", "is_read"),
        Index("ix_global_notifications_triggered_date", "triggered_date"),
        Index("ix_global_notifications_symbol", "symbol"),
    )
