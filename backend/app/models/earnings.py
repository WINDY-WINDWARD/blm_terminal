"""SQLAlchemy model for NSE earnings/financial results."""
from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class EarningsRecord(Base):
    __tablename__ = "earnings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String, nullable=False, index=True)
    exchange: Mapped[str] = mapped_column(String, nullable=False, default="NSE")

    # Period covered by this result (e.g. "Q3 FY2026")
    period: Mapped[str | None] = mapped_column(String, nullable=True)
    result_date: Mapped[str | None] = mapped_column(String, nullable=True)

    # Financial figures (nullable — not all records have all fields)
    net_profit: Mapped[float | None] = mapped_column(Float, nullable=True)
    revenue: Mapped[float | None] = mapped_column(Float, nullable=True)
    eps: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Raw JSON payload from NSE stored for reference
    raw_json: Mapped[str | None] = mapped_column(String, nullable=True)

    cached_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
