"""
NSE India Client using direct HTTP calls for fetching and caching data from NSE India APIs.
"""

import logging
import time
from datetime import datetime
from typing import Any
import requests
from app.schemas.stockuniverse import StockUniverse

from app.services.helpers.json_to_csv import dict_to_csv_text
import nsepython
import pandas

logger = logging.getLogger(__name__)

ILLIQUID_SERIES = frozenset({"BE", "ST", "SM"})
SERIES_PREFERENCE = ["EQ", "BE", "ST", "SM", "T0"]


class SymbolNotFoundError(Exception):
    """Raised when a symbol cannot be found or has no tradeable data on NSE."""

    def __init__(self, symbol: str, reason: str = "not found") -> None:
        self.symbol = symbol
        self.reason = reason
        super().__init__(f"Symbol {symbol}: {reason}")


def _parse_nse_date(date_str: str | None) -> datetime | None:
    """Parse NSE date format like '16-Jul-2025 00:00:00' to datetime."""
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


class NSEClient:
    """NSE India client for fetching data from NSE India APIs with direct HTTP calls and session management."""

    _NSE_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.nseindia.com/",
        "Origin": "https://www.nseindia.com",
    }

    def __init__(self) -> None:
        self._session = requests.Session()
        self._session.headers.update(self._NSE_HEADERS)
        try:
            self._session.get("https://www.nseindia.com/option-chain", timeout=10)
        except Exception:
            pass

    def get_stock_list(self) -> list[str]:
        """Fetch the list of stocks from NSE India."""
        logger.debug("NSE: fetching equity symbols list")
        result = nsepython.nse_eq_symbols()
        logger.info("NSE: fetched %d equity symbols", len(result))
        return result

    def _get_metadata_for_series(self, symbol: str, series: str) -> dict[str, Any] | None:
        """Call getMetaData for a symbol/series and return the active series info, or None."""
        url = (
            "https://www.nseindia.com/api/NextApi/apiClient/GetQuoteApi"
            f"?functionName=getMetaData&marketType=N&series={series}&symbol={symbol}"
        )
        t0 = time.perf_counter()
        resp = self._session.get(url, timeout=20)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        logger.info("NSE GET %s → %d (%.0fms)", url, resp.status_code, elapsed_ms)
        resp.raise_for_status()
        payload = resp.json()
        if isinstance(payload, dict) and payload.get("activeSeries"):
            return payload
        return None

    def _fetch_symbol_data(self, symbol: str, series: str) -> dict[str, Any]:
        """Fetch getSymbolData for a symbol/series and return the parsed payload."""
        url = (
            "https://www.nseindia.com/api/NextApi/apiClient/GetQuoteApi"
            f"?functionName=getSymbolData&marketType=N&series={series}&symbol={symbol}"
        )
        t0 = time.perf_counter()
        resp = self._session.get(url, timeout=20)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        logger.info("NSE GET %s → %d (%.0fms)", url, resp.status_code, elapsed_ms)
        resp.raise_for_status()
        return resp.json()

    def _classify_and_fetch_symbol(self, symbol: str, fallback_series: str | None = None) -> tuple[StockUniverse, str] | None:
        """Try to fetch symbol data, classifying the failure reason.

        Returns (StockUniverse, series) on success, or None.
        Returns None with classification logged; does NOT raise.
        """
        discovered_series: str | None = None

        if fallback_series:
            ordered_series = [fallback_series] + [s for s in SERIES_PREFERENCE if s != fallback_series]
        else:
            ordered_series = SERIES_PREFERENCE[:]

        for series_candidate in ordered_series:
            meta = self._get_metadata_for_series(symbol, series_candidate)
            if meta is None:
                continue

            active = meta.get("activeSeries", [])
            if not active:
                active = [series_candidate]

            for series in active:
                if self._fetch_symbol_data(symbol, series).get("equityResponse"):
                    discovered_series = series
                    break
            else:
                continue
            break

        if discovered_series is None:
            return None

        payload = self._fetch_symbol_data(symbol, discovered_series)
        equity = payload.get("equityResponse", [])
        if not equity:
            return None

        temp = equity[0]
        price_info = temp.get("priceInfo", {})
        sec_info = temp.get("secInfo", {})
        meta = temp.get("metaData", {})

        tempdict: dict[str, Any] = {
            "symbol": meta.get("symbol"),
            "companyName": meta.get("companyName"),
            "segment": discovered_series,
            "industry": sec_info.get("basicIndustry"),
            "sectorPE": sec_info.get("pdSectorPe"),
            "symbolPE": sec_info.get("pdSymbolPe"),
            "industryInfo": {"description": sec_info.get("industryInfo") or ""},
            "lastUpdateTime": meta.get("lastUpdateTime"),
            "high_52w": price_info.get("yearHigh"),
            "low_52w": price_info.get("yearLow"),
            "high_52w_date": _parse_nse_date(price_info.get("yearHightDt")),
            "low_52w_date": _parse_nse_date(price_info.get("yearLowDt")),
            "series": discovered_series,
        }
        return (StockUniverse(**tempdict), discovered_series)

    def get_stock_metadata(self, symbol: str) -> StockUniverse:
        """Fetch metadata for a given stock symbol via GetQuoteApi.

        Auto-detects active series using getMetaData, then fetches data
        via getSymbolData. Series preference: EQ > BE > ST > SM > T0.
        Raises SymbolNotFoundError if the symbol cannot be found in any series.
        """
        result = self._classify_and_fetch_symbol(symbol)
        if result is None:
            raise SymbolNotFoundError(symbol, "no tradeable series found")
        stock_universe, _ = result
        return stock_universe

    def get_corporate_filing_comparison(self, symbol: str) -> str:
        """Fetch corporate filing comparison for `symbol`, convert to CSV, and return CSV text.

        DEPRECATED: Uses nsepython which produces data that is not useful.
        Remove this feature in a future update — no direct NSE API available.
        """
        logger.debug("NSE: fetching corporate filings for %s", symbol)
        try:
            data = nsepython.nse_past_results(symbol)
        except Exception:
            logger.exception("Failed to fetch past results for %s", symbol)
            raise

        # Convert JSON -> CSV using the in-memory helper and return CSV text
        try:
            csv_text = dict_to_csv_text(data)
            logger.debug("NSE: corporate filings for %s converted to CSV", symbol)
            return csv_text
        except Exception:
            logger.exception("Failed to convert past results for %s to CSV", symbol)
            raise

    def get_top_gainers(self) -> pandas.DataFrame:
        """Fetch the list of top gainers from NSE India."""
        logger.debug("NSE: fetching top gainers")
        try:
            rows = self._get_market_turnover(index="gainers")
            df = pandas.DataFrame(rows)
            # Prefer perChange (new API) over pChange (legacy); copy to pChange
            # so downstream consumers (notification worker, tests) keep working.
            if "perChange" in df.columns:
                df["pChange"] = pandas.to_numeric(df["perChange"], errors="coerce")
            elif "pChange" in df.columns:
                df["pChange"] = pandas.to_numeric(df["pChange"], errors="coerce")
            else:
                df["pChange"] = pandas.Series(dtype=float)
            df = df.dropna(subset=["pChange"]).sort_values("pChange", ascending=False).head(20)
            logger.info("NSE: top gainers fetched (%d rows)", len(df))
            return df
        except Exception:
            logger.exception("NSE: top gainers fetch failed")
            raise

    def get_top_losers(self) -> pandas.DataFrame:
        """Fetch the list of top losers from NSE India."""
        logger.debug("NSE: fetching top losers")
        try:
            rows = self._get_market_turnover(index="loosers")
            df = pandas.DataFrame(rows)
            if "perChange" in df.columns:
                df["pChange"] = pandas.to_numeric(df["perChange"], errors="coerce")
            elif "pChange" in df.columns:
                df["pChange"] = pandas.to_numeric(df["pChange"], errors="coerce")
            else:
                df["pChange"] = pandas.Series(dtype=float)
            df = df.dropna(subset=["pChange"]).sort_values("pChange", ascending=True).head(20)
            logger.info("NSE: top losers fetched (%d rows)", len(df))
            return df
        except Exception:
            logger.exception("NSE: top losers fetch failed")
            raise

    def check_bulk_deals(self, symbol: str) -> pandas.DataFrame:
        """Fetch the list of bulk deals from NSE India for a specific symbol."""
        logger.debug("NSE: fetching bulk deals for %s", symbol)
        try:
            snapshot = self.get_largedeal_snapshot()
        except Exception:
            logger.exception("NSE: bulk deals fetch failed for %s", symbol)
            raise

        rows = snapshot.get("BULK_DEALS_DATA", [])
        if not rows:
            return pandas.DataFrame()
        df = pandas.DataFrame(rows)
        if "symbol" in df.columns:
            df = df[df["symbol"].str.upper() == symbol.upper()]
        logger.debug("NSE: bulk deals for %s — %d matching rows", symbol, len(df))
        return df

    def check_block_deals(self, symbol: str) -> pandas.DataFrame:
        """Fetch the list of block deals from NSE India for a specific symbol."""
        logger.debug("NSE: fetching block deals for %s", symbol)
        try:
            snapshot = self.get_largedeal_snapshot()
        except Exception:
            logger.exception("NSE: block deals fetch failed for %s", symbol)
            raise

        rows = snapshot.get("BLOCK_DEALS_DATA", [])
        if not rows:
            return pandas.DataFrame()
        df = pandas.DataFrame(rows)
        if "symbol" in df.columns:
            df = df[df["symbol"].str.upper() == symbol.upper()]
        logger.debug("NSE: block deals for %s — %d matching rows", symbol, len(df))
        return df

    def get_high_short_interest(self) -> pandas.DataFrame:
        """Fetch the list of high short interest stocks from NSE India."""
        logger.debug("NSE: fetching high short interest stocks")
        try:
            snapshot = self.get_largedeal_snapshot()
        except Exception:
            logger.exception("NSE: high short interest fetch failed")
            raise

        rows = snapshot.get("SHORT_DEALS_DATA", [])
        if not rows:
            return pandas.DataFrame()
        df = pandas.DataFrame(rows)
        logger.info("NSE: high short interest fetched (%d rows)", len(df))
        return df

    def get_52week_low_stocks(self) -> dict:
        """Fetch 52-week low stocks snapshot from NSE India."""
        url = "https://www.nseindia.com/api/live-analysis-data-52weeklowstock"

        logger.debug("NSE GET %s", url)
        t0 = time.perf_counter()
        try:
            resp = self._session.get(url, timeout=20)
            elapsed_ms = (time.perf_counter() - t0) * 1000
            logger.info("NSE GET %s → %d (%.0fms)", url, resp.status_code, elapsed_ms)
            resp.raise_for_status()
        except Exception:
            logger.exception("NSE request failed: GET %s", url)
            raise

        payload = resp.json()
        if not isinstance(payload, dict) or "data" not in payload:
            raise ValueError(
                f"Unexpected response format from live-analysis-data-52weeklowstock: {payload!r}"
            )

        return payload

    def get_52week_high_stocks(self) -> dict:
        """Fetch 52-week high stocks snapshot from NSE India."""
        url = "https://www.nseindia.com/api/live-analysis-data-52weekhighstock"

        logger.debug("NSE GET %s", url)
        t0 = time.perf_counter()
        try:
            resp = self._session.get(url, timeout=20)
            elapsed_ms = (time.perf_counter() - t0) * 1000
            logger.info("NSE GET %s → %d (%.0fms)", url, resp.status_code, elapsed_ms)
            resp.raise_for_status()
        except Exception:
            logger.exception("NSE request failed: GET %s", url)
            raise

        payload = resp.json()
        if not isinstance(payload, dict) or "data" not in payload:
            raise ValueError(
                f"Unexpected response format from live-analysis-data-52weekhighstock: {payload!r}"
            )

        return payload

    def get_volume_gainers(self) -> dict:
        """Fetch volume gainers snapshot from NSE India."""
        url = "https://www.nseindia.com/api/live-analysis-volume-gainers"

        logger.debug("NSE GET %s", url)
        t0 = time.perf_counter()
        try:
            resp = self._session.get(url, timeout=20)
            elapsed_ms = (time.perf_counter() - t0) * 1000
            logger.info("NSE GET %s → %d (%.0fms)", url, resp.status_code, elapsed_ms)
            resp.raise_for_status()
        except Exception:
            logger.exception("NSE request failed: GET %s", url)
            raise

        payload = resp.json()
        if not isinstance(payload, dict) or "data" not in payload:
            raise ValueError(
                f"Unexpected response format from live-analysis-volume-gainers: {payload!r}"
            )

        return payload

    def _get_market_variations(self, index: str) -> dict:
        """Fetch the full live-analysis-variations payload for gainers or loosers.

        Args:
            index: 'gainers' or 'loosers' (NSE's misspelling).

        Returns the full parsed JSON: { legends, NIFTY: {data, timestamp},
        BANKNIFTY: {...}, ..., allSec: {data, timestamp} }.
        """
        url = f"https://www.nseindia.com/api/live-analysis-variations?index={index}&type=allSec"
        t0 = time.perf_counter()
        resp = self._session.get(url, timeout=20)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        logger.info("NSE GET %s → %d (%.0fms)", url, resp.status_code, elapsed_ms)
        resp.raise_for_status()
        payload = resp.json()
        if not isinstance(payload, dict) or "allSec" not in payload:
            raise ValueError(
                f"Unexpected response from live-analysis-variations?index={index}: "
                f"keys={list(payload.keys()) if isinstance(payload, dict) else type(payload)}"
            )
        return payload

    def _get_market_turnover(self, index: str = "gainers") -> list[dict]:
        """Fetch market turnover rows for top-gainers/losers.

        Uses the live-analysis-variations API with the requested index to get
        the allSec category data.

        Args:
            index: 'gainers' or 'loosers' (NSE's misspelling).

        Returns:
            list of row dicts, each containing symbol/series/perChange fields.
        """
        payload = self._get_market_variations(index)
        rows: list[dict] = payload["allSec"].get("data", [])
        if not rows:
            raise ValueError(f"No data in allSec category for {index}")
        return rows

    def get_largedeal_snapshot(self) -> dict:
        """Fetch the full largedeal snapshot (bulk/short/block) from NSE India.

        This wraps the documented `snapshot-capital-market-largedeal` endpoint and
        returns the parsed JSON payload as a Python dict. The payload typically
        contains keys:
          - as_on_date
          - BULK_DEALS_DATA
          - SHORT_DEALS_DATA
          - BLOCK_DEALS_DATA
        """

        url = "https://www.nseindia.com/api/snapshot-capital-market-largedeal"

        logger.debug("NSE GET %s", url)
        t0 = time.perf_counter()
        try:
            resp = self._session.get(url, timeout=20)
            elapsed_ms = (time.perf_counter() - t0) * 1000
            logger.info("NSE GET %s \u2192 %d (%.0fms)", url, resp.status_code, elapsed_ms)
            resp.raise_for_status()
        except Exception:
            logger.exception("NSE request failed: GET %s", url)
            raise

        payload = resp.json()
        if not isinstance(payload, dict):
            raise ValueError(
                f"Unexpected response format from snapshot-capital-market-largedeal: {payload!r}"
            )

        # Basic shape validation — keep it lenient to tolerate upstream changes.
        expected_keys = {
            "as_on_date",
            "BULK_DEALS_DATA",
            "SHORT_DEALS_DATA",
            "BLOCK_DEALS_DATA",
        }
        missing = [k for k in expected_keys if k not in payload]
        if missing:
            logger.warning(
                "NSE largedeal snapshot missing expected keys: %s", ", ".join(missing)
            )

        return payload

    def get_change_ranges(self, symbol: str) -> dict[str, float]:
        """Fetch percentage-change data for a symbol from NSE's getYearwiseData endpoint.

        Returns a dict with keys:
            oneDayPercent, oneWeekPercent, oneMonthPercent, threeMonthPercent,
            sixMonthPercent, oneYearPercent, twoYearPercent, threeYearPercent, fiveYearPercent
        """
        _NSE_FIELD_MAP = {
            "oneWeekPercent": "one_week_chng_per",
            "oneMonthPercent": "one_month_chng_per",
            "threeMonthPercent": "three_month_chng_per",
            "sixMonthPercent": "six_month_chng_per",
            "oneYearPercent": "one_year_chng_per",
            "twoYearPercent": "two_year_chng_per",
            "threeYearPercent": "three_year_chng_per",
            "fiveYearPercent": "five_year_chng_per",
        }

        url = (
            "https://www.nseindia.com/api/NextApi/apiClient/GetQuoteApi"
            f"?functionName=getYearwiseData&symbol={symbol}EQN"
        )

        logger.debug("NSE GET %s", url)
        t0 = time.perf_counter()
        try:
            resp = self._session.get(url, timeout=20)
            elapsed_ms = (time.perf_counter() - t0) * 1000
            logger.info("NSE GET %s → %d (%.0fms)", url, resp.status_code, elapsed_ms)
            resp.raise_for_status()
        except Exception:
            logger.exception("NSE request failed: GET %s", url)
            raise

        payload = resp.json()
        if not isinstance(payload, list) or len(payload) == 0:
            logger.warning(
                "getYearwiseData for %s returned empty payload: %r — returning NaN values",
                symbol,
                payload,
            )
            return {k: float("nan") for k in _NSE_FIELD_MAP}

        row = payload[0]
        result: dict[str, float] = {}
        for out_key, nse_key in _NSE_FIELD_MAP.items():
            raw = row.get(nse_key)
            if raw is None:
                result[out_key] = float("nan")
            else:
                try:
                    result[out_key] = float(raw)
                except (TypeError, ValueError):
                    result[out_key] = float("nan")

        return result

    def get_symbol_data(
        self, symbol: str, market_type: str = "N", series: str = "EQ"
    ) -> dict:
        """Fetch symbol data from NSE's GetQuoteApi getSymbolData endpoint.

        Example URL:
        https://www.nseindia.com/api/NextApi/apiClient/GetQuoteApi?functionName=getSymbolData&marketType=N&series=EQ&symbol=HDFCBANK

        Returns the parsed JSON payload as a Python dict. Raises on non-200 responses
        or unexpected payload types.
        """

        url = (
            "https://www.nseindia.com/api/NextApi/apiClient/GetQuoteApi"
            f"?functionName=getSymbolData&marketType={market_type}&series={series}&symbol={symbol}"
        )

        logger.debug("NSE GET %s", url)
        t0 = time.perf_counter()
        try:
            resp = self._session.get(url, timeout=20)
            elapsed_ms = (time.perf_counter() - t0) * 1000
            logger.info("NSE GET %s → %d (%.0fms)", url, resp.status_code, elapsed_ms)
            resp.raise_for_status()
        except Exception:
            logger.exception("NSE request failed: GET %s", url)
            raise

        payload = resp.json()
        if not isinstance(payload, dict):
            # Some NSE endpoints return lists; ensure we return a dict for callers.
            raise ValueError(
                f"Unexpected response format from getSymbolData for {symbol}: {payload!r}"
            )

        return payload

    async def close(self) -> None:
        """No-op teardown hook (kept for lifespan compatibility)."""


# Module-level singleton — import this in routers / services
nse_client = NSEClient()
