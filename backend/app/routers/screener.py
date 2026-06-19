"""
Screener.in proxy endpoints.
Prefix: /api  →  effective routes: /api/screener/search, /api/screener/company/{symbol}
"""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from bs4 import BeautifulSoup

from app.database import get_db
from app.models.stockuniverse import StockUniverse as StockUniverseModel
from app.services.cache import nse_cache
from app.services.screener_client import _parse_all_quarters, screener_client

logger = logging.getLogger(__name__)
router = APIRouter(tags=["screener"])

_SYMBOL_RE = re.compile(r"^[A-Z0-9._-]{1,30}$")


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
    cached = nse_cache.get(cache_key)
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

    nse_cache[cache_key] = results
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

    cache_key = f"screener:company:{symbol}:{'c' if consolidated else 's'}"
    cached = nse_cache.get(cache_key)
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

    nse_cache[cache_key] = data
    return data


@router.get("/screener/trades/{symbol}")
async def screener_trades(
    symbol: str,
    consolidated: bool = True,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Fetch insider trades, bulk deals, and block deals for a company from screener.in.

    Accepts the NSE/BSE `symbol` (e.g. RELIANCE). Looks up the screener trades ID
    from the stock universe DB first (fast path). If not yet cached there, resolves
    it from the company page and persists it so subsequent calls skip the extra request.

    Returns:
      - warehouse_id   : resolved screener trades company ID
      - insider_trades : list of insider trade records
      - bulk_deals     : list of bulk deal records
      - block_deals    : list of block deal records

    Each record contains: person, category, period, quantity_raw, quantity, direction,
    avg_price_raw, avg_price, value_raw, value, value_in, small_quantity.

    Requires a valid screener.in session (same as /api/screener/company/{symbol}).
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

    cache_key = f"screener:trades:{symbol}:{'c' if consolidated else 's'}"
    cached = nse_cache.get(cache_key)
    if cached is not None:
        return cached  # type: ignore[return-value]

    try:
        # Fast path: check if the trades ID is already persisted in the DB
        db_row: StockUniverseModel | None = await db.get(StockUniverseModel, symbol)
        cached_trades_id: str | None = db_row.screener_trades_id if db_row else None

        if cached_trades_id:
            # Skip the company-page request entirely
            data = await screener_client.get_trades(cached_trades_id)
        else:
            # Slow path: fetch company page to resolve trades ID, then fetch trades
            data, resolved_id = await screener_client.get_trades_by_symbol(
                symbol, consolidated=consolidated
            )
            # Persist the resolved ID so future calls use the fast path
            if db_row is not None:
                db_row.screener_trades_id = resolved_id
                await db.commit()
            else:
                logger.debug(
                    "Symbol %s not found in stock_universe; trades ID %s not persisted",
                    symbol,
                    resolved_id,
                )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except httpx.HTTPStatusError as exc:
        logger.error("screener.in trades fetch failed: %s", exc)
        raise HTTPException(status_code=502, detail="screener.in request failed")
    except Exception as exc:
        logger.error("screener.in trades error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    nse_cache[cache_key] = data
    return data  # type: ignore[return-value]


@router.get("/screener/quarterly/{symbol}")
async def screener_quarterly(
    symbol: str,
) -> dict[str, Any]:
    """
    Return full quarterly results for a company from screener.in (consolidated), structured as:

        {
            "symbol": "HDFCBANK",
            "consolidated": true,
            "quarterly_results": {
                "2024": {
                    "Sep": { "Sales": "...", "Net Profit": "...", ... },
                    "Dec": { ... }
                },
                "2025": {
                    "Mar TTM": { ... }
                }
            }
        }

    All rows from the #quarters table are included (Sales, Expenses, OPM%,
    Other Income, Interest, Depreciation, Profit before tax, Tax %, Net Profit,
    EPS in Rs, etc.) and all available periods — not just the last 4.

    Results are served from the shared ``nse_cache`` (TTL configured on
    ``app.services.cache`` — 600s).  If a cached entry exists for the same
    ``(symbol, consolidated)`` key, no parsing is performed and the cached
    structured payload is returned.

    Requires a valid screener.in Chrome session (same as /api/screener/company).
    """
    consolidated = True
    symbol = symbol.upper().strip()
    if not _SYMBOL_RE.fullmatch(symbol):
        raise HTTPException(status_code=422, detail="Invalid symbol format")

    cache_key = f"screener:quarterly:{symbol}:{'c' if consolidated else 's'}"
    cached = nse_cache.get(cache_key)
    if cached is not None:
        return cached  # type: ignore[return-value]

    try:
        html = await screener_client.get_company_html(symbol, consolidated=consolidated)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        logger.error("screener.in quarterly fetch failed for %s: %s", symbol, exc)
        raise HTTPException(status_code=502, detail="screener.in request failed")

    soup = BeautifulSoup(html, "lxml")
    quarterly_results = _parse_all_quarters(soup)

    result: dict[str, Any] = {
        "symbol": symbol,
        "consolidated": consolidated,
        "quarterly_results": quarterly_results,
    }

    nse_cache[cache_key] = result
    return result
