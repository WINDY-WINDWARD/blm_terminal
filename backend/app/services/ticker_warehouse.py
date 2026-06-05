"""
Ticker warehouse service — fetches and stores daily OHLCV data from NSE.

Two data sources:
1. equity_history(symbol, start, end) — per-symbol historical API (used for backfill)
2. get_bhavcopy(date) — single CSV for all symbols (used for daily incremental)

This module is used by background workers and the ticker router.
"""

import logging
import time
from datetime import date, datetime, timedelta, timezone
from io import StringIO
from typing import Generator, Optional
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import nsepython
from sqlalchemy import and_, func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.models.ticker import TickerDaily, TickerIntraday
from app.models.stockuniverse import StockUniverse
from app.models.watchlist import WatchlistItem
from app.database import _SyncSessionLocal
from app.services.indicators import compute_indicators_for_latest_candle

logger = logging.getLogger(__name__)

TICKER_FAILURE_THRESHOLD = 3

NSE_HISTORICAL_URL = "https://www.nseindia.com/api/historicalOR/generateSecurityWiseHistoricalData"

TICKER_SERIES_FILTER = "EQ"
DEFAULT_BACKFILL_DAYS = 365
MIN_EXPECTED_ROWS = 200  # ~1 year of trading days
REQUEST_DELAY_SECONDS = 3.0

_IST = ZoneInfo("Asia/Kolkata")
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


def _backfill_symbol_charting(symbol: str, days: int) -> int:
    """Backfill using NSE charting API (deep history in one request).

    Looks up the symbol's NSE series from stock_universe DB first so the
    charting API uses the correct suffix (e.g. -BE instead of -EQ).
    If the symbol is not in stock_universe, the charting client falls back
    through its own series preference loop (EQ → BE → SM → ST).

    Args:
        symbol: NSE ticker.
        days:  How many calendar days of history to request.

    Returns:
        Number of rows inserted/updated (0 on failure).
    """
    from app.services.nse_charting_client import fetch_candles  # avoid circular at module level

    # Look up the correct series from stock_universe (e.g. 'BE' for BODALCHEM)
    discovered_series: str | None = None
    with _get_session() as db:
        row = db.execute(
            select(StockUniverse.series).where(StockUniverse.symbol == symbol)
        ).scalar_one_or_none()
        if row:
            discovered_series = row

    today = date.today()
    start_dt = today - timedelta(days=days + 30)
    from_ts = int(datetime.combine(start_dt, datetime.min.time(), tzinfo=timezone.utc).timestamp())
    to_ts = int(datetime.combine(today, datetime.max.time(), tzinfo=timezone.utc).timestamp())

    logger.info(
        f"backfill_symbol_charting: fetching {symbol} (series={discovered_series!r}) "
        f"from {start_dt} to {today}"
    )

    try:
        candles = fetch_candles(symbol, "D", from_ts=from_ts, to_ts=to_ts, series=discovered_series)
    except Exception as exc:
        logger.warning(f"backfill_symbol_charting: charting API failed for {symbol}: {exc}")
        return 0

    if not candles:
        logger.warning(f"backfill_symbol_charting: no candles returned for {symbol}")
        return 0

    rows = []
    for c in candles:
        ts_ms = c.get("time_ms")
        if not ts_ms:
            continue
        dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).date()
        close_val = float(c.get("close", 0))
        volume_val = int(c.get("volume", 0))
        # Approximate traded value: close * volume
        value_val = close_val * volume_val
        rows.append({
            "symbol": symbol,
            "date": dt,
            "series": TICKER_SERIES_FILTER,
            "open": float(c.get("open", 0)),
            "high": float(c.get("high", 0)),
            "low": float(c.get("low", 0)),
            "close": close_val,
            "volume": volume_val,
            "value": value_val,
            "source": "nse_charting",
            "created_at": datetime.now(),
        })

    if not rows:
        return 0

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

    logger.info(f"backfill_symbol_charting: upserted {len(rows)} rows for {symbol}")
    return len(rows)


def _backfill_symbol_equity_history(symbol: str, days: int) -> int:
    """Legacy backfill using nsepython.equity_history (shallow history, chunked)."""
    today = date.today()
    start_dt = today - timedelta(days=days + 50)
    start_date = start_dt.strftime("%d-%m-%Y")
    end_date = today.strftime("%d-%m-%Y")

    logger.info(f"backfill_symbol_equity: fetching {symbol} from {start_date} to {end_date}")

    df = _nse_equity_history_sync(symbol, start_date, end_date)

    if df.empty:
        mid_date = (today - timedelta(days=180)).strftime("%d-%m-%Y")
        logger.info(f"backfill_symbol_equity: trying split at {mid_date}")
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
        logger.warning(f"backfill_symbol_equity: empty result for {symbol}")
        return 0

    if "CH_SERIES" not in df.columns:
        logger.warning(f"backfill_symbol_equity: invalid response for {symbol}")
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
        logger.warning(f"backfill_symbol_equity: missing columns {missing} for {symbol}")
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

    logger.info(f"backfill_symbol_equity: upserted {len(rows)} rows for {symbol}")
    return len(rows)


def backfill_symbol(symbol: str, days: int = DEFAULT_BACKFILL_DAYS) -> int:
    """
    Backfill OHLCV data for a single symbol.

    Primary: NSE charting API (deep history, single request).
    Fallback: nsepython.equity_history (legacy, chunked, ~11 month limit).

    Returns:
        Number of rows inserted/updated.
    """
    # Try charting API first — deep history in one shot
    rows = _backfill_symbol_charting(symbol, days)
    if rows > 0:
        # Compute indicators for the latest candle
        try:
            compute_indicators_for_latest_candle(symbol)
        except Exception as e:
            logger.warning(f"backfill_symbol: indicator computation failed for {symbol}: {e}")
        return rows

    # Fallback to legacy equity_history
    rows = _backfill_symbol_equity_history(symbol, days)
    if rows > 0:
        try:
            compute_indicators_for_latest_candle(symbol)
        except Exception as e:
            logger.warning(f"backfill_symbol: indicator computation failed for {symbol}: {e}")
    return rows


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
        watchlist_current = 0
        if watchlist_symbols_list:
            watchlist_covered = db.execute(
                select(func.count(func.distinct(TickerDaily.symbol)))
                .where(TickerDaily.symbol.in_(watchlist_symbols_list))
            ).scalar() or 0
            # Watchlist symbols with data on the last trading day
            watchlist_current = db.execute(
                select(func.count())
                .select_from(
                    select(TickerDaily.symbol)
                    .where(TickerDaily.symbol.in_(watchlist_symbols_list))
                    .group_by(TickerDaily.symbol)
                    .having(func.max(TickerDaily.date) >= last_trading_day)
                    .subquery()
                )
            ).scalar() or 0

        # --- Days-behind breakdown for universe symbols ---
        # Build a map of symbol -> most recent date (for universe symbols only)
        sym_max_date: dict[str, date | None] = {sym: None for sym in universe_symbols}
        for sym, max_date in all_symbol_max:
            if sym in universe_symbols:
                sym_max_date[sym] = max_date

        def _weekdays_behind(d: date | None) -> int:
            """Return how many weekdays behind `d` is relative to last_trading_day."""
            if d is None:
                return 999  # never had data
            if d >= last_trading_day:
                return 0
            # Count weekdays between d (exclusive) and last_trading_day (inclusive)
            behind = 0
            cursor = d + timedelta(days=1)
            while cursor <= last_trading_day:
                if cursor.weekday() < 5:
                    behind += 1
                cursor += timedelta(days=1)
            return behind

        days_behind_breakdown: dict[str, int] = {"0": 0, "1": 0, "2": 0, "3+": 0}
        for sym in universe_symbols:
            behind = _weekdays_behind(sym_max_date.get(sym))
            if behind == 0:
                days_behind_breakdown["0"] += 1
            elif behind == 1:
                days_behind_breakdown["1"] += 1
            elif behind == 2:
                days_behind_breakdown["2"] += 1
            else:
                days_behind_breakdown["3+"] += 1

        # --- Intraday stats (1h / W / M) ---
        intraday_stats: dict[str, dict] = {}
        today = datetime.now().date()
        today_0915 = datetime.combine(today, datetime.min.time().replace(hour=9, minute=15))

        for interval in ("1h", "W", "M"):
            iv_total = db.execute(
                select(func.count(TickerIntraday.id))
                .where(TickerIntraday.interval == interval)
            ).scalar() or 0

            iv_latest_ts = db.execute(
                select(func.max(TickerIntraday.timestamp))
                .where(TickerIntraday.interval == interval)
            ).scalar()

            iv_watchlist_covered = 0
            iv_watchlist_current = 0
            iv_symbols_with_indicators = 0
            if watchlist_symbols_list:
                iv_watchlist_covered = db.execute(
                    select(func.count(func.distinct(TickerIntraday.symbol)))
                    .where(
                        TickerIntraday.interval == interval,
                        TickerIntraday.symbol.in_(watchlist_symbols_list),
                    )
                ).scalar() or 0

                if interval == "1h":
                    iv_watchlist_current = db.execute(
                        select(func.count(func.distinct(TickerIntraday.symbol)))
                        .where(
                            TickerIntraday.interval == interval,
                            TickerIntraday.symbol.in_(watchlist_symbols_list),
                            TickerIntraday.timestamp >= today_0915,
                        )
                    ).scalar() or 0

                iv_symbols_with_indicators = db.execute(
                    select(func.count(func.distinct(TickerIntraday.symbol)))
                    .where(
                        TickerIntraday.interval == interval,
                        TickerIntraday.symbol.in_(watchlist_symbols_list),
                        TickerIntraday.indicators_updated_at.isnot(None),
                    )
                ).scalar() or 0

            # Universe coverage — tracked for W and M (which are now universe-scoped)
            iv_universe_covered = 0
            iv_universe_symbols_with_indicators = 0
            if interval in ("W", "M"):
                universe_symbol_list = list(universe_symbols)
                iv_universe_covered = db.execute(
                    select(func.count(func.distinct(TickerIntraday.symbol)))
                    .where(
                        TickerIntraday.interval == interval,
                        TickerIntraday.symbol.in_(universe_symbol_list),
                    )
                ).scalar() or 0

                iv_universe_symbols_with_indicators = db.execute(
                    select(func.count(func.distinct(TickerIntraday.symbol)))
                    .where(
                        TickerIntraday.interval == interval,
                        TickerIntraday.symbol.in_(universe_symbol_list),
                        TickerIntraday.indicators_updated_at.isnot(None),
                    )
                ).scalar() or 0

            intraday_stats[interval] = {
                "total_rows": iv_total,
                "watchlist_covered": iv_watchlist_covered,
                "watchlist_current": iv_watchlist_current,
                "symbols_with_indicators": iv_symbols_with_indicators,
                "latest_timestamp": iv_latest_ts,
                "universe_covered": iv_universe_covered,
                "universe_symbols_with_indicators": iv_universe_symbols_with_indicators,
            }

        return {
            "total_rows": total_rows,
            "symbols_covered": symbols_covered,
            "symbols_current": current_symbols,
            "symbols_stale": stale_count,
            "universe_count": universe_count,
            "last_trading_day": last_trading_day,
            "latest_date": latest_date,
            "last_update_time": last_update_time,
            "backfill_pending": stale_count,
            "backfill_progress_percent": backfill_progress_percent,
            "watchlist_symbols_covered": watchlist_covered,
            "watchlist_symbols_total": watchlist_total,
            "watchlist_symbols_current": watchlist_current,
            "days_behind_breakdown": days_behind_breakdown,
            "intraday_stats": intraday_stats,
        }


def get_symbols_needing_backfill() -> list[str]:
    """
    Get symbols that need backfilling, prioritized by watchlist.

    A symbol needs backfill if:
      - It has fewer than MIN_EXPECTED_ROWS rows (historical data missing), OR
      - Its most recent date is older than the DB consensus date (stale data).

    Consensus date = the most common max(date) across all stored symbols in the
    universe. This avoids the pitfall of using `get_last_trading_day()` as a live
    reference, which would mark *every* symbol as stale on a non-bhavcopy day
    (e.g. market closed weekends/holidays) and trigger a full universe re-fetch.

    Excludes symbols with `review_status` in ('removed', 'ticker_error').

    Watchlist symbols are returned first, then the rest of universe.

    Returns:
        List of symbols needing backfill.
    """
    from collections import Counter

    with _get_session() as db:
        watchlist_symbols = set(
            db.execute(select(func.distinct(WatchlistItem.symbol))).scalars().all()
        )

        universe_symbols = db.execute(
            select(StockUniverse.symbol).where(
                StockUniverse.review_status.notin_(["removed", "ticker_error"])
            )
        ).scalars().all()

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

    # Compute DB consensus: most common max_date across stored symbols
    max_dates = [row[2] for row in rows if row[2] is not None]
    consensus_date = Counter(max_dates).most_common(1)[0][0] if max_dates else None
    if consensus_date is not None:
        logger.info(
            "[daily_stale] consensus max_date = %s (shared by %d/%d stored symbols)",
            consensus_date,
            sum(1 for d in max_dates if d == consensus_date),
            len(max_dates),
        )

    priority_symbols = []
    other_symbols = []

    for sym in universe_symbols:
        row_count, max_date = stats_by_symbol.get(sym, (0, None))
        needs_backfill = (
            row_count < MIN_EXPECTED_ROWS
            or max_date is None
            or (consensus_date is not None and max_date < consensus_date)
        )

        if not needs_backfill:
            continue

        if sym in watchlist_symbols:
            priority_symbols.append(sym)
        else:
            other_symbols.append(sym)

    total = len(priority_symbols) + len(other_symbols)
    if total == 0:
        logger.info("[daily_stale] all symbols up to date (consensus=%s)", consensus_date)
    else:
        logger.info(
            "[daily_stale] %d/%d universe symbols need backfill (consensus=%s)",
            total, len(universe_symbols), consensus_date,
        )

    return priority_symbols + other_symbols


def get_watchlist_symbols() -> list[str]:
    """Get all unique symbols from all watchlists."""
    with _get_session() as db:
        symbols = db.execute(
            select(func.distinct(WatchlistItem.symbol))
        ).scalars().all()
        return list(symbols)


def get_all_universe_symbols() -> list[str]:
    """Get all symbols from stock_universe, excluding removed and ticker-disabled."""
    with _get_session() as db:
        symbols = db.execute(
            select(StockUniverse.symbol).where(
                StockUniverse.review_status.notin_(["removed", "ticker_error"])
            )
        ).scalars().all()
        return list(symbols)


def get_symbols_needing_intraday_backfill(
    intervals: list[str],
    symbols: list[str],
) -> Optional[dict[str, list[str]]]:
    """Get symbols whose W/M candles are stale compared to DB consensus.

    Computes the most common latest timestamp across all *stored* symbols per
    interval (DB consensus). Symbols whose max timestamp is before that consensus
    are considered stale. New symbols (no rows) are always stale.

    This avoids the pitfall of using a live API reference, which can return an
    *incomplete* current period (e.g. current week just started on Monday)
    while the DB only contains *completed* periods (last week). That mismatch
    caused every symbol to appear stale and triggered a full universe re-fetch.

    Args:
        intervals: List of intervals to check (e.g. ["W", "M"]).
        symbols:   Candidate symbols to evaluate.

    Returns:
        None  → DB query failed.
        {}    → all symbols are up to date.
        {"W": [...], "M": [...]} → stale symbols per interval.
    """
    if not symbols:
        return {}

    symbol_set = set(symbols)

    with _get_session() as db:
        try:
            rows = db.execute(
                select(
                    TickerIntraday.symbol,
                    TickerIntraday.interval,
                    func.max(TickerIntraday.timestamp).label("max_ts"),
                )
                .where(
                    TickerIntraday.symbol.in_(symbol_set),
                    TickerIntraday.interval.in_(intervals),
                )
                .group_by(TickerIntraday.symbol, TickerIntraday.interval)
            ).fetchall()
        except Exception as exc:
            logger.warning("[wm_stale] DB query failed: %s", exc)
            return None

    max_ts_by_sym_iv: dict[tuple[str, str], datetime] = {
        (row[0], row[1]): row[2] for row in rows
    }

    # Build consensus reference timestamp per interval: the most common max_ts
    from collections import Counter

    reference_ts: dict[str, datetime] = {}
    for iv in intervals:
        timestamps = [
            max_ts_by_sym_iv[(sym, iv)]
            for sym in symbols
            if (sym, iv) in max_ts_by_sym_iv and max_ts_by_sym_iv[(sym, iv)] is not None
        ]
        if not timestamps:
            # No symbol has data for this interval → all are stale
            reference_ts[iv] = None
            logger.info("[wm_stale] no stored data for interval %s", iv)
            continue

        most_common_ts, count = Counter(timestamps).most_common(1)[0]
        reference_ts[iv] = most_common_ts
        logger.info(
            "[wm_stale] consensus ref %s = %s (shared by %d/%d symbols)",
            iv, most_common_ts, count, len(timestamps),
        )

    stale_map: dict[str, list[str]] = {}
    for iv in intervals:
        ref_ts = reference_ts[iv]
        stale_symbols: list[str] = []
        for sym in symbols:
            max_ts = max_ts_by_sym_iv.get((sym, iv))
            if max_ts is None:
                # No stored data → definitely needs backfill
                stale_symbols.append(sym)
            elif ref_ts is not None and max_ts < ref_ts:
                # Older than consensus → stale
                stale_symbols.append(sym)
            # max_ts >= ref_ts  → up to date (including symbols ahead of consensus)
        if stale_symbols:
            stale_map[iv] = stale_symbols

    total_stale = sum(len(s) for s in stale_map.values())
    logger.info(
        "[wm_stale] %d/%d symbols need backfill across intervals %s",
        total_stale, len(symbols), intervals,
    )

    return stale_map


# ---------------------------------------------------------------------------
# Intraday / Weekly / Monthly OHLCV  (ticker_intraday table)
# ---------------------------------------------------------------------------

def upsert_intraday(
    symbol: str,
    interval: str,
    rows: list[dict],
    db: Optional[Session] = None,
) -> int:
    """Upsert intraday/weekly/monthly candle rows for *symbol* + *interval*.

    Args:
        symbol:   NSE ticker (e.g. "RELIANCE").
        interval: "1h", "W", or "M".
        rows:     List of dicts from nse_charting_client.fetch_candles():
                  [{time_ms, open, high, low, close, volume}, ...]
        db:       Optional existing sync Session; if None a new one is opened.

    Returns:
        Number of rows upserted.
    """
    if not rows:
        return 0

    def _do_upsert(session: Session) -> int:
        records = []
        for r in rows:
            ts_utc = datetime.fromtimestamp(r["time_ms"] / 1000, tz=timezone.utc).replace(tzinfo=None)
            records.append({
                "symbol":    symbol,
                "timestamp": ts_utc,
                "interval":  interval,
                "open":      r["open"],
                "high":      r["high"],
                "low":       r["low"],
                "close":     r["close"],
                "volume":    r["volume"],
                "source":    "nse_charting",
            })

        stmt = sqlite_insert(TickerIntraday).values(records)
        stmt = stmt.on_conflict_do_update(
            index_elements=["symbol", "timestamp", "interval"],
            set_={
                "open":   stmt.excluded.open,
                "high":   stmt.excluded.high,
                "low":    stmt.excluded.low,
                "close":  stmt.excluded.close,
                "volume": stmt.excluded.volume,
                "source": stmt.excluded.source,
            },
        )
        session.execute(stmt)
        session.commit()
        return len(records)

    if db is not None:
        return _do_upsert(db)
    with _get_session() as session:
        return _do_upsert(session)


def get_intraday(
    symbol: str,
    interval: str,
    from_ts: Optional[int] = None,
    to_ts: Optional[int] = None,
    db: Optional[Session] = None,
) -> list[dict]:
    """Retrieve stored intraday/weekly/monthly candles for *symbol* + *interval*.

    Args:
        symbol:   NSE ticker.
        interval: "1h", "W", or "M".
        from_ts:  Start filter as Unix *milliseconds* (inclusive). None = no filter.
        to_ts:    End filter as Unix *milliseconds* (inclusive). None = no filter.
        db:       Optional existing sync Session.

    Returns:
        List of dicts [{timestamp (unix ms), open, high, low, close, volume}]
        ordered oldest → newest.
    """
    def _do_get(session: Session) -> list[dict]:
        stmt = (
            select(TickerIntraday)
            .where(
                and_(
                    TickerIntraday.symbol == symbol,
                    TickerIntraday.interval == interval,
                )
            )
            .order_by(TickerIntraday.timestamp)
        )

        if from_ts is not None:
            from_dt = datetime.fromtimestamp(from_ts / 1000, tz=timezone.utc).replace(tzinfo=None)
            stmt = stmt.where(TickerIntraday.timestamp >= from_dt)
        if to_ts is not None:
            to_dt = datetime.fromtimestamp(to_ts / 1000, tz=timezone.utc).replace(tzinfo=None)
            stmt = stmt.where(TickerIntraday.timestamp <= to_dt)

        rows = session.execute(stmt).scalars().all()
        return [
            {
                "timestamp": int(r.timestamp.replace(tzinfo=timezone.utc).timestamp() * 1000),
                "open":   r.open,
                "high":   r.high,
                "low":    r.low,
                "close":  r.close,
                "volume": r.volume,
            }
            for r in rows
        ]

    if db is not None:
        return _do_get(db)
    with _get_session() as session:
        return _do_get(session)


def _increment_ticker_failure(symbol: str) -> None:
    """Increment ticker failure count; disable symbol at threshold."""
    with _get_session() as db:
        row = db.get(StockUniverse, symbol)
        if row is None:
            return
        row.ticker_failure_count = (row.ticker_failure_count or 0) + 1
        count = row.ticker_failure_count
        if count >= TICKER_FAILURE_THRESHOLD and row.review_status != "ticker_error":
            row.review_status = "ticker_error"
            logger.warning(
                "[ticker_failure] %s disabled after %d failures (review_status=ticker_error)",
                symbol, count,
            )
        db.commit()


def _reset_ticker_failure(symbol: str) -> None:
    """Reset ticker failure count and clear ticker_error status if set."""
    with _get_session() as db:
        row = db.get(StockUniverse, symbol)
        if row is None:
            return
        if row.ticker_failure_count != 0 or row.review_status == "ticker_error":
            row.ticker_failure_count = 0
            if row.review_status == "ticker_error":
                row.review_status = None
            db.commit()


def _symbol_has_intraday_data(
    symbol: str,
    interval: str,
    db: Optional[Session] = None,
) -> bool:
    """Check if a symbol already has stored intraday rows for a given interval."""
    def _check(session: Session) -> bool:
        count = session.execute(
            select(func.count(TickerIntraday.id))
            .where(TickerIntraday.symbol == symbol, TickerIntraday.interval == interval)
        ).scalar() or 0
        return count > 0

    if db is not None:
        return _check(db)
    with _get_session() as session:
        return _check(session)


def backfill_intraday_symbol(
    symbol: str,
    intervals: Optional[list[str]] = None,
    db: Optional[Session] = None,
    from_ts_overrides: Optional[dict[str, int]] = None,
) -> dict[str, int]:
    """Backfill intraday/weekly/monthly candles for a single symbol.

    Calls the NSE charting API for each interval and upserts into ticker_intraday.

    History depth:
      - "1h": last 90 days
      - "W", "M": all available history (fromDate=0)

    Args:
        symbol:    NSE ticker.
        intervals: List of intervals to backfill. Defaults to ["1h", "W", "M"].
        db:        Optional existing sync Session.
        from_ts_overrides: Optional dict mapping interval → from_ts (Unix seconds).
            When provided and the symbol already has data for that interval,
            the override is used instead of the default. New symbols (no rows)
            always get from_ts=0 to ensure full history.

    Returns:
        Dict mapping interval → number of rows upserted.
    """
    from app.services.nse_charting_client import fetch_candles  # avoid circular at module level

    if intervals is None:
        intervals = ["1h", "W", "M"]

    now_ts = int(datetime.now(timezone.utc).timestamp())
    counts: dict[str, int] = {}

    for iv in intervals:
        if iv == "1h":
            from_ts = int((datetime.now(timezone.utc) - timedelta(days=90)).timestamp())
        else:
            from_ts = 0  # all history

        # Apply override for W/M if symbol already has data
        if from_ts_overrides and iv in from_ts_overrides:
            has_data = _symbol_has_intraday_data(symbol, iv, db=db)
            if has_data:
                from_ts = from_ts_overrides[iv]
            else:
                from_ts = 0  # new symbol needs full history

        try:
            rows = fetch_candles(symbol, iv, from_ts=from_ts, to_ts=now_ts)
            n = upsert_intraday(symbol, iv, rows, db=db)
            counts[iv] = n
            logger.info("[intraday] %s/%s → %d rows upserted", symbol, iv, n)
        except Exception as exc:
            logger.warning("[intraday] backfill failed %s/%s: %s", symbol, iv, exc)
            counts[iv] = 0

    # Track success/failure for the symbol
    total_attempted = sum(counts.values())
    if total_attempted == 0:
        # All intervals failed — increment failure counter
        _increment_ticker_failure(symbol)
    else:
        # At least one interval succeeded — reset failure counter
        _reset_ticker_failure(symbol)

    return counts