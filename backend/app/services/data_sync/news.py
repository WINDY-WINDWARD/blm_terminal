"""News sync cores (audit C.1, A.11 part 2).

Extracted from ``app/backgroundtasks/_impl.py``.  Holds all
news-related sync cores (work bodies) called by the news
worker daemons in ``app.workers.news``.

Public functions (7):
- ``_crawl_news_async()`` — async helper: crawl + store global
  news (MoneyControl)
- ``_news_sync()`` — sync wrapper for the initial crawl
- ``_news_periodic_sync()`` — single periodic news crawl with
  exponential backoff on empty result
- ``_news_rss_sync()`` — fetch + store from all RSS sources
  (sync version; the live path is async)
- ``_news_rss_sync_async()`` — async version of RSS sync
- ``_fetch_company_news_async()`` — async helper: fetch news
  for a single symbol
- ``_watchlist_news_sync()`` — refresh news for every symbol
  on every watchlist

Public constants (3):
- ``NEWS_CRON`` — every-5-minutes cron for the periodic crawl
- ``NEWS_CRAWL_MAX_INTERVAL`` — backoff ceiling (30 min)
- ``WATCHLIST_NEWS_STALE_SECONDS`` — skip re-fetch if a
  symbol's news is fresher than 5 min

NOTE: We import ``logger``, ``_SyncSessionLocal``,
``AsyncSessionLocal``, ``_run_async``, ``_seconds_until_next_cron``,
``_shutdown_event``, ``_sleep_interruptible`` and
``update_job_status_sync`` lazily inside the function bodies to
avoid a circular import: ``app.backgroundtasks._impl`` re-exports
us at the bottom of its own module, so a top-level import from
``_impl`` here would deadlock the import machinery.
"""
from __future__ import annotations


NEWS_CRON = "*/5 * * * *"
NEWS_CRAWL_MAX_INTERVAL = 30 * 60
WATCHLIST_NEWS_STALE_SECONDS = 5 * 60


async def _crawl_news_async(pages: int) -> int:
    """Async helper: crawl and store news using AsyncSession.

    Uses AsyncSessionLocal (NullPool) — called via _run_async() which
    creates a new event loop per worker thread. NullPool is already
    thread-safe; each ``engine.connect()`` opens a fresh DBAPI connection
    bound to the loop that opened it.
    """
    from app.backgroundtasks import _impl as _bg_impl

    AsyncSessionLocal = _bg_impl.AsyncSessionLocal
    news_fetcher = _bg_impl.news_fetcher

    async with AsyncSessionLocal() as session:
        return await news_fetcher.crawl_and_store(pages=pages, db=session)


def _news_sync() -> None:
    """Crawl and persist global news. Runs synchronously in a worker thread."""
    from app.backgroundtasks import _impl as _bg_impl

    logger = _bg_impl.logger
    update_job_status_sync = _bg_impl.update_job_status_sync
    _run_async = _bg_impl._run_async

    try:
        logger.info("news_sync: starting")
        update_job_status_sync("job.news", "running", progress=10, message="Starting news crawl...")
        stored = _run_async(_crawl_news_async(pages=6))
        if stored > 0:
            logger.info("news_sync: initial crawl stored %d articles", stored)
        update_job_status_sync("job.news", "waiting", progress=100, message="Waiting for next cycle")
        logger.info("news_sync: complete")
    except Exception:
        logger.exception("news_sync: unhandled exception; will retry next cycle")
        update_job_status_sync("job.news", "failed", message="Error occurred")


def _news_periodic_sync(backoff_secs: float) -> float:
    """Single periodic news crawl (page 1 only).

    Returns the next sleep duration: resets to cron interval on success,
    doubles (up to NEWS_CRAWL_MAX_INTERVAL) on empty result.
    """
    from app.backgroundtasks import _impl as _bg_impl

    logger = _bg_impl.logger
    update_job_status_sync = _bg_impl.update_job_status_sync
    _run_async = _bg_impl._run_async
    _seconds_until_next_cron = _bg_impl._seconds_until_next_cron

    base = _seconds_until_next_cron(NEWS_CRON)
    try:
        update_job_status_sync("job.news", "running", progress=50, message="Crawling news...")
        stored = _run_async(_crawl_news_async(pages=1))
        if stored == 0:
            new_interval = min(backoff_secs * 2, NEWS_CRAWL_MAX_INTERVAL)
            logger.warning("news_sync: crawl returned 0 articles — backing off to %.0f s", new_interval)
            update_job_status_sync("job.news", "waiting", progress=0, message=f"Backing off {new_interval:.0f}s")
            return new_interval
        else:
            if backoff_secs > base:
                logger.info("news_sync: crawl succeeded (%d articles) — resetting to cron schedule", stored)
            update_job_status_sync("job.news", "waiting", progress=100, message="Waiting for next cycle")
            return base
    except Exception:
        logger.exception("news_sync: periodic crawl exception — keeping interval")
        update_job_status_sync("job.news", "failed", message="Error in periodic crawl")
        return backoff_secs


def _news_rss_sync() -> None:
    """Fetch and store articles from all RSS sources."""
    from app.backgroundtasks import _impl as _bg_impl

    logger = _bg_impl.logger
    _SyncSessionLocal = _bg_impl._SyncSessionLocal
    _run_async = _bg_impl._run_async
    NewsArticle = _bg_impl.NewsArticle
    fetch_all_feeds = _bg_impl.fetch_all_feeds
    HIGH_PRIORITY_SOURCES = _bg_impl.HIGH_PRIORITY_SOURCES
    broadcast_news_update = _bg_impl.broadcast_news_update

    logger.info("news_rss_sync: starting RSS aggregation")
    try:
        from app.services.news_aggregator import _parsed_article_to_db_dict

        all_articles, results = _run_async(
            fetch_all_feeds(
                sources=HIGH_PRIORITY_SOURCES,
                concurrency=5,
                timeout=15.0,
            )
        )

        success_count = sum(1 for r in results if not r.error)
        error_count = sum(1 for r in results if r.error)
        logger.info(
            "news_rss_sync: fetched %d articles from %d sources (%d errors)",
            len(all_articles), success_count, error_count
        )

        # Convert ParsedArticle objects to DB dicts with NLP fields
        processed = []
        for article in all_articles:
            try:
                processed.append(_parsed_article_to_db_dict(article))
            except Exception as e:
                logger.debug("Failed to process article %s: %s", article.url, e)

        if processed:
            with _SyncSessionLocal() as session:
                stored = 0
                for article_dict in processed:
                    from sqlalchemy.dialects.sqlite import insert as sqlite_insert
                    stmt = sqlite_insert(NewsArticle).values(article_dict)
                    stmt = stmt.on_conflict_do_nothing(index_elements=["url"])
                    session.execute(stmt)
                    stored += 1
                session.commit()
                logger.info("news_rss_sync: stored %d articles", stored)

                # Broadcast new articles via WebSocket (sync path — dead code, async path is active)
                for article_dict in processed[:10]:
                    try:
                        _run_async(broadcast_news_update(article_dict))
                    except Exception as e:
                        logger.debug("Failed to broadcast article: %s", e)

        for r in results:
            if r.error:
                logger.debug("news_rss_sync: %s failed: %s", r.source.id, r.error)

    except Exception as e:
        logger.exception("news_rss_sync: failed with exception: %s", e)


async def _news_rss_sync_async() -> None:
    """Async version of news RSS sync for use in worker threads."""
    from app.backgroundtasks import _impl as _bg_impl

    logger = _bg_impl.logger
    AsyncSessionLocal = _bg_impl.AsyncSessionLocal
    broadcast_news_update = _bg_impl.broadcast_news_update
    HIGH_PRIORITY_SOURCES = _bg_impl.HIGH_PRIORITY_SOURCES

    from app.services.news_aggregator import fetch_and_process_all, store_articles

    try:
        processed, results = await fetch_and_process_all(
            sources=HIGH_PRIORITY_SOURCES,
            concurrency=5,
            timeout=15.0,
        )

        success_count = sum(1 for r in results if not r.error)
        error_count = sum(1 for r in results if r.error)
        logger.info(
            "news_rss_sync: fetched %d articles from %d sources (%d errors)",
            len(processed), success_count, error_count
        )

        if processed:
            async with AsyncSessionLocal() as session:
                stored = await store_articles(session, processed)
                logger.info("news_rss_sync_async: stored %d articles", stored)

                # Broadcast new articles via WebSocket
                for article_dict in processed[:10]:  # Broadcast newest 10
                    try:
                        await broadcast_news_update(article_dict)
                    except Exception as e:
                        logger.debug("Failed to broadcast article: %s", e)

    except Exception as e:
        logger.exception("news_rss_sync_async: failed with exception: %s", e)


async def _fetch_company_news_async(symbol: str) -> int:
    """Async helper: fetch company news using AsyncSession.

    Uses AsyncSessionLocal (NullPool) — called via _run_async() which
    creates a new event loop per worker thread. NullPool is already
    thread-safe; each ``engine.connect()`` opens a fresh DBAPI connection
    bound to the loop that opened it.

    Note: We can't easily cancel HTTP requests mid-flight, but we can at least
    check for shutdown between symbols in the caller.
    """
    from app.backgroundtasks import _impl as _bg_impl

    AsyncSessionLocal = _bg_impl.AsyncSessionLocal
    news_fetcher = _bg_impl.news_fetcher

    try:
        async with AsyncSessionLocal() as session:
            return await news_fetcher.fetch_company_news(symbol=symbol, db=session)
    finally:
        await news_fetcher.close()


def _watchlist_news_sync() -> None:
    """Fetch and persist news for each symbol in the watchlist."""
    from datetime import datetime, timezone

    from sqlalchemy import func, select

    from app.backgroundtasks import _impl as _bg_impl

    logger = _bg_impl.logger
    _SyncSessionLocal = _bg_impl._SyncSessionLocal
    _run_async = _bg_impl._run_async
    _shutdown_event = _bg_impl._shutdown_event
    _sleep_interruptible = _bg_impl._sleep_interruptible
    update_job_status_sync = _bg_impl.update_job_status_sync
    WatchlistItem = _bg_impl.WatchlistItem
    NewsArticle = _bg_impl.NewsArticle

    try:
        logger.info("watchlist_news_sync: starting")
        with _SyncSessionLocal() as session:
            result = session.execute(select(WatchlistItem.symbol))
            symbols = [row[0] for row in result]

        if not symbols:
            logger.debug("watchlist_news_sync: watchlist is empty, skipping")
            return

        total = len(symbols)
        logger.info("watchlist_news_sync: refreshing news for %d symbols: %s", total, symbols)

        for idx, symbol in enumerate(symbols, 1):
            if _shutdown_event.is_set():
                logger.info("watchlist_news_sync: shutdown requested, aborting")
                return

            update_job_status_sync(
                "job.watchlist_news", "running",
                progress=int((idx / total) * 100),
                message=f"Fetching news: {symbol} ({idx}/{total})",
            )

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
