"""Worker lifecycle (Phase C.1, A.12 part 3).

Background worker startup / shutdown:

  - ``start_all_workers()`` — register all jobs and spawn all background
    worker daemon threads in the correct startup order.
  - ``stop_all_workers()`` — signal all workers to stop and wait up to
    ``timeout`` seconds for each to exit.
  - ``start_cache_cleanup()`` — no-op kept for backward compatibility
    (``cachetools.TTLCache`` auto-evicts expired entries).

Migrated from ``app.backgroundtasks._impl`` (audit C.1, A.12 part 3).
"""
import asyncio
import logging
import threading

from app.backgroundtasks._runtime import (  # noqa: F401
    _shutdown_event,
    _worker_threads,
    _pipeline_lock,
    _pipeline_idle,
    _is_job_enabled,
    _is_first_run,
    _set_first_run_complete,
    _wait_for_startup_event,
    _wait_for_pipeline,
    _run_async,
    _report_job_waiting,
    _startup_stock_universe_done,
    _startup_ticker_backfill_done,
    _startup_ticker_indicators_done,
    _startup_ticker_scores_done,
    _startup_ticker_hourly_done,
    _startup_market_data_done,
    _startup_pipeline_done,
    reset_async_shutdown_event,
    set_async_shutdown_event,
    _sleep_interruptible,
    _seconds_until_next_cron,
    _cleanup_run_async_loops,
    get_async_shutdown_event,
)
from app.jobs.runner import sync_all_jobs_to_db


logger = logging.getLogger(__name__)


async def start_all_workers() -> list[threading.Thread]:
    """Register jobs and spawn all background worker threads.

    Startup ordering is strictly enforced via threading.Event gates:

      1. stock_universe_worker               — runs first; sets _startup_stock_universe_done
                                                 All other workers wait on this before their first-run.
      2. ticker_backfill_worker              — waits stock_universe_done; sets _startup_ticker_backfill_done
      3. ticker_indicators_worker            — waits ticker_backfill_done; sets _startup_ticker_indicators_done
      4. ticker_scores_worker                — waits ticker_indicators_done; sets _startup_ticker_scores_done
      5. ticker_daily_update_worker          — waits ticker_backfill_done (runs its own inline pipeline)
       6. ticker_intraday_hourly_update_worker    — runs independently; sets _startup_ticker_hourly_done
       6b. ticker_intraday_hourly_indicators_worker — waits _startup_ticker_hourly_done
       7. global_scan_worker                  — waits ticker_scores_done; polls _pipeline_idle on every cycle
       8. watchlist_notification_worker       — waits ticker_scores_done; polls _pipeline_idle on every cycle
       9. news_worker                         — waits stock_universe_done; then runs independently
       10. watchlist_news_worker              — waits stock_universe_done; then runs independently
       11. results_calendar_worker            — waits stock_universe_done; then runs independently
       12. vacuum_worker                      — waits ticker_scores_done; weekly Sunday 04:00 cron

    Cron-cycle ordering is enforced via _pipeline_lock + _pipeline_idle:
      ticker_daily_update / ticker_indicators / ticker_scores each acquire
      _pipeline_lock and clear _pipeline_idle while running. global_scan and
      watchlist_notification call _wait_for_pipeline() before each cycle, so
      they will not start a new cycle while a pipeline run is known to be in
      progress. Note: there is an inherent narrow race where a consumer passes
      the idle check and a producer then starts — this is accepted because scan
      workers are DB-read-only and the window is sub-millisecond.

    Weekly/Monthly (W/M) candle sync + indicators are NOT run by standalone
    workers — they are Stage 5 of the nightly orchestrator pipeline (see
    orchestrator.py) so that W/M data is fresh before the nightly scan.
    """
    from app.workers.jobs import register_all_jobs
    from app.workers.universe import stock_universe_worker
    from app.workers.data import (
        ticker_backfill_worker,
        ticker_daily_update_worker,
        ticker_intraday_hourly_update_worker,
    )
    from app.workers.ticker_compute import (
        ticker_indicators_worker,
        ticker_intraday_hourly_indicators_worker,
        ticker_scores_worker,
    )
    from app.workers.notifications import (
        global_scan_worker,
        watchlist_notification_worker,
    )
    from app.workers.news import (
        news_rss_worker,
        news_worker,
        watchlist_news_worker,
    )
    from app.workers.market_calendar import results_calendar_worker
    from app.workers.maintenance import vacuum_worker
    from app.workers.ai_picks_worker import ai_picks_morning_worker, ai_picks_evening_worker
    from app.workers.deals import watchlist_deals_worker
    from app.workers.fundamentals import fundamentals_worker

    reset_async_shutdown_event()
    register_all_jobs()
    await sync_all_jobs_to_db()

    targets = [
        ticker_backfill_worker,                      # 1 — candle history first
        stock_universe_worker,                       # 2 — symbol metadata
        ticker_indicators_worker,                    # 3 — indicator backfill
        ticker_scores_worker,                          # 4 — momentum scores
        ticker_daily_update_worker,                  # 5 — daily bhavcopy + refresh
        ticker_intraday_hourly_update_worker,       # 6 — 1h candles during market hours
        ticker_intraday_hourly_indicators_worker,   # 6b — 1h indicators during market hours
        global_scan_worker,                          # 7 — full-universe scan
        watchlist_notification_worker,               # 8 — watchlist alerts
        news_worker,                                 # 9 — global news (MoneyControl)
        news_rss_worker,                             # 10 — RSS news aggregation
        watchlist_news_worker,                       # 11 — per-symbol news
        watchlist_deals_worker,                      # 11b — per-symbol deals & trades
        fundamentals_worker,                         # 11c — screener mcap/NP-YoY backfill (nightly)
        results_calendar_worker,                     # 12 — upcoming results alerts
        vacuum_worker,                               # 13 — weekly VACUUM (Sunday 04:00)
        ai_picks_morning_worker,                     # 14 — AI Picks (8am)
        ai_picks_evening_worker,                     # 15 — AI Picks (5pm)
    ]
    for target in targets:
        t = threading.Thread(target=target, daemon=True, name=target.__name__)
        t.start()
        _worker_threads.append(t)
        logger.info("start_all_workers: spawned %s", t.name)
        # Stagger launches so all workers don't simultaneously hammer the DB
        # at startup. 500 ms per worker = 4.5 s spread across 10 workers.
        await asyncio.sleep(0.5)
    return _worker_threads


def stop_all_workers(timeout: float = 35.0) -> None:
    """Signal all workers to stop and wait up to `timeout` seconds for each to exit.

    Default timeout is 35 seconds to allow for HTTP requests to complete (max 30s).
    After all threads exit, closes the persistent per-thread event loops
    created by ``_run_async`` (C.6).
    """
    logger.info("stop_all_workers: setting shutdown event")
    _shutdown_event.set()
    for t in _worker_threads:
        t.join(timeout=timeout)
        if t.is_alive():
            logger.warning("stop_all_workers: %s did not exit within %.1fs, abandoning", t.name, timeout)
        else:
            logger.info("stop_all_workers: %s exited cleanly", t.name)
    _cleanup_run_async_loops()


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
