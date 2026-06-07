import asyncio
import logging
import threading
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

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
    reset_async_shutdown_event,
    set_async_shutdown_event,
    _sleep_interruptible,
    _seconds_until_next_cron,
    get_async_shutdown_event,
)
from app.database import _SyncSessionLocal, AsyncSessionLocal
from app.config import settings
from app.models import stockuniverse
from app.models.stockuniverse import StockUniverse
from app.models.system_config import SystemConfig
from app.models.watchlist import WatchlistItem
from app.services.morningstar_client import (
    REQUEST_DELAY,
    DB_BATCH_SIZE,
    morningstar_client,
)
from app.jobs.runner import sync_all_jobs_to_db, update_job_status, update_job_status_sync


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
      11. market_data_worker                 — waits stock_universe_done; then runs independently
      12. results_calendar_worker            — waits stock_universe_done; then runs independently
      13. vacuum_worker                      — waits ticker_scores_done; weekly Sunday 04:00 cron

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
    from app.workers.market_calendar import market_data_worker, results_calendar_worker
    from app.workers.maintenance import vacuum_worker

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
        market_data_worker,                          # 7 — live market data
        global_scan_worker,                          # 8 — full-universe scan
        watchlist_notification_worker,               # 9 — watchlist alerts
        news_worker,                                 # 10 — global news (MoneyControl)
        news_rss_worker,                             # 11 — RSS news aggregation
        watchlist_news_worker,                       # 12 — per-symbol news
        results_calendar_worker,                     # 13 — upcoming results alerts
        vacuum_worker,                               # 14 — weekly VACUUM (Sunday 04:00)
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


# ---------------------------------------------------------------------------
# Morningstar Fair Value Sync (A.12 part 2 target home)
# ---------------------------------------------------------------------------
# These functions live in ``_impl`` temporarily; the next refactor
# (A.12 part 2) moves them to ``app/services/fair_value.py``.

_watchlist_sync_lock: asyncio.Lock | None = None
_full_sync_lock: asyncio.Lock | None = None


def _get_watchlist_lock() -> asyncio.Lock:
    global _watchlist_sync_lock
    if _watchlist_sync_lock is None:
        _watchlist_sync_lock = asyncio.Lock()
    return _watchlist_sync_lock


def _get_full_lock() -> asyncio.Lock:
    global _full_sync_lock
    if _full_sync_lock is None:
        _full_sync_lock = asyncio.Lock()
    return _full_sync_lock


async def _batch_update_fair_values(
    symbols: list[str],
    update_morningstar_id: bool = False,
    update_fair_value: bool = True,
    progress_job_key: str | None = None,
    progress_start: int = 0,
    progress_end: int = 100,
) -> tuple[int, int]:
    """Batch update fair values for symbols. Returns (updated, failed)."""
    updated = 0
    failed = 0
    pending: list[tuple] = []
    total = len(symbols)

    async with AsyncSessionLocal() as db:
        for i, symbol in enumerate(symbols, 1):
            try:
                result = await morningstar_client.get_fair_value_by_symbol(symbol)
                fair_value = result.get("fairValue")

                if fair_value:
                    values: dict = {
                        "fair_value": fair_value,
                        "fair_value_updated_at": datetime.now(timezone.utc),
                    }
                    if update_morningstar_id:
                        values["morningstar_id"] = result.get("morningstarId")

                    pending.append((values, symbol))
                    updated += 1
                else:
                    failed += 1
            except Exception as e:
                logger.warning(f"Failed to fetch fair value for {symbol}: {e}")
                failed += 1

            if len(pending) >= DB_BATCH_SIZE:
                for values, sym in pending:
                    stmt = (
                        update(stockuniverse.StockUniverse)
                        .where(stockuniverse.StockUniverse.symbol == sym)
                        .values(**values)
                    )
                    await db.execute(stmt)
                await db.commit()
                if progress_job_key and total:
                    pct = progress_start + int((i / total) * (progress_end - progress_start))
                    await update_job_status(
                        progress_job_key, "running", progress=pct,
                        message=f"Fetching fair values: {i}/{total}",
                    )
                logger.debug(f"Fair value sync progress: {i}/{total}")
                pending = []

            await asyncio.sleep(REQUEST_DELAY)

        if pending:
            for values, sym in pending:
                stmt = (
                    update(stockuniverse.StockUniverse)
                    .where(stockuniverse.StockUniverse.symbol == sym)
                    .values(**values)
                )
                await db.execute(stmt)
            await db.commit()

    return updated, failed


async def _batch_resolve_morningstar_ids(
    symbols: list[str],
    progress_job_key: str | None = None,
    progress_start: int = 0,
    progress_end: int = 100,
) -> int:
    """Batch resolve Morningstar IDs for symbols. Returns count of resolved IDs."""
    resolved = 0
    pending: list[tuple] = []
    total = len(symbols)

    async with AsyncSessionLocal() as db:
        for i, symbol in enumerate(symbols, 1):
            try:
                ms_id = await morningstar_client.resolve_symbol_to_id(symbol)
                if ms_id:
                    pending.append((ms_id, symbol))
                    resolved += 1
                    logger.debug(f"Resolved {symbol} -> {ms_id}")
            except Exception as e:
                logger.warning(f"Failed to resolve ID for {symbol}: {e}")

            if len(pending) >= DB_BATCH_SIZE:
                for mid, sym in pending:
                    stmt = (
                        update(stockuniverse.StockUniverse)
                        .where(stockuniverse.StockUniverse.symbol == sym)
                        .values(morningstar_id=mid)
                    )
                    await db.execute(stmt)
                await db.commit()
                if progress_job_key and total:
                    pct = progress_start + int((i / total) * (progress_end - progress_start))
                    await update_job_status(
                        progress_job_key, "running", progress=pct,
                        message=f"Resolving Morningstar IDs: {i}/{total}",
                    )
                logger.info(f"ID sync progress: {i}/{total}")
                pending = []

            await asyncio.sleep(REQUEST_DELAY)

        if pending:
            for mid, sym in pending:
                stmt = (
                    update(stockuniverse.StockUniverse)
                    .where(stockuniverse.StockUniverse.symbol == sym)
                    .values(morningstar_id=mid)
                )
                await db.execute(stmt)
            await db.commit()

    return resolved


async def sync_watchlist_fair_values():
    """Fetch fair values for all watchlist stocks every 3 hours."""
    if not _is_job_enabled("job.watchlist_fair_value"):
        logger.info("watchlist_fair_value sync disabled, skipping")
        return

    lock = _get_watchlist_lock()
    if lock.locked():
        logger.warning("Watchlist sync already running, skipping this cycle")
        return

    async with lock:
        try:
            logger.info("Starting watchlist fair value sync")
            await update_job_status("job.watchlist_fair_value", "running", progress=0, message="Starting watchlist fair value sync...")

            async with AsyncSessionLocal() as db:
                stmt = select(WatchlistItem.symbol).distinct()
                result = await db.execute(stmt)
                symbols = [row[0] for row in result.fetchall()]

            if not symbols:
                logger.info("No symbols in watchlist to sync")
                await _update_sync_timestamp("last_watchlist_fairvalue_sync")
                await update_job_status("job.watchlist_fair_value", "idle", progress=100, message="No symbols to sync")
                return

            updated, failed = await _batch_update_fair_values(
                symbols,
                progress_job_key="job.watchlist_fair_value",
                progress_start=5,
                progress_end=95,
            )

            logger.info(f"Watchlist fair value sync complete: {updated} updated, {failed} failed")
            await _update_sync_timestamp("last_watchlist_fairvalue_sync")
            await update_job_status("job.watchlist_fair_value", "idle", progress=100, message=f"Completed: {updated} updated, {failed} failed")
        except Exception as e:
            logger.exception("Watchlist fair value sync failed")
            await update_job_status("job.watchlist_fair_value", "failed", error=str(e)[:512])


async def sync_all_fair_values():
    """Fetch fair values for all stocks in stock_universe."""
    if not _is_job_enabled("job.full_fair_value"):
        logger.info("full_fair_value sync disabled, skipping")
        return

    lock = _get_full_lock()
    if lock.locked():
        logger.warning("Full sync already running, skipping this cycle")
        return

    async with lock:
        try:
            logger.info("Starting full universe fair value sync")
            await update_job_status("job.full_fair_value", "running", progress=0, message="Starting full fair value sync...")

            async with AsyncSessionLocal() as db:
                stmt = select(stockuniverse.StockUniverse.symbol)
                result = await db.execute(stmt)
                all_symbols = [row[0] for row in result.fetchall()]

            if not all_symbols:
                logger.info("No symbols in stock universe to sync")
                await _update_sync_timestamp("last_full_fairvalue_sync")
                await update_job_status("job.full_fair_value", "idle", progress=100, message="No symbols to sync")
                return

            logger.info("Step 1: Populating missing Morningstar IDs")
            await update_job_status("job.full_fair_value", "running", progress=5, message="Resolving Morningstar IDs...")
            resolved_count = await _batch_resolve_morningstar_ids(
                all_symbols,
                progress_job_key="job.full_fair_value",
                progress_start=5,
                progress_end=45,
            )
            logger.info(f"Step 1 complete: {resolved_count} IDs populated")

            logger.info("Step 2: Fetching fair values")
            await update_job_status("job.full_fair_value", "running", progress=50, message="Fetching fair values...")
            updated, failed = await _batch_update_fair_values(
                all_symbols,
                update_morningstar_id=True,
                progress_job_key="job.full_fair_value",
                progress_start=50,
                progress_end=95,
            )

            logger.info(f"Full universe fair value sync complete: {updated} updated, {failed} failed")
            await _update_sync_timestamp("last_full_fairvalue_sync")
            await update_job_status("job.full_fair_value", "idle", progress=100, message=f"Completed: {updated} updated, {failed} failed")
        except Exception as e:
            logger.exception("Full fair value sync failed")
            await update_job_status("job.full_fair_value", "failed", error=str(e)[:512])


async def _update_sync_timestamp(key: str):
    """Update system_config with current timestamp using upsert."""
    async with AsyncSessionLocal() as db:
        stmt = sqlite_insert(SystemConfig).values(
            key=key,
            value=datetime.now(timezone.utc).isoformat(),
            updated_at=datetime.now(timezone.utc),
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["key"],
            set_={
                "value": stmt.excluded.value,
                "updated_at": stmt.excluded.updated_at,
            }
        )
        await db.execute(stmt)
        await db.commit()


async def _should_trigger_full_sync() -> bool:
    """Check if full sync should run at startup."""
    async with AsyncSessionLocal() as db:
        stmt = select(func.max(stockuniverse.StockUniverse.fair_value_updated_at))
        result = await db.execute(stmt)
        last_update = result.scalar()

        if last_update is None:
            return True

        now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
        if now_naive - last_update > timedelta(hours=24):
            return True

        return False


async def _run_watchlist_scheduler():
    """Run every 3 hours (cron: 0 */3 * * *)."""
    shutdown_event = get_async_shutdown_event()
    while not shutdown_event.is_set():
        await asyncio.sleep(_seconds_until_next_cron("0 */3 * * *"))
        if shutdown_event.is_set():
            break
        await sync_watchlist_fair_values()
    logger.info("watchlist_scheduler: stopped")


async def _run_nightly_scheduler():
    """Run at 8:30 PM UTC daily (cron: 30 20 * * *)."""
    shutdown_event = get_async_shutdown_event()
    while not shutdown_event.is_set():
        await asyncio.sleep(_seconds_until_next_cron("30 20 * * *"))
        if shutdown_event.is_set():
            break
        await sync_all_fair_values()
    logger.info("nightly_scheduler: stopped")


# Re-exports from split submodules (audit C.1, A.3-A.8).
#
# Each of these was moved out of this file to a dedicated submodule
# (e.g. ``app/services/data_sync/universe.py``).  The re-exports here
# keep the package-level import path working and preserve
# ``is``-identity for tests that pin the move.  See
# ``tests/test_data_sync_universe.py`` etc. for the contract.
#
# These are SAFE to re-export at module level: the data_sync modules
# use lazy imports inside their function bodies, so importing them
# here at the bottom of _impl does not create a circular import.
from app.services.data_sync.universe import (  # noqa: E402,F401
    _stock_universe_sync,
    _update_symbol_error_status,
    _bulk_insert_stock_universe,
)
from app.services.data_sync.backfill import (  # noqa: E402,F401
    _ticker_backfill_sync,
)
from app.services.data_sync.intraday import (  # noqa: E402,F401
    _ticker_intraday_update_sync,
    _ticker_intraday_hourly_stale_check_sync,
)
from app.services.data_sync.daily import (  # noqa: E402,F401
    _ticker_daily_update_sync,
)
from app.services.data_sync.scores import (  # noqa: E402,F401
    _ticker_scores_sync,
)
from app.services.data_sync.indicators import (  # noqa: E402,F401
    _ticker_indicators_sync,
    _ticker_intraday_indicators_sync,
)
