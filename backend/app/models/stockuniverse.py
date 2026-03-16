"""SQLALCHEMY ORM MODEL for NSE India stock universe metadata"""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, String, func
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class StockUniverse(Base):
    """ORM model for NSE stock universe metadata."""

    __tablename__ = "stock_universe"

    symbol: Mapped[str] = mapped_column(String(32), primary_key=True, index=True)
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    segment: Mapped[str] = mapped_column(String(64), nullable=False)
    industry: Mapped[str] = mapped_column(String(255), nullable=False)
    sector_pe: Mapped[float | None] = mapped_column(Float, nullable=True)
    symbol_pe: Mapped[float | None] = mapped_column(Float, nullable=True)
    industry_info: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    last_update_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    screener_trades_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    mc_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    review_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    match_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    mc_match_source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    mc_company_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
