"""
NSE India Client using nsepython library for fetching and caching data from NSE India APIs.
"""

import asyncio
import logging
import requests
import nsepython
from app.schemas.stockuniverse import StockUniverse

from app.services.helpers.json_to_csv import dict_to_csv_text
import pandas

logger = logging.getLogger(__name__)


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
        return nsepython.nse_eq_symbols()

    def get_stock_metadata(self, symbol: str) -> StockUniverse:
        """Fetch metadata for a given stock symbol."""
        temp = nsepython.nse_eq(symbol)
        tempdict = {
            "symbol": temp["info"]["symbol"],
            "companyName": temp["info"]["companyName"],
            "segment": temp["info"]["segment"],
            "industry": temp["metadata"]["industry"],
            "sectorPE": temp["metadata"]["pdSectorPe"],
            "symbolPE": temp["metadata"]["pdSymbolPe"],
            "industryInfo": temp["industryInfo"],
            "lastUpdateTime": temp["metadata"]["lastUpdateTime"],
        }

        return StockUniverse(**tempdict)

    def get_corporate_filing_comparison(self, symbol: str) -> str:
        """Fetch corporate filing comparison for `symbol`, convert to CSV, and return CSV text.

        Uses the `json_to_csv.convert` helper which expects an input JSON file path
        and an output CSV file path. The function writes temporary files and returns
        the CSV contents as a string.
        """
        try:
            data = nsepython.nse_past_results(symbol)
        except Exception:
            logger.exception("Failed to fetch past results for %s", symbol)
            raise

        # Convert JSON -> CSV using the in-memory helper and return CSV text
        try:
            csv_text = dict_to_csv_text(data)
            return csv_text
        except Exception:
            logger.exception("Failed to convert past results for %s to CSV", symbol)
            raise

    def get_top_gainers(self) -> pandas.DataFrame:
        """Fetch the list of top gainers from NSE India."""
        return nsepython.nse_get_top_gainers()

    def get_top_losers(self) -> pandas.DataFrame:
        """Fetch the list of top losers from NSE India."""
        return nsepython.nse_get_top_losers()

    def check_bulk_deals(self, symbol: str) -> pandas.DataFrame:
        """Fetch the list of bulk deals from NSE India for a specific symbol."""
        df = nsepython.nse_largedeals("bulk_deals")
        # search df for rows matching the symbol (case-insensitive)
        filtered_df = df[df["symbol"].str.upper() == symbol.upper()]
        return filtered_df

    def check_block_deals(self, symbol: str) -> pandas.DataFrame:
        """Fetch the list of block deals from NSE India for a specific symbol."""
        df = nsepython.nse_largedeals("block_deals")
        # search df for rows matching the symbol (case-insensitive)
        filtered_df = df[df["symbol"].str.upper() == symbol.upper()]
        return filtered_df

    def get_high_short_interest(self) -> pandas.DataFrame:
        """Fetch the list of high short interest stocks from NSE India."""
        return nsepython.nse_largedeals("short_deals")

    def get_change_ranges(self, symbol: str) -> dict[str, float]:
        """Fetch percentage-change data for a symbol from NSE's getYearwiseData endpoint.

        Returns a dict with keys:
            oneDayPercent, oneWeekPercent, oneMonthPercent, threeMonthPercent,
            sixMonthPercent, oneYearPercent, twoYearPercent, threeYearPercent, fiveYearPercent
        """
        _NSE_FIELD_MAP = {
            "oneDayPercent": "yesterday_chng_per",
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

        resp = self._session.get(url, timeout=20)
        resp.raise_for_status()

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

        resp = self._session.get(url, timeout=20)
        resp.raise_for_status()

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
