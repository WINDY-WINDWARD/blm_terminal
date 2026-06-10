"""SQLAlchemy ORM model for daily breakout symbol snapshots.

Stores the list of symbols that appeared in NSE 52-week high, 52-week low,
or volume gainer lists on each trading day. Used to detect repeat breakout
patterns across a rolling window (e.g. 10 trading days).
"""

from datetime import date

from sqlalchemy import Date, Float, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class BreakoutSnapshot(Base):
    """One row per (date, breakout_type, symbol) — capturing who appeared in
    which NSE breakout list on a given trading day."""

    __tablename__ = "breakout_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    breakout_type: Mapped[str] = mapped_column(String(16), nullable=False)  # 52W_HIGH, 52W_LOW, VOLUME_GAINER
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    ltp: Mapped[float | None] = mapped_column(Float, nullable=True)
    pchange: Mapped[float | None] = mapped_column(Float, nullable=True)
    extra_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "snapshot_date",
            "breakout_type",
            "symbol",
            name="uq_breakout_snapshot_daily",
        ),
        Index("ix_breakout_snapshots_date", "snapshot_date"),
        Index("ix_breakout_snapshots_symbol_type", "symbol", "breakout_type"),
    )
