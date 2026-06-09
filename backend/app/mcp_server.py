"""MCP Server for BLM Analytics Backend.

This module exposes the backend's read-only GET API surface via the Model Context Protocol.
All tools call service and DB logic directly rather than making HTTP calls back into FastAPI.
"""

import asyncio
import logging
import os
import re
import time
from datetime import datetime, timedelta
from functools import partial
from typing import Any


def _safe_entities(v: Any) -> dict | None:
    """Return entities as a dict regardless of whether it was stored as a
    dict (post-backfill clean rows) or a JSON string (legacy corrupt rows).
    Mirrors the NewsArticleOut field_validator so mcp_server tools never crash.
    """
    import json as _j
    if v is None or isinstance(v, dict):
        return v
    if isinstance(v, str):
        try:
            result = _j.loads(v)
            if isinstance(result, str):
                result = _j.loads(result)
            return result if isinstance(result, dict) else None
        except (ValueError, TypeError):
            return None
    return None

import numpy as np
import pandas as pd
from mcp.server import FastMCP
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.corporatefilings import CorporateFiling
from app.models.marketcategory import MarketCategory, MarketCategoryStock
from app.models.news import NewsArticle
from app.models.stockuniverse import StockUniverse as StockUniverseModel
from app.models.notification import GlobalNotification, Notification
from app.models.watchlist import Watchlist as WatchlistModel
from app.models.watchlist import WatchlistItem as WatchlistItemModel
from app.services.nse_client import nse_client
from app.services.screener_client import screener_client
from app.services import screener as screener_service
from app.services.news_fetcher import SOURCE_NAME, news_fetcher

logger = logging.getLogger(__name__)

mcp = FastMCP("BLM Analytics", stateless_http=True, json_response=True, host="0.0.0.0")

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


USE_ASYNC_NSE = os.getenv("USE_ASYNC_NSE", "false").lower() == "true"
if USE_ASYNC_NSE:
    from app.services.nse_client_async import nse_client_async as _active_client
else:
    from app.services.nse_client import nse_client as _active_client

from app.services.nse_rate_limiter import throttled_nse_call


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@mcp.tool()
async def health_check() -> dict[str, str]:
    """Check backend service health and connectivity."""
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Market Endpoints
# ---------------------------------------------------------------------------


async def _mcp_snapshot() -> dict:
    """Fetch largedeal snapshot through the rate limiter (one NSE call)."""
    return await throttled_nse_call(
        "mcp:largedeal-snapshot",
        _active_client.get_largedeal_snapshot,
        is_async_fn=USE_ASYNC_NSE,
    )


_MOVERS_VALID_CATEGORIES = frozenset({
    "NIFTY", "BANKNIFTY", "NIFTYNEXT50",
    "SecGtr20", "SecLwr20", "FOSec", "allSec",
})


@mcp.tool()
async def get_top_gainers(category: str = "allSec") -> list[dict[str, Any]]:
    """Fetch today's top-gaining NSE equities ranked by intraday percentage change.

    Args:
        category: Index filter. One of: NIFTY (Nifty 50), BANKNIFTY (Bank Nifty),
                  NIFTYNEXT50 (Nifty Next 50), SecGtr20 (Securities > Rs 20),
                  SecLwr20 (Securities < Rs 20), FOSec (F&O Securities),
                  allSec (All Securities, default).

    Returns rows with: symbol, ltp, open_price, high_price, low_price, prev_price,
    net_price, perChange, trade_quantity, turnover, ca_ex_dt, ca_purpose, series,
    market_type.
    """
    safe_cat = category if category in _MOVERS_VALID_CATEGORIES else "allSec"
    cache_key = f"mcp_top_gainers_{safe_cat}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    payload = await throttled_nse_call(
        "mcp:market-variations-gainers",
        partial(_active_client.get_market_variations, "gainers"),
        is_async_fn=USE_ASYNC_NSE,
    )
    rows = payload.get(safe_cat, payload.get("allSec", {})).get("data", [])
    if rows:
        df = pd.DataFrame(rows)
        if "perChange" in df.columns:
            df["perChange"] = pd.to_numeric(df["perChange"], errors="coerce")
            df = df.dropna(subset=["perChange"]).sort_values("perChange", ascending=False)
            rows = _df_to_json_dict(df)
    result = _clean_nan(rows)
    _cache_set(cache_key, result)
    return result


@mcp.tool()
async def get_top_losers(category: str = "allSec") -> list[dict[str, Any]]:
    """Fetch today's top-losing NSE equities ranked by intraday percentage change.

    Args:
        category: Index filter. Same values as get_top_gainers.

    Returns rows with: symbol, ltp, open_price, high_price, low_price, prev_price,
    net_price, perChange, trade_quantity, turnover, ca_ex_dt, ca_purpose, series,
    market_type.
    """
    safe_cat = category if category in _MOVERS_VALID_CATEGORIES else "allSec"
    cache_key = f"mcp_top_losers_{safe_cat}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    payload = await throttled_nse_call(
        "mcp:market-variations-loosers",
        partial(_active_client.get_market_variations, "loosers"),
        is_async_fn=USE_ASYNC_NSE,
    )
    rows = payload.get(safe_cat, payload.get("allSec", {})).get("data", [])
    if rows:
        df = pd.DataFrame(rows)
        if "perChange" in df.columns:
            df["perChange"] = pd.to_numeric(df["perChange"], errors="coerce")
            df = df.dropna(subset=["perChange"]).sort_values("perChange", ascending=True)
            rows = _df_to_json_dict(df)
    result = _clean_nan(rows)
    _cache_set(cache_key, result)
    return result


@mcp.tool()
async def get_bulk_deals(
    symbol: str | None = None,
    symbols: list[str] | None = None,
) -> list[dict[str, Any]] | dict[str, Any]:
    """Fetch today's NSE bulk deal records for one or multiple stock symbols.

    Note: This returns only today's intraday deals from NSE's live snapshot.
    For historical bulk deal data (multi-year), use the `screener_trades` tool instead.

    Args:
        symbol: NSE ticker symbol for a single lookup (e.g. "RELIANCE", "TCS").
            Mutually exclusive with symbols.
        symbols: List of NSE ticker symbols for a bulk lookup (e.g. ["RELIANCE", "TCS"]).
            Mutually exclusive with symbol.

    Returns a list of deal records in single-symbol mode (empty if no deals today),
    or a dict keyed by symbol in bulk mode. Failed symbols return {"error": "<message>"}.
    """
    if symbol is None and symbols is None:
        raise ValueError("Provide either 'symbol' or 'symbols'")
    if symbol is not None and symbols is not None:
        raise ValueError("Provide either 'symbol' or 'symbols', not both")

    async def _fetch(sym: str, snapshot: dict) -> list[dict]:
        sym = sym.upper()
        cache_key = f"mcp_bulk_deals:{sym}"
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached
        rows = snapshot.get("BULK_DEALS_DATA", [])
        filtered = [r for r in rows if r.get("symbol", "").upper() == sym]
        _cache_set(cache_key, filtered)
        return filtered

    snapshot = await _mcp_snapshot()
    if symbol is not None:
        return await _fetch(symbol, snapshot)
    results = await asyncio.gather(
        *[_fetch(s, snapshot) for s in symbols],
        return_exceptions=True,
    )
    return {
        s.upper(): ({"error": str(r)} if isinstance(r, BaseException) else r)
        for s, r in zip(symbols, results)
    }


@mcp.tool()
async def get_block_deals(
    symbol: str | None = None,
    symbols: list[str] | None = None,
) -> list[dict[str, Any]] | dict[str, Any]:
    """Fetch today's NSE block deal records for one or multiple stock symbols.

    Note: This returns only today's intraday deals from NSE's live snapshot.
    For historical block deal data (multi-year), use the `screener_trades` tool instead.

    Args:
        symbol: NSE ticker symbol for a single lookup (e.g. "RELIANCE", "TCS").
            Mutually exclusive with symbols.
        symbols: List of NSE ticker symbols for a bulk lookup (e.g. ["RELIANCE", "TCS"]).
            Mutually exclusive with symbol.

    Returns a list of deal records in single-symbol mode (empty if no deals today),
    or a dict keyed by symbol in bulk mode. Failed symbols return {"error": "<message>"}.
    """
    if symbol is None and symbols is None:
        raise ValueError("Provide either 'symbol' or 'symbols'")
    if symbol is not None and symbols is not None:
        raise ValueError("Provide either 'symbol' or 'symbols', not both")

    async def _fetch(sym: str, snapshot: dict) -> list[dict]:
        sym = sym.upper()
        cache_key = f"mcp_block_deals:{sym}"
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached
        rows = snapshot.get("BLOCK_DEALS_DATA", [])
        filtered = [r for r in rows if r.get("symbol", "").upper() == sym]
        _cache_set(cache_key, filtered)
        return filtered

    snapshot = await _mcp_snapshot()
    if symbol is not None:
        return await _fetch(symbol, snapshot)
    results = await asyncio.gather(
        *[_fetch(s, snapshot) for s in symbols],
        return_exceptions=True,
    )
    return {
        s.upper(): ({"error": str(r)} if isinstance(r, BaseException) else r)
        for s, r in zip(symbols, results)
    }


@mcp.tool()
async def get_largedeal_snapshot() -> dict[str, Any]:
    """Fetch a combined real-time snapshot of NSE insider, bulk, and block deals across all stocks."""
    cache_key = "mcp_largedeal_snapshot"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    data = await throttled_nse_call(
        "largedeal-snapshot",
        _active_client.get_largedeal_snapshot,
        is_async_fn=USE_ASYNC_NSE,
    )
    data = _clean_nan(data)
    data.pop("SHORT_DEALS_DATA", None)
    _cache_set(cache_key, data)
    return data


@mcp.tool()
async def get_change_ranges(
    symbol: str | None = None,
    symbols: list[str] | None = None,
) -> dict[str, Any]:
    """Fetch NSE percentage price changes across multiple timeframes (1w to 5y) for one or multiple symbols.

    Args:
        symbol: NSE ticker symbol for a single lookup (e.g. "RELIANCE", "TCS").
            Mutually exclusive with symbols.
        symbols: List of NSE ticker symbols for a bulk lookup (e.g. ["RELIANCE", "TCS"]).
            Mutually exclusive with symbol.

    Returns keys per symbol: oneWeekPercent, oneMonthPercent, threeMonthPercent,
    sixMonthPercent, oneYearPercent, twoYearPercent, threeYearPercent,
    fiveYearPercent. In bulk mode returns a dict keyed by symbol; failed symbols
    return {"error": "<message>"}.
    """
    if symbol is None and symbols is None:
        raise ValueError("Provide either 'symbol' or 'symbols'")
    if symbol is not None and symbols is not None:
        raise ValueError("Provide either 'symbol' or 'symbols', not both")

    async def _fetch(sym: str) -> dict[str, Any]:
        sym = sym.upper()
        cache_key = f"mcp_change_ranges:{sym}"
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached
        data = await throttled_nse_call(
            f"change-ranges:{sym}",
            _active_client.get_change_ranges,
            sym,
            is_async_fn=USE_ASYNC_NSE,
        )
        data = _clean_nan(data)
        _cache_set(cache_key, data)
        return data

    if symbol is not None:
        return await _fetch(symbol)
    results = await asyncio.gather(*[_fetch(s) for s in symbols], return_exceptions=True)
    return {
        s.upper(): ({"error": str(r)} if isinstance(r, BaseException) else r)
        for s, r in zip(symbols, results)
    }


@mcp.tool()
async def get_symbol_data(
    symbol: str | None = None,
    symbols: list[str] | None = None,
    fields: list[str] | None = None,
) -> dict[str, Any]:
    """Fetch live NSE quote data for one or multiple symbols, including LTP, 52-week range, sector, and industry.

    Args:
        symbol: NSE ticker symbol for a single lookup (e.g. "RELIANCE", "TCS").
            Mutually exclusive with symbols.
        symbols: List of NSE ticker symbols for a bulk lookup (e.g. ["RELIANCE", "TCS"]).
            Mutually exclusive with symbol.

    In bulk mode returns a dict keyed by symbol; failed symbols return
    {"error": "<message>"}.

    Optional fields filters the returned symbol payload down to just the listed
    keys.
    """
    if symbol is None and symbols is None:
        raise ValueError("Provide either 'symbol' or 'symbols'")
    if symbol is not None and symbols is not None:
        raise ValueError("Provide either 'symbol' or 'symbols', not both")

    async def _fetch(sym: str) -> dict[str, Any]:
        sym = sym.upper()
        cache_key = f"mcp_symbol_data:{sym}"
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached
        data = await throttled_nse_call(
            f"symbol-data:{sym}",
            _active_client.get_symbol_data,
            sym,
            is_async_fn=USE_ASYNC_NSE,
        )
        data = _clean_nan(data)
        if fields:
            data = {k: v for k, v in data.items() if k in fields}
        _cache_set(cache_key, data)
        return data

    if symbol is not None:
        return await _fetch(symbol)
    results = await asyncio.gather(*[_fetch(s) for s in symbols], return_exceptions=True)
    return {
        s.upper(): ({"error": str(r)} if isinstance(r, BaseException) else r)
        for s, r in zip(symbols, results)
    }


@mcp.tool()
async def get_52week_low_stocks() -> dict[str, Any]:
    """Fetch NSE stocks that crossed a new 52-week low today."""
    cache_key = "mcp_52week_low"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    data = await throttled_nse_call(
        "52week-low",
        _active_client.get_52week_low_stocks,
        is_async_fn=USE_ASYNC_NSE,
    )
    data = _clean_nan(data)
    for rec in data.get("data", []):
        if isinstance(rec, dict) and "comapnyName" in rec:
            rec["companyName"] = rec.pop("comapnyName")
    _cache_set(cache_key, data)
    return data


@mcp.tool()
async def get_52week_high_stocks() -> dict[str, Any]:
    """Fetch NSE stocks that crossed a new 52-week high today."""
    cache_key = "mcp_52week_high"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    data = await throttled_nse_call(
        "52week-high",
        _active_client.get_52week_high_stocks,
        is_async_fn=USE_ASYNC_NSE,
    )
    data = _clean_nan(data)
    for rec in data.get("data", []):
        if isinstance(rec, dict) and "comapnyName" in rec:
            rec["companyName"] = rec.pop("comapnyName")
    _cache_set(cache_key, data)
    return data


@mcp.tool()
async def get_volume_gainers() -> dict[str, Any]:
    """Fetch NSE stocks with the largest volume surge relative to their weekly average. This data is more up-to-date than the global scan tool as it is calculated from NSE live data.
    Use this when looking for volume breakouts or unusual trading activity in the current day, and use the global scan tool for a broader historical view of volume trends.
    """
    cache_key = "mcp_volume_gainers"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    data = await throttled_nse_call(
        "volume-gainers",
        _active_client.get_volume_gainers,
        is_async_fn=USE_ASYNC_NSE,
    )
    data = _clean_nan(data)
    _cache_set(cache_key, data)
    return data


# ---------------------------------------------------------------------------
# Corporate Filings
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_corporate_filings(
    symbol: str | None = None,
    symbols: list[str] | None = None,
) -> dict[str, Any]:
    """Fetch NSE quarterly corporate filing results for one or multiple symbols as pipe-delimited CSV.

    Args:
        symbol: NSE ticker symbol for a single lookup (e.g. "RELIANCE", "TCS").
            Mutually exclusive with symbols.
        symbols: List of NSE ticker symbols for a bulk lookup (e.g. ["RELIANCE", "TCS"]).
            Mutually exclusive with symbol.

    Returns structured data containing: symbol, media_type, and csv_text in
    single-symbol mode. In bulk mode returns a dict keyed by symbol; failed
    symbols return {"error": "<message>"}.
    """
    if symbol is None and symbols is None:
        raise ValueError("Provide either 'symbol' or 'symbols'")
    if symbol is not None and symbols is not None:
        raise ValueError("Provide either 'symbol' or 'symbols', not both")

    async def _fetch(sym: str) -> dict[str, Any]:
        sym = sym.upper().strip()
        if not _SYMBOL_RE.fullmatch(sym):
            raise ValueError(f"Invalid symbol format: {sym}")

        async with AsyncSessionLocal() as db:
            record = await db.get(CorporateFiling, sym)

            from datetime import datetime, timedelta, timezone

            stale_after = timedelta(days=30)
            now = datetime.now(tz=timezone.utc).replace(tzinfo=None)
            needs_refresh = record is None or (now - record.last_fetched_at) > stale_after

            if needs_refresh:
                try:
                    csv_text: str = await throttled_nse_call(
                        f"corporate-filing:{sym}",
                        _active_client.get_corporate_filing_comparison,
                        sym,
                        is_async_fn=USE_ASYNC_NSE,
                    )
                except Exception as exc:
                    logger.exception("NSE fetch failed for %s", sym)
                    raise RuntimeError(
                        f"Failed to fetch corporate filings for {sym} from NSE: {exc}"
                    ) from exc

                now = datetime.now(tz=timezone.utc).replace(tzinfo=None)
                if record is None:
                    record = CorporateFiling(
                        symbol=sym,
                        csv_data=csv_text,
                        last_fetched_at=now,
                    )
                    db.add(record)
                else:
                    record.csv_data = csv_text
                    record.last_fetched_at = now

                await db.commit()
                logger.info("Corporate filings refreshed for %s", sym)
            else:
                csv_text = record.csv_data

        return {
            "symbol": sym,
            "media_type": "text/csv",
            "csv_text": csv_text,
        }

    if symbol is not None:
        return await _fetch(symbol)
    results = await asyncio.gather(*[_fetch(s) for s in symbols], return_exceptions=True)
    return {
        s.upper(): ({"error": str(r)} if isinstance(r, BaseException) else r)
        for s, r in zip(symbols, results)
    }


# ---------------------------------------------------------------------------
# Screener Endpoints
# ---------------------------------------------------------------------------


@mcp.tool()
async def screener_search(q: str) -> list[dict[str, Any]]:
    """Search screener.in for NSE companies by name or symbol fragment.

    Args:
        q: Company name or symbol fragment to search (1–80 characters).
    """
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
async def screener_company(
    symbol: str | None = None,
    symbols: list[str] | None = None,
    consolidated: bool = True,
) -> dict[str, Any]:
    """Fetch fundamental ratios and quarterly results for one or multiple NSE companies from screener.in.

    Args:
        symbol: NSE ticker symbol for a single lookup (e.g. "HDFCBANK", "INFY").
            Mutually exclusive with symbols.
        symbols: List of NSE ticker symbols for a bulk lookup (e.g. ["HDFCBANK", "INFY"]).
            Mutually exclusive with symbol.
        consolidated: Use consolidated financials (default: True); set False for standalone.
            Applies uniformly to all symbols in bulk mode.

    Returns: symbol, name, ratios (P/E, ROCE, ROE, etc.), quarters (last 4).
    In bulk mode returns a dict keyed by symbol; failed symbols return {"error": "<message>"}.
    Requires screener.in authentication (browser session).
    """
    if symbol is None and symbols is None:
        raise ValueError("Provide either 'symbol' or 'symbols'")
    if symbol is not None and symbols is not None:
        raise ValueError("Provide either 'symbol' or 'symbols', not both")

    if not screener_client.is_authenticated:
        raise RuntimeError(
            "screener.in session not available. "
            "Log in at https://www.screener.in in Chrome, then restart the backend."
        )

    async def _fetch(sym: str) -> dict[str, Any]:
        sym = sym.upper().strip()
        if not _SYMBOL_RE.fullmatch(sym):
            raise ValueError(f"Invalid symbol format: {sym}")
        cache_key = f"mcp_screener:company:{sym}:{'c' if consolidated else 's'}"
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached
        data = await screener_client.get_company(sym, consolidated=consolidated)
        _cache_set(cache_key, data)
        return data

    if symbol is not None:
        return await _fetch(symbol)
    results = await asyncio.gather(*[_fetch(s) for s in symbols], return_exceptions=True)
    return {
        s.upper(): ({"error": str(r)} if isinstance(r, BaseException) else r)
        for s, r in zip(symbols, results)
    }


@mcp.tool()
async def screener_trades(
    symbol: str | None = None,
    symbols: list[str] | None = None,
    consolidated: bool = True,
) -> dict[str, Any]:
    """Fetch insider trades, bulk deals, and block deals for one or multiple NSE companies from screener.in.

    Args:
        symbol: NSE ticker symbol for a single lookup (e.g. "HDFCBANK", "INFY").
            Mutually exclusive with symbols.
        symbols: List of NSE ticker symbols for a bulk lookup (e.g. ["HDFCBANK", "INFY"]).
            Mutually exclusive with symbol.
        consolidated: Use consolidated financials (default: True); set False for standalone.
            Applies uniformly to all symbols in bulk mode.

    Returns per symbol:
      - warehouse_id   : resolved screener trades company ID
      - insider_trades : list of insider trade records
      - bulk_deals     : list of bulk deal records
      - block_deals    : list of block deal records
    In bulk mode returns a dict keyed by symbol; failed symbols return {"error": "<message>"}.
    Requires screener.in authentication (browser session).
    """
    if symbol is None and symbols is None:
        raise ValueError("Provide either 'symbol' or 'symbols'")
    if symbol is not None and symbols is not None:
        raise ValueError("Provide either 'symbol' or 'symbols', not both")

    if not screener_client.is_authenticated:
        raise RuntimeError(
            "screener.in session not available. "
            "Log in at https://www.screener.in in Chrome, then restart the backend."
        )

    async def _fetch(sym: str) -> dict[str, Any]:
        sym = sym.upper().strip()
        if not _SYMBOL_RE.fullmatch(sym):
            raise ValueError(f"Invalid symbol format: {sym}")
        cache_key = f"mcp_screener:trades:{sym}:{'c' if consolidated else 's'}"
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached
        async with AsyncSessionLocal() as db:
            db_row: StockUniverseModel | None = await db.get(StockUniverseModel, sym)
            cached_trades_id: str | None = db_row.screener_trades_id if db_row else None
            if cached_trades_id:
                data = await screener_client.get_trades(cached_trades_id)
            else:
                data, resolved_id = await screener_client.get_trades_by_symbol(
                    sym, consolidated=consolidated
                )
                if db_row is not None:
                    db_row.screener_trades_id = resolved_id
                    await db.commit()
        _cache_set(cache_key, data)
        return data

    if symbol is not None:
        return await _fetch(symbol)
    results = await asyncio.gather(*[_fetch(s) for s in symbols], return_exceptions=True)
    return {
        s.upper(): ({"error": str(r)} if isinstance(r, BaseException) else r)
        for s, r in zip(symbols, results)
    }


@mcp.tool()
async def run_tql_screener(
    tql: str,
    default_interval: str = "1d",
    sort_by: str = "symbol",
    order: str = "asc",
    limit: int = 50,
) -> dict[str, Any]:
    """Run a custom TQL (Ticker Query Language) screener query against all NSE stocks.

    Returns matching symbols with their technical and fundamental data.

    Args:
        tql: TQL query expression. Examples:
            RSI > 60 AND Sector = "Banks"
            PE < 20 AND Return1y > 20
            1h:RSI < 30 AND Volume > 500000
            From52wHigh > -10 AND MomentumScore > 70
            Sector IN ("Banks", "Finance") AND RSI > 50 AND PE < 25
        default_interval: Default interval for un-prefixed indicator fields.
            One of: 1d (default), 1h, W, M.
            Prefix individual fields to override: 1h:RSI, W:ATR, M:MACD.
        sort_by: Field name to sort results by (default: symbol).
        order: Sort direction — asc (default) or desc.
        limit: Maximum number of results to return, 1–200 (default: 50).

    Supported fields:
        Technical (support interval prefix):
            RSI, ATR, MACD, MACDSignal, MACDHist, BBWidth, BBSqueeze,
            HV20, HV60, Sharpe60, Sharpe126
        Price & volume:
            Change, Volume, Close, DataPoints
        Fundamentals:
            PE, MomentumScore
        Returns:
            Return1w, Return1m, Return3m, Return6m, Return1y
        52-week position:
            From52wHigh, From52wLow
        Classification (use = or IN):
            Sector, Industry, Symbol

    Returns dict with: count, returned, filters_applied, results (list of symbol dicts).
    Raises ValueError on TQL syntax errors.
    """
    if not tql or not tql.strip():
        raise ValueError("tql query expression is required")
    if limit < 1 or limit > 200:
        raise ValueError("limit must be between 1 and 200")
    if order not in ("asc", "desc"):
        raise ValueError("order must be 'asc' or 'desc'")

    return await asyncio.to_thread(
        screener_service.run_screener_tql,
        tql.strip(),
        default_interval,
        sort_by,
        order,
        limit,
    )


# ---------------------------------------------------------------------------
# Stock Universe Endpoints
# ---------------------------------------------------------------------------


@mcp.tool()
async def list_stock_universe() -> dict[str, Any]:
    """List all tracked NSE stocks with symbol, company name, sector, industry, and PE data."""
    async with AsyncSessionLocal() as db:
        q = select(StockUniverseModel).order_by(StockUniverseModel.symbol)
        res = await db.execute(q)
        rows = res.scalars().all()
        return {
            "data": [
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
        }


@mcp.tool()
async def get_stock_universe(
    symbol: str | None = None,
    symbols: list[str] | None = None,
) -> dict[str, Any]:
    """Look up NSE stock universe metadata by symbol — prefer screener_company for deeper research.

    Args:
        symbol: NSE ticker symbol for a single lookup (e.g. "RELIANCE", "TCS").
            Mutually exclusive with symbols.
        symbols: List of NSE ticker symbols for a bulk lookup (e.g. ["RELIANCE", "TCS"]).
            Mutually exclusive with symbol. Issues a single IN query for efficiency.

    In bulk mode returns a dict keyed by symbol. Symbols not found in the
    stock universe return {"error": "Symbol '<SYM>' not found in stock universe"}.
    """
    if symbol is None and symbols is None:
        raise ValueError("Provide either 'symbol' or 'symbols'")
    if symbol is not None and symbols is not None:
        raise ValueError("Provide either 'symbol' or 'symbols', not both")

    def _row_to_dict(rec: StockUniverseModel) -> dict[str, Any]:
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

    if symbol is not None:
        sym = symbol.upper().strip()
        async with AsyncSessionLocal() as db:
            rec = await db.get(StockUniverseModel, sym)
            if rec is None:
                raise ValueError(f"Symbol '{sym}' not found in stock universe")
            return _row_to_dict(rec)

    # Bulk: single IN query
    sym_list = [s.upper().strip() for s in symbols]
    async with AsyncSessionLocal() as db:
        stmt = select(StockUniverseModel).where(StockUniverseModel.symbol.in_(sym_list))
        res = await db.execute(stmt)
        found = {r.symbol: _row_to_dict(r) for r in res.scalars().all()}
    return {
        sym: found.get(sym, {"error": f"Symbol '{sym}' not found in stock universe"})
        for sym in sym_list
    }


@mcp.tool()
async def search_stock_universe(prefix: str) -> dict[str, Any]:
    """Search tracked NSE stocks by symbol or company name prefix.

    Args:
        prefix: Leading characters of a symbol or company name (e.g. "HDFC", "Tata").
    """
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
        return {
            "data": [
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
        }


# ---------------------------------------------------------------------------
# Watchlist Endpoints
# ---------------------------------------------------------------------------

from app.auth import current_user_id

async def _get_user_id_or_default() -> int:
    uid = current_user_id.get()
    return uid if uid is not None else 1

async def _get_default_watchlist_id(db) -> int:
    from sqlalchemy import select
    user_id = await _get_user_id_or_default()
    q = select(WatchlistModel).where(WatchlistModel.user_id == user_id, WatchlistModel.name == "Default")
    wl = (await db.execute(q)).scalar_one_or_none()
    if wl:
        return wl.id
    wl = WatchlistModel(name="Default", user_id=user_id)
    db.add(wl)
    await db.commit()
    await db.refresh(wl)
    return wl.id


@mcp.tool()
async def list_watchlist() -> dict[str, Any]:
    """List all items in the user's default watchlist, ordered by time added.

    Each item contains: id, symbol, exchange, createdAt.
    """
    async with AsyncSessionLocal() as db:
        wl_id = await _get_default_watchlist_id(db)
        q = select(WatchlistItemModel).where(WatchlistItemModel.watchlist_id == wl_id).order_by(WatchlistItemModel.created_at)
        res = await db.execute(q)
        rows = res.scalars().all()
        return {
            "data": [
                {
                    "id": r.id,
                    "symbol": r.symbol,
                    "exchange": r.exchange,
                    "createdAt": r.created_at.isoformat() if r.created_at else None,
                }
                for r in rows
            ]
        }


@mcp.tool()
async def get_watchlist_symbols() -> dict[str, Any]:
    """Fetch distinct symbols from the user's default watchlist as a flat list."""
    async with AsyncSessionLocal() as db:
        wl_id = await _get_default_watchlist_id(db)
        q = select(WatchlistItemModel.symbol).where(WatchlistItemModel.watchlist_id == wl_id).distinct().order_by(WatchlistItemModel.symbol)
        res = await db.execute(q)
        rows = res.scalars().all()
        return {"data": [r for r in rows]}


@mcp.tool()
async def remove_watchlist_item(item_id: int) -> dict[str, Any]:
    """Delete an item from the default watchlist by its numeric ID.

    Args:
        item_id: Numeric ID of the watchlist item to remove.

    Returns {"ok": true, "id": <item_id>} on success.
    Raises ValueError if the item does not exist.
    """
    async with AsyncSessionLocal() as db:
        item = await db.get(WatchlistItemModel, item_id)
        if item is None:
            raise ValueError(f"watchlist item {item_id} not found")
        watchlist = await db.get(WatchlistModel, item.watchlist_id)
        user_id = await _get_user_id_or_default()
        if watchlist is None or watchlist.user_id != user_id:
            raise ValueError(f"watchlist item {item_id} not found")
        await db.delete(item)
        await db.commit()
    return {"ok": True, "id": item_id}


@mcp.tool()
async def list_watchlists() -> dict[str, Any]:
    """List all user-created watchlists with name and item count.

    Each entry includes: id, name, createdAt, itemCount.
    """
    from sqlalchemy import func

    async with AsyncSessionLocal() as db:
        user_id = await _get_user_id_or_default()
        stmt = (
            select(
                WatchlistModel.id,
                WatchlistModel.name,
                WatchlistModel.created_at,
                func.count(WatchlistItemModel.id).label("item_count"),
            )
            .outerjoin(WatchlistItemModel, WatchlistItemModel.watchlist_id == WatchlistModel.id)
            .where(WatchlistModel.user_id == user_id)
            .group_by(WatchlistModel.id)
            .order_by(WatchlistModel.id)
        )
        result = await db.execute(stmt)
        rows = result.all()
        return {
            "data": [
            {
                "id": r.id,
                "name": r.name,
                "createdAt": r.created_at.isoformat() if r.created_at else None,
                "itemCount": r.item_count,
            }
            for r in rows
            ]
        }


@mcp.tool()
async def get_watchlist_items(watchlist_id: int) -> dict[str, Any]:
    """Fetch all symbol/exchange items in a watchlist by its numeric ID.

    Args:
        watchlist_id: Numeric watchlist ID — use list_watchlists() to enumerate valid IDs.

    Each item includes: id, watchlistId, symbol, exchange, createdAt.
    Raises ValueError if the watchlist does not exist.
    """
    async with AsyncSessionLocal() as db:
        user_id = await _get_user_id_or_default()
        watchlist = await db.get(WatchlistModel, watchlist_id)
        if watchlist is None or watchlist.user_id != user_id:
            raise ValueError(f"Watchlist {watchlist_id} not found")

        stmt = (
            select(WatchlistItemModel)
            .where(WatchlistItemModel.watchlist_id == watchlist_id)
            .order_by(WatchlistItemModel.created_at)
        )
        result = await db.execute(stmt)
        rows = result.scalars().all()
        return {
            "data": [
                {
                    "id": r.id,
                    "watchlistId": r.watchlist_id,
                    "symbol": r.symbol,
                    "exchange": r.exchange,
                    "createdAt": r.created_at.isoformat() if r.created_at else None,
                }
                for r in rows
            ]
        }


# ---------------------------------------------------------------------------
# Portfolio Optimization
# ---------------------------------------------------------------------------


@mcp.tool()
async def optimize_portfolio(
    symbols: list[str],
    period: str = "2y",
    objective: str = "max_sharpe",
    risk_free_rate: float = 0.065,
) -> dict[str, Any]:
    """Run portfolio optimization on a list of NSE symbols using mean-variance or hierarchical risk parity.

    Args:
        symbols: List of NSE ticker symbols (no .NS suffix needed). Requires at least 3 symbols.
        period: Lookback period — '1y', '2y' (default), or '3y'.
        objective: Optimization goal — 'max_sharpe' (default), 'min_volatility', or 'risk_parity'.
        risk_free_rate: Annual risk-free rate as decimal (default 0.065 ≈ RBI repo rate).

    Returns weights per symbol, expected annual return/volatility, Sharpe ratio,
    a correlation matrix, and per-symbol individual stats.
    """
    from app.routers.portfolio import _run_optimization_sync, PortfolioOptimizeRequest

    request = PortfolioOptimizeRequest(
        symbols=symbols,
        period=period,
        objective=objective,
        risk_free_rate=risk_free_rate,
    )
    try:
        result = await asyncio.to_thread(_run_optimization_sync, request)
        return result.model_dump(mode="json")
    except ValueError as exc:
        raise ValueError(str(exc)) from exc


# ---------------------------------------------------------------------------
# Watchlist Management
# ---------------------------------------------------------------------------


@mcp.tool()
async def create_watchlist(name: str) -> dict[str, Any]:
    """Create a new named watchlist.

    Args:
        name: Watchlist name — alphanumeric and hyphens only (e.g. 'Tech-Buys', 'Portfolio-2024').

    Returns the created watchlist with its id and creation timestamp.
    """
    async with AsyncSessionLocal() as db:
        user_id = await _get_user_id_or_default()
        watchlist = WatchlistModel(name=name, user_id=user_id)
        db.add(watchlist)
        await db.commit()
        await db.refresh(watchlist)
        return {
            "id": watchlist.id,
            "name": watchlist.name,
            "createdAt": watchlist.created_at.isoformat() if watchlist.created_at else None,
        }


@mcp.tool()
async def add_watchlist_item(
    watchlist_id: int,
    symbol: str,
    exchange: str = "NSE",
) -> dict[str, Any]:
    """Add a single symbol/exchange pair to a named watchlist. Idempotent — returns the existing row if already present.

    Args:
        watchlist_id: Numeric ID of the watchlist — use list_watchlists() to enumerate valid IDs.
        symbol: NSE ticker symbol (e.g. 'RELIANCE', 'TCS').
        exchange: Exchange (default 'NSE').

    Returns the watchlist item with its id, or the existing item if already present.
    Raises ValueError if the watchlist does not exist.
    """
    async with AsyncSessionLocal() as db:
        user_id = await _get_user_id_or_default()
        watchlist = await db.get(WatchlistModel, watchlist_id)
        if watchlist is None or watchlist.user_id != user_id:
            raise ValueError(f"Watchlist {watchlist_id} not found")

        sym = symbol.upper().strip()
        exc = exchange.upper().strip()
        existing = await db.execute(
            select(WatchlistItemModel).where(
                WatchlistItemModel.watchlist_id == watchlist_id,
                WatchlistItemModel.symbol == sym,
                WatchlistItemModel.exchange == exc,
            )
        )
        row = existing.scalar_one_or_none()
        if row is not None:
            return {
                "id": row.id,
                "watchlistId": row.watchlist_id,
                "symbol": row.symbol,
                "exchange": row.exchange,
                "createdAt": row.created_at.isoformat() if row.created_at else None,
            }

        item = WatchlistItemModel(watchlist_id=watchlist_id, symbol=sym, exchange=exc)
        db.add(item)
        await db.commit()
        await db.refresh(item)
        return {
            "id": item.id,
            "watchlistId": item.watchlist_id,
            "symbol": item.symbol,
            "exchange": item.exchange,
            "createdAt": item.created_at.isoformat() if item.created_at else None,
        }


@mcp.tool()
async def bulk_replace_watchlist(
    watchlist_id: int,
    symbols: list[str],
    exchange: str = "NSE",
) -> dict[str, Any]:
    """Atomically replace all items in a watchlist with a new set of symbols.

    Use this to save an optimized portfolio — it DELETES all existing items
    and inserts the new set in a single transaction.

    Args:
        watchlist_id: Numeric ID of the watchlist to overwrite.
        symbols: List of NSE ticker symbols to set as the new portfolio.
        exchange: Exchange for all symbols (default 'NSE').

    Returns {ok: true, watchlist_id, items_added} on success.
    Raises ValueError if the watchlist does not exist.
    """
    async with AsyncSessionLocal() as db:
        user_id = await _get_user_id_or_default()
        watchlist = await db.get(WatchlistModel, watchlist_id)
        if watchlist is None or watchlist.user_id != user_id:
            raise ValueError(f"Watchlist {watchlist_id} not found")

        await db.execute(
            delete(WatchlistItemModel).where(
                WatchlistItemModel.watchlist_id == watchlist_id
            )
        )

        exc = exchange.upper().strip()
        seen: set[str] = set()
        for sym in symbols:
            s = sym.upper().strip()
            if s and s not in seen:
                seen.add(s)
                db.add(
                    WatchlistItemModel(
                        watchlist_id=watchlist_id, symbol=s, exchange=exc
                    )
                )

        await db.commit()
        return {
            "ok": True,
            "watchlist_id": watchlist_id,
            "items_added": len(seen),
        }


# ---------------------------------------------------------------------------
# Notifications Endpoints
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_notifications(
    watchlist_id: int,
    limit: int | None = None,
    since_id: int | None = None,
) -> dict[str, Any]:
    """Fetch unread market-event notifications for a watchlist, newest first.

    Args:
        watchlist_id: Numeric watchlist ID — use list_watchlists() to enumerate valid IDs.

    Each notification includes: id, watchlistId, symbol, exchange, triggerType,
    message, triggeredAt, triggeredDate.
    """
    async with AsyncSessionLocal() as db:
        user_id = await _get_user_id_or_default()
        from app.models.watchlist import Watchlist as WatchlistModel
        wl = await db.get(WatchlistModel, watchlist_id)
        if wl is None or wl.user_id != user_id:
            raise ValueError("Watchlist not found")

        stmt = (
            select(Notification)
            .where(Notification.watchlist_id == watchlist_id)
            .where(Notification.is_read == False)  # noqa: E712
            .order_by(Notification.triggered_at.desc())
        )
        if since_id is not None:
            stmt = stmt.where(Notification.id > since_id)
        if limit is not None:
            stmt = stmt.limit(limit)
        result = await db.execute(stmt)
        rows = result.scalars().all()
        return {
            "data": [
                {
                    "id": r.id,
                    "watchlistId": r.watchlist_id,
                    "symbol": r.symbol,
                    "exchange": r.exchange,
                    "triggerType": r.trigger_type,
                    "message": r.message,
                    "triggeredAt": r.triggered_at.isoformat() if r.triggered_at else None,
                    "triggeredDate": r.triggered_date.isoformat() if r.triggered_date else None,
                }
                for r in rows
            ]
        }


@mcp.tool()
async def get_global_notifications(
    limit: int | None = None,
    trigger_type: str | None = None,
) -> dict[str, Any]:
    """Fetch unread global NSE scan alerts across all stocks, with optional type and count filters.

    Args:
        limit: Cap the number of results returned (default: no limit).
        trigger_type: Filter by event type (e.g. "52w_high_breakout", "52w_low_breakout",
                      "volume_breakout", "top_gainer", "top_loser", "results_upcoming",
                      "rsi_oversold", "rsi_overbought", "macd_bullish_cross",
                      "macd_bearish_cross", "bb_squeeze_alert", "bb_upper_break",
                      "bb_lower_break", "volatility_spike", "atr_expansion",
                      "momentum_surge", "return_1w_spike", "streak_up_5d",
                      "streak_down_5d", "near_52w_high", "near_52w_low"); omit to return all.

    Each alert includes: id, symbol, exchange, triggerType, message,
    triggeredAt, triggeredDate.
    """
    async with AsyncSessionLocal() as db:
        stmt = (
            select(GlobalNotification)
            .where(GlobalNotification.is_read == False)  # noqa: E712
            .order_by(GlobalNotification.triggered_at.desc())
        )
        if trigger_type:
            stmt = stmt.where(GlobalNotification.trigger_type == trigger_type)
        if limit is not None:
            stmt = stmt.limit(limit)
        result = await db.execute(stmt)
        rows = result.scalars().all()
        return {
            "data": [
                {
                    "id": r.id,
                    "symbol": r.symbol,
                    "exchange": r.exchange,
                    "triggerType": r.trigger_type,
                    "message": r.message,
                    "triggeredAt": r.triggered_at.isoformat() if r.triggered_at else None,
                    "triggeredDate": r.triggered_date.isoformat() if r.triggered_date else None,
                }
                for r in rows
            ]
        }


# ---------------------------------------------------------------------------
# Morningstar Endpoints
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_morningstar_fairvalue(
    symbol: str | None = None,
    symbols: list[str] | None = None,
) -> dict[str, Any]:
    """Fetch Morningstar fair value estimate and uncertainty rating for one or multiple NSE stock symbols.

    Args:
        symbol: NSE ticker symbol for a single lookup (e.g. "TCS", "RELIANCE").
            Mutually exclusive with symbols.
        symbols: List of NSE ticker symbols for a bulk lookup (e.g. ["TCS", "RELIANCE"]).
            Mutually exclusive with symbol.

    Returns per symbol: symbol, morningstarId, fairValue, updatedAt.
    In bulk mode returns a dict keyed by symbol; failed symbols return {"error": "<message>"}.
    Requires a valid Morningstar browser session (rookiepy).
    """
    from app.services.morningstar_client import morningstar_client

    if symbol is None and symbols is None:
        raise ValueError("Provide either 'symbol' or 'symbols'")
    if symbol is not None and symbols is not None:
        raise ValueError("Provide either 'symbol' or 'symbols', not both")

    async def _fetch(sym: str) -> dict[str, Any]:
        sym = sym.upper().strip()
        if not _SYMBOL_RE.fullmatch(sym):
            raise ValueError(f"Invalid symbol format: {sym}")
        async with AsyncSessionLocal() as db:
            return await morningstar_client.get_fair_value_by_symbol(sym, db=db)

    if symbol is not None:
        return await _fetch(symbol)
    results = await asyncio.gather(*[_fetch(s) for s in symbols], return_exceptions=True)
    return {
        s.upper(): ({"error": str(r)} if isinstance(r, BaseException) else r)
        for s, r in zip(symbols, results)
    }


@mcp.tool()
async def get_global_news(
    days: int = 7,
    limit: int = 50,
    sources: list[str] | None = None,
    sentiment: str | None = None,
    threat_level: str | None = None,
    language: str | None = None,
) -> dict[str, Any]:
    """Fetch recent financial news from MoneyControl and 35+ RSS sources with NLP analysis.

    Returns articles from all sources by default (MoneyControl + all RSS feeds).
    Supports additive filtering: an article passes if it matches ANY active filter.

    Args:
        days: Number of days to look back (default: 7).
        limit: Maximum number of articles to return (default: 50).
        sources: Filter by source IDs (e.g. ['bloomberg-mkts', 'reuters-markets']).
        sentiment: Filter by sentiment (POSITIVE, NEGATIVE, NEUTRAL).
        threat_level: Filter by threat level (LOW, MEDIUM, HIGH, CRITICAL).
        language: Filter by two-letter language code (en, hi, zh, etc.).
    """
    import json as _json

    from sqlalchemy import or_

    start_date = datetime.now() - timedelta(days=days)

    async with AsyncSessionLocal() as db:
        conditions = [NewsArticle.publish_date >= start_date]

        if sources:
            conditions.append(NewsArticle.source.in_(sources))
        if sentiment:
            conditions.append(NewsArticle.sentiment == sentiment.upper())
        if threat_level:
            conditions.append(NewsArticle.threat_level == threat_level.upper())
        if language:
            conditions.append(NewsArticle.language == language.lower())

        stmt = (
            select(NewsArticle)
            .where(or_(*conditions) if conditions else True)
            .order_by(NewsArticle.publish_date.desc().nullslast())
            .limit(limit)
        )
        result = await db.execute(stmt)
        articles = result.scalars().all()

        return {
            "data": [
                {
                    "url": a.url,
                    "title": a.title,
                    "text": a.text,
                    "publish_date": a.publish_date.isoformat() if a.publish_date else None,
                    "fetched_at": a.fetched_at.isoformat() if a.fetched_at else None,
                    "sentiment": a.sentiment,
                    "sentiment_score": a.sentiment_score,
                    "confidence": a.confidence,
                    "language": a.language,
                    "entities": _safe_entities(a.entities),
                    "threat_level": a.threat_level,
                    "threat_category": a.threat_category,
                    "source_credibility": a.source_credibility,
                }
                for a in articles
            ]
        }


_COMPANY_NEWS_STALE_SECONDS = 30 * 60  # 30 min - less aggressive than 5 min


@mcp.tool()
async def get_company_news(
    symbol: str | None = None,
    symbols: list[str] | None = None,
    days: int = 30,
    limit: int = 50,
    refresh: bool = False,
    sentiment: str | None = None,
    threat_level: str | None = None,
    language: str | None = None,
) -> dict[str, Any]:
    """Fetch news for one or multiple NSE companies with NLP analysis.

    Automatically fetches fresh articles from MoneyControl when needed.
    Supports filtering by sentiment, threat level, and language (additive/OR logic).

    Args:
        symbol: NSE ticker symbol for a single lookup (e.g. "RELIANCE", "INFY").
            Mutually exclusive with symbols.
        symbols: List of NSE ticker symbols for a bulk lookup (e.g. ["RELIANCE", "INFY"]).
            Mutually exclusive with symbol.
        days: Number of days to look back (default: 30). Applies to all symbols.
        limit: Maximum number of articles to return per symbol (default: 50).
        refresh: Force a live fetch from MoneyControl even if articles are fresh (default: False).
        sentiment: Filter by sentiment (POSITIVE, NEGATIVE, NEUTRAL).
        threat_level: Filter by threat level (LOW, MEDIUM, HIGH, CRITICAL).
        language: Filter by two-letter language code (en, hi, zh, etc.).

    Returns a list of articles in single-symbol mode. In bulk mode returns a
    dict keyed by symbol; failed symbols return {"error": "<message>"}.
    """
    import json as _json

    from sqlalchemy import func, or_

    if symbol is None and symbols is None:
        raise ValueError("Provide either 'symbol' or 'symbols'")
    if symbol is not None and symbols is not None:
        raise ValueError("Provide either 'symbol' or 'symbols', not both")

    async def _fetch(sym: str) -> list[dict[str, Any]]:
        sym = sym.upper()
        start_date = datetime.now() - timedelta(days=days)

        async def _query_db(db) -> list[dict[str, Any]]:
            conditions = [
                NewsArticle.company_symbol == sym,
                or_(
                    NewsArticle.publish_date >= start_date,
                    NewsArticle.publish_date.is_(None),
                ),
            ]
            if sentiment:
                conditions.append(NewsArticle.sentiment == sentiment.upper())
            if threat_level:
                conditions.append(NewsArticle.threat_level == threat_level.upper())
            if language:
                conditions.append(NewsArticle.language == language.lower())

            stmt = (
                select(NewsArticle)
                .where(or_(*conditions) if conditions else True)
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
                    "sentiment": a.sentiment,
                    "sentiment_score": a.sentiment_score,
                    "confidence": a.confidence,
                    "language": a.language,
                    "entities": _safe_entities(a.entities),
                    "threat_level": a.threat_level,
                    "threat_category": a.threat_category,
                    "source_credibility": a.source_credibility,
                }
                for a in articles
            ]

        async def _latest_fetched_at(db) -> datetime | None:
            stmt = select(func.max(NewsArticle.fetched_at)).where(
                NewsArticle.company_symbol == sym
            )
            result = await db.execute(stmt)
            return result.scalar_one_or_none()

        async with AsyncSessionLocal() as db:
            existing = await _query_db(db)
            latest_fetched = await _latest_fetched_at(db)

        stale = True
        if latest_fetched is not None:
            age_seconds = (datetime.now() - latest_fetched).total_seconds()
            stale = age_seconds > _COMPANY_NEWS_STALE_SECONDS

        should_fetch = refresh or len(existing) == 0 or stale

        if should_fetch:
            logger.info(
                "get_company_news: fetching %s (stale=%s, existing=%d, refresh=%s)",
                sym,
                stale,
                len(existing),
                refresh,
            )
            try:
                async with AsyncSessionLocal() as db:
                    await asyncio.wait_for(
                        news_fetcher.fetch_company_news(symbol=sym, db=db),
                        timeout=25.0,
                    )
            except asyncio.TimeoutError:
                logger.warning("get_company_news: timeout for %s, returning stale cache", sym)
            async with AsyncSessionLocal() as db:
                return await _query_db(db)

        return existing

    if symbol is not None:
        return await _fetch(symbol)
    results = await asyncio.gather(*[_fetch(s) for s in symbols], return_exceptions=True)
    return {
        s.upper(): ({"error": str(r)} if isinstance(r, BaseException) else r)
        for s, r in zip(symbols, results)
    }


# ---------------------------------------------------------------------------
# Market Categories (Industries & Sectors) Endpoints
# ---------------------------------------------------------------------------


@mcp.tool()
async def list_industries() -> list[dict[str, Any]]:
    """List all NSE industries with market cap, PE ratio, advance/decline counts, and sentiment.

    Returns a list of industries sorted by name. Each industry includes:
    - category_type: "industry"
    - slug: URL-friendly identifier (e.g., "bank-private")
    - name: Display name (e.g., "Bank - Private")
    - url: Link to MoneyControl page
    - market_cap: Total market cap in Rs Cr
    - pe: Industry PE ratio
    - advance: Number of advancing stocks
    - decline: Number of declining stocks
    - sentiment: Market sentiment (Bullish, Bearish, Neutral, etc.)
    - earnings_yoy: Year-over-year earnings change %
    """
    async with AsyncSessionLocal() as db:
        stmt = (
            select(MarketCategory)
            .where(MarketCategory.category_type == "industry")
            .order_by(MarketCategory.name)
        )
        result = await db.execute(stmt)
        categories = result.scalars().all()
        return [
            {
                "category_type": c.category_type,
                "slug": c.slug,
                "name": c.name,
                "url": c.url,
                "market_cap": c.market_cap,
                "pe": c.pe,
                "advance": c.advance,
                "decline": c.decline,
                "sentiment": c.sentiment,
                "earnings_yoy": c.earnings_yoy,
                "last_updated": c.last_updated.isoformat() if c.last_updated else None,
            }
            for c in categories
        ]


@mcp.tool()
async def list_sectors() -> list[dict[str, Any]]:
    """List all NSE sectors with market cap, PE ratio, advance/decline counts, and sentiment.

    Returns a list of sectors sorted by name. Each sector includes:
    - category_type: "sector"
    - slug: URL-friendly identifier (e.g., "banks")
    - name: Display name (e.g., "Banks")
    - url: Link to MoneyControl page
    - market_cap: Total market cap in Rs Cr
    - pe: Sector PE ratio
    - advance: Number of advancing stocks
    - decline: Number of declining stocks
    - sentiment: Market sentiment (Bullish, Bearish, Neutral, etc.)
    - earnings_yoy: Year-over-year earnings change %
    """
    async with AsyncSessionLocal() as db:
        stmt = (
            select(MarketCategory)
            .where(MarketCategory.category_type == "sector")
            .order_by(MarketCategory.name)
        )
        result = await db.execute(stmt)
        categories = result.scalars().all()
        return [
            {
                "category_type": c.category_type,
                "slug": c.slug,
                "name": c.name,
                "url": c.url,
                "market_cap": c.market_cap,
                "pe": c.pe,
                "advance": c.advance,
                "decline": c.decline,
                "sentiment": c.sentiment,
                "earnings_yoy": c.earnings_yoy,
                "last_updated": c.last_updated.isoformat() if c.last_updated else None,
            }
            for c in categories
        ]


@mcp.tool()
async def get_industry_stocks(slug: str) -> list[dict[str, Any]]:
    """Fetch all NSE stocks in a given industry by slug, sorted by market cap descending.

    Args:
        slug: Industry slug identifier (e.g., "bank-private", "it-services-consulting").
              Use list_industries() to get valid slugs.

    Returns a list of stocks. Each stock includes:
    - symbol: Stock identifier (e.g., "HDF01")
    - company_name: Company name (e.g., "HDFC Bank")
    - exchange: Exchange (NSE/BSE)
    - curr_price: Current price in Rs
    - per_change: % change
    - market_cap: Market cap in Rs Cr
    - ttm_pe: Trailing 12-month PE
    - net_profit: Latest net profit in Rs Cr
    - net_profit_yoy: Net profit YOY %
    - tech_trend: Technical trend (Very Bullish, Bullish, Neutral, Bearish, Very Bearish)
    - mc_url: MoneyControl stock page URL
    - categories: List of categories the stock belongs to (both industries and sectors)
    """
    slug = slug.strip().lower()

    # First check if industry exists
    async with AsyncSessionLocal() as db:
        stmt = select(MarketCategory).where(
            MarketCategory.category_type == "industry", MarketCategory.slug == slug
        )
        result = await db.execute(stmt)
        category = result.scalar_one_or_none()

        if not category:
            raise ValueError(
                f"Industry '{slug}' not found. Use list_industries() to get valid slugs."
            )

    # Get all stocks and filter in Python
    async with AsyncSessionLocal() as db:
        stmt = select(MarketCategoryStock)
        result = await db.execute(stmt)
        all_stocks = result.scalars().all()

        stocks = [
            s
            for s in all_stocks
            if s.categories
            and any(
                c.get("type") == "industry" and c.get("slug") == slug
                for c in s.categories
            )
        ]

        # Sort by market cap descending
        stocks.sort(key=lambda x: x.market_cap or 0, reverse=True)

        return [
            {
                "symbol": s.symbol,
                "company_name": s.company_name,
                "exchange": s.exchange,
                "curr_price": s.curr_price,
                "per_change": s.per_change,
                "market_cap": s.market_cap,
                "ttm_pe": s.ttm_pe,
                "net_profit": s.net_profit,
                "net_profit_yoy": s.net_profit_yoy,
                "tech_trend": s.tech_trend,
                "mc_url": s.mc_url,
                "categories": s.categories,
                "last_updated": s.last_updated.isoformat() if s.last_updated else None,
            }
            for s in stocks
        ]


@mcp.tool()
async def get_sector_stocks(slug: str) -> list[dict[str, Any]]:
    """Fetch all NSE stocks in a given sector by slug, sorted by market cap descending.

    Args:
        slug: Sector slug identifier (e.g., "banks", "finance", "it-services").
              Use list_sectors() to get valid slugs.

    Returns a list of stocks. Each stock includes:
    - symbol: Stock identifier (e.g., "HDF01")
    - company_name: Company name (e.g., "HDFC Bank")
    - exchange: Exchange (NSE/BSE)
    - curr_price: Current price in Rs
    - per_change: % change
    - market_cap: Market cap in Rs Cr
    - ttm_pe: Trailing 12-month PE
    - net_profit: Latest net profit in Rs Cr
    - net_profit_yoy: Net profit YOY %
    - tech_trend: Technical trend (Very Bullish, Bullish, Neutral, Bearish, Very Bearish)
    - mc_url: MoneyControl stock page URL
    - categories: List of categories the stock belongs to (both industries and sectors)
    """
    slug = slug.strip().lower()

    # First check if sector exists
    async with AsyncSessionLocal() as db:
        stmt = select(MarketCategory).where(
            MarketCategory.category_type == "sector", MarketCategory.slug == slug
        )
        result = await db.execute(stmt)
        category = result.scalar_one_or_none()

        if not category:
            raise ValueError(
                f"Sector '{slug}' not found. Use list_sectors() to get valid slugs."
            )

    # Get all stocks and filter in Python
    async with AsyncSessionLocal() as db:
        stmt = select(MarketCategoryStock)
        result = await db.execute(stmt)
        all_stocks = result.scalars().all()

        stocks = [
            s
            for s in all_stocks
            if s.categories
            and any(
                c.get("type") == "sector" and c.get("slug") == slug
                for c in s.categories
            )
        ]

        # Sort by market cap descending
        stocks.sort(key=lambda x: x.market_cap or 0, reverse=True)

        return [
            {
                "symbol": s.symbol,
                "company_name": s.company_name,
                "exchange": s.exchange,
                "curr_price": s.curr_price,
                "per_change": s.per_change,
                "market_cap": s.market_cap,
                "ttm_pe": s.ttm_pe,
                "net_profit": s.net_profit,
                "net_profit_yoy": s.net_profit_yoy,
                "tech_trend": s.tech_trend,
                "mc_url": s.mc_url,
                "categories": s.categories,
                "last_updated": s.last_updated.isoformat() if s.last_updated else None,
            }
            for s in stocks
        ]
