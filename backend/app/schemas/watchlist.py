"""Pydantic schemas for the watchlist endpoints."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator


class WatchlistItemCreate(BaseModel):
    """Input schema for adding a watchlist item."""

    symbol: str
    exchange: str

    @field_validator("symbol", "exchange", mode="before")
    @classmethod
    def upper_strip(cls, v: object) -> str:
        if not isinstance(v, str) or not v.strip():
            raise ValueError("must be a non-empty string")
        return v.strip().upper()


class WatchlistItemOut(BaseModel):
    """Output schema for a persisted watchlist item."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    symbol: str
    exchange: str
    created_at: datetime
