"""Router for ticker warehouse endpoints."""

from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, status

from app.schemas.ticker import (
    TickerDailyRow,
    TickerLatestResponse,
    TickerOHLCVResponse,
    TickerStatusResponse,
    TriggerResponse,
)
from app.services import ticker_warehouse
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