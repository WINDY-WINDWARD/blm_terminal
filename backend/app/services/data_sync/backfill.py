"""Ticker backfill sync core (audit C.1, A.4, A.13).

Extracted from ``app/backgroundtasks/_impl.py`` so the heavy
``_impl.py`` shrinks toward its target size.

Public function:
- ``_ticker_backfill_sync()`` — pull ~365 days of OHLCV data for
  symbols whose warehouse rows are stale, processed in batches of
  10 with NSE session refresh every 50 symbols.

A.13: migrated ``_bg_impl`` references to canonical imports.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

from app.services import ticker_warehouse


logger = logging.getLogger(__name__)


def _ticker_backfill_sync() -> None:
    """Perform the ticker backfill synchronization.

    Processes up to 10 symbols concurrently using a thread pool. Each batch
    of 10 is submitted together; results are collected before moving to the
    next batch. One REQUEST_DELAY_SECONDS sleep is applied per batch (not per
    symbol) to stay within NSE rate limits while improving throughput ~10x.
    """
    from app.backgroundtasks._runtime import (
        _is_job_enabled,
        _shutdown_event,
        _sleep_interruptible,
    )
    from app.jobs.runner import update_job_status_sync

    from app.services.checkpoint_service import get_checkpoint, set_checkpoint, clear_checkpoint

    _BATCH_SIZE = 10

    symbols = ticker_warehouse.get_symbols_needing_backfill()
    _, cursor_info = get_checkpoint("ticker_backfill")
    resume_from = 0
    if cursor_info:
        try:
            # cursor_info stores the batch_start index of the last completed batch
            resume_from = int(cursor_info) + _BATCH_SIZE
        except ValueError:
            logger.warning("ticker_backfill_sync: invalid checkpoint cursor '%s', restarting", cursor_info)
    if resume_from > 0:
        logger.info("ticker_backfill_sync: resuming from index %d / %d", resume_from, len(symbols))
        symbols = symbols[resume_from:]

    total = len(symbols)
    if total == 0:
        logger.info("ticker_backfill_sync: no symbols need backfill")
        clear_checkpoint("ticker_backfill")
        update_job_status_sync("job.ticker_backfill", "idle", progress=100, message="All symbols up to date")
        return

    logger.info(f"ticker_backfill_sync: {total} symbols need backfill (batch_size={_BATCH_SIZE})")

    processed = 0
    for batch_start in range(0, total, _BATCH_SIZE):
        if _shutdown_event.is_set():
            break

        batch = symbols[batch_start : batch_start + _BATCH_SIZE]

        # Refresh NSE session every 50 cumulative symbols
        if processed > 0 and (processed // 50) != ((processed - len(batch)) // 50):
            logger.info(f"ticker_backfill_sync: refreshing session after {processed} symbols")
            ticker_warehouse._refresh_nse_session()

        progress = int((batch_start / total) * 100)
        update_job_status_sync(
            "job.ticker_backfill",
            "running",
            progress=progress,
            message=f"Backfilling {batch[0]}..{batch[-1]} ({batch_start + 1}-{min(batch_start + _BATCH_SIZE, total)}/{total})",
        )

        with ThreadPoolExecutor(max_workers=_BATCH_SIZE) as pool:
            future_to_symbol = {
                pool.submit(ticker_warehouse.backfill_symbol, sym, 365): sym
                for sym in batch
            }
            for future in as_completed(future_to_symbol):
                sym = future_to_symbol[future]
                try:
                    future.result()
                except Exception as e:
                    logger.warning(f"ticker_backfill_sync: failed for {sym}: {e}")

        processed += len(batch)
        set_checkpoint("ticker_backfill", cursor_info=str(batch_start))
        # explicit lock yielding
        time.sleep(0.05)
        time.sleep(ticker_warehouse.REQUEST_DELAY_SECONDS)

    if not _shutdown_event.is_set():
        clear_checkpoint("ticker_backfill")
    update_job_status_sync("job.ticker_backfill", "idle", progress=100, message="Backfill complete")
    logger.info("ticker_backfill_sync: complete")
