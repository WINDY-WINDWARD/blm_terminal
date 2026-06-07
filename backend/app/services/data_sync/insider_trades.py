"""Insider-trades fetcher (Phase C.1, A.12 part 1).

Thin wrapper around ``screener_client.get_insider_trades`` that
runs the async call from a sync context and gracefully handles
network/parse failures by returning an empty list.

Used by both ``_notification_cycle_full`` and
``_notification_cycle_reduced`` to enrich watchlist alerts with
insider buy/sell information.

Migrated from ``app.backgroundtasks._impl`` (audit C.1, A.12 part 1).
"""
import logging

from app.services.screener_client import screener_client


logger = logging.getLogger(__name__)

# Imported lazily inside the function body to break the circular
# dependency: ``app.backgroundtasks.__init__`` (the shim) imports
# these helpers from this module, so we cannot import
# ``app.backgroundtasks._impl`` at module level here.  See
# ``tests/test_backgroundtasks_split.py`` for the shim contract.


def _fetch_insider_trades_cached(symbol: str) -> list[dict]:
    """Fetch insider trades from screener.in, returning a list of trade dicts."""
    # Lazy import to break the circular dep with the shim.
    from app.backgroundtasks import _impl as _bg_impl
    try:
        result = _bg_impl._run_async(_fetch_insider_trades_async(symbol))
        return result
    except Exception:
        logger.debug("insider_trades: failed for %s, skipping", symbol)
        return []


async def _fetch_insider_trades_async(symbol: str) -> list[dict]:
    """Async helper: call screener_client.get_insider_trades."""
    try:
        data = await screener_client.get_insider_trades(symbol)
        if data and "insider_trades" in data:
            return data["insider_trades"]
    except Exception:
        pass
    return []
