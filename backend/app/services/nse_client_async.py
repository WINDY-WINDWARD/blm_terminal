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


class NSEClientAsync:
    """
    Async NSE client with proper instance state.

    Use as a singleton:
        nse_client = NSEClientAsync()
        data = await nse_client.get_52week_high_stocks()
    """

    def __init__(self) -> None:
        self._http: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Lazily create the persistent httpx client with NSE cookie warmup."""
        if self._http is None:
            self._http = httpx.AsyncClient(
                base_url=NSE_BASE_URL,
                headers=NSE_HEADERS,
                timeout=httpx.Timeout(20.0, connect=10.0),
                follow_redirects=True,
                limits=httpx.Limits(
                    max_connections=10,
                    max_keepalive_connections=5,
                    keepalive_expiry=30.0,
                ),
            )
            logger.info("NSEClientAsync: creating httpx client — warming cookie session")
            try:
                await self._http.get("/option-chain")
                logger.info("NSEClientAsync: cookie session warmed successfully")
            except Exception as exc:
                logger.warning("NSEClientAsync: cookie warmup failed: %s", exc)

        return self._http

    async def close(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

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
