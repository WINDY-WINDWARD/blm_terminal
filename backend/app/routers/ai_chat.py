"""AI Chat router — SSE streaming endpoint for the MiniMax agentic chat panel,
with persistent chat history stored in SQLite.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from typing import Any, Literal

import httpx

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import get_current_user, current_user_id
from app.database import AsyncSessionLocal, get_db
from app.models.ai_chat import ChatMessageRecord, ChatSession
from app.models.user import User
from app.services.ai_chat_service import AVAILABLE_MODELS, run_chat_agent
from app.services.ai_config import get_dynamic_ai_provider, get_dynamic_ai_api_key, is_ai_provider_configured
from app.services.proxy_supervisor import get_proxy_supervisor
from app.services.route_registry import (
    DEFAULT_ROUTE_MODELS,
    format_route_model_id,
    map_legacy_model_to_route,
    resolve_active_route_id,
    provider_to_route_id,
)
from app.services.document_service import (
    DocumentError,
    attach_documents,
    build_document_context,
    create_document,
    delete_document,
    detach_document,
    document_file_path,
    get_document,
    list_documents,
    session_documents,
)

from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ai", tags=["ai-chat"])

@router.get("/status")
async def get_ai_status():
    """Return the current provider configuration status and route health."""
    from app.services.direct_proxy_routes import is_supported_direct_route, direct_proxy_prefix

    route_id = await resolve_active_route_id()
    is_configured = await is_ai_provider_configured(route_id)
    free_tier = (route_id == "direct:zen-free" or route_id == "zen-free")

    supervisor = get_proxy_supervisor()
    status_dict = supervisor.get_status()

    if route_id.startswith("direct:"):
        is_supported = is_supported_direct_route(route_id)
        models_ok = False
        if is_supported and is_configured:
            try:
                models = await supervisor.list_proxy_models(direct_proxy_prefix(route_id))
                models_ok = bool(models)
            except Exception:
                models_ok = False

        is_healthy = bool(is_supported and is_configured and models_ok and status_dict.get("state") != "crashed")
        route_health = {
            "healthy": is_healthy,
            "transport": "proxy",
            "proxy_status": status_dict.get("state", "stopped"),
            "status": "ok" if is_healthy else ("unsupported" if not is_supported else ("configured" if is_configured else "unconfigured")),
        }
    elif route_id.startswith("oauth:") or route_id.startswith("endpoint:"):
        route_health = {
            "proxy_status": status_dict.get("state", "stopped"),
            "is_running": status_dict.get("is_running", False),
            "healthy": is_configured and status_dict.get("state") != "crashed",
        }
    else:
        # Bare provider name or other route
        canon_id = provider_to_route_id(route_id)
        if canon_id.startswith("direct:"):
            is_supported = is_supported_direct_route(canon_id)
            models_ok = False
            if is_supported and is_configured:
                try:
                    models = await supervisor.list_proxy_models(direct_proxy_prefix(canon_id))
                    models_ok = bool(models)
                except Exception:
                    models_ok = False
            is_healthy = bool(is_supported and is_configured and models_ok and status_dict.get("state") != "crashed")
            route_health = {
                "healthy": is_healthy,
                "transport": "proxy",
                "proxy_status": status_dict.get("state", "stopped"),
                "status": "ok" if is_healthy else ("unsupported" if not is_supported else ("configured" if is_configured else "unconfigured")),
            }
        else:
            route_health = {
                "status": "ok" if is_configured else "unconfigured",
                "healthy": is_configured,
            }

    return {
        "provider": route_id,
        "route_id": route_id,
        "is_configured": is_configured,
        "free_tier": free_tier,
        "route_health": route_health,
    }

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
    mode: Literal["research", "script"] | None = Field(default=None, description="Chat mode: research (default) or script (Script Lab — AI writes chart scripts).")
    document_ids: list[int] = Field(default_factory=list, description="Library documents to attach to this turn (max 5).")


class AttachDocumentsRequest(BaseModel):
    session_id: int
    document_ids: list[int]


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
    attachments: list[int] | None = None
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
    documents: list["DocumentOut"] = []

    model_config = {"from_attributes": True}


class DocumentOut(BaseModel):
    id: int
    filename: str
    file_type: str
    mime_type: str
    file_size: int
    row_count: int | None
    page_count: int | None
    needs_ocr: bool
    is_inlineable: bool
    summary: dict[str, Any] = {}
    attached_session_ids: list[int] = []
    created_at: datetime


def _document_out(document, attached_session_ids: list[int] | None = None) -> DocumentOut:
    try:
        summary = json.loads(document.summary_json or "{}")
    except (TypeError, ValueError):
        summary = {}
    return DocumentOut(
        id=document.id,
        filename=document.filename,
        file_type=document.file_type,
        mime_type=document.mime_type,
        file_size=document.file_size,
        row_count=document.row_count,
        page_count=document.page_count,
        needs_ocr=document.needs_ocr,
        is_inlineable=document.is_inlineable,
        summary=summary,
        attached_session_ids=(
            attached_session_ids
            if attached_session_ids is not None
            else [link.session_id for link in document.session_links]
        ),
        created_at=document.created_at,
    )


SessionDetail.model_rebuild()


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def normalize_gemini_model_id(model: str) -> str:
    """Normalize legacy/deprecated Gemini models to Gemini 3.8 Flash tiers."""
    m = model.strip() if model else ""
    if not m:
        return "gemini-3.8-flash-medium"
    if not m.startswith("gemini-") and m != "gemini":
        return model
    if m.startswith("gemini-3.8-flash"):
        if m in ("gemini-3.8-flash-high", "gemini-3.8-flash-medium", "gemini-3.8-flash-low"):
            return m
        return "gemini-3.8-flash-medium"
    if m.endswith("-high"):
        return "gemini-3.8-flash-high"
    if m.endswith("-medium"):
        return "gemini-3.8-flash-medium"
    return "gemini-3.8-flash-low"


def _make_title(first_user_content: str) -> str:
    title = first_user_content.strip().replace("\n", " ")
    return title[:80] if len(title) > 80 else title


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


from app.services.ai_config import get_dynamic_ai_provider, get_dynamic_ai_api_key

_ZEN_MODELS_CACHE: dict[str, Any] = {"ts": 0.0, "models": []}

FALLBACK_ZEN_MODELS = [
    {"id": "deepseek-v4-flash-free", "label": "[FREE] deepseek-v4-flash-free", "is_free": True},
    {"id": "mimo-v2.5-free", "label": "[FREE] mimo-v2.5-free", "is_free": True},
    {"id": "nemotron-3.5-lightning-free", "label": "[FREE] nemotron-3.5-lightning-free", "is_free": True},
    {"id": "nemotron-3-ultra-free", "label": "[FREE] nemotron-3-ultra-free", "is_free": True},
    {"id": "ling-3.0-flash-fin-free", "label": "[FREE] ling-3.0-flash-fin-free", "is_free": True},
    {"id": "muse-spark-1.3-contributor-free", "label": "[FREE] muse-spark-1.3-contributor-free", "is_free": True},
    {"id": "muse-spark-1.2-contributor-free", "label": "[FREE] muse-spark-1.2-contributor-free", "is_free": True},
    {"id": "claude-sonnet-4-5", "label": "claude-sonnet-4-5", "is_free": False},
    {"id": "claude-haiku-4-5", "label": "claude-haiku-4-5", "is_free": False},
    {"id": "gemini-3.8-flash", "label": "gemini-3.8-flash", "is_free": False},
    {"id": "gpt-5.4-mini", "label": "gpt-5.4-mini", "is_free": False},
    {"id": "deepseek-v4-flash", "label": "deepseek-v4-flash", "is_free": False},
    {"id": "kimi-k2.5", "label": "kimi-k2.5", "is_free": False},
    {"id": "minimax-m3", "label": "minimax-m3", "is_free": False},
    {"id": "qwen3.6-plus", "label": "qwen3.6-plus", "is_free": False},
]


async def fetch_zen_models(api_key: str = "", *, free_only: bool = False) -> list[dict[str, Any]]:
    """Legacy helper preserved for backward compatibility tests; returns static fallback models."""
    if free_only:
        return [m for m in FALLBACK_ZEN_MODELS if m.get("is_free")]
    return list(FALLBACK_ZEN_MODELS)


# Model IDs that are not text-chat capable (TTS, image, video, audio,
# embeddings, agents) — filtered out of the AI Studio dropdown.
_AISTUDIO_NONCHAT = (
    "tts", "image", "embedding", "transcribe", "live", "audio", "veo",
    "lyria", "aqa", "robotics", "computer-use", "realtime",
    "deep-research", "antigravity",
)

# Retired model families — verified 404 ("no longer available to new users")
# on the chat endpoint. The whole gemini-1.x / gemini-2.x generation is gone;
# Google points to gemini-3.x replacements instead.
_AISTUDIO_RETIRED_PREFIXES = ("gemini-1.", "gemini-2.", "gemini-3.1-pro", "gemini-3.5-flash", "gemini-3.6-flash", "gemini-3.7-flash")

# Groq models that are not general text chat (speech, transcription, guards).
_GROQ_NONCHAT = ("whisper", "orpheus", "prompt-guard")

# NVIDIA NIM catalog entries that are not general text chat (embeddings,
# vision, safety guards, translators, parsers, reward models, detectors).
_NVIDIA_NONCHAT = (
    "embed", "vision", "guard", "nemoguard", "translate", "riva", "reward",
    "parse", "detector", "kosmos", "deplot", "neva", "nvclip", "vila",
    "fuyu", "jailbreak", "content-safety", "topic-control", "gliner",
    "pii", "usdcode", "cosmos", "ising",
)


class ProviderModelsRequest(BaseModel):
    provider: str
    api_key: str = ""


async def _resolve_provider_models(provider: str, api_key: str = "") -> list[dict]:
    """Internal helper for resolving models by provider/route ID and optional key."""
    prov = provider.strip()
    route_id = prov if (prov.startswith("oauth:") or prov.startswith("direct:") or prov.startswith("endpoint:")) else provider_to_route_id(prov)

    if route_id.startswith("oauth:"):
        from app.services.route_catalog import get_route_catalog
        return await get_route_catalog(route_id)
    elif route_id.startswith("endpoint:"):
        stored_models: list[str] = []
        try:
            from app.database import AsyncSessionLocal
            from app.models.ai_provider import AIProviderRoute

            async with AsyncSessionLocal() as session:
                r = (await session.execute(select(AIProviderRoute).where(AIProviderRoute.id == route_id))).scalar_one_or_none()
                if r and r.config_json:
                    cfg = json.loads(r.config_json)
                    stored_models = cfg.get("models") or cfg.get("cached_models") or []
        except Exception:
            pass
        from app.services.route_catalog import _filter_chat_models
        stored_models = _filter_chat_models(list(stored_models))
        return [{"id": format_route_model_id(route_id, m), "label": m} for m in stored_models]
    elif route_id.startswith("direct:"):
        from app.services.direct_proxy_routes import is_supported_direct_route
        if not is_supported_direct_route(route_id):
            return []
        from app.services.route_catalog import get_route_models
        models = await get_route_models(route_id)
        return [{"id": format_route_model_id(route_id, m), "label": m} for m in models]

    return []


@router.post("/provider-models")
async def get_provider_models(payload: ProviderModelsRequest) -> list[dict]:
    """Fetch models dynamically from the provider API without secrets in URL."""
    if isinstance(payload, str):
        return await _resolve_provider_models(payload)
    return await _resolve_provider_models(payload.provider, payload.api_key)


@router.get("/chat/models")
async def get_chat_models() -> list[dict]:
    """Return model options across every configured route (active route first).

    Legacy callers expect a flat list; newer UI prefers GET /ai/routes/models.
    Per-message routing honors the route embedded in the selected model id, so
    this endpoint must never pin the list to the active route alone.
    """
    try:
        from app.services.route_catalog import get_all_route_catalogs

        routes, _warnings = await get_all_route_catalogs()
        flat: list[dict] = []
        for route in routes:
            route_label = route.get("label", route.get("route_id", ""))
            for m in route.get("models", []):
                flat.append({"id": m["id"], "label": "[" + route_label + "] " + m["label"]})
        if flat:
            return flat
    except Exception as exc:
        logger.warning("get_chat_models aggregated catalog failed: %s", exc)

    # Fallback: previous active-route-only behavior (never 500, never empty-crash).
    try:
        raw_provider = await get_dynamic_ai_provider()
        active_route_id = provider_to_route_id(raw_provider)

        if active_route_id.startswith("oauth:"):
            from app.services.route_catalog import get_route_catalog
            return await get_route_catalog(active_route_id)

        elif active_route_id.startswith("endpoint:"):
            stored_models: list[str] = []
            try:
                from app.database import AsyncSessionLocal
                from app.models.ai_provider import AIProviderRoute

                async with AsyncSessionLocal() as session:
                    r = (await session.execute(select(AIProviderRoute).where(AIProviderRoute.id == active_route_id))).scalar_one_or_none()
                    if r and r.config_json:
                        cfg = json.loads(r.config_json)
                        stored_models = cfg.get("models") or cfg.get("cached_models") or []
            except Exception:
                pass
            from app.services.route_catalog import _filter_chat_models
            stored_models = _filter_chat_models(list(stored_models))
            if not stored_models:
                stored_models = ["default"]

            return [
                {
                    "id": format_route_model_id(active_route_id, m),
                    "label": f"[Endpoint] {m}",
                }
                for m in stored_models
            ]

        elif active_route_id.startswith("direct:"):
            from app.services.direct_proxy_routes import is_supported_direct_route
            if not is_supported_direct_route(active_route_id):
                return []
            from app.services.route_catalog import get_route_models
            models = await get_route_models(active_route_id)
            return [
                {
                    "id": format_route_model_id(active_route_id, m),
                    "label": m,
                }
                for m in models
            ]

    except Exception as exc:
        logger.warning("get_chat_models failed: %s", exc)
        return []

    return []


@router.get("/chat/sessions", response_model=list[SessionSummary])
async def list_sessions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> list[SessionSummary]:
    """List all chat sessions ordered by most recently updated."""
    result = await db.execute(
        select(
            ChatSession,
            func.count(ChatMessageRecord.id).label("message_count"),
        )
        .outerjoin(ChatMessageRecord, ChatMessageRecord.session_id == ChatSession.id)
        .where(ChatSession.user_id == current_user.id)
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
                model=normalize_gemini_model_id(session.model) if (session.model and session.model.startswith("gemini")) else session.model,
                symbol=session.symbol,
                exchange=session.exchange,
                message_count=count,
                created_at=session.created_at,
                updated_at=session.updated_at,
            )
        )
    return out


@router.get("/chat/sessions/{session_id}", response_model=SessionDetail)
async def get_session(
    session_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> SessionDetail:
    """Return a full chat session with all messages."""
    result = await db.execute(
        select(ChatSession)
        .options(selectinload(ChatSession.messages))
        .where(ChatSession.id == session_id, ChatSession.user_id == current_user.id)
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
            attachments=json.loads(m.attachments_json) if m.attachments_json else None,
            created_at=m.created_at,
        )
        for m in session.messages
    ]
    documents = await session_documents(db, current_user.id, session_id)
    return SessionDetail(
        id=session.id,
        title=session.title,
        model=normalize_gemini_model_id(session.model) if (session.model and session.model.startswith("gemini")) else session.model,
        symbol=session.symbol,
        exchange=session.exchange,
        created_at=session.created_at,
        updated_at=session.updated_at,
        messages=messages_out,
        documents=[_document_out(document, [session_id]) for document in documents],
    )


@router.delete("/chat/sessions/{session_id}")
async def delete_session(
    session_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> dict:
    """Delete a chat session and all its messages."""
    result = await db.execute(select(ChatSession).where(ChatSession.id == session_id, ChatSession.user_id == current_user.id))
    session = result.scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    await db.delete(session)
    await db.commit()
    return {"ok": True, "id": session_id}


@router.post("/documents/upload", response_model=DocumentOut)
async def upload_document(
    file: UploadFile = File(...),
    session_id: int | None = Form(default=None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DocumentOut:
    """Upload a PDF/CSV into the user's document library, optionally attaching it."""
    if session_id is not None:
        session = (
            await db.execute(
                select(ChatSession).where(
                    ChatSession.id == session_id,
                    ChatSession.user_id == current_user.id,
                )
            )
        ).scalar_one_or_none()
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")

    content = await file.read()
    try:
        document = await create_document(
            db,
            current_user.id,
            file.filename or "document",
            content,
            file.content_type,
        )
        if session_id is not None:
            await attach_documents(db, current_user.id, session_id, [document.id])
    except DocumentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    document = await get_document(db, current_user.id, document.id)
    return _document_out(document)


@router.get("/documents", response_model=list[DocumentOut])
async def list_user_documents(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[DocumentOut]:
    """Return the user's persistent PDF/CSV library."""
    documents = await list_documents(db, current_user.id)
    return [_document_out(document) for document in documents]


@router.post("/documents/attach", response_model=list[DocumentOut])
async def attach_session_documents(
    request: AttachDocumentsRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[DocumentOut]:
    """Attach library documents to an existing chat session."""
    session = (
        await db.execute(
            select(ChatSession).where(
                ChatSession.id == request.session_id,
                ChatSession.user_id == current_user.id,
            )
        )
    ).scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    try:
        await attach_documents(db, current_user.id, request.session_id, request.document_ids)
    except DocumentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    documents = await session_documents(db, current_user.id, request.session_id)
    return [_document_out(document, [request.session_id]) for document in documents]


@router.delete("/documents/{document_id}/sessions/{session_id}")
async def detach_session_document(
    document_id: int,
    session_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Detach a library document from a chat session."""
    session = (
        await db.execute(
            select(ChatSession).where(
                ChatSession.id == session_id,
                ChatSession.user_id == current_user.id,
            )
        )
    ).scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    detached = await detach_document(db, current_user.id, session_id, document_id)
    if not detached:
        raise HTTPException(status_code=404, detail="Document attachment not found")
    return {"ok": True, "document_id": document_id, "session_id": session_id}


@router.get("/documents/{document_id}", response_model=DocumentOut)
async def get_user_document(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DocumentOut:
    document = await get_document(db, current_user.id, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return _document_out(document)


@router.get("/documents/{document_id}/file")
async def download_user_document(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    document = await get_document(db, current_user.id, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    path = document_file_path(document)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Stored file is missing")
    return FileResponse(path, media_type=document.mime_type, filename=document.filename)


@router.delete("/documents/{document_id}")
async def delete_user_document(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    deleted = await delete_document(db, current_user.id, document_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"ok": True, "id": document_id}


@router.post("/chat")
async def chat(
    request: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> StreamingResponse:
    """Stream an AI chat response via Server-Sent Events and persist the exchange.

    Event types (each a JSON object on a `data:` line):
    - `{"type": "session_id", "id": 123}` — session created/continued (first event)
    - `{"type": "token", "text": "..."}` — LLM output chunk
    - `{"type": "tool_call", "name": "...", "args": {...}}` — tool being invoked
    - `{"type": "tool_result", "name": "...", "preview": "..."}` — tool completed
    - `{"type": "script_card", "action": "created"|"revised", "script_id": N, "name": "...", "rev_no": N}` — script saved; UI renders Accept/Discard
    - `{"type": "error", "message": "..."}` — error (non-fatal if possible)
    - `{"type": "done"}` — stream finished
    """
    messages = [{"role": m.role, "content": m.content} for m in request.messages]
    symbol = request.symbol.upper()
    exchange = request.exchange.upper()
    active_route_id = await resolve_active_route_id()
    active_model = map_legacy_model_to_route(request.model, active_route_id, preserve_qualified=True)
    
    current_user_id.set(current_user.id)

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
                select(ChatSession).where(ChatSession.id == request.session_id, ChatSession.user_id == current_user.id)
            )
            session = result.scalar_one_or_none()
            if session is None:
                return _sse_error_response("Session not found")
            if session.model and session.model.startswith("gemini"):
                norm_m = normalize_gemini_model_id(session.model)
                if session.model != norm_m:
                    session.model = norm_m
        else:
            session = ChatSession(
                title=_make_title(last_user_content),
                model=active_model,
                symbol=symbol,
                exchange=exchange,
                user_id=current_user.id,
            )
            db.add(session)
            await db.flush()  # get the id

        session_id = session.id

        document_ids = list(dict.fromkeys(request.document_ids or []))
        try:
            await attach_documents(db, current_user.id, session_id, document_ids)
        except DocumentError as exc:
            return _sse_error_response(str(exc))
        document_context = await build_document_context(db, current_user.id, document_ids)

        # Persist the user message
        user_msg_record = ChatMessageRecord(
            session_id=session_id,
            role="user",
            content=last_user_content,
            attachments_json=json.dumps(document_ids) if document_ids else None,
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
                model=active_model,
                persona=request.persona,
                session_id=session_id,
                mode=request.mode,
                user_id=current_user.id,
                document_context=document_context,
                allow_external_route=True,
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
