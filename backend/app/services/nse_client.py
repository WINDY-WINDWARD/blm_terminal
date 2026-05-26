"""
NSE India Client using nsepython library for fetching and caching data from NSE India APIs.
"""

import asyncio
import logging
import time
from datetime import datetime
import requests
import nsepython
from app.schemas.stockuniverse import StockUniverse

from app.services.helpers.json_to_csv import dict_to_csv_text
import pandas

logger = logging.getLogger(__name__)


def _parse_nse_date(date_str: str | None) -> datetime | None:
    """Parse NSE date format like '05-Jan-2026' to datetime."""
    if not date_str or date_str == '-':
        return None
    try:
        return datetime.strptime(date_str, "%d-%b-%Y")
    except ValueError:
        logger.debug("Failed to parse date: %s", date_str)
        return None


class NSEClient:
    """Singleton async client nsepython library for fetching data from NSE India APIs with built-in caching and session management."""

    _NSE_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json",
        "Referer": "https://www.nseindia.com/",
    }

    def __init__(self) -> None:
        self._session = requests.Session()
        self._session.headers.update(self._NSE_HEADERS)
        # Warm up cookies on first instantiation; ignore errors
        try:
            self._session.get("https://www.nseindia.com/", timeout=10)
        except Exception:
            pass

    def get_stock_list(self) -> list[str]:
        """Fetch the list of stocks from NSE India."""
        logger.debug("NSE: fetching equity symbols list")
        result = nsepython.nse_eq_symbols()
        logger.info("NSE: fetched %d equity symbols", len(result))
        return result

    def get_stock_metadata(self, symbol: str) -> StockUniverse:
        """Fetch metadata for a given stock symbol."""
        logger.debug("NSE: fetching metadata for %s", symbol)
        try:
            temp = nsepython.nse_eq(symbol)
        except requests.exceptions.RequestException as e:
            logger.warning("NSE: metadata fetch failed for %s: %s", symbol, e)
            raise
        except Exception:
            logger.exception("NSE: metadata fetch failed for %s", symbol)
            raise

        week_high_low = temp.get("priceInfo", {}).get("weekHighLow", {})

        tempdict = {
            "symbol": temp["info"]["symbol"],
            "companyName": temp["info"]["companyName"],
            "segment": temp["info"]["segment"],
            "industry": temp["metadata"]["industry"],
            "sectorPE": temp["metadata"]["pdSectorPe"],
            "symbolPE": temp["metadata"]["pdSymbolPe"],
            "industryInfo": temp["industryInfo"],
            "lastUpdateTime": temp["metadata"]["lastUpdateTime"],
            "high_52w": week_high_low.get("max"),
            "low_52w": week_high_low.get("min"),
            "high_52w_date": _parse_nse_date(week_high_low.get("maxDate")),
            "low_52w_date": _parse_nse_date(week_high_low.get("minDate")),
        }
        logger.debug("NSE: metadata fetched for %s", symbol)
        return StockUniverse(**tempdict)

    def get_corporate_filing_comparison(self, symbol: str) -> str:
        """Fetch corporate filing comparison for `symbol`, convert to CSV, and return CSV text."""
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
            rows = self._get_market_turnover()
            df = pandas.DataFrame(rows)
            if "perChange" in df.columns and "pChange" not in df.columns:
                df["pChange"] = pandas.to_numeric(df["perChange"], errors="coerce")
            df["pChange"] = pandas.to_numeric(df.get("pChange", pandas.Series(dtype=float)), errors="coerce")
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
            rows = self._get_market_turnover()
            df = pandas.DataFrame(rows)
            if "perChange" in df.columns and "pChange" not in df.columns:
                df["pChange"] = pandas.to_numeric(df["perChange"], errors="coerce")
            df["pChange"] = pandas.to_numeric(df.get("pChange", pandas.Series(dtype=float)), errors="coerce")
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
            df = nsepython.nse_largedeals("bulk_deals")
        except Exception:
            logger.exception("NSE: bulk deals fetch failed for %s", symbol)
            raise
        filtered_df = df[df["symbol"].str.upper() == symbol.upper()]
        logger.debug(
            "NSE: bulk deals for %s — %d matching rows", symbol, len(filtered_df)
        )
        return filtered_df

    def check_block_deals(self, symbol: str) -> pandas.DataFrame:
        """Fetch the list of block deals from NSE India for a specific symbol."""
        logger.debug("NSE: fetching block deals for %s", symbol)
        try:
            df = nsepython.nse_largedeals("block_deals")
        except Exception:
            logger.exception("NSE: block deals fetch failed for %s", symbol)
            raise
        filtered_df = df[df["symbol"].str.upper() == symbol.upper()]
        logger.debug(
            "NSE: block deals for %s — %d matching rows", symbol, len(filtered_df)
        )
        return filtered_df

    def get_high_short_interest(self) -> pandas.DataFrame:
        """Fetch the list of high short interest stocks from NSE India."""
        logger.debug("NSE: fetching high short interest stocks")
        try:
            df = nsepython.nse_largedeals("short_deals")
            logger.info("NSE: high short interest fetched (%d rows)", len(df))
            return df
        except Exception:
            logger.exception("NSE: high short interest fetch failed")
            raise

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

    def _get_market_turnover(self) -> list[dict]:
        """Fetch market turnover rows for top-gainers/losers.

        Uses the live-analysis-variations API (gainers index) to get the allSec
        category data. Falls back to the loosers index on failure.

        Returns:
            list of row dicts, each containing symbol/series/perChange fields.
        """
        try:
            payload = self._get_market_variations("gainers")
            rows: list[dict] = payload["allSec"].get("data", [])
            if not rows:
                raise ValueError("No data in allSec category for gainers")
            return rows
        except Exception as exc:
            logger.warning(
                "variations-gainers failed (%s), falling back to loosers index",
                exc,
            )
            payload = self._get_market_variations("loosers")
            rows: list[dict] = payload["allSec"].get("data", [])
            if not rows:
                raise ValueError("No data in allSec category for loosers")
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
            raise ValueError(
                f"Unexpected response format from getYearwiseData for {symbol}: {payload!r}"
            )

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
