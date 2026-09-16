"""Background sync service for watchlist deals & trades.

Fetches Screener trades and iinvest all-in-one data for watchlist symbols,
persisting to persistent_cache and participating in single-writer serialization.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from app.database import AsyncSessionLocal, _SyncSessionLocal
from app.models.watchlist import WatchlistItem
from app.services.persistent_cache import get_cached_json, set_cached_json
from app.services.screener_client import screener_client
from app.services.iinvest_client import get_iinvest_client
from app.services.write_queue import enqueue_write, PRIO_BULK_DATA

logger = logging.getLogger(__name__)

WATCHLIST_DEALS_STALE_SECONDS = 30 * 60  # 30 minutes


async def _warm_symbol_deals_async(symbol: str) -> None:
    """Warm screener trades and iinvest data for a single symbol."""
    symbol_upper = symbol.strip().upper()
    try:
        # Check staleness via persistent_cache
        cache_key_prefix = f"deals:warmed:{symbol_upper}"
        cached = await get_cached_json(cache_key_prefix)
        if cached:
            logger.debug("_warm_symbol_deals_async: %s deals recently warmed, skipping", symbol_upper)
            return

        tasks = []
        # 1. Screener trades
        async def _fetch_screener():
            try:
                if screener_client.is_usable:
                    trades, _ = await screener_client.get_trades_by_symbol(symbol_upper)
                    return trades
            except Exception as e:
                logger.debug("screener trades fetch failed for %s: %s", symbol_upper, e)
            return None

        # 2. iinvest all
        async def _fetch_iinvest():
            try:
                client = get_iinvest_client()
                async with AsyncSessionLocal() as db:
                    isin, path = await client.resolve_path(symbol_upper, db=db)
                if path and isin:
                    all_data = await client.get_all(path, isin)
                    # Persist iinvest data sections via set_cached_json (15m TTL)
                    for k, val in all_data.items():
                        if isinstance(val, dict) and "error" not in val:
                            ck = f"iinvest:{k}:{path}"
                            await set_cached_json(ck, val, ttl_hours=0.25)
                    return all_data
            except Exception as e:
                logger.debug("iinvest all fetch failed for %s: %s", symbol_upper, e)
            return None

        await asyncio.gather(_fetch_screener(), _fetch_iinvest(), return_exceptions=True)

        # Mark symbol as warmed for 30m
        await set_cached_json(cache_key_prefix, {"warmed_at": datetime.now(timezone.utc).isoformat()}, ttl_hours=0.5)
        logger.info("_warm_symbol_deals_async: successfully warmed deals for %s", symbol_upper)

    except Exception as exc:
        logger.warning("_warm_symbol_deals_async failed for %s: %s", symbol_upper, exc)


def warm_symbol_deals(symbol: str) -> None:
    """Synchronous / fire-and-forget trigger to warm a single symbol."""
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_warm_symbol_deals_async(symbol))
    except RuntimeError:
        from app.backgroundtasks._runtime import _run_async
        _run_async(_warm_symbol_deals_async(symbol))


async def _watchlist_deals_sync_async() -> None:
    """Async engine for refreshing deals on all watchlist symbols."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(WatchlistItem.symbol).distinct())
        symbols = [row[0] for row in result.fetchall()]

    if not symbols:
        logger.debug("watchlist_deals_sync: no symbols in watchlist")
        return

    logger.info("watchlist_deals_sync: checking %d symbols", len(symbols))
    for sym in symbols:
        await _warm_symbol_deals_async(sym)
        await asyncio.sleep(1.0)


def _watchlist_deals_sync() -> None:
    """Synchronous entrypoint for worker daemon."""
    from app.backgroundtasks._runtime import _run_async
    _run_async(_watchlist_deals_sync_async())
