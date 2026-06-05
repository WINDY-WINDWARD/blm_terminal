"""AI Chat router — SSE streaming endpoint for the MiniMax agentic chat panel,
with persistent chat history stored in SQLite.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import AsyncSessionLocal, get_db
from app.models.ai_chat import ChatMessageRecord, ChatSession
from app.services.ai_chat_service import AVAILABLE_MODELS, run_chat_agent

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ai", tags=["ai-chat"])


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class ChatMessageSchema(BaseModel):
    role: Literal["user", "assistant"] = Field(..., description="'user' or 'assistant'")
    content: str = Field(..., description="Message text")
class ChatRequest(BaseModel):
    messages: list[ChatMessageSchema] = Field(
        ..., description="Full conversation history ending with the latest user message."
    )
    symbol: str = Field(default="RELIANCE", description="Active NSE symbol for context.")
    exchange: str = Field(default="NSE", description="Active exchange.")
    model: str = Field(default="kimi-k2.5", description="Model ID on OpenCode Go.")
    session_id: int | None = Field(default=None, description="Existing session ID to continue; null to create new.")
    persona: str | None = Field(default=None, description="Optional analyst persona key: value | earnings | fno | macro")


class SessionSummary(BaseModel):
    id: int
    title: str
    model: str
    symbol: str
    exchange: str
    message_count: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MessageOut(BaseModel):
    id: int
    role: str
    content: str
    tool_calls: list[str] | None
    created_at: datetime

    model_config = {"from_attributes": True}


class SessionDetail(BaseModel):
    id: int
    title: str
    model: str
    symbol: str
    exchange: str
    created_at: datetime
    updated_at: datetime
    messages: list[MessageOut]

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _make_title(first_user_content: str) -> str:
    title = first_user_content.strip().replace("\n", " ")
    return title[:80] if len(title) > 80 else title


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/chat/models")
async def get_chat_models() -> list[dict]:
    """Return available MiniMax model options."""
    return AVAILABLE_MODELS


@router.get("/chat/sessions", response_model=list[SessionSummary])
async def list_sessions(db: AsyncSession = Depends(get_db)) -> list[SessionSummary]:
    """List all chat sessions ordered by most recently updated."""
    result = await db.execute(
        select(
            ChatSession,
            func.count(ChatMessageRecord.id).label("message_count"),
        )
        .outerjoin(ChatMessageRecord, ChatMessageRecord.session_id == ChatSession.id)
        .group_by(ChatSession.id)
        .order_by(ChatSession.updated_at.desc())
    )
    rows = result.all()
    out = []
    for session, count in rows:
        out.append(
            SessionSummary(
                id=session.id,
                title=session.title,
                model=session.model,
                symbol=session.symbol,
                exchange=session.exchange,
                message_count=count,
                created_at=session.created_at,
                updated_at=session.updated_at,
            )
        )
    return out


@router.get("/chat/sessions/{session_id}", response_model=SessionDetail)
async def get_session(session_id: int, db: AsyncSession = Depends(get_db)) -> SessionDetail:
    """Return a full chat session with all messages."""
    result = await db.execute(
        select(ChatSession)
        .options(selectinload(ChatSession.messages))
        .where(ChatSession.id == session_id)
    )
    session = result.scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    messages_out = [
        MessageOut(
            id=m.id,
            role=m.role,
            content=m.content,
            tool_calls=json.loads(m.tool_calls_json) if m.tool_calls_json else None,
            created_at=m.created_at,
        )
        for m in session.messages
    ]
    return SessionDetail(
        id=session.id,
        title=session.title,
        model=session.model,
        symbol=session.symbol,
        exchange=session.exchange,
        created_at=session.created_at,
        updated_at=session.updated_at,
        messages=messages_out,
    )


@router.delete("/chat/sessions/{session_id}")
async def delete_session(session_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    """Delete a chat session and all its messages."""
    result = await db.execute(select(ChatSession).where(ChatSession.id == session_id))
    session = result.scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    await db.delete(session)
    await db.commit()
    return {"ok": True, "id": session_id}


@router.post("/chat")
async def chat(request: ChatRequest, db: AsyncSession = Depends(get_db)) -> StreamingResponse:
    """Stream an AI chat response via Server-Sent Events and persist the exchange.

    Event types (each a JSON object on a `data:` line):
    - `{"type": "session_id", "id": 123}` — session created/continued (first event)
    - `{"type": "token", "text": "..."}` — LLM output chunk
    - `{"type": "tool_call", "name": "...", "args": {...}}` — tool being invoked
    - `{"type": "tool_result", "name": "...", "preview": "..."}` — tool completed
    - `{"type": "error", "message": "..."}` — error (non-fatal if possible)
    - `{"type": "done"}` — stream finished
    """
    messages = [{"role": m.role, "content": m.content} for m in request.messages]
    symbol = request.symbol.upper()
    exchange = request.exchange.upper()

    # Find the last user message (for title generation)
    last_user_content = next(
        (m["content"] for m in reversed(messages) if m["role"] == "user"), ""
    )

    # ------------------------------------------------------------------
    # Resolve or create session + persist user message.
    # Wrapped in try/except so that DB lock errors are surfaced as an SSE
    # error event rather than an unhandled 500.
    # ------------------------------------------------------------------
    session_id: int | None = None
    try:
        if request.session_id is not None:
            result = await db.execute(
                select(ChatSession).where(ChatSession.id == request.session_id)
            )
            session = result.scalar_one_or_none()
            if session is None:
                return _sse_error_response("Session not found")
        else:
            session = ChatSession(
                title=_make_title(last_user_content),
                model=request.model,
                symbol=symbol,
                exchange=exchange,
            )
            db.add(session)
            await db.flush()  # get the id

        session_id = session.id

        # Persist the user message
        user_msg_record = ChatMessageRecord(
            session_id=session_id,
            role="user",
            content=last_user_content,
        )
        db.add(user_msg_record)
        await db.commit()
    except Exception as exc:
        logger.warning("Chat DB pre-flight failed: %s", exc)
        return _sse_error_response(f"Database error: {exc}")

    async def _event_generator() -> AsyncGenerator[str, None]:
        # First event: tell the frontend which session this belongs to
        yield f"data: {json.dumps({'type': 'session_id', 'id': session_id})}\n\n"

        full_response = ""
        tool_calls_seen: list[str] = []

        try:
            async for chunk in run_chat_agent(
                messages=messages,
                symbol=symbol,
                exchange=exchange,
                model=request.model,
                persona=request.persona,
            ):
                # Track content and tool calls for persistence
                try:
                    event = json.loads(chunk)
                    if event.get("type") == "token":
                        full_response += event.get("text", "")
                    elif event.get("type") == "tool_call":
                        tool_calls_seen.append(event.get("name", ""))
                except Exception:
                    pass

                yield f"data: {chunk}\n\n"

        except Exception as exc:
            logger.exception("Unhandled error in chat stream")
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"

        # Persist the assistant response — skip if nothing was generated (abort / pure error)
        if full_response or tool_calls_seen:
            try:
                async with AsyncSessionLocal() as save_db:
                    async with save_db.begin():
                        assistant_record = ChatMessageRecord(
                            session_id=session_id,
                            role="assistant",
                            content=full_response,
                            tool_calls_json=json.dumps(tool_calls_seen) if tool_calls_seen else None,
                        )
                        save_db.add(assistant_record)
                        # Touch updated_at on the session
                        sess_result = await save_db.execute(
                            select(ChatSession).where(ChatSession.id == session_id)
                        )
                        sess = sess_result.scalar_one_or_none()
                        if sess:
                            sess.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
            except Exception as exc:
                logger.warning("Failed to persist assistant message: %s", exc)

    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


def _sse_error_response(message: str) -> StreamingResponse:
    """Return a minimal SSE stream containing a single error event."""
    async def _generator() -> AsyncGenerator[str, None]:
        yield f"data: {json.dumps({'type': 'error', 'message': message})}\n\n"
        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(
        _generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
