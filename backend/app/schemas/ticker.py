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
    is_stale: bool = False


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


class IntradayIntervalStatus(BaseModel):
    """Per-interval intraday warehouse status (1h / W / M)."""

    total_rows: int
    watchlist_covered: int
    watchlist_current: int
    symbols_with_indicators: int
    latest_timestamp: datetime | None
    # Universe-level coverage (populated for W and M only; 0 for 1h)
    universe_covered: int = 0
    universe_symbols_with_indicators: int = 0


class TickerStatusResponse(BaseModel):
    """Warehouse status response."""

    total_rows: int
    symbols_covered: int
    symbols_current: int
    symbols_stale: int
    universe_count: int
    last_trading_day: date | None
    latest_date: date | None
    last_update_time: datetime | None
    backfill_pending: int
    backfill_progress_percent: float
    watchlist_symbols_covered: int
    watchlist_symbols_total: int
    watchlist_symbols_current: int
    days_behind_breakdown: dict[str, int]
    intraday_stats: dict[str, IntradayIntervalStatus]


class TriggerResponse(BaseModel):
    """Response for manual trigger endpoints."""

    job_key: str
    status: str
    message: str


# ---------------------------------------------------------------------------
# Router-defined request/response models (moved from routers/ticker.py under
# audit B.5; field shapes are preserved).
# ---------------------------------------------------------------------------


class ReturnsResponse(BaseModel):
    """Multi-period returns response for a single symbol."""

    symbol: str
    d1: float | None
    d1w: float | None
    d1m: float | None
    d3m: float | None
    d6m: float | None
    d1y: float | None
    latest_date: date | None


class UniverseReturnsResponse(BaseModel):
    """Universe returns heatmap response."""

    period: str
    count: int
    results: list[dict]


class SectorReturnsResponse(BaseModel):
    """Sector returns response."""

    period: str
    results: list[dict]


class Position52wResponse(BaseModel):
    """52-week position response for a single symbol."""

    symbol: str
    high_52w: float | None
    low_52w: float | None
    high_52w_date: date | None
    low_52w_date: date | None
    current_close: float | None
    pct_from_52w_high: float | None
    pct_from_52w_low: float | None
    is_52w_high: bool
    is_52w_low: bool


class MomentumScoreResponse(BaseModel):
    """Composite momentum score response for a single symbol."""

    symbol: str
    score: float | None
    rank: int | None
    universe_size: int
    reason: str | None = None
    components: dict | None = None


class MomentumLeaderboardResponse(BaseModel):
    """Momentum leaderboard response (top N symbols)."""

    count: int
    results: list[dict]


class StreakResponse(BaseModel):
    """Streak tracking response for a single symbol."""

    symbol: str
    consecutive_up_days: int
    consecutive_down_days: int
    consecutive_volume_up_days: int
    days_since_52w_high: int | None


class ScreenerResponse(BaseModel):
    """Screener response."""

    count: int
    returned: int
    filters_applied: list[str]
    results: list[dict]


class IntradayCandleRow(BaseModel):
    """Single intraday OHLCV candle."""

    timestamp: int   # Unix milliseconds
    open: float
    high: float
    low: float
    close: float
    volume: int


class IntradayOHLCVResponse(BaseModel):
    """Intraday OHLCV response (1h / W / M)."""

    symbol: str
    interval: str
    candles: list[IntradayCandleRow]
    count: int