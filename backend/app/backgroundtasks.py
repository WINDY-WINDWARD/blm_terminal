import asyncio
import datetime
import logging
import threading
from typing import Any

from sqlalchemy import delete, func
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
    """Spawn all background worker threads and return them."""
    targets = [
        stock_universe_worker,
        news_worker,
        watchlist_news_worker,
        market_data_worker,
        watchlist_notification_worker,
    ]
    for target in targets:
        t = threading.Thread(target=target, daemon=True, name=target.__name__)
        t.start()
        _worker_threads.append(t)
        logger.info("start_all_workers: spawned %s", t.name)
    return _worker_threads


# ---------------------------------------------------------------------------
# Notification worker — watchlist stock alert generator
# ---------------------------------------------------------------------------

NOTIFICATION_CHECK_INTERVAL = 5 * 60       # 5 minutes  (market hours)
AFTER_HOURS_INTERVAL = 30 * 60             # 30 minutes (outside market hours)
DAILY_NOTIFICATION_WINDOW_DAYS = 7          # lookback for deals and insider trades
CLEANUP_READ_AFTER_DAYS = 30              # hard-delete read notifications older than this
CLEANUP_INTERVAL = 24 * 60 * 60            # run cleanup at most once per 24 hours

_cleanup_last_run: "datetime.datetime | None" = None


def _get_watchlist_symbols() -> dict[int, list[str]]:
    """Return all watchlist items grouped by watchlist_id."""
    from app.models.watchlist import WatchlistItem
    from sqlalchemy import select

    with _SyncSessionLocal() as session:
        result = session.execute(select(WatchlistItem.watchlist_id, WatchlistItem.symbol))
        rows = result.fetchall()
    grouped: dict[int, list[str]] = {}
    for wl_id, symbol in rows:
        grouped.setdefault(wl_id, []).append(symbol.upper())
    return grouped


def _get_seen_today() -> set[tuple[int, str, str]]:
    """Return {(watchlist_id, symbol, trigger_type)} for all unread notifications today."""
    from app.models.notification import Notification

    today = datetime.now().date()
    with _SyncSessionLocal() as session:
        rows = session.execute(
            select(Notification.watchlist_id, Notification.symbol, Notification.trigger_type)
            .where(
                Notification.triggered_date == today,
                Notification.is_read == False,
            )
        )
        return {(r[0], r[1], r[2]) for r in rows}


def _bulk_upsert_notifications(rows: list[dict]) -> None:
    """Insert notification rows, skipping duplicates via UniqueConstraint.

    rows is a list of plain dicts keyed by column name — NOT ORM objects.
    Using ORM object __dict__ would include SQLAlchemy internal state keys,
    causing the insert to fail or behave unexpectedly.
    """
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert
    from app.models.notification import Notification

    if not rows:
        return
    with _SyncSessionLocal() as session:
        stmt = (
            sqlite_insert(Notification)
            .values(rows)
            .on_conflict_do_nothing(constraint="uq_notification_daily")
        )
        session.execute(stmt)
        session.commit()


def _run_cleanup_if_due() -> None:
    """Hard-delete read notifications older than CLEANUP_READ_AFTER_DAYS.

    Runs at most once per CLEANUP_INTERVAL to avoid unnecessary DB writes.
    """
    global _cleanup_last_run
    now = datetime.now()
    if _cleanup_last_run is not None and (now - _cleanup_last_run).total_seconds() < CLEANUP_INTERVAL:
        return
    from app.models.notification import Notification
    from datetime import timedelta as td

    cutoff = datetime.combine(now.date() - td(days=CLEANUP_READ_AFTER_DAYS), datetime.min.time())
    with _SyncSessionLocal() as session:
        deleted = session.execute(
            delete(Notification).where(
                Notification.is_read == True,
                Notification.triggered_at < cutoff,
            )
        )
        session.commit()
        if deleted.rowcount > 0:
            logger.info(
                "notification_cleanup: deleted %d read notifications older than %s",
                deleted.rowcount,
                cutoff.date(),
            )
    _cleanup_last_run = now


def _notification_cycle_full() -> None:
    """Full cycle: check all 9 trigger types. Called in a worker thread."""
    global _cleanup_last_run

    try:
        logger.info("notification_cycle_full: starting")
        now = datetime.now()
        today_date = now.date()

        symbols_by_watchlist = _get_watchlist_symbols()
        if not symbols_by_watchlist:
            logger.debug("notification_cycle_full: watchlist is empty, skipping")
            return

        seen_today = _get_seen_today()
        pending: list[dict] = []

        high52 = {str(r.symbol): r for r in _nse_client.get_52week_high().itertuples()}
        low52  = {str(r.symbol): r for r in _nse_client.get_52week_low().itertuples()}
        vol    = {str(r.symbol): r for r in _nse_client.get_volume_gainers().itertuples()}
        gainers = {str(r.symbol): r for r in _nse_client.get_top_gainers().itertuples()}
        losers  = {str(r.symbol): r for r in _nse_client.get_top_losers().itertuples()}
        deals   = _nse_client.get_largedeal_snapshot()

        insider_cache: dict[str, list[dict]] = {}

        for wl_id, symbols in symbols_by_watchlist.items():
            for symbol in symbols:
                alerts: list[tuple[str, str]] = []

                if symbol in high52:
                    row = high52[symbol]
                    price = getattr(row, "ltp", None) or getattr(row, "new52WHL", None) or "—"
                    alerts.append(("52w_high_breakout", f"{symbol} hit a new 52-week HIGH @ ₹{price}"))
                if symbol in low52:
                    row = low52[symbol]
                    price = getattr(row, "ltp", None) or getattr(row, "new52WHL", None) or "—"
                    alerts.append(("52w_low_breakout", f"{symbol} hit a new 52-week LOW @ ₹{price}"))
                if symbol in vol:
                    row = vol[symbol]
                    ratio = getattr(row, "week1volChange", None) or 0
                    alerts.append(("volume_breakout", f"{symbol} showing volume breakout ({ratio:+.0f}x avg)"))
                if symbol in gainers:
                    row = gainers[symbol]
                    pchg = getattr(row, "pChange", 0) or 0
                    alerts.append(("top_gainer", f"{symbol} among TOP GAINERS ({pchg:+.1f}%)"))
                if symbol in losers:
                    row = losers[symbol]
                    pchg = getattr(row, "pChange", 0) or 0
                    alerts.append(("top_loser", f"{symbol} among TOP LOSERS ({pchg:+.1f}%)"))

                for deal in deals.get_deals_for_symbol(symbol):
                    if deal.is_recent(days=DAILY_NOTIFICATION_WINDOW_DAYS):
                        alerts.append((
                            f"{deal.deal_type}_deal",
                            f"{symbol} — {deal.deal_type} deal: {deal.qty:,} shares @ ₹{deal.watp}",
                        ))

                if symbol not in insider_cache:
                    insider_cache[symbol] = _fetch_insider_trades_cached(symbol)
                for trade in insider_cache[symbol]:
                    if trade.is_recent(days=DAILY_NOTIFICATION_WINDOW_DAYS):
                        direction = (trade.buy_sell or "").lower()
                        if direction in ("buy", "acquisition"):
                            t_type = "insider_buy"
                        elif direction in ("sell", "disposal"):
                            t_type = "insider_sell"
                        else:
                            t_type = f"insider_{direction}"
                        alerts.append((
                            t_type,
                            f"{symbol} insider {direction.upper()}: "
                            f"{getattr(trade, 'acquirer_name', 'Unknown')} "
                            f"{direction} {getattr(trade, 'qty', 0):,} shares",
                        ))

                for trigger_type, message in alerts:
                    key = (wl_id, symbol, trigger_type)
                    if key in seen_today:
                        continue
                    seen_today.add(key)
                    pending.append({
                        "watchlist_id": wl_id,
                        "symbol": symbol,
                        "exchange": "NSE",
                        "trigger_type": trigger_type,
                        "message": message,
                        "triggered_at": now,
                        "triggered_date": today_date,
                        "is_read": False,
                    })

                if _shutdown_event.is_set():
                    return

        if pending:
            _bulk_upsert_notifications(pending)
            logger.info("notification_cycle_full: upserted %d notifications", len(pending))
        else:
            logger.info("notification_cycle_full: no new notifications")

        _run_cleanup_if_due()
    except Exception:
        logger.exception("notification_cycle_full: unhandled exception")


def _notification_cycle_reduced() -> None:
    """Reduced cycle: deals + insider only. Outside market hours."""
    try:
        logger.info("notification_cycle_reduced: starting")
        now = datetime.now()
        today_date = now.date()

        symbols_by_watchlist = _get_watchlist_symbols()
        if not symbols_by_watchlist:
            logger.debug("notification_cycle_reduced: watchlist is empty, skipping")
            return

        seen_today = _get_seen_today()
        pending: list[dict] = []
        deals = _nse_client.get_largedeal_snapshot()
        insider_cache: dict[str, list[dict]] = {}

        for wl_id, symbols in symbols_by_watchlist.items():
            for symbol in symbols:
                alerts: list[tuple[str, str]] = []

                for deal in deals.get_deals_for_symbol(symbol):
                    if deal.is_recent(days=DAILY_NOTIFICATION_WINDOW_DAYS):
                        alerts.append((
                            f"{deal.deal_type}_deal",
                            f"{symbol} — {deal.deal_type} deal: {deal.qty:,} shares @ ₹{deal.watp}",
                        ))

                if symbol not in insider_cache:
                    insider_cache[symbol] = _fetch_insider_trades_cached(symbol)
                for trade in insider_cache[symbol]:
                    if trade.is_recent(days=DAILY_NOTIFICATION_WINDOW_DAYS):
                        direction = (trade.buy_sell or "").lower()
                        if direction in ("buy", "acquisition"):
                            t_type = "insider_buy"
                        elif direction in ("sell", "disposal"):
                            t_type = "insider_sell"
                        else:
                            t_type = f"insider_{direction}"
                        alerts.append((
                            t_type,
                            f"{symbol} insider {direction.upper()}: "
                            f"{getattr(trade, 'acquirer_name', 'Unknown')} "
                            f"{direction} {getattr(trade, 'qty', 0):,} shares",
                        ))

                for trigger_type, message in alerts:
                    key = (wl_id, symbol, trigger_type)
                    if key in seen_today:
                        continue
                    seen_today.add(key)
                    pending.append({
                        "watchlist_id": wl_id,
                        "symbol": symbol,
                        "exchange": "NSE",
                        "trigger_type": trigger_type,
                        "message": message,
                        "triggered_at": now,
                        "triggered_date": today_date,
                        "is_read": False,
                    })

                if _shutdown_event.is_set():
                    return

        if pending:
            _bulk_upsert_notifications(pending)
            logger.info("notification_cycle_reduced: upserted %d notifications", len(pending))
        _run_cleanup_if_due()
    except Exception:
        logger.exception("notification_cycle_reduced: unhandled exception")


def _fetch_insider_trades_cached(symbol: str) -> list[dict]:
    """Fetch insider trades from screener.in, returning a list of trade dicts."""
    try:
        result = _run_async(_fetch_insider_trades_async(symbol))
        return result
    except Exception:
        logger.debug("insider_trades: failed for %s, skipping", symbol)
        return []


async def _fetch_insider_trades_async(symbol: str) -> list[dict]:
    """Async helper: call screener_client.get_insider_trades."""
    from app.services.screener_client import screener_client

    try:
        data = await screener_client.get_insider_trades(symbol)
        if data and "insider_trades" in data:
            return data["insider_trades"]
    except Exception:
        pass
    return []


def watchlist_notification_worker() -> None:
    """Daemon thread: monitors watchlist stocks for significant market events."""
    logger.info("watchlist_notification_worker: started")
    _sleep_interruptible(30)  # wait for app startup before first cycle

    while not _shutdown_event.is_set():
        if _is_market_open():
            _notification_cycle_full()
            _sleep_interruptible(NOTIFICATION_CHECK_INTERVAL)
        else:
            _notification_cycle_reduced()
            _sleep_interruptible(AFTER_HOURS_INTERVAL)

    logger.info("watchlist_notification_worker: stopped")


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


async def start_cache_cleanup(interval: float = 600.0) -> asyncio.Task:
    """No-op: cachetools.TTLCache auto-evicts expired entries.
    
    Kept for backward compatibility with existing callers.
    """
    async def _noop() -> None:
        while True:
            await asyncio.sleep(interval)

    task = asyncio.create_task(_noop(), name="cache-cleanup-noop")
    logger.info("Cache cleanup: using cachetools.TTLCache (auto-eviction, no manual cleanup needed)")
    return task
