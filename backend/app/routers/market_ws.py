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
from typing import Set

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


async def _handle_get_change_ranges(websocket: WebSocket, symbols: list[str]) -> None:
    """Fetch change-ranges for all requested symbols concurrently and respond."""
    if not symbols or not isinstance(symbols, list):
        await websocket.send_json({"type": "error", "message": "symbols must be a non-empty list"})
        return

    data = await fetch_change_ranges_batch(symbols)
    await websocket.send_json({"type": "change_ranges", "data": data})


async def _handle_get_symbol_data(websocket: WebSocket, symbols: list[str]) -> None:
    """Fetch symbol-data for all requested symbols concurrently and respond."""
    if not symbols or not isinstance(symbols, list):
        await websocket.send_json({"type": "error", "message": "symbols must be a non-empty list"})
        return

    data = await fetch_symbol_data_batch(symbols)
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
