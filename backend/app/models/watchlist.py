"""SQLAlchemy ORM model for the user watchlist."""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class WatchlistItem(Base):
    """Persisted watchlist entry: one row per (symbol, exchange) pair."""

    __tablename__ = "watchlist_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    exchange: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        UniqueConstraint("symbol", "exchange", name="uq_watchlist_symbol_exchange"),
    )
