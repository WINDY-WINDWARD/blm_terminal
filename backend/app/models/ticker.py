"""SQLALCHEMY ORM MODEL for NSE daily OHLCV ticker warehouse"""

from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Float, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class TickerDaily(Base):
    """ORM model for daily OHLCV tick data from NSE."""

    __tablename__ = "ticker_daily"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    series: Mapped[str] = mapped_column(String(4), nullable=False, server_default="EQ")
    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[int] = mapped_column(BigInteger, nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        UniqueConstraint("symbol", "date", "series", name="uq_ticker_symbol_date_series"),
    )