"""Morningstar fair-value sync (Phase C.1, A.12 part 2).

Background sync of stock fair values from Morningstar.

Two daily cron cycles:

  - ``sync_watchlist_fair_values`` — every 3 hours, fetches fair values
    for the user's watchlist symbols.
  - ``sync_all_fair_values`` — nightly at 20:30 UTC, fetches fair values
    for every symbol in the stock universe (and resolves any missing
    Morningstar IDs along the way).

Both cycles gate on ``_is_job_enabled(job_name)`` and acquire a
per-job lock so they never run concurrently.  Progress is reported via
``update_job_status`` so the frontend Jobs panel can show live progress.

Migrated from ``app.backgroundtasks._impl`` (audit C.1, A.12 part 2).
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.database import AsyncSessionLocal
from app.models import stockuniverse
from app.models.stockuniverse import StockUniverse
from app.models.system_config import SystemConfig
from app.models.watchlist import WatchlistItem
from app.services.morningstar_client import (
    REQUEST_DELAY,
    DB_BATCH_SIZE,
    morningstar_client,
)
from app.jobs.runner import update_job_status


logger = logging.getLogger(__name__)

# Imported lazily inside function bodies to break the circular
# dependency: ``app.backgroundtasks.__init__`` (the shim) imports
# symbols from this module, so we cannot import
# ``app.backgroundtasks._impl`` at module level here.  See
# ``tests/test_backgroundtasks_split.py`` for the shim contract.


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
    from app.backgroundtasks import _impl as _bg_impl
    if not _bg_impl._is_job_enabled("job.watchlist_fair_value"):
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
    from app.backgroundtasks import _impl as _bg_impl
    if not _bg_impl._is_job_enabled("job.full_fair_value"):
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
    from app.backgroundtasks import _impl as _bg_impl
    shutdown_event = _bg_impl.get_async_shutdown_event()
    while not shutdown_event.is_set():
        await asyncio.sleep(_bg_impl._seconds_until_next_cron("0 */3 * * *"))
        if shutdown_event.is_set():
            break
        await sync_watchlist_fair_values()
    logger.info("watchlist_scheduler: stopped")


async def _run_nightly_scheduler():
    """Run at 8:30 PM UTC daily (cron: 30 20 * * *)."""
    from app.backgroundtasks import _impl as _bg_impl
    shutdown_event = _bg_impl.get_async_shutdown_event()
    while not shutdown_event.is_set():
        await asyncio.sleep(_bg_impl._seconds_until_next_cron("30 20 * * *"))
        if shutdown_event.is_set():
            break
        await sync_all_fair_values()
    logger.info("nightly_scheduler: stopped")
