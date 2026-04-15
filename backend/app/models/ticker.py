"""SQLALCHEMY ORM MODEL for NSE daily OHLCV ticker warehouse"""

from datetime import date, datetime
from typing import Optional

from sqlalchemy import BigInteger, Date, DateTime, Float, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class TickerDaily(Base):
    """ORM model for daily OHLCV tick data from NSE.

    Indicator columns (rsi_14 … indicators_updated_at) are nullable and
    populated by the indicator backfill / nightly update jobs.  Early candles
    that have insufficient historical lookback will have NULL values.
    """

    __tablename__ = "ticker_daily"

    # --- core identity ---
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    series: Mapped[str] = mapped_column(String(4), nullable=False, server_default="EQ")

    # --- OHLCV ---
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

    # --- Technical indicators (computed nightly, NULL until first backfill) ---
    rsi_14: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    macd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    macd_signal: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    macd_histogram: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    bb_middle: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    bb_upper: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    bb_lower: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    bb_width: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # "Y" = squeeze active, "N" = no squeeze, NULL = not yet computed
    bb_squeeze: Mapped[Optional[str]] = mapped_column(String(1), nullable=True)
    atr_14: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    atr_percent: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    vwma_20: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    hv_20: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    hv_60: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    sharpe_60: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    sharpe_126: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # timestamp set when indicator columns are written for this row
    indicators_updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=False), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("symbol", "date", "series", name="uq_ticker_symbol_date_series"),
    )
