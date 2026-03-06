"""This router serves non-cached data directly from NSE India.

It is intended for one-time-use market snapshots (top gainers, top losers,
most active, etc.) that we do not want to persist in our database.

some endpoints can have a cache layer with a short TTL of 10 minutes

Because NSE India rate-limits these endpoints aggressively, every outgoing
request is guarded by a courtesy delay: if the previous request finished less
than COURTESY_DELAY_SECONDS ago, the handler sleeps for the remaining time
before hitting NSE again.  An asyncio.Lock ensures only one NSE call runs at
a time so concurrent requests queue up rather than flooding the upstream API.
"""

import asyncio
import logging
import time

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.services.nse_client import nse_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/market", tags=["market"])

# Minimum gap (in seconds) between two consecutive NSE requests.
COURTESY_DELAY_SECONDS: float = 2.0

_nse_lock = asyncio.Lock()
_last_request_at: float = 0.0  # monotonic timestamp of the last NSE call

# ---------------------------------------------------------------------------
# Simple in-memory TTL cache  {key: (stored_at, data)}
# ---------------------------------------------------------------------------

CACHE_TTL_SECONDS: float = 600.0  # 10 minutes — override per-call if needed

_cache: dict[str, tuple[float, object]] = {}


def _cache_get(key: str, ttl: float = CACHE_TTL_SECONDS) -> object | None:
    """Return cached data for *key* if it exists and has not expired."""
    entry = _cache.get(key)
    if entry and (time.monotonic() - entry[0]) < ttl:
        return entry[1]
    return None


def _cache_set(key: str, data: object) -> None:
    """Store *data* under *key* with the current timestamp."""
    _cache[key] = (time.monotonic(), data)


def _cache_evict_expired() -> None:
    """Remove all entries whose TTL has elapsed."""
    now = time.monotonic()
    expired = [k for k, (t, _) in _cache.items() if now - t >= CACHE_TTL_SECONDS]
    for k in expired:
        del _cache[k]
    if expired:
        logger.debug("Cache evicted %d expired entries", len(expired))


async def start_cache_cleanup(interval: float = CACHE_TTL_SECONDS) -> asyncio.Task:
    """Start a background task that evicts expired cache entries every *interval* seconds.

    Returns the Task so the caller can cancel it on shutdown.
    """

    async def _loop() -> None:
        while True:
            await asyncio.sleep(interval)
            _cache_evict_expired()

    task = asyncio.create_task(_loop(), name="cache-cleanup")
    logger.info("Cache cleanup task started (interval=%.0fs)", interval)
    return task


async def _throttled_call(fn, *args):
    """Run a synchronous *fn* in a thread-pool, honouring the courtesy delay.

    Acquires the lock so concurrent calls are serialised, waits out any
    remaining courtesy window, then delegates to asyncio.to_thread.
    """
    global _last_request_at

    async with _nse_lock:
        elapsed = time.monotonic() - _last_request_at
        wait = COURTESY_DELAY_SECONDS - elapsed
        if wait > 0:
            logger.debug("Courtesy delay: sleeping %.2fs before NSE request", wait)
            await asyncio.sleep(wait)

        try:
            result = await asyncio.to_thread(fn, *args)
        finally:
            _last_request_at = time.monotonic()

    return result


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/top-gainers",
    summary="Top gainers on NSE",
    response_class=JSONResponse,
)
async def top_gainers() -> JSONResponse:
    """Return today's top-gaining equities on NSE India.

    Data is fetched live on every call — no caching.
    """
    df = await _throttled_call(nse_client.get_top_gainers)
    return JSONResponse(content=df.to_dict(orient="records"))


@router.get(
    "/top-losers",
    summary="Top losers on NSE",
    response_class=JSONResponse,
)
async def top_losers() -> JSONResponse:
    """Return today's top-losing equities on NSE India.

    Data is fetched live on every call — no caching.
    """
    df = await _throttled_call(nse_client.get_top_losers)
    return JSONResponse(content=df.to_dict(orient="records"))


@router.get(
    "/bulk-deals/{symbol}",
    summary="Bulk deals for a specific stock symbol on NSE",
    response_class=JSONResponse,
)
async def bulk_deals(symbol: str) -> JSONResponse:
    """Return today's bulk deals for a specific stock symbol on NSE India.

    Data is fetched live on every call — with a 10min in-memory cache.
    """
    cache_key = f"bulk_deals:{symbol.upper()}"
    cached = _cache_get(cache_key)
    if cached is not None:
        logger.debug("Cache hit for %s", cache_key)
        return JSONResponse(content=cached)

    df = await _throttled_call(nse_client.check_bulk_deals, symbol)
    data = df.to_dict(orient="records")
    _cache_set(cache_key, data)
    return JSONResponse(content=data)


# block deals
@router.get(
    "/block-deals/{symbol}",
    summary="Block deals for a specific stock symbol on NSE",
    response_class=JSONResponse,
)
async def block_deals(symbol: str) -> JSONResponse:
    """Return today's block deals for a specific stock symbol on NSE India.

    Data is fetched live on every call — with a 10min in-memory cache.
    """
    cache_key = f"block_deals:{symbol.upper()}"
    cached = _cache_get(cache_key)
    if cached is not None:
        logger.debug("Cache hit for %s", cache_key)
        return JSONResponse(content=cached)

    df = await _throttled_call(nse_client.check_block_deals, symbol)
    data = df.to_dict(orient="records")
    _cache_set(cache_key, data)
    return JSONResponse(content=data)


# check high short volume stocks
@router.get(
    "/high-short-interest",
    summary="Stocks with high short interest on NSE",
    response_class=JSONResponse,
)
async def high_short_interest() -> JSONResponse:
    """Return today's stocks with high short interest on NSE India.

    Data is fetched live on every call — with a 10min in-memory cache.
    """
    cache_key = "high_short_interest"
    cached = _cache_get(cache_key)
    if cached is not None:
        logger.debug("Cache hit for %s", cache_key)
        return JSONResponse(content=cached)

    df = await _throttled_call(nse_client.get_high_short_interest)
    data = df.to_dict(orient="records")
    _cache_set(cache_key, data)
    return JSONResponse(content=data)


_CHANGE_RANGES_TTL: float = 300.0  # 5 minutes


@router.get(
    "/change-ranges/{symbol}",
    summary="Percentage changes over multiple timeframes for a symbol",
    response_class=JSONResponse,
)
async def change_ranges(symbol: str) -> JSONResponse:
    """Return pre-computed percentage changes for *symbol* from NSE's getYearwiseData.

    Keys: oneDayPercent, oneWeekPercent, oneMonthPercent, threeMonthPercent,
    sixMonthPercent, oneYearPercent, twoYearPercent, threeYearPercent, fiveYearPercent.

    Results are cached for 5 minutes.
    """
    cache_key = f"change_ranges:{symbol.upper()}"
    cached = _cache_get(cache_key, ttl=_CHANGE_RANGES_TTL)
    if cached is not None:
        logger.debug("Cache hit for %s", cache_key)
        return JSONResponse(content=cached)

    data = await _throttled_call(nse_client.get_change_ranges, symbol)
    _cache_set(cache_key, data)
    return JSONResponse(content=data)
