import asyncio
import datetime
import logging

from sqlalchemy import func
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.services.nse_client import NSEClient
from app.models import stockuniverse
from app.database import AsyncSessionLocal
from app.config import settings
from app.services.news_fetcher import news_fetcher

logger = logging.getLogger(__name__)

_nse_client = NSEClient()

_db_lock = asyncio.Lock()


def _seconds_until_midnight() -> float:
    """Return seconds from now until the next 00:00:00 local time."""
    now = datetime.datetime.now()
    tomorrow_midnight = (now + datetime.timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return (tomorrow_midnight - now).total_seconds()


async def populate_stock_universe() -> None:
    """Upsert the full NSE stock universe into the database.

    Blocking NSE client calls are offloaded to a thread via asyncio.to_thread
    so the event loop (and therefore the API server) is never stalled.
    """
    logger.info("populate_stock_universe: fetching stock list from NSE")
    stock_list: list[str] = await asyncio.to_thread(_nse_client.get_stock_list)
    logger.info("populate_stock_universe: %d symbols to process", len(stock_list))

    # Skip updating symbols that have been refreshed within the last 30 days.
    stale_delta = datetime.timedelta(days=30)

    async with _db_lock:
        async with AsyncSessionLocal() as session:
            for symbol in stock_list:
                # Check existing record first to avoid unnecessary NSE requests
                existing = await session.get(stockuniverse.StockUniverse, symbol)
                # last_update_time in model is named `last_update_time`; other modules may use `last_fetched_at`.
                last_time = None
                if existing is not None:
                    last_time = getattr(existing, "last_update_time", None) or getattr(
                        existing, "last_fetched_at", None
                    )
                if last_time is not None:
                    try:
                        now = datetime.datetime.now()
                        if (now - last_time) < stale_delta:
                            logger.debug(
                                "Skipping %s — last update was %s (within %d days)",
                                symbol,
                                last_time,
                                stale_delta.days,
                            )
                            continue
                    except Exception:
                        # If comparison fails for any reason, proceed to refresh
                        logger.debug(
                            "Unable to compare last update time for %s; refreshing",
                            symbol,
                        )

                try:
                    metadata = await asyncio.to_thread(
                        _nse_client.get_stock_metadata, symbol
                    )
                except Exception:
                    logger.exception(
                        "Failed to fetch metadata for %s, skipping", symbol
                    )
                    await asyncio.sleep(1)
                    continue

                stmt = (
                    sqlite_insert(stockuniverse.StockUniverse)
                    .values(
                        symbol=metadata.symbol,
                        company_name=metadata.companyName,
                        segment=metadata.segment,
                        industry=metadata.industry,
                        sector_pe=metadata.sectorPE,
                        symbol_pe=metadata.symbolPE,
                        industry_info=metadata.industryInfo,
                        last_update_time=metadata.lastUpdateTime,
                    )
                    .on_conflict_do_update(
                        index_elements=["symbol"],
                        set_={
                            "company_name": metadata.companyName,
                            "segment": metadata.segment,
                            "industry": metadata.industry,
                            "sector_pe": metadata.sectorPE,
                            "symbol_pe": metadata.symbolPE,
                            "industry_info": metadata.industryInfo,
                            "last_update_time": metadata.lastUpdateTime,
                            "updated_at": func.now(),
                        },
                    )
                )
                await session.execute(stmt)
                await asyncio.sleep(1)

            await session.commit()
    logger.info("populate_stock_universe: done")


async def stock_universe_scheduler() -> None:
    """Run populate_stock_universe at startup then repeat every day at midnight.

    Designed to be started as an asyncio background task via asyncio.create_task().
    Handles CancelledError cleanly so the lifespan shutdown is not blocked.
    """
    try:
        logger.info("stock_universe_scheduler: initial run at startup")
        await populate_stock_universe()

        while True:
            wait = _seconds_until_midnight()
            logger.info(
                "stock_universe_scheduler: next run in %.0f s (next midnight)", wait
            )
            await asyncio.sleep(wait)
            await populate_stock_universe()
    except asyncio.CancelledError:
        logger.info("stock_universe_scheduler: cancelled, shutting down cleanly")


NEWS_CRAWL_INTERVAL = 5 * 60
NEWS_CRAWL_MAX_INTERVAL = 30 * 60


async def news_scheduler() -> None:
    """Run news crawl at startup (pages 1-6) then repeat every 5 minutes (page 1 only).

    Implements exponential backoff when the crawl returns 0 articles (indicating
    a 403 block from MoneyControl). Doubles the wait interval up to 30 minutes,
    then resets to 5 minutes on any successful crawl.

    Designed to be started as an asyncio background task via asyncio.create_task().
    Handles CancelledError cleanly so the lifespan shutdown is not blocked.
    """
    current_interval = NEWS_CRAWL_INTERVAL
    try:
        logger.info("news_scheduler: initial crawl of pages 1-6")
        async with _db_lock:
            async with AsyncSessionLocal() as session:
                stored = await news_fetcher.crawl_and_store(pages=6, db=session)
                if stored > 0:
                    current_interval = NEWS_CRAWL_INTERVAL

        while True:
            logger.info(
                "news_scheduler: next run in %d s (backoff: %s)",
                current_interval,
                current_interval > NEWS_CRAWL_INTERVAL,
            )
            await asyncio.sleep(current_interval)

            async with _db_lock:
                async with AsyncSessionLocal() as session:
                    stored = await news_fetcher.crawl_and_store(pages=1, db=session)

            if stored == 0:
                current_interval = min(current_interval * 2, NEWS_CRAWL_MAX_INTERVAL)
                logger.warning(
                    "news_scheduler: crawl returned 0 articles — backing off to %d s",
                    current_interval,
                )
            else:
                if current_interval > NEWS_CRAWL_INTERVAL:
                    logger.info(
                        "news_scheduler: crawl succeeded (%d articles) — resetting interval to %d s",
                        stored,
                        NEWS_CRAWL_INTERVAL,
                    )
                current_interval = NEWS_CRAWL_INTERVAL

    except asyncio.CancelledError:
        logger.info("news_scheduler: cancelled, shutting down cleanly")
        await news_fetcher.close()


WATCHLIST_NEWS_INTERVAL = 5 * 60
WATCHLIST_NEWS_STALE_SECONDS = 5 * 60


async def refresh_watchlist_news() -> None:
    """Fetch/refresh company news for all symbols in the watchlist."""
    from app.models.watchlist import WatchlistItem
    from app.models.news import NewsArticle
    from sqlalchemy import select, func
    from datetime import datetime, timedelta, timezone

    async with _db_lock:
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(WatchlistItem.symbol))
            symbols = [row[0] for row in result]

    if not symbols:
        logger.debug("refresh_watchlist_news: watchlist is empty, skipping")
        return

    logger.info(
        "refresh_watchlist_news: refreshing news for %d symbols: %s",
        len(symbols),
        symbols,
    )

    for symbol in symbols:
        async with _db_lock:
            async with AsyncSessionLocal() as session:
                stale_check = await session.execute(
                    select(func.max(NewsArticle.fetched_at)).where(
                        NewsArticle.company_symbol == symbol.upper()
                    )
                )
                latest = stale_check.scalar_one_or_none()

        if latest is not None:
            if latest.tzinfo is None:
                latest = latest.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - latest).total_seconds()
            if age < WATCHLIST_NEWS_STALE_SECONDS:
                logger.debug(
                    "refresh_watchlist_news: %s is fresh (age=%.0fs), skipping",
                    symbol,
                    age,
                )
                continue

        try:
            async with _db_lock:
                async with AsyncSessionLocal() as session:
                    count = await news_fetcher.fetch_company_news(
                        symbol=symbol, db=session
                    )
            logger.info(
                "refresh_watchlist_news: %s — %d articles stored/tagged", symbol, count
            )
        except Exception:
            logger.exception("refresh_watchlist_news: failed for %s", symbol)

        await asyncio.sleep(2)


async def watchlist_news_scheduler() -> None:
    """Run refresh_watchlist_news every 5 minutes."""
    try:
        logger.info("watchlist_news_scheduler: initial run at startup")
        await refresh_watchlist_news()

        while True:
            logger.info(
                "watchlist_news_scheduler: next run in %d s", WATCHLIST_NEWS_INTERVAL
            )
            await asyncio.sleep(WATCHLIST_NEWS_INTERVAL)
            await refresh_watchlist_news()
    except asyncio.CancelledError:
        logger.info("watchlist_news_scheduler: cancelled, shutting down cleanly")


def _is_market_open() -> bool:
    """Check if the market is currently open (Mon-Fri, 09:15-15:30 IST).

    Uses the server's local timezone. For more accurate IST handling,
    consider using pytz or zoneinfo.
    """
    import pytz

    now_utc = datetime.datetime.now(pytz.utc)
    now_ist = now_utc.astimezone(pytz.timezone("Asia/Kolkata"))

    # Check if it's a weekday (Mon=0, Fri=4, Sat=5, Sun=6)
    if now_ist.weekday() >= 5:
        return False

    # Check market hours (09:15 - 15:30 IST)
    market_start = now_ist.replace(
        hour=settings.market_start_hour,
        minute=settings.market_start_minute,
        second=0,
        microsecond=0,
    )
    market_end = now_ist.replace(
        hour=settings.market_end_hour,
        minute=settings.market_end_minute,
        second=0,
        microsecond=0,
    )

    return market_start <= now_ist <= market_end


def _seconds_until_market_open() -> float:
    """Calculate seconds until the next market open time (09:15 IST).

    Returns 0 if market is currently open.
    """
    import pytz

    now_utc = datetime.datetime.now(pytz.utc)
    now_ist = now_utc.astimezone(pytz.timezone("Asia/Kolkata"))

    # If it's Saturday or Sunday, calculate time until Monday 09:15
    if now_ist.weekday() == 5:  # Saturday
        days_until_monday = 2
    elif now_ist.weekday() == 6:  # Sunday
        days_until_monday = 1
    else:
        # It's a weekday
        market_start = now_ist.replace(
            hour=settings.market_start_hour,
            minute=settings.market_start_minute,
            second=0,
            microsecond=0,
        )

        if now_ist < market_start:
            # Before market open today
            return (market_start - now_ist).total_seconds()
        else:
            # After market close today, next open is tomorrow
            days_until_monday = 1
            # If it's Friday, next open is Monday
            if now_ist.weekday() == 4:
                days_until_monday = 3

    # Calculate next Monday 09:15
    next_open = now_ist + datetime.timedelta(days=days_until_monday)
    next_open = next_open.replace(
        hour=settings.market_start_hour,
        minute=settings.market_start_minute,
        second=0,
        microsecond=0,
    )

    return (next_open - now_ist).total_seconds()


async def refresh_market_data() -> None:
    """Fetch and store all industry and sector data from MoneyControl."""
    from app.services.mc_market_fetcher import market_data_fetcher

    async with _db_lock:
        async with AsyncSessionLocal() as session:
            await market_data_fetcher.refresh_all(session)


async def market_data_scheduler() -> None:
    """Run market data refresh during market hours only.

    Schedule:
    - Weekdays: Every 5 minutes during market hours (09:15-15:30 IST)
    - Weekends/After hours: Sleep until next market open

    Designed to be started as an asyncio background task via asyncio.create_task().
    Handles CancelledError cleanly so the lifespan shutdown is not blocked.
    """
    from app.services.mc_market_fetcher import market_data_fetcher

    try:
        logger.info("market_data_scheduler: initial run at startup")
        await refresh_market_data()

        while True:
            if _is_market_open():
                # Market is open - refresh every 5 minutes
                wait = 5 * 60
                logger.info(
                    "market_data_scheduler: market is open, next run in %d s", wait
                )
                await asyncio.sleep(wait)

                if _is_market_open():  # Check again after sleep in case market closed
                    await refresh_market_data()
            else:
                # Market is closed - wait until next open
                wait = _seconds_until_market_open()
                logger.info(
                    "market_data_scheduler: market is closed, next run in %.0f s (%.1f hours)",
                    wait,
                    wait / 3600,
                )
                await asyncio.sleep(wait)

    except asyncio.CancelledError:
        logger.info("market_data_scheduler: cancelled, shutting down cleanly")
        await market_data_fetcher.close()
