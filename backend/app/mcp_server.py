"""MCP Server for BLM Analytics Backend.

This module exposes the backend's read-only GET API surface via the Model Context Protocol.
All tools call service and DB logic directly rather than making HTTP calls back into FastAPI.
"""

import asyncio
import logging
import re
import time
from typing import Any

import numpy as np
import pandas as pd
from mcp.server import FastMCP
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.corporatefilings import CorporateFiling
from app.models.news import NewsArticle
from app.models.stockuniverse import StockUniverse as StockUniverseModel
from app.models.watchlist import WatchlistItem as WatchlistItemModel
from app.services.nse_client import nse_client
from app.services.screener_client import _parse_all_quarters, screener_client
from app.services.news_fetcher import SOURCE_NAME, news_fetcher

logger = logging.getLogger(__name__)

mcp = FastMCP("BLM Analytics", stateless_http=True, json_response=True)

# Symbol validation regex (same as in screener router)
_SYMBOL_RE = re.compile(r"^[A-Z0-9._-]{1,30}$")

# In-memory cache for MCP tools (mirrors router caching behavior)
_CACHE: dict[str, tuple[float, object]] = {}
CACHE_TTL_SECONDS = 600.0  # 10 minutes


def _cache_get(key: str) -> object | None:
    entry = _CACHE.get(key)
    if entry and (time.monotonic() - entry[0]) < CACHE_TTL_SECONDS:
        return entry[1]
    return None


def _cache_set(key: str, value: object) -> None:
    _CACHE[key] = (time.monotonic(), value)


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


# Minimum gap (in seconds) between two consecutive NSE requests.
_NSE_COURTESY_DELAY_SECONDS: float = 2.0
_nse_lock = asyncio.Lock()
_last_request_at: float = 0.0


async def _throttled_call(fn, *args):
    global _last_request_at
    async with _nse_lock:
        elapsed = time.monotonic() - _last_request_at
        wait = _NSE_COURTESY_DELAY_SECONDS - elapsed
        if wait > 0:
            logger.debug("MCP: Courtesy delay: sleeping %.2fs before NSE request", wait)
            await asyncio.sleep(wait)
        try:
            result = await asyncio.to_thread(fn, *args)
        finally:
            _last_request_at = time.monotonic()
    return result


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@mcp.tool()
async def health_check() -> dict[str, str]:
    """Return service health status."""
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Market Endpoints
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_top_gainers() -> list[dict[str, Any]]:
    """Return today's top-gaining equities on NSE India."""
    df = await _throttled_call(nse_client.get_top_gainers)
    return _df_to_json_dict(df)


@mcp.tool()
async def get_top_losers() -> list[dict[str, Any]]:
    """Return today's top-losing equities on NSE India."""
    df = await _throttled_call(nse_client.get_top_losers)
    return _df_to_json_dict(df)


@mcp.tool()
async def get_bulk_deals(symbol: str) -> list[dict[str, Any]]:
    """Return Recent bulk deals for a specific stock symbol on NSE India."""
    symbol = symbol.upper()
    cache_key = f"mcp_bulk_deals:{symbol}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    df = await _throttled_call(nse_client.check_bulk_deals, symbol)
    data = _df_to_json_dict(df)
    _cache_set(cache_key, data)
    return data


@mcp.tool()
async def get_block_deals(symbol: str) -> list[dict[str, Any]]:
    """Return Recent block deals for a specific stock symbol on NSE India."""
    symbol = symbol.upper()
    cache_key = f"mcp_block_deals:{symbol}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    df = await _throttled_call(nse_client.check_block_deals, symbol)
    data = _df_to_json_dict(df)
    _cache_set(cache_key, data)
    return data


@mcp.tool()
async def get_high_short_interest() -> list[dict[str, Any]]:
    """Return today's stocks with high short interest on NSE India."""
    cache_key = "mcp_high_short_interest"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    df = await _throttled_call(nse_client.get_high_short_interest)
    data = _df_to_json_dict(df)
    _cache_set(cache_key, data)
    return data


@mcp.tool()
async def get_largedeal_snapshot() -> dict[str, Any]:
    """Returns a snapshot of recent large deals (Insiders + bulk + block) across NSE, with details like symbol, price, quantity, deal type, and timestamp."""
    cache_key = "mcp_largedeal_snapshot"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    data = await _throttled_call(nse_client.get_largedeal_snapshot)
    data = _clean_nan(data)
    _cache_set(cache_key, data)
    return data


@mcp.tool()
async def get_change_ranges(symbol: str) -> dict[str, float | None]:
    """Return percentage changes over multiple timeframes for a symbol from NSE.

    Keys: oneDayPercent, oneWeekPercent, oneMonthPercent, threeMonthPercent,
    sixMonthPercent, oneYearPercent, twoYearPercent, threeYearPercent, fiveYearPercent.
    """
    symbol = symbol.upper()
    cache_key = f"mcp_change_ranges:{symbol}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    data = await _throttled_call(nse_client.get_change_ranges, symbol)
    data = _clean_nan(data)
    _cache_set(cache_key, data)
    return data


@mcp.tool()
async def get_symbol_data(symbol: str) -> dict[str, Any]:
    """Return live symbol data from NSE's GetQuoteApi getSymbolData endpoint. used to fetch latest data
    like ltp, dayHigh, dayLow, 52weekHigh, 52weekLow, etc. also sector and industry info for the symbol.
    with metadata on the company
    """
    symbol = symbol.upper()
    cache_key = f"mcp_symbol_data:{symbol}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    data = await _throttled_call(nse_client.get_symbol_data, symbol)
    data = _clean_nan(data)
    _cache_set(cache_key, data)
    return data


@mcp.tool()
async def get_52week_low_stocks() -> dict[str, Any]:
    """Return Global List of stocks which have crossed their previous NSE 52-week low and set new 52-week lows."""
    cache_key = "mcp_52week_low"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    data = await _throttled_call(nse_client.get_52week_low_stocks)
    data = _clean_nan(data)
    _cache_set(cache_key, data)
    return data


@mcp.tool()
async def get_52week_high_stocks() -> dict[str, Any]:
    """Return Global List of stocks which have crossed their previous NSE 52-week high and set new 52-week highs."""
    cache_key = "mcp_52week_high"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    data = await _throttled_call(nse_client.get_52week_high_stocks)
    data = _clean_nan(data)
    _cache_set(cache_key, data)
    return data


@mcp.tool()
async def get_volume_gainers() -> dict[str, Any]:
    """Returns Global List of stocks with highest volume gain compared to average weekly volume, along with percentage gain."""
    cache_key = "mcp_volume_gainers"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    data = await _throttled_call(nse_client.get_volume_gainers)
    data = _clean_nan(data)
    _cache_set(cache_key, data)
    return data


# ---------------------------------------------------------------------------
# Corporate Filings
# ---------------------------------------------------------------------------


# @mcp.tool()
# async def get_corporate_filings(symbol: str) -> dict[str, Any]:
#     """Return quarterly financial results for a symbol as CSV.

#     Returns structured data containing: symbol, media_type, and csv_text.
#     """
#     symbol = symbol.upper().strip()
#     if not _SYMBOL_RE.fullmatch(symbol):
#         raise ValueError(f"Invalid symbol format: {symbol}")

#     async with AsyncSessionLocal() as db:
#         record = await db.get(CorporateFiling, symbol)

#         from datetime import datetime, timedelta, timezone

#         stale_after = timedelta(days=30)
#         now = datetime.now(tz=timezone.utc).replace(tzinfo=None)
#         needs_refresh = record is None or (now - record.last_fetched_at) > stale_after

#         if needs_refresh:
#             try:
#                 csv_text: str = await asyncio.to_thread(
#                     nse_client.get_corporate_filing_comparison, symbol
#                 )
#             except Exception as exc:
#                 logger.exception("NSE fetch failed for %s", symbol)
#                 raise RuntimeError(
#                     f"Failed to fetch corporate filings for {symbol} from NSE: {exc}"
#                 ) from exc

#             now = datetime.now(tz=timezone.utc).replace(tzinfo=None)
#             if record is None:
#                 record = CorporateFiling(
#                     symbol=symbol,
#                     csv_data=csv_text,
#                     last_fetched_at=now,
#                 )
#                 db.add(record)
#             else:
#                 record.csv_data = csv_text
#                 record.last_fetched_at = now

#             await db.commit()
#             logger.info("Corporate filings refreshed for %s", symbol)
#         else:
#             csv_text = record.csv_data

#     return {
#         "symbol": symbol,
#         "media_type": "text/csv",
#         "csv_text": csv_text,
#     }


# ---------------------------------------------------------------------------
# Screener Endpoints
# ---------------------------------------------------------------------------


@mcp.tool()
async def screener_search(q: str) -> list[dict[str, Any]]:
    """Search screener.in for matching companies by name or symbol."""
    if not q or len(q) > 80:
        raise ValueError("Query must be between 1 and 80 characters")

    cache_key = f"mcp_screener:search:{q.lower()}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    results = await screener_client.search(q)
    _cache_set(cache_key, results)
    return results


@mcp.tool()
async def screener_company(symbol: str, consolidated: bool = True) -> dict[str, Any]:
    """Fetch parsed fundamentals for a company from screener.in.

    Returns: symbol, name, ratios (P/E, ROCE, ROE, etc.), quarters (last 4).
    Requires screener.in authentication (browser session).
    """
    symbol = symbol.upper().strip()
    if not _SYMBOL_RE.fullmatch(symbol):
        raise ValueError(f"Invalid symbol format: {symbol}")

    if not screener_client.is_authenticated:
        raise RuntimeError(
            "screener.in session not available. "
            "Log in at https://www.screener.in in Chrome, then restart the backend."
        )

    cache_key = f"mcp_screener:company:{symbol}:{'c' if consolidated else 's'}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    data = await screener_client.get_company(symbol, consolidated=consolidated)
    _cache_set(cache_key, data)
    return data


@mcp.tool()
async def screener_trades(symbol: str, consolidated: bool = True) -> dict[str, Any]:
    """Fetch insider trades, bulk deals, and block deals for a company from screener.in.

    Returns:
      - warehouse_id   : resolved screener trades company ID
      - insider_trades : list of insider trade records
      - bulk_deals     : list of bulk deal records
      - block_deals    : list of block deal records
    """
    symbol = symbol.upper().strip()
    if not _SYMBOL_RE.fullmatch(symbol):
        raise ValueError(f"Invalid symbol format: {symbol}")

    if not screener_client.is_authenticated:
        raise RuntimeError(
            "screener.in session not available. "
            "Log in at https://www.screener.in in Chrome, then restart the backend."
        )

    cache_key = f"mcp_screener:trades:{symbol}:{'c' if consolidated else 's'}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    async with AsyncSessionLocal() as db:
        db_row: StockUniverseModel | None = await db.get(StockUniverseModel, symbol)
        cached_trades_id: str | None = db_row.screener_trades_id if db_row else None

        if cached_trades_id:
            data = await screener_client.get_trades(cached_trades_id)
        else:
            data, resolved_id = await screener_client.get_trades_by_symbol(
                symbol, consolidated=consolidated
            )
            if db_row is not None:
                db_row.screener_trades_id = resolved_id
                await db.commit()

    _cache_set(cache_key, data)
    return data


@mcp.tool()
async def get_company_quarterly_results(symbol: str) -> dict[str, Any]:
    """Return full quarterly results for a company from screener.in (consolidated).

    Results are structured as year → month → {metric: value}, covering all
    rows in the #quarters table (Sales, Expenses, OPM%, Other Income, Interest,
    Depreciation, Profit before tax, Tax %, Net Profit, EPS in Rs, etc.) and
    all available periods — not just the last 4.

    Periods follow the format "Sep 2024"; trailing-twelve-month entries are
    returned under a month key of e.g. "Mar TTM".

    Example output::

        {
            "symbol": "HDFCBANK",
            "consolidated": true,
            "quarterly_results": {
                "2024": {
                    "Sep": { "Sales": "12345", "Net Profit": "1234", ... },
                    "Dec": { ... }
                },
                "2025": {
                    "Mar TTM": { ... }
                }
            }
        }

    Requires screener.in authentication (browser session).
    """
    from bs4 import BeautifulSoup

    consolidated = True
    symbol = symbol.upper().strip()
    if not _SYMBOL_RE.fullmatch(symbol):
        raise ValueError(f"Invalid symbol format: {symbol}")

    if not screener_client.is_authenticated:
        raise RuntimeError(
            "screener.in session not available. "
            "Log in at https://www.screener.in in Chrome, then restart the backend."
        )

    cache_key = f"mcp_screener:quarterly:{symbol}:{'c' if consolidated else 's'}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached  # type: ignore[return-value]

    html = await screener_client.get_company_html(symbol, consolidated=consolidated)
    soup = BeautifulSoup(html, "lxml")
    quarterly_results = _parse_all_quarters(soup)

    result: dict[str, Any] = {
        "symbol": symbol,
        "consolidated": consolidated,
        "quarterly_results": quarterly_results,
    }

    # Store with stored-at timestamp; quarterly data warrants the same 15-min
    # TTL as the HTML cache — use _cache_set (flat 10-min TTL) here since the
    # HTML cache is the authoritative 15-min layer; parsed quarterly data is
    # just a view over it.
    _cache_set(cache_key, result)
    return result


# ---------------------------------------------------------------------------
# Stock Universe Endpoints
# ---------------------------------------------------------------------------


@mcp.tool()
async def list_stock_universe() -> list[dict[str, Any]]:
    """Return all stock universe records from the database."""
    async with AsyncSessionLocal() as db:
        q = select(StockUniverseModel).order_by(StockUniverseModel.symbol)
        res = await db.execute(q)
        rows = res.scalars().all()
        return [
            {
                "symbol": r.symbol,
                "companyName": r.company_name,
                "segment": r.segment,
                "industry": r.industry,
                "sectorPE": r.sector_pe,
                "symbolPE": r.symbol_pe,
                "industryInfo": r.industry_info or {},
                "lastUpdateTime": r.last_update_time,
                "screenerTradesId": r.screener_trades_id,
            }
            for r in rows
        ]


@mcp.tool()
async def get_stock_universe(symbol: str) -> dict[str, Any]:
    """PREFER screener_company or get_symbol_data for stock research; this is a fallback for basic symbol/company name/sector search.
    Return a single stock universe record by symbol from the database."""
    symbol = symbol.upper().strip()
    async with AsyncSessionLocal() as db:
        rec = await db.get(StockUniverseModel, symbol)
        if rec is None:
            raise ValueError(f"Symbol '{symbol}' not found in stock universe")
        return {
            "symbol": rec.symbol,
            "companyName": rec.company_name,
            "segment": rec.segment,
            "industry": rec.industry,
            "sectorPE": rec.sector_pe,
            "symbolPE": rec.symbol_pe,
            "industryInfo": rec.industry_info or {},
            "lastUpdateTime": rec.last_update_time,
            "screenerTradesId": rec.screener_trades_id,
        }


@mcp.tool()
async def search_stock_universe(prefix: str) -> list[dict[str, Any]]:
    """Return stock universe records that match the prefix in symbol or company name."""
    prefix = prefix.strip()
    async with AsyncSessionLocal() as db:
        q = (
            select(StockUniverseModel)
            .where(
                StockUniverseModel.symbol.ilike(f"{prefix}%")
                | StockUniverseModel.company_name.ilike(f"{prefix}%")
            )
            .order_by(StockUniverseModel.symbol)
        )
        res = await db.execute(q)
        rows = res.scalars().all()
        return [
            {
                "symbol": r.symbol,
                "companyName": r.company_name,
                "segment": r.segment,
                "industry": r.industry,
                "sectorPE": r.sector_pe,
                "symbolPE": r.symbol_pe,
                "industryInfo": r.industry_info or {},
                "lastUpdateTime": r.last_update_time,
                "screenerTradesId": r.screener_trades_id,
            }
            for r in rows
        ]


# ---------------------------------------------------------------------------
# Watchlist Endpoints
# ---------------------------------------------------------------------------


@mcp.tool()
async def list_watchlist() -> list[dict[str, Any]]:
    """Return all stocks the user is interested in, ordered by creation time.

    Each item contains: id, symbol, exchange, createdAt.
    """
    async with AsyncSessionLocal() as db:
        q = select(WatchlistItemModel).order_by(WatchlistItemModel.created_at)
        res = await db.execute(q)
        rows = res.scalars().all()
        return [
            {
                "id": r.id,
                "symbol": r.symbol,
                "exchange": r.exchange,
                "createdAt": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]


@mcp.tool()
async def add_watchlist_item(symbol: str, exchange: str) -> dict[str, Any]:
    """Add a symbol/exchange pair to the watchlist (idempotent).

    If the pair already exists the existing row is returned unchanged.
    Returns the persisted item: id, symbol, exchange, createdAt.
    """
    symbol = symbol.strip().upper()
    exchange = exchange.strip().upper()
    if not symbol or not exchange:
        raise ValueError("symbol and exchange must be non-empty strings")

    async with AsyncSessionLocal() as db:
        existing = await db.execute(
            select(WatchlistItemModel).where(
                WatchlistItemModel.symbol == symbol,
                WatchlistItemModel.exchange == exchange,
            )
        )
        row = existing.scalar_one_or_none()
        if row is not None:
            return {
                "id": row.id,
                "symbol": row.symbol,
                "exchange": row.exchange,
                "createdAt": row.created_at.isoformat() if row.created_at else None,
            }

        item = WatchlistItemModel(symbol=symbol, exchange=exchange)
        db.add(item)
        await db.commit()
        await db.refresh(item)
        return {
            "id": item.id,
            "symbol": item.symbol,
            "exchange": item.exchange,
            "createdAt": item.created_at.isoformat() if item.created_at else None,
        }


@mcp.tool()
async def remove_watchlist_item(item_id: int) -> dict[str, Any]:
    """Remove a watchlist item by its numeric id.

    Returns {"ok": true, "id": <item_id>} on success.
    Raises ValueError if the item does not exist.
    """
    async with AsyncSessionLocal() as db:
        item = await db.get(WatchlistItemModel, item_id)
        if item is None:
            raise ValueError(f"watchlist item {item_id} not found")
        await db.delete(item)
        await db.commit()
    return {"ok": True, "id": item_id}


# ---------------------------------------------------------------------------
# News Endpoints
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_global_news(days: int = 7, limit: int = 50) -> list[dict[str, Any]]:
    """Return cached global news articles from MoneyControl.

    Args:
        days: Number of days to look back (default: 7)
        limit: Maximum number of articles to return (default: 50)
    """
    from datetime import datetime, timedelta

    start_date = datetime.now() - timedelta(days=days)

    async with AsyncSessionLocal() as db:
        stmt = (
            select(NewsArticle)
            .where(NewsArticle.source == SOURCE_NAME)
            .where(NewsArticle.publish_date >= start_date)
            .order_by(NewsArticle.publish_date.desc().nullslast())
            .limit(limit)
        )
        result = await db.execute(stmt)
        articles = result.scalars().all()

        return [
            {
                "url": a.url,
                "title": a.title,
                "text": a.text,
                "publish_date": a.publish_date.isoformat() if a.publish_date else None,
                "fetched_at": a.fetched_at.isoformat() if a.fetched_at else None,
            }
            for a in articles
        ]


_COMPANY_NEWS_STALE_SECONDS = 5 * 60  # matches global crawl cadence


@mcp.tool()
async def get_company_news(
    symbol: str, days: int = 30, limit: int = 50, refresh: bool = False
) -> list[dict[str, Any]]:
    """Return news articles for a specific company symbol from MoneyControl.

    Automatically fetches fresh articles from MoneyControl when needed:
      - No articles stored yet for the symbol (first call)
      - The most recently fetched article is older than 5 minutes (matches the
        global news crawl cadence — company pages are re-scraped at the same rate)
      - refresh=True is passed explicitly

    For unknown symbols (not in the built-in map), returns whatever is already
    stored in the DB without attempting a live fetch.

    Args:
        symbol: NSE ticker symbol (e.g., "RELIANCE", "INFY")
        days: Number of days to look back (default: 30)
        limit: Maximum number of articles to return (default: 50)
        refresh: Force a live fetch from MoneyControl even if articles are fresh (default: False)
    """
    from datetime import datetime, timedelta
    from sqlalchemy import func, or_

    symbol = symbol.upper()
    start_date = datetime.now() - timedelta(days=days)

    async def _query_db(db) -> list[dict[str, Any]]:
        stmt = (
            select(NewsArticle)
            .where(NewsArticle.company_symbol == symbol)
            .where(
                or_(
                    NewsArticle.publish_date >= start_date,
                    NewsArticle.publish_date.is_(None),
                )
            )
            .order_by(NewsArticle.publish_date.desc().nullslast())
            .limit(limit)
        )
        result = await db.execute(stmt)
        articles = result.scalars().all()
        return [
            {
                "url": a.url,
                "title": a.title,
                "text": a.text,
                "publish_date": a.publish_date.isoformat() if a.publish_date else None,
                "fetched_at": a.fetched_at.isoformat() if a.fetched_at else None,
            }
            for a in articles
        ]

    async def _latest_fetched_at(db) -> datetime | None:
        """Return the most recent fetched_at timestamp for this symbol's articles."""
        stmt = select(func.max(NewsArticle.fetched_at)).where(
            NewsArticle.company_symbol == symbol
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async with AsyncSessionLocal() as db:
        existing = await _query_db(db)
        latest_fetched = await _latest_fetched_at(db)

    # Determine staleness: compare the most recent fetched_at to now
    stale = True
    if latest_fetched is not None:
        age_seconds = (datetime.now() - latest_fetched).total_seconds()
        stale = age_seconds > _COMPANY_NEWS_STALE_SECONDS

    should_fetch = refresh or len(existing) == 0 or stale

    if should_fetch:
        logger.info(
            "get_company_news: fetching %s (stale=%s, existing=%d, refresh=%s)",
            symbol,
            stale,
            len(existing),
            refresh,
        )
        async with AsyncSessionLocal() as db:
            await news_fetcher.fetch_company_news(symbol=symbol, db=db)
        async with AsyncSessionLocal() as db:
            return await _query_db(db)

    return existing
