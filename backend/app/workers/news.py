"""News worker daemons (audit C.1, A.9 step 4).

Extracted from ``app/backgroundtasks/_impl.py``.  The actual sync
functions stay in ``_impl.py`` for now and move in A.11.

Public workers:
- ``news_worker()`` — cron ``*/5 * * * *`` with backoff; waits for
  the stock universe at startup.
- ``news_rss_worker()`` — cron ``*/5 * * * *``; multi-source RSS.
- ``watchlist_news_worker()`` — cron ``*/5 * * * *``; per-symbol.

NOTE: Lazy imports from ``_impl`` to avoid circular import deadlock.
"""
from __future__ import annotations


def news_worker() -> None:
    """Daemon thread target for news crawling (cron: */5 * * * * with backoff)."""
    from datetime import datetime, timedelta, timezone

    from app.backgroundtasks import _impl as _bg_impl

    logger = _bg_impl.logger
    _is_job_enabled = _bg_impl._is_job_enabled
    _is_first_run = _bg_impl._is_first_run
    _set_first_run_complete = _bg_impl._set_first_run_complete
    _shutdown_event = _bg_impl._shutdown_event
    _sleep_interruptible = _bg_impl._sleep_interruptible
    _seconds_until_next_cron = _bg_impl._seconds_until_next_cron
    _wait_for_startup_event = _bg_impl._wait_for_startup_event
    _startup_stock_universe_done = _bg_impl._startup_stock_universe_done
    update_job_status_sync = _bg_impl.update_job_status_sync
    _report_job_waiting = _bg_impl._report_job_waiting
    _news_sync = _bg_impl._news_sync
    _news_periodic_sync = _bg_impl._news_periodic_sync
    NEWS_CRON = _bg_impl.NEWS_CRON
    news_fetcher = _bg_impl.news_fetcher
    _run_async = _bg_impl._run_async

    logger.info("news_worker: started")

    if not _is_job_enabled("job.news"):
        logger.info("news_worker: disabled, waiting...")
        update_job_status_sync("job.news", "waiting", progress=0, message="Disabled")
        while not _shutdown_event.is_set():
            _sleep_interruptible(60)
        update_job_status_sync("job.news", "idle", progress=0, message="Stopped")
        logger.info("news_worker: stopped")
        return

    # Check first_run for startup execution
    if _is_first_run("news"):
        # Wait for stock universe before crawling news (universe provides symbol context)
        if _wait_for_startup_event(_startup_stock_universe_done, "stock_universe", "job.news"):
            update_job_status_sync("job.news", "idle", progress=0, message="Stopped")
            logger.info("news_worker: stopped")
            return
        update_job_status_sync("job.news", "running", progress=10, message="Starting initial news crawl...")
        _news_sync()
        _set_first_run_complete("news")
    else:
        logger.info("news_worker: first_run=False, skipping startup crawl")
        update_job_status_sync("job.news", "waiting", progress=0, message="Waiting for cron schedule")

    current_interval = _seconds_until_next_cron(NEWS_CRON)
    while not _shutdown_event.is_set():
        is_backoff = current_interval > _seconds_until_next_cron(NEWS_CRON)
        logger.info("news_worker: next run in %.0f s (backoff: %s)", current_interval, is_backoff)
        if is_backoff:
            next_trig = datetime.now(timezone.utc) + timedelta(seconds=current_interval)
            update_job_status_sync("job.news", "waiting", progress=0,
                                   message=f"Next run in {current_interval:.0f}s (backoff)",
                                   next_trigger=next_trig)
        else:
            _report_job_waiting("job.news", NEWS_CRON)
        if _sleep_interruptible(current_interval):
            break
        if not _shutdown_event.is_set():
            if not _is_job_enabled("job.news"):
                update_job_status_sync("job.news", "waiting", progress=0, message="Disabled")
                _sleep_interruptible(60)
                continue
            current_interval = _news_periodic_sync(current_interval)

    update_job_status_sync("job.news", "idle", progress=0, message="Stopped")
    try:
        _run_async(news_fetcher.close())
    except Exception:
        logger.debug("news_worker: close() raised, ignoring (client may already be closed)")
    logger.info("news_worker: stopped")


def news_rss_worker() -> None:
    """Daemon thread target for RSS news aggregation (cron: */5 * * * *)."""
    from app.backgroundtasks import _impl as _bg_impl

    logger = _bg_impl.logger
    _is_job_enabled = _bg_impl._is_job_enabled
    _shutdown_event = _bg_impl._shutdown_event
    _sleep_interruptible = _bg_impl._sleep_interruptible
    _report_job_waiting = _bg_impl._report_job_waiting
    _run_async = _bg_impl._run_async
    _news_rss_sync_async = _bg_impl._news_rss_sync_async
    NEWS_RSS_CRON = _bg_impl.NEWS_RSS_CRON
    update_job_status_sync = _bg_impl.update_job_status_sync

    logger.info("news_rss_worker: started")

    if not _is_job_enabled("job.news_rss"):
        logger.info("news_rss_worker: disabled, waiting...")
        update_job_status_sync("job.news_rss", "waiting", progress=0, message="Disabled")
        while not _shutdown_event.is_set():
            _sleep_interruptible(60)
        update_job_status_sync("job.news_rss", "idle", progress=0, message="Stopped")
        logger.info("news_rss_worker: stopped")
        return

    # Run immediately on startup
    logger.info("news_rss_worker: running initial sync")
    update_job_status_sync("job.news_rss", "running", progress=10, message="Initial RSS sync...")
    _run_async(_news_rss_sync_async())

    # Then run on cron schedule
    while not _shutdown_event.is_set():
        wait_secs = _report_job_waiting("job.news_rss", NEWS_RSS_CRON)
        logger.info("news_rss_worker: next run in %.0f s", wait_secs)
        if _sleep_interruptible(wait_secs):
            break

        if not _shutdown_event.is_set():
            if not _is_job_enabled("job.news_rss"):
                update_job_status_sync("job.news_rss", "waiting", progress=0, message="Disabled")
                _sleep_interruptible(60)
                continue

            update_job_status_sync("job.news_rss", "running", progress=50, message="Fetching RSS feeds...")
            _run_async(_news_rss_sync_async())
            update_job_status_sync("job.news_rss", "completed", progress=100, message="Sync complete")

    update_job_status_sync("job.news_rss", "idle", progress=0, message="Stopped")
    logger.info("news_rss_worker: stopped")


def watchlist_news_worker() -> None:
    """Daemon thread target for watchlist news fetching (cron: */5 * * * *)."""
    from app.backgroundtasks import _impl as _bg_impl

    logger = _bg_impl.logger
    _is_job_enabled = _bg_impl._is_job_enabled
    _is_first_run = _bg_impl._is_first_run
    _set_first_run_complete = _bg_impl._set_first_run_complete
    _shutdown_event = _bg_impl._shutdown_event
    _sleep_interruptible = _bg_impl._sleep_interruptible
    _wait_for_startup_event = _bg_impl._wait_for_startup_event
    _startup_stock_universe_done = _bg_impl._startup_stock_universe_done
    _report_job_waiting = _bg_impl._report_job_waiting
    _watchlist_news_sync = _bg_impl._watchlist_news_sync
    update_job_status_sync = _bg_impl.update_job_status_sync

    logger.info("watchlist_news_worker: started")

    if not _is_job_enabled("job.watchlist_news"):
        logger.info("watchlist_news_worker: disabled, waiting...")
        update_job_status_sync("job.watchlist_news", "waiting", progress=0, message="Disabled")
        while not _shutdown_event.is_set():
            _sleep_interruptible(60)
        update_job_status_sync("job.watchlist_news", "idle", progress=0, message="Stopped")
        logger.info("watchlist_news_worker: stopped")
        return

    # Check first_run for startup execution
    if _is_first_run("watchlist_news"):
        # Wait for stock universe to be populated before fetching per-symbol news
        if _wait_for_startup_event(_startup_stock_universe_done, "stock_universe", "job.watchlist_news"):
            update_job_status_sync("job.watchlist_news", "idle", progress=0, message="Stopped")
            logger.info("watchlist_news_worker: stopped")
            return
        update_job_status_sync("job.watchlist_news", "running", progress=0, message="Starting initial fetch...")
        _watchlist_news_sync()
        _set_first_run_complete("watchlist_news")
    else:
        logger.info("watchlist_news_worker: first_run=False, skipping startup fetch")
        update_job_status_sync("job.watchlist_news", "waiting", progress=0, message="Waiting for cron schedule")

    while not _shutdown_event.is_set():
        wait_secs = _report_job_waiting("job.watchlist_news", "*/5 * * * *")
        if _sleep_interruptible(wait_secs):
            break
        if not _shutdown_event.is_set():
            if not _is_job_enabled("job.watchlist_news"):
                update_job_status_sync("job.watchlist_news", "waiting", progress=0, message="Disabled")
                _sleep_interruptible(60)
                continue
            update_job_status_sync("job.watchlist_news", "running", progress=50, message="Fetching watchlist news...")
            _watchlist_news_sync()

    update_job_status_sync("job.watchlist_news", "idle", progress=0, message="Stopped")
    logger.info("watchlist_news_worker: stopped")
