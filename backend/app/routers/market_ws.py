"""WebSocket endpoint for batched market data requests with
per-symbol streaming.

Clients connect to /ws/market and send batch requests for change-ranges
and symbol-data. The server streams per-symbol partial responses as
each NSE call completes — a 20-symbol watchlist can paint its first
row in ~200ms (cache hit) and fill in the rest as NSE responds,
rather than waiting for the slowest symbol.

Protocol:
  Client → Server:
    {"action": "get_change_ranges", "request_id": N, "symbols": [...]}
    {"action": "get_symbol_data",   "request_id": N, "symbols": [...]}
    {"action": "ping"}

  Server → Client:
    {"type": "connected"}
    {"type": "change_ranges_started",  "request_id": N, "symbols": [...]}
    {"type": "change_ranges_partial",  "request_id": N, "symbol": "X", "data": {...} | null, "error"?: "..."}
    {"type": "change_ranges_complete", "request_id": N}
    (same three messages for symbol_data)
    {"type": "heartbeat"}
    {"type": "pong"}
    {"type": "error", "request_id"?: N, "message": "..."}
"""

import asyncio
import json
import logging
from typing import Any, Awaitable, Callable, Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services.market_data import (
    fetch_change_ranges_batch,
    fetch_symbol_data_batch,
)

logger = logging.getLogger(__name__)

router = APIRouter()


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


async def _stream_batch(
    websocket: WebSocket,
    *,
    action: str,
    request_id: int,
    symbols: list[str],
    started_type: str,
    partial_type: str,
    complete_type: str,
    fetcher: Callable[[list[str]], Awaitable[dict[str, Any]]],
) -> None:
    """Shared per-symbol streaming logic for both change-ranges and symbol-data.

    Sends one `*_started` message up front, then one `*_partial` per
    symbol as each per-symbol NSE call completes (using
    `asyncio.as_completed` so partials fan out in completion order,
    not submission order), then a final `*_complete` message.
    """
    if not symbols or not isinstance(symbols, list):
        await websocket.send_json({
            "type": "error",
            "request_id": request_id,
            "message": "symbols must be a non-empty list",
        })
        return

    # Announce the batch up front so the client can pre-allocate
    # loading state for exactly these symbols.
    await websocket.send_json({
        "type": started_type,
        "request_id": request_id,
        "symbols": list(symbols),
    })

    # Kick off the per-symbol fetches concurrently. We use a helper
    # that wraps each (symbol, future) pair so we can iterate with
    # `asyncio.as_completed` — that gives us per-symbol streaming
    # in completion order, so the first row paints as soon as its
    # NSE call returns, not after the slowest call.
    async def _one(sym: str) -> tuple[str, Any]:
        # We invoke the batch fetcher with a single-symbol list so
        # the cache + rate-limit plumbing in market_data.py does the
        # right thing per call. The overhead vs. a direct call is
        # one extra dict allocation.
        out = await fetcher([sym])
        return sym, out.get(sym)

    tasks = {asyncio.create_task(_one(sym)): sym for sym in symbols}
    try:
        for completed in asyncio.as_completed(tasks):
            try:
                sym, value = await completed
            except Exception as e:  # noqa: BLE001 — surface as soft miss
                logger.warning(
                    "Market WS: %s partial failed for one symbol: %s (%s)",
                    action, e or "(empty)", type(e).__name__,
                )
                continue
            partial: dict[str, Any] = {
                "type": partial_type,
                "request_id": request_id,
                "symbol": sym,
            }
            if value is None:
                partial["data"] = None
            else:
                partial["data"] = value
            await websocket.send_json(partial)
    finally:
        # Cancel any stragglers in case of an early disconnect.
        for t in tasks:
            if not t.done():
                t.cancel()

    await websocket.send_json({
        "type": complete_type,
        "request_id": request_id,
    })


async def _handle_get_change_ranges(
    websocket: WebSocket, request_id: int, symbols: list[str]
) -> None:
    await _stream_batch(
        websocket,
        action="get_change_ranges",
        request_id=request_id,
        symbols=symbols,
        started_type="change_ranges_started",
        partial_type="change_ranges_partial",
        complete_type="change_ranges_complete",
        fetcher=fetch_change_ranges_batch,
    )


async def _handle_get_symbol_data(
    websocket: WebSocket, request_id: int, symbols: list[str]
) -> None:
    await _stream_batch(
        websocket,
        action="get_symbol_data",
        request_id=request_id,
        symbols=symbols,
        started_type="symbol_data_started",
        partial_type="symbol_data_partial",
        complete_type="symbol_data_complete",
        fetcher=fetch_symbol_data_batch,
    )


@router.websocket("/market")
async def market_websocket(websocket: WebSocket) -> None:
    """WebSocket endpoint for per-symbol streaming market data.

    Accepts batch requests and responds with one partial per symbol
    as each NSE call completes. See the module docstring for the
    full protocol.
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
            request_id = message.get("request_id", 0)
            try:
                request_id = int(request_id)
            except (TypeError, ValueError):
                request_id = 0

            if action == "ping":
                await websocket.send_json({"type": "pong"})

            elif action == "get_change_ranges":
                symbols = message.get("symbols", [])
                await _handle_get_change_ranges(websocket, request_id, symbols)

            elif action == "get_symbol_data":
                symbols = message.get("symbols", [])
                await _handle_get_symbol_data(websocket, request_id, symbols)

            else:
                if action is not None:
                    await websocket.send_json({
                        "type": "error",
                        "request_id": request_id,
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
