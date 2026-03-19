import asyncio
import datetime
import logging
import threading

from sqlalchemy import func
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.services.nse_client import NSEClient
from app.models import stockuniverse
from app.database import _SyncSessionLocal, AsyncSessionLocal
from app.config import settings
from app.services.news_fetcher import news_fetcher
from app.services.mc_market_fetcher import market_data_fetcher

logger = logging.getLogger(__name__)

_nse_client = NSEClient()


# ---------------------------------------------------------------------------
# Worker thread state — do not access from async code
# ---------------------------------------------------------------------------
_shutdown_event = threading.Event()
_worker_threads: list[threading.Thread] = []


def _sleep_interruptible(seconds: float) -> bool:
    """Sleep for up to `seconds`, returning True if interrupted by shutdown."""
    return _shutdown_event.wait(timeout=seconds)


def _run_async(coro):
    """
    Run an async coroutine to completion using a fresh event loop.

    Creates a new event loop in the worker thread, runs the coroutine, and
    closes the loop. The Semaphore/Event in news_fetcher (created at module
    load in the main thread) is passed as an argument, so it's used within
    the same fresh loop — avoiding "bound to a different event loop" errors.

    NEVER call this from the main async event loop.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()
        asyncio.set_event_loop(None)


def _seconds_until_midnight() -> float:
    """Return seconds from now until the next 00:00:00 local time."""
    now = datetime.datetime.now()
    tomorrow_midnight = (now + datetime.timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return (tomorrow_midnight - now).total_seconds()


def _stock_universe_sync() -> None:
    """Populate or refresh the stock universe table. Runs synchronously in a worker thread."""
    try:
        logger.info("stock_universe_sync: starting")
        stock_list: list[str] = _nse_client.get_stock_list()
        logger.info("stock_universe_sync: %d symbols to process", len(stock_list))

        stale_delta = datetime.timedelta(days=30)

        with _SyncSessionLocal() as session:
            for symbol in stock_list:
                if _shutdown_event.is_set():
                    logger.info("stock_universe_sync: shutdown requested mid-run, aborting")
                    return

                existing = session.get(stockuniverse.StockUniverse, symbol)
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
                        logger.debug(
                            "Unable to compare last update time for %s; refreshing",
                            symbol,
                        )

                try:
                    metadata = _nse_client.get_stock_metadata(symbol)
                except Exception:
                    logger.exception("Failed to fetch metadata for %s, skipping", symbol)
                    if _sleep_interruptible(1.0):
                        return
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
                session.execute(stmt)
                if _sleep_interruptible(1.0):
                    return

            session.commit()
        logger.info("stock_universe_sync: complete")
    except Exception:
        logger.exception("stock_universe_sync: unhandled exception; will retry next cycle")


def stock_universe_worker() -> None:
    """Daemon thread target for stock universe refresh."""
    logger.info("stock_universe_worker: started")
    _stock_universe_sync()

    while not _shutdown_event.is_set():
        wait_secs = _seconds_until_midnight()
        logger.debug("stock_universe_worker: sleeping %.0fs until midnight", wait_secs)
        if _sleep_interruptible(wait_secs):
            break
        if not _shutdown_event.is_set():
            _stock_universe_sync()

    logger.info("stock_universe_worker: stopped")


NEWS_CRAWL_INTERVAL = 5 * 60
NEWS_CRAWL_MAX_INTERVAL = 30 * 60


async def _crawl_news_async(pages: int) -> int:
    """Async helper: crawl and store news using AsyncSession."""
    async with AsyncSessionLocal() as session:
        return await news_fetcher.crawl_and_store(pages=pages, db=session)


def _news_sync() -> None:
    """Crawl and persist global news. Runs synchronously in a worker thread."""
    try:
        logger.info("news_sync: starting")
        stored = _run_async(_crawl_news_async(pages=6))
        if stored > 0:
            logger.info("news_sync: initial crawl stored %d articles", stored)
        logger.info("news_sync: complete")
    except Exception:
        logger.exception("news_sync: unhandled exception; will retry next cycle")


def _news_periodic_sync(current_interval: int) -> int:
    """Single periodic news crawl (page 1 only). Returns updated interval."""
    try:
        stored = _run_async(_crawl_news_async(pages=1))
        if stored == 0:
            new_interval = min(current_interval * 2, NEWS_CRAWL_MAX_INTERVAL)
            logger.warning("news_sync: crawl returned 0 articles — backing off to %d s", new_interval)
            return new_interval
        else:
            if current_interval > NEWS_CRAWL_INTERVAL:
                logger.info("news_sync: crawl succeeded (%d articles) — resetting interval", stored)
            return NEWS_CRAWL_INTERVAL
    except Exception:
        logger.exception("news_sync: periodic crawl exception — keeping interval")
        return current_interval


def news_worker() -> None:
    """Daemon thread target for news crawling."""
    logger.info("news_worker: started")
    _news_sync()

    current_interval = NEWS_CRAWL_INTERVAL
    while not _shutdown_event.is_set():
        logger.info("news_worker: next run in %d s (backoff: %s)", current_interval, current_interval > NEWS_CRAWL_INTERVAL)
        if _sleep_interruptible(current_interval):
            break
        if not _shutdown_event.is_set():
            current_interval = _news_periodic_sync(current_interval)

    try:
        _run_async(news_fetcher.close())
    except Exception:
        logger.debug("news_worker: close() raised, ignoring (client may already be closed)")
    logger.info("news_worker: stopped")


WATCHLIST_NEWS_INTERVAL = 5 * 60
WATCHLIST_NEWS_STALE_SECONDS = 5 * 60


async def _fetch_company_news_async(symbol: str) -> int:
    """Async helper: fetch company news using AsyncSession.
    
    Note: We can't easily cancel HTTP requests mid-flight, but we can at least
    check for shutdown between symbols in the caller.
    """
    async with AsyncSessionLocal() as session:
        return await news_fetcher.fetch_company_news(symbol=symbol, db=session)


def _watchlist_news_sync() -> None:
    """Fetch and persist news for each symbol in the watchlist."""
    from app.models.watchlist import WatchlistItem
    from app.models.news import NewsArticle
    from sqlalchemy import select
    from datetime import datetime, timezone

    try:
        logger.info("watchlist_news_sync: starting")
        with _SyncSessionLocal() as session:
            result = session.execute(select(WatchlistItem.symbol))
            symbols = [row[0] for row in result]

        if not symbols:
            logger.debug("watchlist_news_sync: watchlist is empty, skipping")
            return

        logger.info("watchlist_news_sync: refreshing news for %d symbols: %s", len(symbols), symbols)

        for symbol in symbols:
            if _shutdown_event.is_set():
                logger.info("watchlist_news_sync: shutdown requested, aborting")
                return

            with _SyncSessionLocal() as session:
                stale_check = session.execute(
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
                    logger.debug("watchlist_news_sync: %s is fresh (age=%.0fs), skipping", symbol, age)
                    continue

            try:
                count = _run_async(_fetch_company_news_async(symbol))
                logger.info("watchlist_news_sync: %s — %d articles stored/tagged", symbol, count)
            except Exception:
                logger.exception("watchlist_news_sync: failed for %s", symbol)

            if _sleep_interruptible(2.0):
                return

        logger.info("watchlist_news_sync: complete")
    except Exception:
        logger.exception("watchlist_news_sync: unhandled exception; will retry next cycle")


def watchlist_news_worker() -> None:
    """Daemon thread target for watchlist news fetching."""
    logger.info("watchlist_news_worker: started")
    _watchlist_news_sync()

    while not _shutdown_event.is_set():
        if _sleep_interruptible(WATCHLIST_NEWS_INTERVAL):
            break
        if not _shutdown_event.is_set():
            _watchlist_news_sync()

    logger.info("watchlist_news_worker: stopped")


def _is_market_open() -> bool:
    """Check if the market is currently open (Mon-Fri, 09:15-15:30 IST)."""
    import pytz

    now_utc = datetime.datetime.now(pytz.utc)
    now_ist = now_utc.astimezone(pytz.timezone("Asia/Kolkata"))

    if now_ist.weekday() >= 5:
        return False

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
    """Calculate seconds until the next market open time (09:15 IST)."""
    import pytz

    now_utc = datetime.datetime.now(pytz.utc)
    now_ist = now_utc.astimezone(pytz.timezone("Asia/Kolkata"))

    if now_ist.weekday() == 5:
        days_until_monday = 2
    elif now_ist.weekday() == 6:
        days_until_monday = 1
    else:
        market_start = now_ist.replace(
            hour=settings.market_start_hour,
            minute=settings.market_start_minute,
            second=0,
            microsecond=0,
        )

        if now_ist < market_start:
            return (market_start - now_ist).total_seconds()
        else:
            days_until_monday = 1
            if now_ist.weekday() == 4:
                days_until_monday = 3

    next_open = now_ist + datetime.timedelta(days=days_until_monday)
    next_open = next_open.replace(
        hour=settings.market_start_hour,
        minute=settings.market_start_minute,
        second=0,
        microsecond=0,
    )

    return (next_open - now_ist).total_seconds()


async def _refresh_market_data_async() -> None:
    """Async helper: refresh all market data using AsyncSession."""
    async with AsyncSessionLocal() as session:
        await market_data_fetcher.refresh_all(session)


def _market_data_sync() -> None:
    """Fetch and store all industry and sector data from MoneyControl."""
    try:
        logger.info("market_data_sync: starting")
        _run_async(_refresh_market_data_async())
        logger.info("market_data_sync: complete")
    except Exception:
        logger.exception("market_data_sync: unhandled exception; will retry next cycle")


def market_data_worker() -> None:
    """Daemon thread target for market data fetching."""
    logger.info("market_data_worker: started")
    _market_data_sync()

    while not _shutdown_event.is_set():
        if _is_market_open():
            wait = 5 * 60
            logger.info("market_data_worker: market is open, next run in %d s", wait)
            if _sleep_interruptible(wait):
                break
            if not _shutdown_event.is_set() and _is_market_open():
                _market_data_sync()
        else:
            wait = _seconds_until_market_open()
            logger.info("market_data_worker: market is closed, next run in %.0f s (%.1f hours)", wait, wait / 3600)
            if _sleep_interruptible(wait):
                break

    try:
        _run_async(market_data_fetcher.close())
    except Exception:
        logger.debug("market_data_worker: close() raised, ignoring (client may already be closed)")
    logger.info("market_data_worker: stopped")


def start_all_workers() -> list[threading.Thread]:
    """Spawn all four background worker threads and return them."""
    targets = [
        stock_universe_worker,
        news_worker,
        watchlist_news_worker,
        market_data_worker,
    ]
    for target in targets:
        t = threading.Thread(target=target, daemon=True, name=target.__name__)
        t.start()
        _worker_threads.append(t)
        logger.info("start_all_workers: spawned %s", t.name)
    return _worker_threads


def stop_all_workers(timeout: float = 35.0) -> None:
    """Signal all workers to stop and wait up to `timeout` seconds for each to exit.
    
    Default timeout is 35 seconds to allow for HTTP requests to complete (max 30s).
    """
    logger.info("stop_all_workers: setting shutdown event")
    _shutdown_event.set()
    for t in _worker_threads:
        t.join(timeout=timeout)
        if t.is_alive():
            logger.warning("stop_all_workers: %s did not exit within %.1fs, abandoning", t.name, timeout)
        else:
            logger.info("stop_all_workers: %s exited cleanly", t.name)
