"""WebSocket endpoint for real-time market updates.

Clients connect to /ws/market and receive market ticks.
"""

import asyncio
import json
import logging
from typing import Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

router = APIRouter()


class MarketConnectionManager:
    """Manages WebSocket connections for market updates."""

    def __init__(self):
        self.active_connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.add(websocket)
        logger.info(f"Market WS: client connected. Total: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket) -> None:
        self.active_connections.discard(websocket)
        logger.info(f"Market WS: client disconnected. Total: {len(self.active_connections)}")

    async def broadcast(self, message: dict) -> None:
        """Broadcast a message to all connected clients in parallel."""
        if not self.active_connections:
            return

        message_str = json.dumps(message)
        connections = list(self.active_connections)

        results = await asyncio.gather(
            *[conn.send_text(message_str) for conn in connections],
            return_exceptions=True,
        )

        disconnected = {
            conn for conn, exc in zip(connections, results)
            if isinstance(exc, Exception)
        }
        self.active_connections -= disconnected

market_connection_manager = MarketConnectionManager()

async def broadcast_market_update(symbol: str) -> None:
    """Helper to broadcast a market refresh event to clients."""
    await market_connection_manager.broadcast({
        "type": "market_refresh",
        "symbol": symbol
    })
