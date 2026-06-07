r"""Stock universe sync core (audit C.1, A.3, A.13).

Extracted from ``app/backgroundtasks/_impl.py`` (the original
4994-LOC module).  This module is the **sync core** that the
``stock_universe_worker`` daemon-thread runs once per day:

  1. Fetch the full NSE stock list (``nse_client.get_stock_list()``).
  2. For each symbol, fetch metadata (``nse_client.get_stock_metadata()``).
  3. Skip symbols that were updated within the stale window
     (``stale_delta = 12 hours``).
  4. Batch the metadata and ``_bulk_insert_stock_universe`` into
     the ``stock_universe`` table (with ``ON CONFLICT DO
     UPDATE`` semantics).
  5. On ``SymbolNotFoundError``, call
     ``_update_symbol_error_status`` to mark the row as 'unknown'.

The worker (``stock_universe_worker()``) lives in
``app.workers.universe``.

A.13: migrated ``_bg_impl`` references to canonical imports.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import OperationalError as _SAOperationalError

from app.database import _SyncSessionLocal
from app.jobs.runner import update_job_status_sync
from app.models import stockuniverse
from app.services.nse_client import SymbolNotFoundError, nse_client

logger = logging.getLogger(__name__)


# Module-level singletons from the runtime helpers.  These are
# rebound at import time and read at function-call time so callers
# can still monkeypatch \`\`app.backgroundtasks._shutdown_event\`\`
# without breaking the import here.
# (We resolve lazily inside each function to keep this module
# import-order safe and to support tests that patch the runtime
# singletons after import.)


def _shutdown_event():
    r"""Lazy-resolve the threading.Event from ``app.backgroundtasks._runtime``.

    Imported lazily so this module doesn't depend on the package's
    import order.
    """
    from app.backgroundtasks._runtime import _shutdown_event
    return _shutdown_event


def _sleep_interruptible(seconds: float) -> bool:
    from app.backgroundtasks._runtime import _sleep_interruptible
    return _sleep_interruptible(seconds)


# ─── Sync core ────────────────────────────────────────────────────────────


def _stock_universe_sync() -> None:
    """Populate or refresh the stock universe table. Runs synchronously in a worker thread."""
    try:
        logger.info("stock_universe_sync: starting")
        stock_list: list[str] = nse_client.get_stock_list()
        total = len(stock_list)
        logger.info("stock_universe_sync: %d symbols to process", total)

        stale_delta = timedelta(hours=12)
        batch_size = 50
        shutdown = _shutdown_event()

        with _SyncSessionLocal() as session:
            batch: list = []
            for i, symbol in enumerate(stock_list, 1):
                if shutdown.is_set():
                    logger.info("stock_universe_sync: shutdown requested mid-run, aborting")
                    return

                if i % 100 == 0:
                    progress = int((i / total) * 100)
                    update_job_status_sync(
                        "job.stock_universe", "running", progress=progress,
                        message=f"Processing {i}/{total} symbols",
                    )

                existing = session.get(stockuniverse.StockUniverse, symbol)
                last_time = None
                if existing is not None:
                    last_time = getattr(existing, "last_update_time", None) or getattr(
                        existing, "last_fetched_at", None
                    )
                if last_time is not None:
                    try:
                        now = datetime.now()
                        if (now - last_time) < stale_delta:
                            logger.debug(
                                "Skipping %s — last update was %s (within %.0f hours)",
                                symbol,
                                last_time,
                                stale_delta.total_seconds() / 3600,
                            )
                            continue
                    except Exception:
                        logger.debug(
                            "Unable to compare last update time for %s; refreshing",
                            symbol,
                        )

                try:
                    metadata = nse_client.get_stock_metadata(symbol)
                    batch.append(metadata)
                    if len(batch) >= batch_size:
                        _bulk_insert_stock_universe(session, batch)
                        session.commit()
                        batch.clear()
                        if _sleep_interruptible(0.5):
                            return
                except SymbolNotFoundError:
                    _update_symbol_error_status(session, symbol, "unknown")
                    session.commit()
                    logger.warning("Symbol %s: no tradeable series found, marked as unknown", symbol)
                    if _sleep_interruptible(0.5):
                        return
                    continue
                except _SAOperationalError as e:
                    logger.warning(
                        "DB write failed for %s (will retry next cycle): %s", symbol, e
                    )
                    session.rollback()
                    if _sleep_interruptible(1.0):
                        return
                    continue
                except Exception:
                    logger.warning("Failed to fetch NSE metadata for %s, skipping", symbol)
                    if _sleep_interruptible(1.0):
                        return
                    continue

            if batch:
                _bulk_insert_stock_universe(session, batch)
                session.commit()

        update_job_status_sync(
            "job.stock_universe",
            "idle",
            progress=100,
            message="Stock universe sync complete",
        )
        logger.info("stock_universe_sync: complete")
    except Exception:
        logger.exception("stock_universe_sync: unhandled exception; will retry next cycle")


# ─── Helpers (also moved; called by the sync core) ────────────────────────


def _update_symbol_error_status(session, symbol: str, reason: str, series: str | None = None) -> None:
    """Set review_status (and optionally series) on an existing stock_universe row."""
    values: dict[str, Any] = {"review_status": reason}
    if series is not None:
        values["series"] = series
    session.execute(
        update(stockuniverse.StockUniverse)
        .where(stockuniverse.StockUniverse.symbol == symbol)
        .values(**values)
    )


def _bulk_insert_stock_universe(session, batch: list) -> None:
    """Bulk insert or update a batch of stock universe records."""
    if not batch:
        return
    for metadata in batch:
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
                high_52w=metadata.high_52w,
                low_52w=metadata.low_52w,
                high_52w_date=metadata.high_52w_date,
                low_52w_date=metadata.low_52w_date,
                series=metadata.series if hasattr(metadata, "series") else None,
                review_status=None,
                ticker_failure_count=0,
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
                    "high_52w": metadata.high_52w,
                    "low_52w": metadata.low_52w,
                    "high_52w_date": metadata.high_52w_date,
                    "low_52w_date": metadata.low_52w_date,
                    "series": metadata.series if hasattr(metadata, "series") else None,
                    "review_status": None,  # clear error status on re-fetch
                    "high_52w_updated_at": func.now(),
                    "updated_at": func.now(),
                },
            )
        )
        session.execute(stmt)
