"""NSE market-cap fill — ``StockUniverse.market_cap_cr`` for symbols missing it.

Why this exists: Analysis market caps (``MarketCategory.market_cap``) aggregate
per-member caps from ``StockUniverse.market_cap_cr`` first
(``market_local._member_mcap``), but the universe sync only stores a cap when
NSE metadata happens to carry tradeInfo — usually absent — and
``ticker_screener_snapshot.market_cap`` is hardcoded NULL. On a fresh install
every category therefore aggregates NULL and the Analysis window shows "—"
no matter how often ``job.market_data`` is re-triggered (it just re-sums the
same NULLs). The screener backfill (``job.fundamentals``) is login-walled,
throttled and nightly-bounded, so it cannot close the gap promptly.

This pass fetches NSE tradeInfo (``totalMarketCap``) directly for the symbols
still missing a cap and stores it in Rs Cr. Bounded per run with a
``SyncState`` cursor (``task_name = "market_caps"``) so nightly runs and
manual triggers make steady resume-exact progress. A successful fill chains a
``market_data`` rebuild so Analysis picks the new caps up immediately.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.database import _SyncSessionLocal
from app.jobs.runner import update_job_status_sync
from app.models.stockuniverse import StockUniverse
from app.models.sync_state import SyncState
from app.services.nse_client import SymbolNotFoundError, nse_client

logger = logging.getLogger(__name__)

TASK_NAME = "market_caps"
BATCH_LIMIT = 100
CURSOR_WRITE_EVERY = 25
MAX_RUN_SECONDS = 30 * 60


def _report(status: str, progress: int | None, message: str) -> None:
    try:
        update_job_status_sync("job.market_caps", status, progress=progress, message=message)
    except Exception:
        pass


def _read_cursor(session) -> str | None:
    row = (
        session.execute(
            select(SyncState.last_symbol).where(SyncState.task_name == TASK_NAME)
        )
    ).scalar_one_or_none()
    return row


def _write_cursor(session, last_symbol: str | None) -> None:
    stmt = sqlite_insert(SyncState).values(task_name=TASK_NAME, last_symbol=last_symbol)
    stmt = stmt.on_conflict_do_update(
        index_elements=["task_name"],
        set_={"last_symbol": stmt.excluded.last_symbol},
    )
    session.execute(stmt)
    session.commit()


def _chain_market_rebuild() -> None:
    """Rebuild sector/industry aggregates so fresh caps reach Analysis now."""
    from app.services.data_sync.market import _market_data_sync

    _market_data_sync()


def _market_caps_sync(max_symbols: int = BATCH_LIMIT) -> dict[str, int]:
    """Fill missing ``StockUniverse.market_cap_cr`` from NSE tradeInfo.

    Bounded: processes at most ``max_symbols`` NULL-cap symbols per run,
    resuming from the persisted cursor. Never clobbers an existing value
    with NULL. Returns outcome counts.
    """
    from app.backgroundtasks._runtime import _shutdown_event

    total = {"processed": 0, "filled": 0, "skipped": 0, "failed": 0}
    started = time.monotonic()
    shutdown = _shutdown_event

    with _SyncSessionLocal() as session:
        cursor = _read_cursor(session)
        stmt = (
            select(StockUniverse.symbol)
            .where(StockUniverse.market_cap_cr.is_(None))
            .order_by(StockUniverse.symbol)
        )
        if cursor:
            stmt = stmt.where(StockUniverse.symbol > cursor)
        candidates = [r for r in session.execute(stmt.limit(max_symbols + 1)).scalars().all()]

    exhausted = len(candidates) <= max_symbols
    todo = candidates[:max_symbols]
    if not todo:
        # Nothing missing (or cursor past the end): reset for wrap-around.
        try:
            with _SyncSessionLocal() as session:
                _write_cursor(session, None)
        except Exception:
            logger.debug("market_caps_sync: cursor reset failed", exc_info=True)
        logger.info("market_caps_sync: no symbols missing market cap — nothing to do")
        _report("idle", 100, "All symbols have market cap — nothing to do")
        return total

    logger.info("market_caps_sync: starting (%d candidates%s)", len(todo),
                f", cursor {cursor}" if cursor else "")
    last_symbol: str | None = cursor
    for i, symbol in enumerate(todo, 1):
        if shutdown.is_set():
            logger.info("market_caps_sync: shutdown requested — exiting")
            break
        if time.monotonic() - started >= MAX_RUN_SECONDS:
            logger.info("market_caps_sync: runtime cap reached after %d symbols", i - 1)
            break
        total["processed"] += 1
        try:
            metadata = nse_client.get_stock_metadata(symbol)
            mcap = getattr(metadata, "market_cap_cr", None)
        except SymbolNotFoundError:
            logger.debug("market_caps_sync: %s has no tradeable series — skipping", symbol)
            total["skipped"] += 1
            last_symbol = symbol
            continue
        except Exception as exc:
            logger.warning("market_caps_sync: NSE fetch failed for %s: %s", symbol, exc)
            total["failed"] += 1
            last_symbol = symbol
            continue
        if mcap:
            try:
                with _SyncSessionLocal() as session:
                    session.execute(
                        update(StockUniverse)
                        .where(StockUniverse.symbol == symbol)
                        .values(market_cap_cr=mcap, updated_at=func.now())
                    )
                    session.commit()
                total["filled"] += 1
            except Exception as exc:
                logger.warning("market_caps_sync: DB write failed for %s: %s", symbol, exc)
                total["failed"] += 1
        else:
            # NSE had no tradeInfo for this symbol — leave NULL, advance.
            total["skipped"] += 1
        last_symbol = symbol
        if i % CURSOR_WRITE_EVERY == 0 or i == len(todo):
            try:
                with _SyncSessionLocal() as session:
                    _write_cursor(session, last_symbol)
            except Exception:
                logger.debug("market_caps_sync: cursor write failed", exc_info=True)
        if i % 25 == 0:
            _report("running", int(100 * i / len(todo)),
                    f"Filled {total['filled']}/{total['processed']} symbols")

    if exhausted and not shutdown.is_set():
        try:
            with _SyncSessionLocal() as session:
                _write_cursor(session, None)
        except Exception:
            logger.debug("market_caps_sync: cursor reset failed", exc_info=True)

    _report("idle", 100, f"Filled {total['filled']}/{total['processed']} symbols")
    logger.info("market_caps_sync: done — processed=%d filled=%d skipped=%d failed=%d",
                total["processed"], total["filled"], total["skipped"], total["failed"])

    if total["filled"]:
        try:
            logger.info("market_caps_sync: chaining market_data rebuild")
            _chain_market_rebuild()
        except Exception:
            logger.exception("market_caps_sync: chained market_data rebuild failed")

    return total
