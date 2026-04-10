"""
Ticker warehouse service — fetches and stores daily OHLCV data from NSE.

Two data sources:
1. equity_history(symbol, start, end) — per-symbol historical API (used for backfill)
2. get_bhavcopy(date) — single CSV for all symbols (used for daily incremental)

This module is used by background workers and the ticker router.
"""

import logging
import time
from datetime import date, datetime, timedelta
from typing import Generator, Optional

import nsepython
import pandas as pd
from sqlalchemy import and_, func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.models.ticker import TickerDaily
from app.models.stockuniverse import StockUniverse
from app.models.watchlist import WatchlistItem
from app.database import _SyncSessionLocal
from app.services.nse_rate_limiter import throttled_nse_call

logger = logging.getLogger(__name__)

TICKER_SERIES_FILTER = "EQ"
DEFAULT_BACKFILL_DAYS = 365
REQUEST_DELAY_SECONDS = 2.0


def _get_session() -> Generator[Session, None, None]:
    """Get a sync DB session."""
    return _SyncSessionLocal()


def _nse_equity_history_sync(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    """Fetch equity history synchronously via nsepython."""
    return nsepython.equity_history(symbol, "EQ", start_date, end_date)


async def _nse_equity_history_async(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    """Fetch equity history with rate limiting."""
    return await throttled_nse_call(
        f"equity_history:{symbol}",
        _nse_equity_history_sync,
        symbol,
        start_date,
        end_date,
    )


def _nse_bhavcopy_sync(date_str: str) -> pd.DataFrame:
    """Fetch bhavcopy CSV synchronously."""
    return nsepython.get_bhavcopy(date_str)


def backfill_symbol(symbol: str, days: int = DEFAULT_BACKFILL_DAYS) -> int:
    """
    Backfill OHLCV data for a single symbol.

    Fetches `days` trading days of history via equity_history() API
    and upserts into ticker_daily table.

    Returns:
        Number of rows inserted/updated.
    """
    today = date.today()
    start_date = (today - timedelta(days=days + 50)).strftime("%d-%m-%Y")
    end_date = today.strftime("%d-%m-%Y")

    logger.info(f"backfill_symbol: fetching {symbol} from {start_date} to {end_date}")

    try:
        df = _nse_equity_history_sync(symbol, start_date, end_date)
    except Exception as e:
        logger.warning(f"backfill_symbol: equity_history failed for {symbol}: {e}")
        return 0

    if df.empty:
        logger.warning(f"backfill_symbol: empty result for {symbol}")
        return 0

    df = df.rename(
        columns={
            "CH_TIMESTAMP": "date",
            "CH_OPENING_PRICE": "open",
            "CH_TRADE_HIGH_PRICE": "high",
            "CH_TRADE_LOW_PRICE": "low",
            "CH_CLOSING_PRICE": "close",
            "CH_TOT_TRADED_QTY": "volume",
            "CH_TOT_TRADED_VAL": "value",
        }
    )

    df["symbol"] = symbol
    df["series"] = TICKER_SERIES_FILTER
    df["source"] = "equity_history"
    df["created_at"] = datetime.now()

    df["date"] = pd.to_datetime(df["date"], format="%d-%b-%Y").dt.date

    rows = df[
        ["symbol", "date", "series", "open", "high", "low", "close", "volume", "value", "source", "created_at"]
    ].to_dict("records")

    with _get_session() as db:
        stmt = sqlite_insert(TickerDaily).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["symbol", "date", "series"],
            set_={
                "open": stmt.excluded.open,
                "high": stmt.excluded.high,
                "low": stmt.excluded.low,
                "close": stmt.excluded.close,
                "volume": stmt.excluded.volume,
                "value": stmt.excluded.value,
                "source": stmt.excluded.source,
                "created_at": stmt.excluded.created_at,
            },
        )
        db.execute(stmt)
        db.commit()

    logger.info(f"backfill_symbol: upserted {len(rows)} rows for {symbol}")
    return len(rows)


def bulk_update_via_bhavcopy(date_str: str) -> int:
    """
    Bulk update via bhavcopy CSV.

    Downloads the bhavcopy for `date_str` (DD-MM-YYYY format),
    filters to EQ series, and upserts all matching symbols.

    Returns:
        Number of rows inserted/updated.
    """
    logger.info(f"bulk_update_via_bhavcopy: fetching {date_str}")

    try:
        df = nsepython.get_bhavcopy(date_str)
    except Exception as e:
        logger.warning(f"bulk_update_via_bhavcopy: bhavcopy fetch failed for {date_str}: {e}")
        return 0

    if df.empty:
        logger.warning(f"bulk_update_via_bhavcopy: empty result for {date_str}")
        return 0

    df.columns = df.columns.str.strip()
    df["SERIES"] = df["SERIES"].str.strip()
    df = df[df["SERIES"] == TICKER_SERIES_FILTER].copy()

    if df.empty:
        logger.warning(f"bulk_update_via_bhavcopy: no EQ series data for {date_str}")
        return 0

    df = df.rename(
        columns={
            "SYMBOL": "symbol",
            "OPEN_PRICE": "open",
            "HIGH_PRICE": "high",
            "LOW_PRICE": "low",
            "CLOSE_PRICE": "close",
            "TURNOVER_LACS": "value",
            "TTL_TRD_QNTY": "volume",
        }
    )

    parsed_date = datetime.strptime(date_str, "%d-%m-%Y").date()
    df["date"] = parsed_date
    df["series"] = TICKER_SERIES_FILTER
    df["source"] = "bhavcopy"
    df["created_at"] = datetime.now()

    rows = df[
        ["symbol", "date", "series", "open", "high", "low", "close", "volume", "value", "source", "created_at"]
    ].to_dict("records")

    with _get_session() as db:
        stmt = sqlite_insert(TickerDaily).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["symbol", "date", "series"],
            set_={
                "open": stmt.excluded.open,
                "high": stmt.excluded.high,
                "low": stmt.excluded.low,
                "close": stmt.excluded.close,
                "volume": stmt.excluded.volume,
                "value": stmt.excluded.value,
                "source": stmt.excluded.source,
                "created_at": stmt.excluded.created_at,
            },
        )
        db.execute(stmt)
        db.commit()

    logger.info(f"bulk_update_via_bhavcopy: upserted {len(rows)} rows for {date_str}")
    return len(rows)


def update_symbol_today(symbol: str, target_date: Optional[date] = None) -> int:
    """
    Update a single symbol for a specific date via equity_history.

    Used as fallback when bhavcopy fails.

    Returns:
        Number of rows inserted/updated.
    """
    if target_date is None:
        target_date = date.today()

    target_str = target_date.strftime("%d-%m-%Y")

    logger.info(f"update_symbol_today: fetching {symbol} for {target_str}")

    try:
        df = _nse_equity_history_sync(symbol, target_str, target_str)
    except Exception as e:
        logger.warning(f"update_symbol_today: equity_history failed for {symbol}: {e}")
        return 0

    if df.empty:
        return 0

    df = df.rename(
        columns={
            "CH_TIMESTAMP": "date",
            "CH_OPENING_PRICE": "open",
            "CH_TRADE_HIGH_PRICE": "high",
            "CH_TRADE_LOW_PRICE": "low",
            "CH_CLOSING_PRICE": "close",
            "CH_TOT_TRADED_QTY": "volume",
            "CH_TOT_TRADED_VAL": "value",
        }
    )

    df["symbol"] = symbol
    df["series"] = TICKER_SERIES_FILTER
    df["source"] = "equity_history"
    df["created_at"] = datetime.now()

    df["date"] = pd.to_datetime(df["date"], format="%d-%b-%Y").dt.date

    row = df.iloc[0]
    row_dict = {
        "symbol": row["symbol"],
        "date": row["date"],
        "series": row["series"],
        "open": row["open"],
        "high": row["high"],
        "low": row["low"],
        "close": row["close"],
        "volume": int(row["volume"]),
        "value": row["value"],
        "source": row["source"],
        "created_at": row["created_at"],
    }

    with _get_session() as db:
        stmt = sqlite_insert(TickerDaily).values([row_dict])
        stmt = stmt.on_conflict_do_update(
            index_elements=["symbol", "date", "series"],
            set_={
                "open": stmt.excluded.open,
                "high": stmt.excluded.high,
                "low": stmt.excluded.low,
                "close": stmt.excluded.close,
                "volume": stmt.excluded.volume,
                "value": stmt.excluded.value,
                "source": stmt.excluded.source,
                "created_at": stmt.excluded.created_at,
            },
        )
        db.execute(stmt)
        db.commit()

    logger.info(f"update_symbol_today: upserted 1 row for {symbol}")
    return 1


def get_ohlcv(
    symbol: str,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
) -> list[dict]:
    """
    Get OHLCV data for a symbol.

    Args:
        symbol: Stock symbol.
        from_date: Start date (default: 365 days ago).
        to_date: End date (default: today).

    Returns:
        List of OHLCV dicts sorted by date ascending.
    """
    if from_date is None:
        from_date = date.today() - timedelta(days=DEFAULT_BACKFILL_DAYS)
    if to_date is None:
        to_date = date.today()

    with _get_session() as db:
        stmt = (
            select(TickerDaily)
            .where(
                and_(
                    TickerDaily.symbol == symbol,
                    TickerDaily.date >= from_date,
                    TickerDaily.date <= to_date,
                )
            )
            .order_by(TickerDaily.date)
        )
        result = db.execute(stmt)
        rows = result.scalars().all()

        return [
            {
                "symbol": r.symbol,
                "date": r.date,
                "series": r.series,
                "open": r.open,
                "high": r.high,
                "low": r.low,
                "close": r.close,
                "volume": r.volume,
                "value": r.value,
                "source": r.source,
            }
            for r in rows
        ]


def get_latest_candle(symbol: str) -> Optional[dict]:
    """Get the most recent OHLCV candle for a symbol."""
    with _get_session() as db:
        stmt = (
            select(TickerDaily)
            .where(TickerDaily.symbol == symbol)
            .order_by(TickerDaily.date.desc())
            .limit(1)
        )
        result = db.execute(stmt)
        row = result.scalar_one_or_none()

        if not row:
            return None

        return {
            "symbol": row.symbol,
            "date": row.date,
            "open": row.open,
            "high": row.high,
            "low": row.low,
            "close": row.close,
            "volume": row.volume,
            "value": row.value,
        }


def get_warehouse_status() -> dict:
    """Get warehouse statistics."""
    with _get_session() as db:
        total_rows = db.execute(select(func.count(TickerDaily.id))).scalar() or 0
        symbols_covered = db.execute(
            select(func.count(func.distinct(TickerDaily.symbol)))
            .scalar() or 0
        )

        latest_row = db.execute(
            select(TickerDaily).order_by(TickerDaily.date.desc()).limit(1)
        ).scalar_one_or_none()

        latest_date = latest_row.date if latest_row else None
        last_update_time = latest_row.created_at if latest_row else None

        max_date = db.execute(
            select(func.max(TickerDaily.date))
        ).scalar()

        today = date.today()
        backfill_pending = 0

        if max_date:
            universe_count = db.execute(
                select(func.count(StockUniverse.symbol))
            ).scalar() or 0
            covered_count = db.execute(
                select(func.count(func.distinct(TickerDaily.symbol)))
            ).scalar() or 0

            if max_date < today - timedelta(days=1):
                backfill_pending = max(0, universe_count - covered_count)

        watchlist_symbols = db.execute(
            select(func.distinct(WatchlistItem.symbol))
        ).scalars().all()
        watchlist_symbols_list = list(watchlist_symbols)
        watchlist_total = len(watchlist_symbols_list)

        watchlist_covered = 0
        if watchlist_symbols_list:
            watchlist_covered = db.execute(
                select(func.count(func.distinct(TickerDaily.symbol)))
                .where(TickerDaily.symbol.in_(watchlist_symbols_list))
            ).scalar() or 0

        return {
            "total_rows": total_rows,
            "symbols_covered": symbols_covered,
            "latest_date": latest_date,
            "last_update_time": last_update_time,
            "backfill_pending": backfill_pending,
            "backfill_progress_percent": (
                0.0 if symbols_covered == 0 else 100.0
            ),
            "watchlist_symbols_covered": watchlist_covered,
            "watchlist_symbols_total": watchlist_total,
        }


def get_symbols_needing_backfill() -> list[str]:
    """
    Get symbols that need backfilling, prioritized.

    Returns:
        List of symbols, watchlist symbols first, then universe.
    """
    with _get_session() as db:
        watchlist_symbols = db.execute(
            select(func.distinct(WatchlistItem.symbol))
        ).scalars().all()

        universe_symbols = db.execute(
            select(StockUniverse.symbol)
        ).scalars().all()

    priority_symbols = []
    other_symbols = []

    for sym in universe_symbols:
        with _get_session() as db:
            latest = db.execute(
                select(func.max(TickerDaily.date)).where(
                    TickerDaily.symbol == sym
                )
            ).scalar()

        if sym in watchlist_symbols:
            if latest is None or latest < date.today() - timedelta(days=1):
                priority_symbols.append(sym)
        else:
            if latest is None or latest < date.today() - timedelta(days=1):
                other_symbols.append(sym)

    return priority_symbols + other_symbols


def get_watchlist_symbols() -> list[str]:
    """Get all unique symbols from all watchlists."""
    with _get_session() as db:
        symbols = db.execute(
            select(func.distinct(WatchlistItem.symbol))
        ).scalars().all()
        return list(symbols)


def get_all_universe_symbols() -> list[str]:
    """Get all symbols from stock_universe that are EQ series."""
    with _get_session() as db:
        symbols = db.execute(
            select(StockUniverse.symbol)
        ).scalars().all()
        return list(symbols)