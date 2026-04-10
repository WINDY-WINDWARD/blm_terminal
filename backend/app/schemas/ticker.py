"""Pydantic schemas for ticker warehouse data."""

from datetime import date, datetime
from pydantic import BaseModel


class TickerDailyRow(BaseModel):
    """Single daily OHLCV candle."""

    symbol: str
    Date: date
    series: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    value: float
    source: str

    @property
    def ohlcv(self) -> dict:
        return {
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
        }


class TickerOHLCVResponse(BaseModel):
    """OHLCV data response for a symbol."""

    symbol: str
    from_date: date
    to_date: date
    candles: list[TickerDailyRow]
    count: int


class TickerLatestResponse(BaseModel):
    """Latest candle response."""

    symbol: str
    Date: date | None
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    volume: int | None
    value: float | None


class TickerStatusResponse(BaseModel):
    """Warehouse status response."""

    total_rows: int
    symbols_covered: int
    latest_date: date | None
    last_update_time: datetime | None
    backfill_pending: int
    backfill_progress_percent: float
    watchlist_symbols_covered: int
    watchlist_symbols_total: int


class TriggerResponse(BaseModel):
    """Response for manual trigger endpoints."""

    job_key: str
    status: str
    message: str