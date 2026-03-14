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
