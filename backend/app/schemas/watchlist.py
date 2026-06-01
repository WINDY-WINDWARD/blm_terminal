"""Pydantic schemas for the watchlist endpoints."""

import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

WATCHLIST_NAME_REGEX = re.compile(r"^[A-Za-z0-9-]+$")


class WatchlistCreate(BaseModel):
    """Input schema for creating a watchlist."""

    name: str = Field(..., min_length=1, max_length=32)

    @field_validator("name", mode="before")
    @classmethod
    def validate_name(cls, v: object) -> str:
        if not isinstance(v, str) or not v.strip():
            raise ValueError("must be a non-empty string")
        v = v.strip()
        if len(v) > 32:
            raise ValueError("must be at most 32 characters")
        if not WATCHLIST_NAME_REGEX.match(v):
            raise ValueError("must contain only letters and hyphens")
        return v


class WatchlistOut(BaseModel):
    """Output schema for a persisted watchlist."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    created_at: datetime


class WatchlistWithCountOut(BaseModel):
    """Output schema for a watchlist with item count."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    created_at: datetime
    item_count: int


class WatchlistItemCreate(BaseModel):
    """Input schema for adding a watchlist item."""

    symbol: str
    exchange: str
    watchlist_id: int | None = None

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
    watchlist_id: int
    symbol: str
    exchange: str
    created_at: datetime


class WatchlistBulkReplace(BaseModel):
    """Input schema for atomically replacing all items in a watchlist."""

    symbols: list[str] = Field(..., min_length=1, max_length=100)
    exchange: str = Field(default="NSE")

    @field_validator("symbols", mode="before")
    @classmethod
    def upper_and_dedupe(cls, v: object) -> list[str]:
        if not isinstance(v, list):
            raise ValueError("must be a list of strings")
        cleaned = [str(item).strip().upper() for item in v if isinstance(item, (str, int))]
        seen: set[str] = set()
        deduped: list[str] = []
        for sym in cleaned:
            if sym and sym not in seen:
                seen.add(sym)
                deduped.append(sym)
        return deduped

    @field_validator("exchange", mode="before")
    @classmethod
    def upper_strip_exchange(cls, v: object) -> str:
        if not isinstance(v, str) or not v.strip():
            raise ValueError("must be a non-empty string")
        return v.strip().upper()
