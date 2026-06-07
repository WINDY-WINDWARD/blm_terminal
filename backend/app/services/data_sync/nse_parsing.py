"""NSE parse + safe-fetch helpers (Phase C.1, A.12 part 1).

The functions in this module wrap the NSE client in a small
`try/except` boundary and normalize its various response shapes
into dicts keyed by symbol.  They are used by both the watchlist
notification cycles and the global scan cycle, so they live here
in a leaf module that the cycles import.

All functions are pure: they take raw NSE response payloads (or
make a single NSE client call) and return plain dicts.  No DB
access, no global state.

Migrated from ``app.backgroundtasks._impl`` (audit C.1, A.12 part 1).
"""
import logging

import pandas as pd

from app.services.nse_client import NSEClient


logger = logging.getLogger(__name__)


_nse_client = NSEClient()


def _parse_52week_data(data: dict) -> dict[str, dict]:
    """Parse 52-week high/low response into {symbol: {...}} mapping."""
    result = {}
    for item in data.get("data", []):
        symbol = item.get("symbol")
        if symbol:
            result[symbol] = {
                "ltp": item.get("ltp"),
                "new52WHL": item.get("new52WHL"),
                "pChange": item.get("pChange") or item.get("perChange"),
            }
    return result


def _parse_volume_gainers(data: dict) -> dict[str, dict]:
    """Parse volume gainers response into {symbol: {...}} mapping."""
    result = {}
    for item in data.get("data", []):
        symbol = item.get("symbol")
        if symbol:
            result[symbol] = {
                "week1volChange": item.get("week1volChange"),
                "pChange": item.get("pChange") or item.get("perChange"),
            }
    return result


def _safe_fetch_52week_high() -> dict:
    try:
        return _nse_client.get_52week_high_stocks()
    except Exception:
        logger.exception("Failed to fetch 52-week high data")
        return {}


def _safe_fetch_52week_low() -> dict:
    try:
        return _nse_client.get_52week_low_stocks()
    except Exception:
        logger.exception("Failed to fetch 52-week low data")
        return {}


def _safe_fetch_volume_gainers() -> dict:
    try:
        return _nse_client.get_volume_gainers()
    except Exception:
        logger.exception("Failed to fetch volume gainers")
        return {}


def _safe_fetch_top_gainers() -> pd.DataFrame | None:
    try:
        return _nse_client.get_top_gainers()
    except Exception:
        logger.exception("Failed to fetch top gainers")
        return None


def _safe_fetch_top_losers() -> pd.DataFrame | None:
    try:
        return _nse_client.get_top_losers()
    except Exception:
        logger.exception("Failed to fetch top losers")
        return None


def _safe_fetch_largedeal_snapshot() -> dict:
    try:
        return _nse_client.get_largedeal_snapshot()
    except Exception:
        logger.exception("Failed to fetch largedeal snapshot")
        return {}
