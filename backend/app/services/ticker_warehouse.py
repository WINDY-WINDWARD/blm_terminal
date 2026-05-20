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
from io import StringIO
from typing import Generator, Optional

import pytz

import pandas as pd
import requests
import nsepython
from sqlalchemy import and_, func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.models.ticker import TickerDaily
from app.models.stockuniverse import StockUniverse
from app.models.watchlist import WatchlistItem
from app.database import _SyncSessionLocal
from app.services.indicators import compute_indicators_for_latest_candle

logger = logging.getLogger(__name__)

NSE_HISTORICAL_URL = "https://www.nseindia.com/api/historicalOR/generateSecurityWiseHistoricalData"

TICKER_SERIES_FILTER = "EQ"
DEFAULT_BACKFILL_DAYS = 365
MIN_EXPECTED_ROWS = 200  # ~1 year of trading days
REQUEST_DELAY_SECONDS = 3.0

_IST = pytz.timezone("Asia/Kolkata")
_MARKET_CLOSE_HOUR = 15
_MARKET_CLOSE_MINUTE = 30


def get_last_trading_day() -> date:
    """Return the most recent trading day for which end-of-day data should exist.

    Rules:
    - If today is a weekday AND current IST time is at or after market close
      (15:30), today counts as the last trading day.
    - Otherwise return the most recent weekday before today.
    - Weekends (Sat/Sun) are skipped; public holidays are NOT modelled here
      (NSE bhavcopy simply won't have data for them and the daily update will
      skip those dates gracefully).
    """
    now_ist = datetime.now(_IST)
    candidate = now_ist.date()

    # If it's a weekday and market has closed, today is the last trading day
    if candidate.weekday() < 5:
        market_close = now_ist.replace(
            hour=_MARKET_CLOSE_HOUR,
            minute=_MARKET_CLOSE_MINUTE,
            second=0,
            microsecond=0,
        )
        if now_ist >= market_close:
            return candidate

    # Step back to the most recent weekday
    candidate -= timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate -= timedelta(days=1)
    return candidate


def _get_session() -> Generator[Session, None, None]:
    """Get a sync DB session."""
    return _SyncSessionLocal()


_session = requests.Session()
_session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/csv,application/csv,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
    "Origin": "https://www.nseindia.com",
})


def _refresh_nse_session() -> None:
    """Re-initialize NSE session by fetching homepage to get fresh cookies."""
    try:
        _session.get("https://www.nseindia.com/", timeout=15)
        time.sleep(2)
    except Exception as e:
        logger.debug(f"_refresh_nse_session: failed to refresh session: {e}")


def _nse_equity_history_sync(symbol: str, start_date: str, end_date: str, _attempt: int = 1) -> pd.DataFrame:
    """Fetch equity history via the new NSE historical CSV API.

    Includes retry with exponential backoff and session refresh on failure.
    """
    timeouts = (30, 45, 60)
    max_attempts = 3

    for attempt in range(_attempt, max_attempts + 1):
        try:
            params = {
                "symbol": symbol,
                "type": "priceVolume",
                "series": "ALL",
                "from": start_date,
                "to": end_date,
                "csv": "true",
            }
            timeout = timeouts[attempt - 1]
            resp = _session.get(NSE_HISTORICAL_URL, params=params, timeout=timeout)
            resp.raise_for_status()
            df = pd.read_csv(StringIO(resp.text))
            if df.empty:
                return pd.DataFrame()
            new_cols = []
            for col in df.columns:
                col = col.strip()
                col = col.replace("ï»¿", "").replace('"', "")
                new_cols.append(col)
            df.columns = new_cols
            rename = {}
            for col in df.columns:
                lower = col.lower()
                if "symbol" in lower:
                    rename[col] = "CH_SYMBOL"
                elif "series" in lower:
                    rename[col] = "CH_SERIES"
                elif lower.startswith("date"):
                    rename[col] = "CH_TIMESTAMP"
                elif "open price" in lower:
                    rename[col] = "CH_OPENING_PRICE"
                elif "high price" in lower:
                    rename[col] = "CH_TRADE_HIGH_PRICE"
                elif "low price" in lower:
                    rename[col] = "CH_TRADE_LOW_PRICE"
                elif "close price" in lower:
                    rename[col] = "CH_CLOSING_PRICE"
                elif "traded quantity" in lower:
                    rename[col] = "CH_TOT_TRADED_QTY"
                elif "turnover" in lower:
                    rename[col] = "CH_TOT_TRADED_VAL"
            df = df.rename(columns=rename)
            df = df[df.get("CH_SERIES", "") == "EQ"].copy() if "CH_SERIES" in df.columns else df
            return df
        except Exception as e:
            logger.warning(f"_nse_equity_history_sync: attempt {attempt}/{max_attempts} failed for {symbol}: {e}")
            if attempt < max_attempts:
                backoff = 5 * (2 ** (attempt - 1))
                logger.info(f"_nse_equity_history_sync: backing off {backoff}s before retry")
                _refresh_nse_session()
                time.sleep(backoff)
                continue
            else:
                logger.warning(f"_nse_equity_history_sync: all attempts failed for {symbol}")
                return pd.DataFrame()

    return pd.DataFrame()


def backfill_symbol(symbol: str, days: int = DEFAULT_BACKFILL_DAYS) -> int:
    """
    Backfill OHLCV data for a single symbol.

    Fetches `days` trading days of history via equity_history() API.
    The API has a ~11 month limit, so we split into 2 requests if needed.

    Returns:
        Number of rows inserted/updated.
    """
    today = date.today()
    start_dt = today - timedelta(days=days + 50)
    start_date = start_dt.strftime("%d-%m-%Y")
    end_date = today.strftime("%d-%m-%Y")

    logger.info(f"backfill_symbol: fetching {symbol} from {start_date} to {end_date}")

    df = _nse_equity_history_sync(symbol, start_date, end_date)

    if df.empty:
        mid_date = (today - timedelta(days=180)).strftime("%d-%m-%Y")
        logger.info(f"backfill_symbol: trying split at {mid_date}")
        df1 = _nse_equity_history_sync(symbol, start_date, mid_date)
        time.sleep(REQUEST_DELAY_SECONDS)
        df2 = _nse_equity_history_sync(symbol, mid_date, end_date)
        if not df1.empty and not df2.empty:
            df = pd.concat([df1, df2], ignore_index=True)
        elif not df2.empty:
            df = df2
        else:
            df = df1

    if df.empty:
        logger.warning(f"backfill_symbol: empty result for {symbol}")
        return 0

    if "CH_SERIES" not in df.columns:
        logger.warning(f"backfill_symbol: invalid response for {symbol}")
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

    required_cols = ["date", "open", "high", "low", "close", "volume", "value"]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        logger.warning(f"backfill_symbol: missing columns {missing} for {symbol}")
        return 0

    df["symbol"] = symbol
    df["series"] = TICKER_SERIES_FILTER
    df["source"] = "equity_history"
    df["created_at"] = datetime.now()

    df["date"] = pd.to_datetime(df["date"], format="%d-%b-%Y").dt.date

    def clean_numeric(val):
        if pd.isna(val):
            return 0.0
        if isinstance(val, (int, float)):
            return float(val)
        return float(str(val).replace(",", ""))

    numeric_cols = ["open", "high", "low", "close", "volume", "value"]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = df[col].apply(clean_numeric)

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

    # Compute indicators for the latest candle now that data is stored.
    # Full per-candle backfill is handled separately by _ticker_indicators_sync.
    try:
        compute_indicators_for_latest_candle(symbol)
    except Exception as e:
        logger.warning(f"backfill_symbol: indicator computation failed for {symbol}: {e}")

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

    # Update indicators for each symbol that received a fresh candle.
    inserted_symbols = df["symbol"].unique().tolist()
    for sym in inserted_symbols:
        try:
            compute_indicators_for_latest_candle(sym)
        except Exception as e:
            logger.warning(f"bulk_update_via_bhavcopy: indicator update failed for {sym}: {e}")

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

    try:
        compute_indicators_for_latest_candle(symbol)
    except Exception as e:
        logger.warning(f"update_symbol_today: indicator computation failed for {symbol}: {e}")

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
    last_trading_day = get_last_trading_day()

    with _get_session() as db:
        total_rows = db.execute(select(func.count(TickerDaily.id))).scalar() or 0
        symbols_covered = db.execute(
            select(func.count(func.distinct(TickerDaily.symbol)))
        ).scalar() or 0

        latest_row = db.execute(
            select(TickerDaily).order_by(TickerDaily.date.desc()).limit(1)
        ).scalar_one_or_none()

        latest_date = latest_row.date if latest_row else None
        last_update_time = latest_row.created_at if latest_row else None

        universe_count = db.execute(
            select(func.count(StockUniverse.symbol))
        ).scalar() or 0

        # Count symbols whose most recent candle is on the last trading day
        current_symbols = db.execute(
            select(func.count())
            .select_from(
                select(TickerDaily.symbol)
                .group_by(TickerDaily.symbol)
                .having(func.max(TickerDaily.date) >= last_trading_day)
                .subquery()
            )
        ).scalar() or 0

        # Stale = in universe but max date is behind last trading day
        all_symbol_max = db.execute(
            select(TickerDaily.symbol, func.max(TickerDaily.date).label("max_date"))
            .group_by(TickerDaily.symbol)
        ).fetchall()

        universe_symbols = set(
            db.execute(select(StockUniverse.symbol)).scalars().all()
        )

        stale_count = sum(
            1 for sym, max_date in all_symbol_max
            if sym in universe_symbols and (max_date is None or max_date < last_trading_day)
        )
        # Also count universe symbols with zero rows
        symbols_with_any_rows = {sym for sym, _ in all_symbol_max}
        stale_count += sum(1 for sym in universe_symbols if sym not in symbols_with_any_rows)

        backfill_progress_percent = (
            round((current_symbols / universe_count) * 100, 1)
            if universe_count > 0
            else 0.0
        )

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
            "symbols_current": current_symbols,
            "symbols_stale": stale_count,
            "last_trading_day": last_trading_day,
            "latest_date": latest_date,
            "last_update_time": last_update_time,
            "backfill_pending": stale_count,
            "backfill_progress_percent": backfill_progress_percent,
            "watchlist_symbols_covered": watchlist_covered,
            "watchlist_symbols_total": watchlist_total,
        }


def get_symbols_needing_backfill() -> list[str]:
    """
    Get symbols that need backfilling, prioritized by watchlist.

    A symbol needs backfill if:
      - It has fewer than MIN_EXPECTED_ROWS rows (historical data missing), OR
      - Its most recent date is older than the last trading day (stale data).

    Watchlist symbols are returned first, then the rest of universe.

    Returns:
        List of symbols needing backfill.
    """
    last_trading_day = get_last_trading_day()

    with _get_session() as db:
        watchlist_symbols = set(
            db.execute(select(func.distinct(WatchlistItem.symbol))).scalars().all()
        )

        universe_symbols = db.execute(select(StockUniverse.symbol)).scalars().all()

        if not universe_symbols:
            return []

        rows = (
            db.execute(
                select(
                    TickerDaily.symbol,
                    func.count(TickerDaily.id).label("cnt"),
                    func.max(TickerDaily.date).label("max_date"),
                )
                .where(TickerDaily.symbol.in_(universe_symbols))
                .group_by(TickerDaily.symbol)
            )
            .fetchall()
        )

    stats_by_symbol = {row[0]: (row[1], row[2]) for row in rows}

    priority_symbols = []
    other_symbols = []

    for sym in universe_symbols:
        row_count, max_date = stats_by_symbol.get(sym, (0, None))
        needs_backfill = (
            row_count < MIN_EXPECTED_ROWS
            or max_date is None
            or max_date < last_trading_day
        )

        if not needs_backfill:
            continue

        if sym in watchlist_symbols:
            priority_symbols.append(sym)
        else:
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