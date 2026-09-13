"""SQLAlchemy ORM models for paper trading dummy positions."""

from datetime import datetime
from typing import List, Optional

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class PaperTrade(Base):
    """Master model for a paper trade position."""

    __tablename__ = "paper_trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="OPEN", index=True)  # OPEN, CLOSED
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

    legs: Mapped[List["PaperTradeLeg"]] = relationship(
        "PaperTradeLeg",
        back_populates="trade",
        cascade="all, delete-orphan",
        order_by="PaperTradeLeg.created_at.asc()",
    )


class PaperTradeLeg(Base):
    """Individual trade execution leg (initial buy, additional buys, or sells)."""

    __tablename__ = "paper_trade_legs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    paper_trade_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("paper_trades.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    action: Mapped[str] = mapped_column(String(8), nullable=False)  # BUY or SELL
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
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

    trade: Mapped["PaperTrade"] = relationship("PaperTrade", back_populates="legs")
