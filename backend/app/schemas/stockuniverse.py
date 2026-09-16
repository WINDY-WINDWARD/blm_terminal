"""stockuniverse schema for NSE India stock universe data."""

from datetime import datetime
from pydantic import BaseModel, field_validator


class StockUniverse(BaseModel):
    """Pydantic schema for NSE India stock universe data."""

    symbol: str
    companyName: str
    segment: str
    industry: str
    sectorPE: float | None
    symbolPE: float | None
    industryInfo: dict[str, str]
    series: str | None = None
    lastUpdateTime: datetime | None = None
    screenerTradesId: str | None = None
    mcUrl: str | None = None
    reviewUrl: str | None = None
    matchConfidence: float | None = None
    mcMatchSource: str | None = None
    mcCompanyName: str | None = None
    morningstarId: str | None = None
    fairValue: float | None = None
    fairValueUpdatedAt: datetime | None = None
    high_52w: float | None = None
    low_52w: float | None = None
    high_52w_date: datetime | None = None
    low_52w_date: datetime | None = None
    isin: str | None = None
    iinvestPath: str | None = None
    iinvestPathResolvedAt: datetime | None = None
    market_cap_cr: float | None = None

    @field_validator("sectorPE", "symbolPE", mode="before")
    @classmethod
    def parse_pe(cls, v: object) -> float | None:
        if v is None:
            return None
        try:
            return float(v)
        except (ValueError, TypeError):
            return None

    @field_validator("lastUpdateTime", mode="before")
    @classmethod
    def parse_datetime(cls, v: object) -> datetime | None:
        if v is None:
            return None
        if isinstance(v, datetime):
            return v
        try:
            return datetime.strptime(str(v), "%d-%b-%Y %H:%M:%S")
        except (ValueError, TypeError):
            return None

    @field_validator("industryInfo", mode="before")
    @classmethod
    def parse_industry_info(cls, v):
        if isinstance(v, dict):
            return v
        return {}


# ---------------------------------------------------------------------------
# Router-defined request/response models (moved from routers/stockuniverse.py
# under audit B.5; field shapes are preserved).
# ---------------------------------------------------------------------------


class MatchResultResponse(BaseModel):
    """Response for /stockuniverse/run-mc-linker."""

    total_matched: int
    exact_matches: int
    url_extract_matches: int
    fuzzy_matches: int
    ambiguous_matches: int


class ConfirmMatchRequest(BaseModel):
    """Request body for PUT /stockuniverse/{symbol}/confirm-match."""

    confirmed: bool
    mc_url: str | None = None


class StockUniverseErrorSymbol(BaseModel):
    """One error category row in the /stockuniverse/errors response."""

    symbol: str
    companyName: str | None
    reviewStatus: str
    series: str | None
    lastUpdateTime: datetime | None


class ErrorCategory(BaseModel):
    """Aggregate count + sample symbols for one error category."""

    count: int
    symbols: list[StockUniverseErrorSymbol]


class StockUniverseErrorsResponse(BaseModel):
    """Response for /stockuniverse/errors (one category per reviewStatus)."""

    delisted: ErrorCategory
    illiquid: ErrorCategory
    suspended: ErrorCategory
    not_tradable: ErrorCategory
    unknown: ErrorCategory
    ticker_error: ErrorCategory


class ChangeSymbolRequest(BaseModel):
    """Request body for POST /stockuniverse/{symbol}/change-symbol."""

    newSymbol: str
