"""Shared helpers for NSE change-ranges and symbol-data.

Used by:
  - app.routers.market_ws      (WebSocket actions)
  - app.routers.markets        (REST fallback for the Next.js proxy)
"""

from __future__ import annotations

import asyncio
import logging
import os
from functools import partial

import numpy as np

from app.services.cache import nse_cache
from app.services.nse_rate_limiter import throttled_nse_call

logger = logging.getLogger(__name__)

USE_ASYNC_NSE = os.getenv("USE_ASYNC_NSE", "false").lower() == "true"
if USE_ASYNC_NSE:
    from app.services.nse_client_async import nse_client_async as _active_client
else:
    from app.services.nse_client import nse_client as _active_client

_MAX_SYMBOLS_PER_REQUEST = 50
_MAX_CONCURRENT_NSE_FETCHES = 10
_nse_fetch_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_NSE_FETCHES)


def clean_nan(obj):
    """Recursively replace NaN/Inf floats with None for JSON safety."""
    if isinstance(obj, dict):
        return {k: clean_nan(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [clean_nan(item) for item in obj]
    elif isinstance(obj, float) and (np.isnan(obj) or np.isinf(obj)):
        return None
    return obj


async def _fetch_change_ranges_for_symbol(symbol: str) -> tuple[str, object]:
    """Fetch change-ranges for a single symbol, using cache when available."""
    sym = symbol.upper()
    cache_key = f"change-ranges:{sym}"
    cached = nse_cache.get(cache_key)
    if cached is not None:
        return sym, cached

    try:
        data = await throttled_nse_call(
            cache_key,
            partial(_active_client.get_change_ranges, sym),
            is_async_fn=USE_ASYNC_NSE,
        )
        cleaned = clean_nan(data)
        nse_cache[cache_key] = cleaned
        return sym, cleaned
    except Exception as e:
        logger.warning(
            "Market data: change-ranges fetch failed for %s: %s (%s)",
            sym, e or "(empty)", type(e).__name__,
        )
        return sym, None


async def _fetch_symbol_data_for_symbol(symbol: str) -> tuple[str, object]:
    """Fetch symbol-data for a single symbol, using cache when available."""
    sym = symbol.upper()
    cache_key = f"symbol-data:{sym}"
    cached = nse_cache.get(cache_key)
    if cached is not None:
        return sym, cached

    try:
        data = await throttled_nse_call(
            cache_key,
            partial(_active_client.get_symbol_data, sym),
            is_async_fn=USE_ASYNC_NSE,
        )
        cleaned = clean_nan(data)
        nse_cache[cache_key] = cleaned
        return sym, cleaned
    except Exception as e:
        logger.warning(
            "Market data: symbol-data fetch failed for %s: %s (%s)",
            sym, e or "(empty)", type(e).__name__,
        )
        return sym, None


async def bounded_change_ranges(symbol: str) -> tuple[str, object]:
    async with _nse_fetch_semaphore:
        return await _fetch_change_ranges_for_symbol(symbol)


async def bounded_symbol_data(symbol: str) -> tuple[str, object]:
    async with _nse_fetch_semaphore:
        return await _fetch_symbol_data_for_symbol(symbol)


async def fetch_change_ranges_batch(symbols: list[str]) -> dict[str, object]:
    """Fetch change-ranges for a list of symbols concurrently. Returns {sym: value | null}."""
    symbols = [s for s in (symbols or []) if s][:_MAX_SYMBOLS_PER_REQUEST]
    if not symbols:
        return {}
    results = await asyncio.gather(
        *[bounded_change_ranges(s) for s in symbols],
        return_exceptions=False,
    )
    return {sym: val for sym, val in results}


async def fetch_symbol_data_batch(symbols: list[str]) -> dict[str, object]:
    """Fetch symbol-data for a list of symbols concurrently. Returns {sym: value | null}."""
    symbols = [s for s in (symbols or []) if s][:_MAX_SYMBOLS_PER_REQUEST]
    if not symbols:
        return {}
    results = await asyncio.gather(
        *[bounded_symbol_data(s) for s in symbols],
        return_exceptions=False,
    )
    return {sym: val for sym, val in results}
