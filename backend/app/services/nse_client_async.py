"""
Async NSE India client — replaces nsepython with direct httpx calls.

All methods are async. No requests.Session, no nsepython, no to_thread().
Uses a shared httpx.AsyncClient with connection pooling.

For infrequently-used methods (stock list, metadata, corporate filings),
sync stubs via nsepython are kept as fallback. The critical path methods
(top_gainers, top_losers, bulk/block deals, etc.) are fully async.

Design: proper class with instance state. Self._http is created lazily
on first use and reused for all subsequent requests within the process.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from typing import Any

import httpx
import numpy as np
import pandas as pd

from app.schemas.stockuniverse import StockUniverse

logger = logging.getLogger(__name__)

ILLIQUID_SERIES = frozenset({"BE", "ST", "SM"})
SERIES_PREFERENCE = ["EQ", "BE", "ST", "SM", "T0"]


class SymbolNotFoundError(Exception):
    """Raised when a symbol cannot be found or has no tradeable data on NSE."""

    def __init__(self, symbol: str, reason: str = "not found") -> None:
        self.symbol = symbol
        self.reason = reason
        super().__init__(f"Symbol {symbol}: {reason}")

NSE_BASE_URL = "https://www.nseindia.com"
NSE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
    "Origin": "https://www.nseindia.com",
}

NSE_FIELD_MAP_CHANGE_RANGES: dict[str, str] = {
    "oneWeekPercent": "one_week_chng_per",
    "oneMonthPercent": "one_month_chng_per",
    "threeMonthPercent": "three_month_chng_per",
    "sixMonthPercent": "six_month_chng_per",
    "oneYearPercent": "one_year_chng_per",
    "twoYearPercent": "two_year_chng_per",
    "threeYearPercent": "three_year_chng_per",
    "fiveYearPercent": "five_year_chng_per",
}

#: NSE reports total market capitalisation in **rupees**;
#: the warehouse stores it in **Rs Cr**.
_INR_PER_CR = 1e7


def mcap_cr_from_trade_info(trade_info: dict[str, Any] | None) -> float | None:
    """Extract market cap in Rs Cr from a getSymbolData ``tradeInfo`` block.

    Returns None when the block is missing or ``totalMarketCap`` is absent
    / non-positive (e.g. suspended series) so callers never clobber a
    previously stored value with NULL.
    """
    if not isinstance(trade_info, dict):
        return None
    try:
        raw = float(trade_info.get("totalMarketCap"))
    except (TypeError, ValueError):
        return None
    if raw <= 0:
        return None
    return raw / _INR_PER_CR


class NSEClientAsync:
    """
    Async NSE client with proper instance state.

    Use as a singleton:
        nse_client = NSEClientAsync()
        data = await nse_client.get_52week_high_stocks()
    """

    def __init__(self) -> None:
        self._http_clients: dict[int, tuple[asyncio.AbstractEventLoop, httpx.AsyncClient]] = {}

    async def _get_client(self) -> httpx.AsyncClient:
        """Lazily create the persistent httpx client per event loop.

        Detects event loop changes and maintains a separate client per loop
        to avoid using a stale client bound to a different (possibly closed)
        event loop. Proactively removes clients for closed loops to prevent memory leaks.
        """
        current_loop = asyncio.get_running_loop()
        loop_id = id(current_loop)

        # Proactively clean up closed loops
        stale_ids = []
        for lid, (loop, client) in list(self._http_clients.items()):
            if loop.is_closed():
                stale_ids.append(lid)
        
        for lid in stale_ids:
            del self._http_clients[lid]

        if loop_id not in self._http_clients:
            self._http_clients[loop_id] = (
                current_loop,
                httpx.AsyncClient(
                    base_url=NSE_BASE_URL,
                    headers=NSE_HEADERS,
                    timeout=httpx.Timeout(30.0, connect=15.0),
                    follow_redirects=True,
                    limits=httpx.Limits(
                        max_connections=40,
                        max_keepalive_connections=20,
                        keepalive_expiry=30.0,
                    ),
                )
            )

        return self._http_clients[loop_id][1]

    async def close(self) -> None:
        for loop, client in self._http_clients.values():
            if not loop.is_closed():
                await client.aclose()
        self._http_clients.clear()

    def _clean_df(self, df: pd.DataFrame) -> pd.DataFrame:
        return df.replace({np.nan: None, pd.NA: None})

    async def _nse_get(self, url: str) -> dict[str, Any] | list[dict[str, Any]]:
        """Perform an NSE GET request and return parsed JSON."""
        client = await self._get_client()
        t0 = time.perf_counter()
        resp = await client.get(url)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        logger.info("NSE GET %s → %d (%.0fms)", url, resp.status_code, elapsed_ms)
        resp.raise_for_status()
        return resp.json()

    async def get_52week_low_stocks(self) -> dict[str, Any]:
        url = "https://www.nseindia.com/api/live-analysis-data-52weeklowstock"
        payload: dict[str, Any] = await self._nse_get(url)
        if not isinstance(payload, dict) or "data" not in payload:
            raise ValueError(f"Unexpected 52week-low response: {payload!r}")
        return payload

    async def get_52week_high_stocks(self) -> dict[str, Any]:
        url = "https://www.nseindia.com/api/live-analysis-data-52weekhighstock"
        payload: dict[str, Any] = await self._nse_get(url)
        if not isinstance(payload, dict) or "data" not in payload:
            raise ValueError(f"Unexpected 52week-high response: {payload!r}")
        return payload

    async def get_volume_gainers(self) -> dict[str, Any]:
        url = "https://www.nseindia.com/api/live-analysis-volume-gainers"
        payload: dict[str, Any] = await self._nse_get(url)
        if not isinstance(payload, dict) or "data" not in payload:
            raise ValueError(f"Unexpected volume-gainers response: {payload!r}")
        return payload

    async def get_largedeal_snapshot(self) -> dict[str, Any]:
        """Fetch bulk/block/short deals in a single NSE API call."""
        url = "https://www.nseindia.com/api/snapshot-capital-market-largedeal"
        payload: dict[str, Any] = await self._nse_get(url)

        expected_keys = {"as_on_date", "BULK_DEALS_DATA", "SHORT_DEALS_DATA", "BLOCK_DEALS_DATA"}
        missing = [k for k in expected_keys if k not in payload]
        if missing:
            logger.warning("Largedeal snapshot missing keys: %s", ", ".join(missing))
        return payload

    async def get_market_variations(self, index: str) -> dict[str, Any]:
        """Fetch the full live-analysis-variations payload for gainers or loosers.

        Args:
            index: 'gainers' or 'loosers' (NSE's misspelling).

        Returns the full parsed JSON: { legends, NIFTY: {data, timestamp},
        BANKNIFTY: {...}, ..., allSec: {data, timestamp} }.
        """
        url = f"https://www.nseindia.com/api/live-analysis-variations?index={index}&type=allSec"
        payload: dict[str, Any] = await self._nse_get(url)
        if not isinstance(payload, dict) or "allSec" not in payload:
            raise ValueError(
                f"Unexpected response from live-analysis-variations?index={index}: "
                f"keys={list(payload.keys()) if isinstance(payload, dict) else type(payload)}"
            )
        return payload

    async def _get_market_turnover(self) -> list[dict[str, Any]]:
        """Fetch the raw market turnover payload from NSE.

        Used by both get_top_gainers and get_top_losers to avoid firing
        two separate HTTP calls to the same endpoint. Callers must cache
        the result upstream so both endpoints share one NSE call when
        invoked simultaneously.
        """
        url = "https://www.nseindia.com/api/live-analysis-market-turnover"
        payload: dict[str, Any] = await self._nse_get(url)
        rows: list[dict[str, Any]] = payload.get("data", [])
        if not rows:
            raise ValueError("No data in market turnover response")
        return rows

    async def get_top_gainers(self) -> pd.DataFrame:
        """Fetch today's top-gaining equities on NSE India."""
        try:
            rows = await self._get_market_turnover()
            df = pd.DataFrame(rows)
            if "symbol" not in df.columns or "pChange" not in df.columns:
                raise ValueError(f"Unexpected columns: {df.columns.tolist()}")

            df_eq = df[df["series"] == "EQ"].copy()
            df_eq["pChange"] = pd.to_numeric(df_eq["pChange"], errors="coerce")
            df_eq = df_eq.dropna(subset=["pChange"])
            df_eq = df_eq.sort_values("pChange", ascending=False).head(20)

            logger.info("NSE top gainers: %d rows from market turnover", len(df_eq))
            return self._clean_df(df_eq)

        except Exception as exc:
            logger.warning("Market turnover JSON failed (%s), falling back to nsepython", exc)
            import nsepython
            return await asyncio.to_thread(nsepython.nse_get_top_gainers)

    async def get_top_losers(self) -> pd.DataFrame:
        """Fetch today's top-losing equities on NSE India."""
        try:
            rows = await self._get_market_turnover()
            df = pd.DataFrame(rows)
            if "symbol" not in df.columns or "pChange" not in df.columns:
                raise ValueError(f"Unexpected columns: {df.columns.tolist()}")

            df_eq = df[df["series"] == "EQ"].copy()
            df_eq["pChange"] = pd.to_numeric(df_eq["pChange"], errors="coerce")
            df_eq = df_eq.dropna(subset=["pChange"])
            df_eq = df_eq.sort_values("pChange", ascending=True).head(20)

            logger.info("NSE top losers: %d rows from market turnover", len(df_eq))
            return self._clean_df(df_eq)

        except Exception as exc:
            logger.warning("Market turnover JSON failed (%s), falling back to nsepython", exc)
            import nsepython
            return await asyncio.to_thread(nsepython.nse_get_top_losers)

    async def check_bulk_deals(self, symbol: str) -> pd.DataFrame:
        raise NotImplementedError(
            "check_bulk_deals must be called with a pre-fetched snapshot. "
            "Use _bulk_deals_from_snapshot() for the parsing logic."
        )

    async def check_block_deals(self, symbol: str) -> pd.DataFrame:
        raise NotImplementedError(
            "check_block_deals must be called with a pre-fetched snapshot. "
            "Use _block_deals_from_snapshot() for the parsing logic."
        )

    async def get_high_short_interest(self) -> pd.DataFrame:
        raise NotImplementedError(
            "get_high_short_interest must be called with a pre-fetched snapshot. "
            "Use _short_interest_from_snapshot() for the parsing logic."
        )

    def _bulk_deals_from_snapshot(self, symbol: str, snapshot: dict) -> pd.DataFrame:
        rows = snapshot.get("BULK_DEALS_DATA", [])
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows)
        if "symbol" in df.columns:
            df = df[df["symbol"].str.upper() == symbol.upper()]
        logger.debug("Bulk deals for %s — %d matching rows", symbol, len(df))
        return self._clean_df(df)

    def _block_deals_from_snapshot(self, symbol: str, snapshot: dict) -> pd.DataFrame:
        rows = snapshot.get("BLOCK_DEALS_DATA", [])
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows)
        if "symbol" in df.columns:
            df = df[df["symbol"].str.upper() == symbol.upper()]
        logger.debug("Block deals for %s — %d matching rows", symbol, len(df))
        return self._clean_df(df)

    def _short_interest_from_snapshot(self, snapshot: dict) -> pd.DataFrame:
        rows = snapshot.get("SHORT_DEALS_DATA", [])
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows)
        logger.info("High short interest: %d rows", len(df))
        return self._clean_df(df)

    async def get_change_ranges(self, symbol: str) -> dict[str, float]:
        url = (
            "https://www.nseindia.com/api/NextApi/apiClient/GetQuoteApi"
            f"?functionName=getYearwiseData&symbol={symbol}EQN"
        )
        payload: list[dict[str, Any]] = await self._nse_get(url)
        if not isinstance(payload, list) or len(payload) == 0:
            raise ValueError(f"Unexpected getYearwiseData response for {symbol}: {payload!r}")

        row = payload[0]
        result: dict[str, float] = {}
        for out_key, nse_key in NSE_FIELD_MAP_CHANGE_RANGES.items():
            raw = row.get(nse_key)
            if raw is None:
                result[out_key] = float("nan")
            else:
                try:
                    result[out_key] = float(raw)
                except (TypeError, ValueError):
                    result[out_key] = float("nan")
        return result

    async def get_symbol_data(self, symbol: str) -> dict[str, Any]:
        url = (
            "https://www.nseindia.com/api/NextApi/apiClient/GetQuoteApi"
            f"?functionName=getSymbolData&marketType=N&series=EQ&symbol={symbol}"
        )
        payload: dict[str, Any] = await self._nse_get(url)
        if not isinstance(payload, dict):
            raise ValueError(f"Unexpected getSymbolData response for {symbol}: {payload!r}")
        return payload

    def get_stock_list(self) -> list[str]:
        raise NotImplementedError(
            "get_stock_list() has no direct NSE API and nsepython is no longer used. "
            "Maintain a static symbol list or fetch from an alternate source."
        )

    async def get_isin_for_symbol(self, symbol: str) -> tuple[str, str] | None:
        """Fetch just the ISIN + companyName for a symbol via GetQuoteApi.

        Returns (isin, companyName) on success, None on failure. Lightweight:
        one HTTP call to getMetaData. This is the source of truth for NSE
        symbols and is the most reliable way to resolve a symbol to its
        iinvest path slug (replaces the iinvest /api/v1/marketdata/symbollookup
        endpoint which returns wrong ISINs for short symbols like RELIANCE).
        """
        from app.services.nse_client_async import SymbolNotFoundError
        symbol_upper = symbol.upper()
        for series_candidate in SERIES_PREFERENCE:
            meta_url = (
                "https://www.nseindia.com/api/NextApi/apiClient/GetQuoteApi"
                f"?functionName=getMetaData&marketType=N&series={series_candidate}&symbol={symbol_upper}"
            )
            try:
                client = await self._get_client()
                resp = await client.get(meta_url)
                resp.raise_for_status()
            except Exception:
                continue
            payload = resp.json()
            if not isinstance(payload, dict) or not payload.get("activeSeries"):
                continue
            isin = payload.get("isin")
            company_name = payload.get("companyName")
            if isin and company_name:
                return isin, company_name
        return None

    async def get_stock_metadata(self, symbol: str) -> StockUniverse:
        """Fetch metadata for a given stock symbol via GetQuoteApi.

        Auto-detects active series using getMetaData, then fetches data
        via getSymbolData. Series preference: EQ > BE > ST > SM > T0.
        Raises SymbolNotFoundError if the symbol cannot be found in any series.
        """
        from app.schemas.stockuniverse import StockUniverse

        for series_candidate in SERIES_PREFERENCE:
            meta_url = (
                "https://www.nseindia.com/api/NextApi/apiClient/GetQuoteApi"
                f"?functionName=getMetaData&marketType=N&series={series_candidate}&symbol={symbol}"
            )
            t0 = time.perf_counter()
            try:
                client = await self._get_client()
                resp = await client.get(meta_url)
                elapsed_ms = (time.perf_counter() - t0) * 1000
                logger.info("NSE GET %s → %d (%.0fms)", meta_url, resp.status_code, elapsed_ms)
                resp.raise_for_status()
            except Exception:
                logger.debug("NSE: getMetaData failed for %s series=%s", symbol, series_candidate)
                continue

            meta_payload = resp.json()
            if not isinstance(meta_payload, dict) or not meta_payload.get("activeSeries"):
                continue

            active_series = meta_payload.get("activeSeries", [])
            for active_s in active_series:
                data_url = (
                    "https://www.nseindia.com/api/NextApi/apiClient/GetQuoteApi"
                    f"?functionName=getSymbolData&marketType=N&series={active_s}&symbol={symbol}"
                )
                t0 = time.perf_counter()
                resp2 = await client.get(data_url)
                elapsed_ms = (time.perf_counter() - t0) * 1000
                logger.info("NSE GET %s → %d (%.0fms)", data_url, resp2.status_code, elapsed_ms)
                resp2.raise_for_status()
                payload = resp2.json()

                if isinstance(payload, dict) and payload.get("equityResponse"):
                    equity = payload["equityResponse"]
                    if equity:
                        temp = equity[0]
                        price_info = temp.get("priceInfo", {})
                        sec_info = temp.get("secInfo", {})
                        meta = temp.get("metaData", {})
                        trade_info = temp.get("tradeInfo", {})

                        def _parse_date(date_str: str | None) -> datetime | None:
                            if not date_str or date_str == "-":
                                return None
                            try:
                                return datetime.strptime(date_str, "%d-%b-%Y %H:%M:%S")
                            except ValueError:
                                try:
                                    return datetime.strptime(date_str, "%d-%b-%Y")
                                except ValueError:
                                    logger.debug("Failed to parse date: %s", date_str)
                                    return None

                        tempdict: dict[str, Any] = {
                            "symbol": meta.get("symbol"),
                            "companyName": meta.get("companyName"),
                            "segment": active_s,
                            "industry": sec_info.get("basicIndustry"),
                            "sectorPE": sec_info.get("pdSectorPe"),
                            "symbolPE": sec_info.get("pdSymbolPe"),
                            "industryInfo": {"description": sec_info.get("industryInfo") or ""},
                            "lastUpdateTime": meta.get("lastUpdateTime"),
                            "high_52w": price_info.get("yearHigh"),
                            "low_52w": price_info.get("yearLow"),
                            "high_52w_date": _parse_date(price_info.get("yearHightDt")),
                            "low_52w_date": _parse_date(price_info.get("yearLowDt")),
                            "series": active_s,
                            "isin": meta_payload.get("isin") or meta.get("isin"),
                            "market_cap_cr": mcap_cr_from_trade_info(trade_info),
                        }
                        logger.debug("NSE: metadata fetched for %s", symbol)
                        return StockUniverse(**tempdict)

        raise SymbolNotFoundError(symbol, "no tradeable series found")

    def get_corporate_filing_comparison(self, symbol: str) -> str:
        """DEPRECATED: Uses nsepython which produces data that is not useful.
        Remove this feature in a future update — no direct NSE API available.
        """
        from app.services.helpers.json_to_csv import dict_to_csv_text
        import nsepython
        data = nsepython.nse_past_results(symbol)
        return dict_to_csv_text(data)


nse_client_async = NSEClientAsync()


# ─── Sync facade (audit B.10) ────────────────────────────────────────────────
#
# The legacy ``app.services.nse_client`` module held a 545-LOC sync ``NSEClient``
# class that duplicated the HTTP / parsing logic in this file.  Drift between
# the two was a top audit finding.
#
# The single source of truth for NSE behaviour is now ``NSEClientAsync`` above.
# This ``NSEClient`` class is a thin sync-compatible facade that delegates
# every method to the async client via ``asyncio.run()``.  It exists so the
# 8 call sites in routers / orchestrator / backgroundtasks / mcp_server that
# historically imported the sync class keep working without a behaviour
# change in the call site itself.
#
# Behavioural note: a few methods had divergent implementations between the
# old sync class and the async class (e.g. ``get_top_gainers`` previously
# copied ``perChange`` into ``pChange``; the async path filters to ``EQ``
# series only and falls back to ``nsepython``).  The facade always uses
# the async implementation, so any caller that depended on the OLD sync
# behaviour will see the (more correct) async behaviour.  This is the
# intentional outcome of the "drift-proof" audit goal.


def _run_async_from_sync(coro):
    """Run an async coroutine from sync code with the right strategy.

    - If the calling thread has a registered event loop (daemon worker via
      ``_run_async``), use it.
    - Otherwise, create a new event loop with ``asyncio.run`` (FastAPI sync
      path, one-off scripts).
    """
    from app.backgroundtasks._runtime import _run_async
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass  # no running loop — safe to use _run_async or asyncio.run
    else:
        raise RuntimeError(
            "Cannot use sync NSEClient facade from within an async context. "
            "Use `await nse_client_async.method()` instead."
        )
    
    # We always use _run_async because it natively falls back to 
    # creating a per-thread event loop if none exists.
    return _run_async(coro)


class NSEClient:
    """Sync-compatible facade over :class:`NSEClientAsync` (audit B.10).

    Every method that requires an event loop runs the corresponding async
    method via :func:`asyncio.run` (a fresh event loop is created per
    call).  The overhead is ~1-10ms, which is negligible against the
    100ms-2s NSE HTTP latency.

    Sync-only methods (``get_stock_list``, ``get_corporate_filing_comparison``)
    delegate without ``asyncio.run`` because they don't use the async
    httpx client.
    """

    def __init__(self) -> None:
        self._async = NSEClientAsync()

    def get_stock_list(self) -> list[str]:
        """Sync — delegates to ``NSEClientAsync.get_stock_list``.

        Returns the NSE equity symbol list.  The async client raises
        ``NotImplementedError`` here (it expects an upstream source);
        this facade falls back to ``nsepython.nse_eq_symbols()`` to
        preserve the pre-refactor behaviour.
        """
        try:
            return self._async.get_stock_list()
        except NotImplementedError:
            import nsepython
            return nsepython.nse_eq_symbols()

    def get_stock_metadata(self, symbol: str) -> Any:
        return _run_async_from_sync(self._async.get_stock_metadata(symbol))

    def get_corporate_filing_comparison(self, symbol: str) -> str:
        """Sync — delegates to ``NSEClientAsync.get_corporate_filing_comparison``."""
        return self._async.get_corporate_filing_comparison(symbol)

    def get_top_gainers(self) -> "pd.DataFrame":
        return _run_async_from_sync(self._async.get_top_gainers())

    def get_top_losers(self) -> "pd.DataFrame":
        return _run_async_from_sync(self._async.get_top_losers())

    def check_bulk_deals(self, symbol: str) -> "pd.DataFrame":
        return _run_async_from_sync(self._async.check_bulk_deals(symbol))

    def check_block_deals(self, symbol: str) -> "pd.DataFrame":
        return _run_async_from_sync(self._async.check_block_deals(symbol))

    def get_high_short_interest(self) -> "pd.DataFrame":
        return _run_async_from_sync(self._async.get_high_short_interest())

    def get_52week_low_stocks(self) -> dict:
        return _run_async_from_sync(self._async.get_52week_low_stocks())

    def get_52week_high_stocks(self) -> dict:
        return _run_async_from_sync(self._async.get_52week_high_stocks())

    def get_volume_gainers(self) -> dict:
        return _run_async_from_sync(self._async.get_volume_gainers())

    def get_largedeal_snapshot(self) -> dict:
        return _run_async_from_sync(self._async.get_largedeal_snapshot())

    def get_market_variations(self, index: str) -> dict[str, Any]:
        return _run_async_from_sync(self._async.get_market_variations(index))

    def get_change_ranges(self, symbol: str) -> dict[str, float]:
        return _run_async_from_sync(self._async.get_change_ranges(symbol))

    def get_symbol_data(self, symbol: str) -> dict[str, Any]:
        return _run_async_from_sync(self._async.get_symbol_data(symbol))

    async def close(self) -> None:
        """Async close (mirrors the legacy ``NSEClient.close`` signature)."""
        await self._async.close()


nse_client = NSEClient()
