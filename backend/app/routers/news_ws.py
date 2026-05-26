"""WebSocket endpoint for real-time news updates.

Clients connect to /ws/news and receive new articles as they are fetched.
"""

import asyncio
import json
import logging
from typing import Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models.news import NewsArticle

logger = logging.getLogger(__name__)

router = APIRouter()

# Connection manager for news WebSocket
class NewsConnectionManager:
    """Manages WebSocket connections for news updates."""

    def __init__(self):
        self.active_connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.add(websocket)
        logger.info(f"News WS: client connected. Total: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket) -> None:
        self.active_connections.discard(websocket)
        logger.info(f"News WS: client disconnected. Total: {len(self.active_connections)}")

    async def broadcast(self, message: dict) -> None:
        """Broadcast a message to all connected clients."""
        if not self.active_connections:
            return

        message_str = json.dumps(message)
        disconnected = set()

        for connection in self.active_connections:
            try:
                await connection.send_text(message_str)
            except Exception:
                disconnected.add(connection)

        # Clean up disconnected clients
        self.active_connections -= disconnected

    async def send_personal(self, websocket: WebSocket, message: dict) -> None:
        """Send a message to a specific client."""
        try:
            await websocket.send_json(message)
        except Exception:
            pass


# Global connection manager instance
news_connection_manager = NewsConnectionManager()


@router.websocket("/news")
async def news_websocket(websocket: WebSocket) -> None:
    """WebSocket endpoint for real-time news updates.

    Protocol:
    - Client connects → server sends {"type": "connected", "message": "News WS connected"}
    - Client can send {"action": "subscribe", "sources": ["bloomberg-mkts"]} to subscribe to specific sources
    - Client can send {"action": "ping"} and server responds with {"type": "pong"}
    - Server pushes {"type": "news", "article": {...}} when new articles arrive
    - Server pushes {"type": "heartbeat"} every 30 seconds to keep connection alive
    """
    await news_connection_manager.connect(websocket)

    # Send initial connection confirmation
    await websocket.send_json({
        "type": "connected",
        "message": "News WebSocket connected"
    })

    # Start heartbeat task
    heartbeat_task = asyncio.create_task(_heartbeat(websocket))

    try:
        while True:
            try:
                # Wait for client messages
                data = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=60.0  # Client should send something at least once per minute
                )

                message = json.loads(data)
                action = message.get("action")

                if action == "ping":
                    await websocket.send_json({"type": "pong"})
                elif action == "subscribe":
                    # Client wants to subscribe to specific sources
                    sources = message.get("sources", [])
                    await websocket.send_json({
                        "type": "subscribed",
                        "sources": sources
                    })
                elif action == "get_recent":
                    # Client requests recent articles
                    limit = message.get("limit", 20)
                    articles = await _get_recent_articles(limit)
                    await websocket.send_json({
                        "type": "recent_articles",
                        "articles": articles
                    })

            except asyncio.TimeoutError:
                # No message received within timeout, continue loop
                continue
            except json.JSONDecodeError:
                logger.warning("News WS: received invalid JSON")
                continue

    except WebSocketDisconnect:
        logger.info("News WS: client disconnected")
    except Exception as e:
        logger.error(f"News WS: error: {e}")
    finally:
        heartbeat_task.cancel()
        news_connection_manager.disconnect(websocket)


async def _heartbeat(websocket: WebSocket) -> None:
    """Send heartbeat every 30 seconds to keep connection alive."""
    while True:
        try:
            await asyncio.sleep(30)
            await websocket.send_json({"type": "heartbeat"})
        except Exception:
            break


async def _get_recent_articles(limit: int = 20) -> list[dict]:
    """Fetch recent articles from database."""
    async with AsyncSessionLocal() as session:
        stmt = (
            select(NewsArticle)
            .order_by(NewsArticle.publish_date.desc())
            .limit(limit)
        )
        result = await session.execute(stmt)
        articles = result.scalars().all()

        return [_article_to_dict(article) for article in articles]


def _article_to_dict(article: NewsArticle) -> dict:
    """Convert NewsArticle to dictionary for JSON serialization."""
    return {
        "url": article.url,
        "source": article.source,
        "title": article.title,
        "text": article.text,
        "publish_date": article.publish_date.isoformat() if article.publish_date else None,
        "fetched_at": article.fetched_at.isoformat() if article.fetched_at else None,
        "company_symbol": article.company_symbol,
        "sentiment": getattr(article, 'sentiment', None),
        "sentiment_score": getattr(article, 'sentiment_score', None),
        "confidence": getattr(article, 'confidence', None),
        "language": getattr(article, 'language', None),
        "entities": getattr(article, 'entities', None),
        "threat_level": getattr(article, 'threat_level', None),
        "threat_category": getattr(article, 'threat_category', None),
        "source_credibility": getattr(article, 'source_credibility', None),
    }


async def broadcast_news_update(article: dict) -> None:
    """Broadcast a new article to all connected clients.

    Called by background workers when new articles are fetched.
    """
    await news_connection_manager.broadcast({
        "type": "news",
        "article": article
    })
