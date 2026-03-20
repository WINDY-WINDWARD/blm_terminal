"""This router serves non-cached data directly from NSE India.

Performance optimizations (v1.3):
- Global semaphore (2 concurrent NSE requests) replaces single Lock
- Per-endpoint courtesy delay (no more global 2s gap between ANY calls)
- Request coalescing: simultaneous requests share one upstream call
- Circuit breaker with OPEN → HALF_OPEN → CLOSED recovery
- Shared snapshot cache: bulk/block/short deals from ONE NSE call
- Shared market-turnover cache: top-gainers and top-losers share ONE call
- cachetools.TTLCache replaces dict-based TTL (auto-eviction, thread-safe)
"""

import logging
import os
from functools import partial

import numpy as np
import pandas as pd
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.services.cache import nse_cache
from app.services.nse_rate_limiter import throttled_nse_call

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/market", tags=["market"])

USE_ASYNC_NSE = os.getenv("USE_ASYNC_NSE", "false").lower() == "true"
if USE_ASYNC_NSE:
    from app.services.nse_client_async import nse_client_async as _active_client
else:
    from app.services.nse_client import nse_client as _active_client

_CHANGE_RANGES_TTL = 300.0
_SYMBOL_DATA_TTL = 60.0
_FIFTY_TWO_WEEK_TTL = 3 * 60 * 60.0
_VOLUME_GAINERS_TTL = 25 * 60.0


def _df_to_json_dict(df: pd.DataFrame) -> list[dict]:
    return df.replace({np.nan: None, pd.NA: None}).to_dict(orient="records")


def _clean_nan(obj):
    if isinstance(obj, dict):
        return {k: _clean_nan(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_clean_nan(item) for item in obj]
    elif isinstance(obj, float) and (np.isnan(obj) or np.isinf(obj)):
        return None
    return obj


def _cache_response(data: object, cache_key: str, ttl: float) -> JSONResponse:
    nse_cache[cache_key] = data
    response = JSONResponse(content=_clean_nan(data))
    response.headers["Cache-Control"] = f"public, max-age={int(ttl)}"
    return response


def _json_response(data: object, ttl: float) -> JSONResponse:
    response = JSONResponse(content=_clean_nan(data))
    response.headers["Cache-Control"] = f"public, max-age={int(ttl)}"
    return response


async def _get_largedeal_snapshot_shared() -> dict:
    """Fetch largedeal snapshot once; derive bulk/block/short from it.

    Cached for 10 minutes so concurrent requests for bulk-deals:X,
    block-deals:X, and high-short-interest all share the same upstream fetch.
    Works in Phase 1 (sync nsepython via to_thread) and Phase 2 (async httpx).
    """
    cached = nse_cache.get("largedeal-snapshot")
    if cached is not None:
        logger.debug("Shared snapshot cache hit")
        return cached

    data = await throttled_nse_call(
        "largedeal-snapshot",
        _active_client.get_largedeal_snapshot,
        is_async_fn=USE_ASYNC_NSE,
    )
    nse_cache["largedeal-snapshot"] = data
    return data


async def _get_market_turnover_shared() -> list[dict]:
    """Fetch market turnover payload once; cache for subsequent calls.

    Both top-gainers and top-losers hit the same NSE URL. Cache the payload
    so simultaneous requests share one upstream call.
    """
    cached = nse_cache.get("market-turnover")
    if cached is not None:
        logger.debug("Market turnover cache hit")
        return cached

    rows = await throttled_nse_call(
        "market-turnover",
        _active_client._get_market_turnover,
        is_async_fn=USE_ASYNC_NSE,
    )
    nse_cache["market-turnover"] = rows
    return rows


@router.get("/top-gainers", summary="Top gainers on NSE", response_class=JSONResponse)
async def top_gainers() -> JSONResponse:
    cached = nse_cache.get("top-gainers")
    if cached is not None:
        return _json_response(cached, 60.0)

    rows = await _get_market_turnover_shared()
    df = pd.DataFrame(rows)
    df_eq = df[df["series"] == "EQ"].copy()
    df_eq["pChange"] = pd.to_numeric(df_eq["pChange"], errors="coerce")
    df_eq = df_eq.dropna(subset=["pChange"])
    df_eq = df_eq.sort_values("pChange", ascending=False).head(20)
    data = _df_to_json_dict(df_eq)
    return _cache_response(data, "top-gainers", 60.0)


@router.get("/top-losers", summary="Top losers on NSE", response_class=JSONResponse)
async def top_losers() -> JSONResponse:
    cached = nse_cache.get("top-losers")
    if cached is not None:
        return _json_response(cached, 60.0)

    rows = await _get_market_turnover_shared()
    df = pd.DataFrame(rows)
    df_eq = df[df["series"] == "EQ"].copy()
    df_eq["pChange"] = pd.to_numeric(df_eq["pChange"], errors="coerce")
    df_eq = df_eq.dropna(subset=["pChange"])
    df_eq = df_eq.sort_values("pChange", ascending=True).head(20)
    data = _df_to_json_dict(df_eq)
    return _cache_response(data, "top-losers", 60.0)


@router.get("/bulk-deals/{symbol}", summary="Bulk deals for a specific stock symbol on NSE", response_class=JSONResponse)
async def bulk_deals(symbol: str) -> JSONResponse:
    cache_key = f"bulk-deals:{symbol.upper()}"
    cached = nse_cache.get(cache_key)
    if cached is not None:
        return _json_response(cached, 600.0)

    snapshot = await _get_largedeal_snapshot_shared()
    rows = [
        r for r in snapshot.get("BULK_DEALS_DATA", [])
        if r.get("symbol", "").upper() == symbol.upper()
    ]
    return _cache_response(rows, cache_key, 600.0)


@router.get("/block-deals/{symbol}", summary="Block deals for a specific stock symbol on NSE", response_class=JSONResponse)
async def block_deals(symbol: str) -> JSONResponse:
    cache_key = f"block-deals:{symbol.upper()}"
    cached = nse_cache.get(cache_key)
    if cached is not None:
        return _json_response(cached, 600.0)

    snapshot = await _get_largedeal_snapshot_shared()
    rows = [
        r for r in snapshot.get("BLOCK_DEALS_DATA", [])
        if r.get("symbol", "").upper() == symbol.upper()
    ]
    return _cache_response(rows, cache_key, 600.0)


@router.get("/high-short-interest", summary="Stocks with high short interest on NSE", response_class=JSONResponse)
async def high_short_interest() -> JSONResponse:
    cached = nse_cache.get("high-short-interest")
    if cached is not None:
        return _json_response(cached, 600.0)

    snapshot = await _get_largedeal_snapshot_shared()
    data = snapshot.get("SHORT_DEALS_DATA", [])
    return _cache_response(data, "high-short-interest", 600.0)


@router.get("/largedeal-snapshot", summary="Full largedeal snapshot (bulk/short/block) from NSE", response_class=JSONResponse)
async def largedeal_snapshot() -> JSONResponse:
    cached = nse_cache.get("largedeal-snapshot")
    if cached is not None:
        return _json_response(cached, 600.0)

    data = await throttled_nse_call(
        "largedeal-snapshot",
        _active_client.get_largedeal_snapshot,
        is_async_fn=USE_ASYNC_NSE,
    )
    return _cache_response(_clean_nan(data), "largedeal-snapshot", 600.0)


@router.get("/change-ranges/{symbol}", summary="Percentage changes over multiple timeframes for a symbol", response_class=JSONResponse)
async def change_ranges(symbol: str) -> JSONResponse:
    cache_key = f"change-ranges:{symbol.upper()}"
    cached = nse_cache.get(cache_key)
    if cached is not None:
        return _json_response(cached, _CHANGE_RANGES_TTL)

    data = await throttled_nse_call(
        f"change-ranges:{symbol.upper()}",
        partial(_active_client.get_change_ranges, symbol.upper()),
        is_async_fn=USE_ASYNC_NSE,
    )
    return _cache_response(_clean_nan(data), cache_key, _CHANGE_RANGES_TTL)


@router.get("/symbol-data/{symbol}", summary="Live symbol data from NSE (getSymbolData)", response_class=JSONResponse)
async def symbol_data(symbol: str) -> JSONResponse:
    cache_key = f"symbol-data:{symbol.upper()}"
    cached = nse_cache.get(cache_key)
    if cached is not None:
        return _json_response(cached, _SYMBOL_DATA_TTL)

    data = await throttled_nse_call(
        f"symbol-data:{symbol.upper()}",
        partial(_active_client.get_symbol_data, symbol.upper()),
        is_async_fn=USE_ASYNC_NSE,
    )
    return _cache_response(_clean_nan(data), cache_key, _SYMBOL_DATA_TTL)


@router.get("/52week-low", summary="52-week low stocks snapshot from NSE", response_class=JSONResponse)
async def fifty_two_week_low() -> JSONResponse:
    cached = nse_cache.get("52week-low")
    if cached is not None:
        return _json_response(cached, _FIFTY_TWO_WEEK_TTL)

    data = await throttled_nse_call(
        "52week-low",
        _active_client.get_52week_low_stocks,
        is_async_fn=USE_ASYNC_NSE,
    )
    return _cache_response(_clean_nan(data), "52week-low", _FIFTY_TWO_WEEK_TTL)


@router.get("/52week-high", summary="52-week high stocks snapshot from NSE", response_class=JSONResponse)
async def fifty_two_week_high() -> JSONResponse:
    cached = nse_cache.get("52week-high")
    if cached is not None:
        return _json_response(cached, _FIFTY_TWO_WEEK_TTL)

    data = await throttled_nse_call(
        "52week-high",
        _active_client.get_52week_high_stocks,
        is_async_fn=USE_ASYNC_NSE,
    )
    return _cache_response(_clean_nan(data), "52week-high", _FIFTY_TWO_WEEK_TTL)


@router.get("/volume-gainers", summary="Volume gainers snapshot from NSE", response_class=JSONResponse)
async def volume_gainers() -> JSONResponse:
    cached = nse_cache.get("volume-gainers")
    if cached is not None:
        return _json_response(cached, _VOLUME_GAINERS_TTL)

    data = await throttled_nse_call(
        "volume-gainers",
        _active_client.get_volume_gainers,
        is_async_fn=USE_ASYNC_NSE,
    )
    return _cache_response(_clean_nan(data), "volume-gainers", _VOLUME_GAINERS_TTL)
