"""
NSE India Client using nsepython library for fetching and caching data from NSE India APIs.
"""
import asyncio
import logging
import time
import json
import tempfile
import os
from typing import Any
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
            symbol: temp["symbol"],
            "companyName": temp["companyName"],
            "segment": temp["segment"],
            "industry": temp["metadata"]["industry"],
            "sectorPE": temp["metadata"]["pdSectorPe"],
            "symbolPE": temp["metadata"]["pdSymbolPe"],
            "industryInfo": temp["industryInfo"],
            "lastUpdateTime": temp["lastUpdateTime"]
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

    async def close(self) -> None:
        """No-op teardown hook (kept for lifespan compatibility)."""


# Module-level singleton — import this in routers / services
nse_client = NSEClient()
        