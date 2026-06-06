"""Ticker backfill sync core (audit C.1, A.4).

Extracted from ``app/backgroundtasks/_impl.py`` so the heavy
``_impl.py`` shrinks toward its target size.

Public function:
- ``_ticker_backfill_sync()`` — pull ~365 days of OHLCV data for
  symbols whose warehouse rows are stale, processed in batches of
  10 with NSE session refresh every 50 symbols.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import time

from app.services import ticker_warehouse


def _shutdown_event():
    r"""Lazy-resolve the threading.Event from ``app.backgroundtasks``.

    Imported lazily so this module doesn't depend on the package's
    import order (the original ``_impl.py`` defines both the
    helpers and the workers; after the split, ``_impl.py``
    imports the workers, and the workers in turn depend on
    ``_shutdown_event``).
    """
    from app.backgroundtasks import _impl
    return _impl._shutdown_event


def _sleep_interruptible(seconds: float) -> bool:
    r"""Lazy-resolve the interruptible sleep helper.

    Returns True if shutdown was requested during the sleep.
    """
    from app.backgroundtasks import _impl
    return _impl._sleep_interruptible(seconds)


def _is_job_enabled(name: str) -> bool:
    r"""Lazy-resolve the job-enabled check helper."""
    from app.backgroundtasks import _impl
    return _impl._is_job_enabled(name)


def _update_job_status_sync(*args, **kwargs):
    r"""Lazy-resolve the job-status updater helper."""
    from app.backgroundtasks import _impl
    return _impl.update_job_status_sync(*args, **kwargs)


def _ticker_backfill_sync() -> None:
    """Perform the ticker backfill synchronization.

    Processes up to 10 symbols concurrently using a thread pool. Each batch
    of 10 is submitted together; results are collected before moving to the
    next batch. One REQUEST_DELAY_SECONDS sleep is applied per batch (not per
    symbol) to stay within NSE rate limits while improving throughput ~10x.
    """
    from app.backgroundtasks._impl import logger

    _BATCH_SIZE = 10

    symbols = ticker_warehouse.get_symbols_needing_backfill()
    total = len(symbols)
    if total == 0:
        logger.info("ticker_backfill_sync: no symbols need backfill")
        _update_job_status_sync("job.ticker_backfill", "idle", progress=100, message="All symbols up to date")
        return

    logger.info(f"ticker_backfill_sync: {total} symbols need backfill (batch_size={_BATCH_SIZE})")

    processed = 0
    for batch_start in range(0, total, _BATCH_SIZE):
        if _shutdown_event().is_set():
            break

        batch = symbols[batch_start : batch_start + _BATCH_SIZE]

        # Refresh NSE session every 50 cumulative symbols
        if processed > 0 and (processed // 50) != ((processed - len(batch)) // 50):
            logger.info(f"ticker_backfill_sync: refreshing session after {processed} symbols")
            ticker_warehouse._refresh_nse_session()

        progress = int((batch_start / total) * 100)
        _update_job_status_sync(
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
        time.sleep(ticker_warehouse.REQUEST_DELAY_SECONDS)

    _update_job_status_sync("job.ticker_backfill", "idle", progress=100, message="Backfill complete")
    logger.info("ticker_backfill_sync: complete")
