"""Router for ticker warehouse endpoints."""

from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel

from app.schemas.ticker import (
    TickerDailyRow,
    TickerLatestResponse,
    TickerOHLCVResponse,
    TickerStatusResponse,
    TriggerResponse,
)
from app.services import ticker_warehouse
from app.services import returns as returns_service
from app.services import momentum as momentum_service
from app.services import indicators as indicators_service
from app.services import screener as screener_service
from app.jobs.runner import trigger_job

router = APIRouter(prefix="/ticker", tags=["ticker"])


def _row_to_schema(row: dict) -> TickerDailyRow:
    """Convert a dict row to TickerDailyRow schema."""
    return TickerDailyRow(
        symbol=row["symbol"],
        Date=row["date"],
        series=row["series"],
        open=row["open"],
        high=row["high"],
        low=row["low"],
        close=row["close"],
        volume=row["volume"],
        value=row["value"],
        source=row["source"],
    )


@router.get("/ohlcv/{symbol}", response_model=TickerOHLCVResponse)
async def get_ohlcv(
    symbol: str,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
) -> TickerOHLCVResponse:
    """Get OHLCV data for a symbol within a date range."""
    from_date_obj: Optional[ date] = None
    to_date_obj: Optional[date] = None

    if from_date:
        try:
            from_date_obj = datetime.strptime(from_date, "%d-%m-%Y").date()
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid from_date format. Use DD-MM-YYYY",
            )

    if to_date:
        try:
            to_date_obj = datetime.strptime(to_date, "%d-%m-%Y").date()
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid to_date format. Use DD-MM-YYYY",
            )

    candles = ticker_warehouse.get_ohlcv(symbol, from_date_obj, to_date_obj)
    candle_rows = [_row_to_schema(c) for c in candles]

    return TickerOHLCVResponse(
        symbol=symbol,
        from_date=candles[0]["date"] if candles else date.today(),
        to_date=candles[-1]["date"] if candles else date.today(),
        candles=candle_rows,
        count=len(candle_rows),
    )


@router.get("/ohlcv/{symbol}/latest", response_model=TickerLatestResponse)
async def get_latest(symbol: str) -> TickerLatestResponse:
    """Get the most recent OHLCV candle for a symbol."""
    candle = ticker_warehouse.get_latest_candle(symbol)

    if not candle:
        return TickerLatestResponse(
            symbol=symbol,
            Date=None,
            open=None,
            high=None,
            low=None,
            close=None,
            volume=None,
            value=None,
        )

    return TickerLatestResponse(
        symbol=candle["symbol"],
        Date=candle["date"],
        open=candle["open"],
        high=candle["high"],
        low=candle["low"],
        close=candle["close"],
        volume=candle["volume"],
        value=candle["value"],
    )


@router.get("/status", response_model=TickerStatusResponse)
async def get_status() -> TickerStatusResponse:
    """Get warehouse status and statistics."""
    status_data = ticker_warehouse.get_warehouse_status()

    return TickerStatusResponse(
        total_rows=status_data["total_rows"],
        symbols_covered=status_data["symbols_covered"],
        latest_date=status_data["latest_date"],
        last_update_time=status_data["last_update_time"],
        backfill_pending=status_data["backfill_pending"],
        backfill_progress_percent=status_data["backfill_progress_percent"],
        watchlist_symbols_covered=status_data["watchlist_symbols_covered"],
        watchlist_symbols_total=status_data["watchlist_symbols_total"],
    )


@router.post("/trigger-backfill", response_model=TriggerResponse)
async def trigger_backfill() -> TriggerResponse:
    """Manually trigger a backfill job run."""
    try:
        await trigger_job("job.ticker_backfill")
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to trigger backfill: {str(e)}",
        )

    return TriggerResponse(
        job_key="job.ticker_backfill",
        status="triggered",
        message="Backfill job triggered successfully",
    )


@router.post("/trigger-daily-update", response_model=TriggerResponse)
async def trigger_daily_update() -> TriggerResponse:
    """Manually trigger a daily update job run."""
    try:
        await trigger_job("job.ticker_daily_update")
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to trigger daily update: {str(e)}",
        )

    return TriggerResponse(
        job_key="job.ticker_daily_update",
        status="triggered",
        message="Daily update job triggered successfully",
    )


class ReturnsResponse(BaseModel):
    """Multi-period returns response."""
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


@router.get("/returns/{symbol}", response_model=ReturnsResponse)
async def get_returns(symbol: str) -> ReturnsResponse:
    """Get multi-period returns for a symbol (1d, 1w, 1m, 3m, 6m, 1y)."""
    data = returns_service.get_returns(symbol.upper())
    return ReturnsResponse(
        symbol=data["symbol"],
        d1=data.get("1d"),
        d1w=data.get("1w"),
        d1m=data.get("1m"),
        d3m=data.get("3m"),
        d6m=data.get("6m"),
        d1y=data.get("1y"),
        latest_date=data.get("latest_date"),
    )


@router.get("/returns-bulk")
async def get_returns_bulk(
    symbols: str = Query(..., description="Comma-separated symbols, e.g. RELIANCE,TCS,INFY"),
) -> list[ReturnsResponse]:
    """Get multi-period returns for multiple symbols."""
    symbol_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    results = returns_service.get_returns_bulk(symbol_list)
    return [
        ReturnsResponse(
            symbol=r["symbol"],
            d1=r.get("1d"),
            d1w=r.get("1w"),
            d1m=r.get("1m"),
            d3m=r.get("3m"),
            d6m=r.get("6m"),
            d1y=r.get("1y"),
            latest_date=r.get("latest_date"),
        )
        for r in results
    ]


@router.get("/universe-returns", response_model=UniverseReturnsResponse)
async def get_universe_returns(
    period: str = Query("1m", description="Return period: 1d, 1w, 1m, 3m, 6m, 1y"),
    sort_by: str = Query("return", description="Field to sort by"),
    order: str = Query("desc", description="Sort order: asc or desc"),
    limit: int = Query(50, ge=1, le=200, description="Max results"),
) -> UniverseReturnsResponse:
    """Get ranked returns across the universe."""
    results = returns_service.get_universe_returns(period, sort_by, order, limit)
    return UniverseReturnsResponse(
        period=period,
        count=len(results),
        results=results,
    )


@router.get("/sector-returns", response_model=SectorReturnsResponse)
async def get_sector_returns(
    period: str = Query("1m", description="Return period: 1d, 1w, 1m, 3m, 6m, 1y"),
) -> SectorReturnsResponse:
    """Get average and median returns by sector."""
    results = returns_service.get_sector_returns(period)
    return SectorReturnsResponse(
        period=period,
        results=results,
    )


class Position52wResponse(BaseModel):
    """52-week position response."""
    symbol: str
    high_52w: float | None
    low_52w: float | None
    current_close: float | None
    pct_from_52w_high: float | None
    pct_from_52w_low: float | None
    is_52w_high: bool
    is_52w_low: bool


class PositionAthResponse(BaseModel):
    """All-time position response."""
    symbol: str
    ath: float | None
    atl: float | None
    current_close: float | None
    ath_drawdown: float | None
    is_ath: bool
    is_atl: bool


@router.get("/position/52w/{symbol}", response_model=Position52wResponse)
async def get_52w_position(symbol: str) -> Position52wResponse:
    """Get 52-week high/low position for a symbol."""
    data = returns_service.get_52w_position(symbol.upper())
    return Position52wResponse(
        symbol=data["symbol"],
        high_52w=data.get("52w_high"),
        low_52w=data.get("52w_low"),
        current_close=data.get("current_close"),
        pct_from_52w_high=data.get("pct_from_52w_high"),
        pct_from_52w_low=data.get("pct_from_52w_low"),
        is_52w_high=data.get("is_52w_high", False),
        is_52w_low=data.get("is_52w_low", False),
    )


@router.get("/position/ath/{symbol}", response_model=PositionAthResponse)
async def get_ath_position(symbol: str) -> PositionAthResponse:
    """Get all-time high/low position for a symbol."""
    data = returns_service.get_ath_position(symbol.upper())
    return PositionAthResponse(
        symbol=data["symbol"],
        ath=data.get("ath"),
        atl=data.get("atl"),
        current_close=data.get("current_close"),
        ath_drawdown=data.get("ath_drawdown"),
        is_ath=data.get("is_ath", False),
        is_atl=data.get("is_atl", False),
    )


class MomentumScoreResponse(BaseModel):
    """Momentum score response."""
    symbol: str
    score: float | None
    rank: int | None
    universe_size: int
    reason: str | None = None
    components: dict | None = None


class MomentumLeaderboardResponse(BaseModel):
    """Momentum leaderboard response."""
    count: int
    results: list[dict]


@router.get("/momentum-score/{symbol}", response_model=MomentumScoreResponse)
async def get_momentum_score(symbol: str) -> MomentumScoreResponse:
    """Get composite momentum score for a symbol."""
    data = momentum_service.get_momentum_score(symbol.upper())
    return MomentumScoreResponse(
        symbol=data["symbol"],
        score=data.get("score"),
        rank=data.get("rank"),
        universe_size=data.get("universe_size"),
        reason=data.get("reason"),
        components=data.get("components"),
    )


@router.get("/momentum-leaderboard", response_model=MomentumLeaderboardResponse)
async def get_momentum_leaderboard(
    limit: int = Query(50, ge=1, le=200, description="Max results"),
) -> MomentumLeaderboardResponse:
    """Get top N symbols by momentum score."""
    results = momentum_service.get_momentum_leaderboard(limit)
    return MomentumLeaderboardResponse(
        count=len(results),
        results=results,
    )


@router.get("/indicators/{symbol}")
async def get_indicators(symbol: str) -> dict:
    """Get technical indicators for a symbol (RSI, MACD, Bollinger Bands, ATR, etc.)."""
    return indicators_service.get_indicators(symbol.upper())


class StreakResponse(BaseModel):
    """Streak tracking response."""
    symbol: str
    consecutive_up_days: int
    consecutive_down_days: int
    consecutive_volume_up_days: int
    days_since_52w_high: int | None
    days_since_ath: int | None


@router.get("/streaks/{symbol}", response_model=StreakResponse)
async def get_streaks(symbol: str) -> StreakResponse:
    """Get streak metrics for a symbol (consecutive up/down days, volume streaks, etc.)."""
    data = returns_service.get_streak_tracking(symbol.upper())
    return StreakResponse(
        symbol=data["symbol"],
        consecutive_up_days=data.get("consecutive_up_days", 0),
        consecutive_down_days=data.get("consecutive_down_days", 0),
        consecutive_volume_up_days=data.get("consecutive_volume_up_days", 0),
        days_since_52w_high=data.get("days_since_52w_high"),
        days_since_ath=data.get("days_since_ath"),
    )


class ScreenerResponse(BaseModel):
    """Screener response."""
    count: int
    returned: int
    filters_applied: list[str]
    results: list[dict]


@router.get("/screener", response_model=ScreenerResponse)
async def get_screener(
    pct_change_today_min: Optional[float] = Query(None, description="Min % change today"),
    pct_change_today_max: Optional[float] = Query(None, description="Max % change today"),
    pct_change_1w_min: Optional[float] = Query(None, description="Min % change 1W"),
    pct_change_1w_max: Optional[float] = Query(None, description="Max % change 1W"),
    pct_change_1m_min: Optional[float] = Query(None, description="Min % change 1M"),
    pct_change_1m_max: Optional[float] = Query(None, description="Max % change 1M"),
    pct_change_3m_min: Optional[float] = Query(None, description="Min % change 3M"),
    pct_change_3m_max: Optional[float] = Query(None, description="Max % change 3M"),
    pct_change_6m_min: Optional[float] = Query(None, description="Min % change 6M"),
    pct_change_6m_max: Optional[float] = Query(None, description="Max % change 6M"),
    pct_change_1y_min: Optional[float] = Query(None, description="Min % change 1Y"),
    pct_change_1y_max: Optional[float] = Query(None, description="Max % change 1Y"),
    volume_ratio_min: Optional[float] = Query(None, description="Min volume ratio (today/avg20d)"),
    volume_ratio_max: Optional[float] = Query(None, description="Max volume ratio"),
    pct_from_52w_high_max: Optional[float] = Query(None, description="Max % from 52W high"),
    pct_from_52w_high_min: Optional[float] = Query(None, description="Min % from 52W high"),
    pct_from_52w_low_min: Optional[float] = Query(None, description="Min % from 52W low"),
    pct_from_52w_low_max: Optional[float] = Query(None, description="Max % from 52W low"),
    is_52w_high: Optional[bool] = Query(None, description="Filter for 52W high"),
    is_52w_low: Optional[bool] = Query(None, description="Filter for 52W low"),
    is_ath: Optional[bool] = Query(None, description="Filter for all-time high"),
    ath_drawdown_min: Optional[float] = Query(None, description="Min ATH drawdown %"),
    ath_drawdown_max: Optional[float] = Query(None, description="Max ATH drawdown %"),
    atr_pct_max: Optional[float] = Query(None, description="Max ATR % (volatility)"),
    atr_pct_min: Optional[float] = Query(None, description="Min ATR %"),
    rsi_min: Optional[float] = Query(None, description="Min RSI (14)"),
    rsi_max: Optional[float] = Query(None, description="Max RSI (14)"),
    bb_squeeze: Optional[bool] = Query(None, description="Filter for Bollinger squeeze"),
    pe_min: Optional[float] = Query(None, description="Min PE ratio"),
    pe_max: Optional[float] = Query(None, description="Max PE ratio"),
    sector: Optional[str] = Query(None, description="Filter by sector"),
    industry: Optional[str] = Query(None, description="Filter by industry (partial match)"),
    above_sma50: Optional[bool] = Query(None, description="Price above SMA50"),
    momentum_score_min: Optional[float] = Query(None, description="Min momentum score"),
    min_data_points: Optional[int] = Query(None, description="Min data points required"),
    sort_by: str = Query("symbol", description="Sort field"),
    order: str = Query("asc", description="Sort order"),
    limit: int = Query(50, ge=1, le=200, description="Max results"),
) -> ScreenerResponse:
    """Run screener with filters."""
    filters = {}
    if pct_change_today_min is not None:
        filters["pct_change_today_min"] = pct_change_today_min
    if pct_change_today_max is not None:
        filters["pct_change_today_max"] = pct_change_today_max
    if pct_change_1w_min is not None:
        filters["pct_change_1w_min"] = pct_change_1w_min
    if pct_change_1w_max is not None:
        filters["pct_change_1w_max"] = pct_change_1w_max
    if pct_change_1m_min is not None:
        filters["pct_change_1m_min"] = pct_change_1m_min
    if pct_change_1m_max is not None:
        filters["pct_change_1m_max"] = pct_change_1m_max
    if pct_change_3m_min is not None:
        filters["pct_change_3m_min"] = pct_change_3m_min
    if pct_change_3m_max is not None:
        filters["pct_change_3m_max"] = pct_change_3m_max
    if pct_change_6m_min is not None:
        filters["pct_change_6m_min"] = pct_change_6m_min
    if pct_change_6m_max is not None:
        filters["pct_change_6m_max"] = pct_change_6m_max
    if pct_change_1y_min is not None:
        filters["pct_change_1y_min"] = pct_change_1y_min
    if pct_change_1y_max is not None:
        filters["pct_change_1y_max"] = pct_change_1y_max
    if volume_ratio_min is not None:
        filters["volume_ratio_min"] = volume_ratio_min
    if volume_ratio_max is not None:
        filters["volume_ratio_max"] = volume_ratio_max
    if pct_from_52w_high_max is not None:
        filters["pct_from_52w_high_max"] = pct_from_52w_high_max
    if pct_from_52w_high_min is not None:
        filters["pct_from_52w_high_min"] = pct_from_52w_high_min
    if pct_from_52w_low_min is not None:
        filters["pct_from_52w_low_min"] = pct_from_52w_low_min
    if pct_from_52w_low_max is not None:
        filters["pct_from_52w_low_max"] = pct_from_52w_low_max
    if is_52w_high is not None:
        filters["is_52w_high"] = is_52w_high
    if is_52w_low is not None:
        filters["is_52w_low"] = is_52w_low
    if is_ath is not None:
        filters["is_ath"] = is_ath
    if ath_drawdown_min is not None:
        filters["ath_drawdown_min"] = ath_drawdown_min
    if ath_drawdown_max is not None:
        filters["ath_drawdown_max"] = ath_drawdown_max
    if atr_pct_max is not None:
        filters["atr_pct_max"] = atr_pct_max
    if atr_pct_min is not None:
        filters["atr_pct_min"] = atr_pct_min
    if rsi_min is not None:
        filters["rsi_min"] = rsi_min
    if rsi_max is not None:
        filters["rsi_max"] = rsi_max
    if bb_squeeze is not None:
        filters["bb_squeeze"] = bb_squeeze
    if pe_min is not None:
        filters["pe_min"] = pe_min
    if pe_max is not None:
        filters["pe_max"] = pe_max
    if sector is not None:
        filters["sector"] = sector
    if industry is not None:
        filters["industry"] = industry
    if above_sma50 is not None:
        filters["above_sma50"] = above_sma50
    if momentum_score_min is not None:
        filters["momentum_score_min"] = momentum_score_min
    if min_data_points is not None:
        filters["min_data_points"] = min_data_points

    result = screener_service.run_screener(filters, sort_by, order, limit)
    return ScreenerResponse(
        count=result["count"],
        returned=result["returned"],
        filters_applied=result["filters_applied"],
        results=result["results"],
    )