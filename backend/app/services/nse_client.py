"""
NSE India Client using nsepython library for fetching and caching data from NSE India APIs.
"""
import asyncio
import logging
import time
import json
import tempfile
import os
from datetime import datetime, timedelta
from typing import Any
from app.services.helpers.customrequests import fetch_nse_historical_csv
import nsepython
from app.schemas.stockuniverse import StockUniverse

from app.config import settings
from app.services.helpers.json_to_csv import dict_to_csv_text
import pandas

logger = logging.getLogger(__name__)


class NSEClient:
    """Singleton async client nsepython library for fetching data from NSE India APIs with built-in caching and session management."""

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
        """Fetch up to 5 years of historical data and compute percentage changes.

        This function fetches data in ~1-year chunks using `fetch_nse_historical_csv` and
        computes percentage changes for several ranges by locating the closest available
        trading day on or before each target date (so holidays/weekends are handled).
        """
        end_date = datetime.now()
        start_date = end_date - timedelta(days=365 * 5)

        # Fetch data in year-sized chunks to respect single-call limits
        df_list: list[pd.DataFrame] = []
        chunk_start = start_date
        while chunk_start < end_date:
            chunk_end = min(chunk_start + timedelta(days=365), end_date)
            from_date_str = chunk_start.strftime("%d-%m-%Y")
            to_date_str = chunk_end.strftime("%d-%m-%Y")
            try:
                df = fetch_nse_historical_csv(symbol, from_date_str, to_date_str)
                if df is None or df.empty:
                    logger.info("No data for %s from %s to %s", symbol, from_date_str, to_date_str)
                else:
                    df_list.append(df)
                time.sleep(settings.nse_request_delay_ms / 1000)  # brief pause to avoid hitting rate limits
            except Exception as exc:
                logger.warning(
                    "Failed to fetch historical data for %s from %s to %s: %s",
                    symbol,
                    from_date_str,
                    to_date_str,
                    exc,
                    exc_info=True,
                )
            # move to next chunk (start after chunk_end)
            chunk_start = chunk_end + timedelta(days=1)

        if not df_list:
            raise ValueError(f"No historical data found for symbol {symbol}")

        full_df = pd.concat(df_list, ignore_index=True)
        full_df["Date"] = pd.to_datetime(full_df["Date"], format="%d-%m-%Y", errors="coerce")
        full_df.dropna(subset=["Date"], inplace=True)
        full_df.sort_values("Date", inplace=True)
        full_df.reset_index(drop=True, inplace=True)

        if "Close" not in full_df.columns:
            raise ValueError("Historical data missing 'Close' column")

        full_df["Close"] = pd.to_numeric(full_df["Close"], errors="coerce")
        full_df.dropna(subset=["Close"], inplace=True)

        if full_df.empty:
            raise ValueError(f"No usable historical data for symbol {symbol}")

        last_row = full_df.iloc[-1]
        last_close = float(last_row["Close"])
        last_date = pd.to_datetime(last_row["Date"])  # latest available trading date

        # map ranges to calendar-day offsets; we choose calendar days and then find
        # the closest trading day on-or-before the target date
        ranges_days = {
            "1d%": 1,
            "1w%": 7,
            "1M%": 30,
            "3M%": 90,
            "1Y%": 365,
            "3Y%": 365 * 3,
            "5Y%": 365 * 5,
        }

        change_ranges: dict[str, float] = {}
        for name, days in ranges_days.items():
            target_date = last_date - pd.Timedelta(days=days)
            prior_rows = full_df[full_df["Date"] <= target_date]
            if prior_rows.empty:
                change_ranges[name] = float("nan")
                continue
            prior_close = float(prior_rows.iloc[-1]["Close"])
            if prior_close == 0 or pd.isna(prior_close):
                change_ranges[name] = float("nan")
            else:
                change_ranges[name] = (last_close - prior_close) / prior_close * 100

        return change_ranges

    async def close(self) -> None:
        """No-op teardown hook (kept for lifespan compatibility)."""


# Module-level singleton — import this in routers / services
nse_client = NSEClient()
        