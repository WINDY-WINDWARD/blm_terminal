"""
Screener.in proxy endpoints.
Prefix: /api  →  effective routes: /api/screener/search, /api/screener/company/{symbol}
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Query

from app.services.screener_client import screener_client

logger = logging.getLogger(__name__)
router = APIRouter(tags=["screener"])

_CACHE: dict[str, tuple[float, object]] = {}
SEARCH_TTL = 60
COMPANY_TTL = 15 * 60

_SYMBOL_RE = re.compile(r"^[A-Z0-9._-]{1,30}$")


def _cache_get(key: str) -> object | None:
    entry = _CACHE.get(key)
    if entry and time.monotonic() < entry[0]:
        return entry[1]
    return None


def _cache_set(key: str, value: object, ttl: float) -> None:
    _CACHE[key] = (time.monotonic() + ttl, value)


@router.get("/screener/search")
async def screener_search(
    q: str = Query(
        ..., min_length=1, max_length=80, description="Company name or symbol fragment"
    ),
) -> list[dict[str, Any]]:
    """
    Search screener.in for matching companies.
    Public endpoint — no login required.
    """
    cache_key = f"screener:search:{q.lower()}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    try:
        results = await screener_client.search(q)
    except httpx.HTTPStatusError as exc:
        logger.error("screener.in search failed: %s", exc)
        raise HTTPException(status_code=502, detail="screener.in request failed")
    except Exception as exc:
        logger.error("screener.in search error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    _cache_set(cache_key, results, SEARCH_TTL)
    return results


@router.get("/screener/company/{symbol}")
async def screener_company(
    symbol: str,
    consolidated: bool = True,
) -> dict[str, Any]:
    """
    Fetch parsed fundamentals for a company from screener.in.
    Requires a valid Chrome sessionid cookie for screener.in.

    Returns: symbol, name, ratios (P/E, ROCE, ROE, etc.), quarters (last 4).
    """
    symbol = symbol.upper().strip()
    if not _SYMBOL_RE.fullmatch(symbol):
        raise HTTPException(status_code=422, detail="Invalid symbol format")

    if not screener_client.is_authenticated:
        raise HTTPException(
            status_code=503,
            detail=(
                "screener.in session not available. "
                "Log in at https://www.screener.in in Chrome, then restart the backend."
            ),
        )

    cache_key = f"screener:company:{symbol}:{'c' if consolidated else 's'}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    try:
        data = await screener_client.get_company(symbol, consolidated=consolidated)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except httpx.HTTPStatusError as exc:
        logger.error("screener.in company fetch failed: %s", exc)
        raise HTTPException(status_code=502, detail="screener.in request failed")
    except Exception as exc:
        logger.error("screener.in company error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    _cache_set(cache_key, data, COMPANY_TTL)
    return data
