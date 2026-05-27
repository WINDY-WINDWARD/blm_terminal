"""WebSocket endpoint for batched market data requests.

Clients connect to /ws/market and send batch requests for change-ranges
and symbol-data. Responses are batched, reducing N HTTP calls to 1 WS message.

Protocol:
  Client → Server:
    {"action": "get_change_ranges", "symbols": ["RELIANCE", "TCS"]}
    {"action": "get_symbol_data",   "symbols": ["RELIANCE", "TCS"]}
    {"action": "ping"}

  Server → Client:
    {"type": "connected"}
    {"type": "pong"}
    {"type": "heartbeat"}
    {"type": "change_ranges", "data": {"RELIANCE": {...}, "TCS": {...}}}
    {"type": "symbol_data",   "data": {"RELIANCE": {...}, "TCS": {...}}}
    {"type": "error", "message": "..."}
"""

import asyncio
import json
import logging
import os
from functools import partial
from typing import Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services.cache import nse_cache
from app.services.nse_rate_limiter import throttled_nse_call

logger = logging.getLogger(__name__)

router = APIRouter()

USE_ASYNC_NSE = os.getenv("USE_ASYNC_NSE", "false").lower() == "true"
if USE_ASYNC_NSE:
    from app.services.nse_client_async import nse_client_async as _active_client
else:
    from app.services.nse_client import nse_client as _active_client

_CHANGE_RANGES_TTL = 300.0
_SYMBOL_DATA_TTL = 60.0

# Maximum symbols allowed per batch request to avoid overloading the backend
_MAX_SYMBOLS_PER_REQUEST = 50


def _clean_nan(obj):
    """Recursively replace NaN/Inf floats with None for JSON safety."""
    import numpy as np
    if isinstance(obj, dict):
        return {k: _clean_nan(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_clean_nan(item) for item in obj]
    elif isinstance(obj, float) and (np.isnan(obj) or np.isinf(obj)):
        return None
    return obj


class MarketConnectionManager:
    """Manages WebSocket connections for market data requests."""

    def __init__(self):
        self.active_connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.add(websocket)
        logger.info("Market WS: client connected. Total: %d", len(self.active_connections))

    def disconnect(self, websocket: WebSocket) -> None:
        self.active_connections.discard(websocket)
        logger.info("Market WS: client disconnected. Total: %d", len(self.active_connections))


market_connection_manager = MarketConnectionManager()


async def _fetch_change_ranges_for_symbol(symbol: str) -> tuple[str, object]:
    """Fetch change-ranges for a single symbol, using cache when available."""
    sym = symbol.upper()
    cache_key = f"change-ranges:{sym}"
    cached = nse_cache.get(cache_key)
    if cached is not None:
        return sym, cached

    try:
        data = await throttled_nse_call(
            cache_key,
            partial(_active_client.get_change_ranges, sym),
            is_async_fn=USE_ASYNC_NSE,
        )
        cleaned = _clean_nan(data)
        nse_cache[cache_key] = cleaned
        return sym, cleaned
    except Exception as e:
        logger.warning("Market WS: change-ranges fetch failed for %s: %s", sym, e)
        return sym, None


async def _fetch_symbol_data_for_symbol(symbol: str) -> tuple[str, object]:
    """Fetch symbol-data for a single symbol, using cache when available."""
    sym = symbol.upper()
    cache_key = f"symbol-data:{sym}"
    cached = nse_cache.get(cache_key)
    if cached is not None:
        return sym, cached

    try:
        data = await throttled_nse_call(
            cache_key,
            partial(_active_client.get_symbol_data, sym),
            is_async_fn=USE_ASYNC_NSE,
        )
        cleaned = _clean_nan(data)
        nse_cache[cache_key] = cleaned
        return sym, cleaned
    except Exception as e:
        logger.warning("Market WS: symbol-data fetch failed for %s: %s", sym, e)
        return sym, None


async def _handle_get_change_ranges(websocket: WebSocket, symbols: list[str]) -> None:
    """Fetch change-ranges for all requested symbols concurrently and respond."""
    if not symbols or not isinstance(symbols, list):
        await websocket.send_json({"type": "error", "message": "symbols must be a non-empty list"})
        return

    # Clamp to max allowed
    symbols = symbols[:_MAX_SYMBOLS_PER_REQUEST]

    results = await asyncio.gather(
        *[_fetch_change_ranges_for_symbol(s) for s in symbols],
        return_exceptions=False,
    )

    data = {sym: val for sym, val in results}
    await websocket.send_json({"type": "change_ranges", "data": data})


async def _handle_get_symbol_data(websocket: WebSocket, symbols: list[str]) -> None:
    """Fetch symbol-data for all requested symbols concurrently and respond."""
    if not symbols or not isinstance(symbols, list):
        await websocket.send_json({"type": "error", "message": "symbols must be a non-empty list"})
        return

    symbols = symbols[:_MAX_SYMBOLS_PER_REQUEST]

    results = await asyncio.gather(
        *[_fetch_symbol_data_for_symbol(s) for s in symbols],
        return_exceptions=False,
    )

    data = {sym: val for sym, val in results}
    await websocket.send_json({"type": "symbol_data", "data": data})


@router.websocket("/market")
async def market_websocket(websocket: WebSocket) -> None:
    """WebSocket endpoint for batched market data (change-ranges, symbol-data).

    Accepts batch requests and responds with data for all requested symbols
    in a single message, reducing N HTTP calls to 1 WebSocket round-trip.
    """
    await market_connection_manager.connect(websocket)

    await websocket.send_json({"type": "connected"})

    heartbeat_task = asyncio.create_task(_heartbeat(websocket))

    try:
        while True:
            try:
                raw = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=60.0,
                )
            except asyncio.TimeoutError:
                continue

            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("Market WS: received invalid JSON from client")
                continue

            action = message.get("action")

            if action == "ping":
                await websocket.send_json({"type": "pong"})

            elif action == "get_change_ranges":
                symbols = message.get("symbols", [])
                await _handle_get_change_ranges(websocket, symbols)

            elif action == "get_symbol_data":
                symbols = message.get("symbols", [])
                await _handle_get_symbol_data(websocket, symbols)

            else:
                if action is not None:
                    await websocket.send_json({
                        "type": "error",
                        "message": f"Unknown action: {action}",
                    })

    except WebSocketDisconnect:
        logger.info("Market WS: client disconnected cleanly")
    except Exception as e:
        logger.error("Market WS: unexpected error: %s", e)
    finally:
        heartbeat_task.cancel()
        market_connection_manager.disconnect(websocket)


async def _heartbeat(websocket: WebSocket) -> None:
    """Send heartbeat every 30 seconds to keep connection alive."""
    while True:
        try:
            await asyncio.sleep(30)
            await websocket.send_json({"type": "heartbeat"})
        except Exception:
            break
