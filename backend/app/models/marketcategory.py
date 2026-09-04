"""SQLAlchemy ORM models for market categories (industries and sectors)."""

from datetime import datetime

from sqlalchemy import (
    DateTime,
    Float,
    Index,
    Integer,
    JSON,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class MarketCategory(Base):
    """ORM model for market categories (industries and sectors)."""

    __tablename__ = "market_categories"

    category_type: Mapped[str] = mapped_column(String(32), primary_key=True)
    slug: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    market_cap: Mapped[float | None] = mapped_column(Float, nullable=True)
    pe: Mapped[float | None] = mapped_column(Float, nullable=True)
    advance: Mapped[int | None] = mapped_column(Integer, nullable=True)
    decline: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sentiment: Mapped[str | None] = mapped_column(String(32), nullable=True)
    earnings_yoy: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_updated: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        default=func.now(),
    )

    __table_args__ = (Index("ix_market_categories_type_slug", "category_type", "slug"),)


class MarketCategoryStock(Base):
    """ORM model for stocks within market categories.

    Each stock has a unique row with all its categories stored as JSON.
    """

    __tablename__ = "market_category_stocks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    exchange: Mapped[str | None] = mapped_column(String(16), nullable=True)
    curr_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    per_change: Mapped[float | None] = mapped_column(Float, nullable=True)
    market_cap: Mapped[float | None] = mapped_column(Float, nullable=True)
    ttm_pe: Mapped[float | None] = mapped_column(Float, nullable=True)
    net_profit: Mapped[float | None] = mapped_column(Float, nullable=True)
    net_profit_yoy: Mapped[float | None] = mapped_column(Float, nullable=True)
    tech_trend: Mapped[str | None] = mapped_column(String(32), nullable=True)
    mc_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    categories: Mapped[list[dict[str, str]]] = mapped_column(JSON, nullable=False)
    """List of categories, e.g. [{"type": "industry", "slug": "bank-private", "name": "Bank - Private"}, {"type": "sector", "slug": "banks", "name": "Banks"}]"""
    last_updated: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        default=func.now(),
    )

    __table_args__ = (
        UniqueConstraint("symbol", name="uq_market_stock_symbol"),
        Index("ix_market_category_stocks_symbol", "symbol"),
    )
