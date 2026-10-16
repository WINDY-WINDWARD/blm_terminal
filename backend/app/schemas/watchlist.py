"""Pydantic schemas for the watchlist endpoints."""

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

WATCHLIST_NAME_REGEX = re.compile(r"^[A-Za-z0-9 _-]+$")


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
            raise ValueError("must contain only letters, numbers, spaces, underscores, and hyphens")
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


class WatchlistImportItem(BaseModel):
    """Input schema for an item in a watchlist import section."""

    symbol: str
    exchange: str = "NSE"

    @field_validator("symbol", "exchange", mode="before")
    @classmethod
    def upper_strip(cls, v: object) -> str:
        if not isinstance(v, str) or not v.strip():
            raise ValueError("must be a non-empty string")
        return v.strip().upper()


class WatchlistImportSection(BaseModel):
    """Section containing a group of symbols."""

    name: str = Field(default="DEFAULT", max_length=64)
    items: list[WatchlistImportItem] = Field(default_factory=list)

    @field_validator("name", mode="before")
    @classmethod
    def clean_name(cls, v: object) -> str:
        if not isinstance(v, str) or not v.strip():
            return "DEFAULT"
        return v.strip()


class WatchlistImportRequest(BaseModel):
    """Input schema for importing a watchlist."""

    base_name: str = Field(..., min_length=1, max_length=32)
    mode: Literal["create", "append", "replace"] = Field(default="create")
    split_sections: bool = Field(default=False)
    target_watchlist_id: int | None = Field(default=None)
    sections: list[WatchlistImportSection] = Field(..., min_length=1)

    @field_validator("base_name", mode="before")
    @classmethod
    def validate_base_name(cls, v: object) -> str:
        if not isinstance(v, str) or not v.strip():
            raise ValueError("must be a non-empty string")
        v = v.strip()
        if len(v) > 32:
            raise ValueError("must be at most 32 characters")
        if not WATCHLIST_NAME_REGEX.match(v):
            raise ValueError("must contain only letters, numbers, spaces, underscores, and hyphens")
        return v


class WatchlistImportSkippedItem(BaseModel):
    """Detail of a symbol skipped during import."""

    symbol: str
    exchange: str = "NSE"
    reason: str


class WatchlistImportResponse(BaseModel):
    """Output schema for a completed watchlist import."""

    ok: bool
    created_watchlists: list[WatchlistOut] = Field(default_factory=list)
    target_watchlist_id: int | None = None
    total_imported: int
    skipped_symbols: list[WatchlistImportSkippedItem] = Field(default_factory=list)


class WatchlistImportUrlRequest(BaseModel):
    """Input schema for fetching a public TradingView watchlist URL."""

    url: str = Field(..., min_length=5, max_length=1024)

    @field_validator("url", mode="before")
    @classmethod
    def validate_url(cls, v: object) -> str:
        if not isinstance(v, str) or not v.strip():
            raise ValueError("must be a non-empty string")
        return v.strip()


class WatchlistImportUrlResponse(BaseModel):
    """Output schema for fetched TradingView symbols."""

    source_name: str
    raw_symbols: list[str]
