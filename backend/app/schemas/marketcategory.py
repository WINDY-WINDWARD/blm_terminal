"""Pydantic schemas for market category endpoints."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class MarketCategoryOut(BaseModel):
    """Output schema for a market category (industry or sector)."""

    model_config = ConfigDict(from_attributes=True)

    category_type: str
    slug: str
    name: str
    url: str | None
    market_cap: float | None
    pe: float | None
    advance: int | None
    decline: int | None
    sentiment: str | None
    earnings_yoy: float | None
    return_1d: float | None = None
    return_1w: float | None = None
    return_1m: float | None = None
    return_6m: float | None = None
    last_updated: datetime
    created_at: datetime


class StockCategory(BaseModel):
    """A single category entry for a stock."""

    type: str
    slug: str
    name: str


class MarketCategoryStockOut(BaseModel):
    """Output schema for a stock with its categories."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    symbol: str
    company_name: str
    exchange: str | None
    curr_price: float | None
    per_change: float | None
    market_cap: float | None
    ttm_pe: float | None
    net_profit: float | None
    net_profit_yoy: float | None
    tech_trend: str | None
    mc_url: str | None
    categories: list[dict[str, str]]
    last_updated: datetime
    created_at: datetime
