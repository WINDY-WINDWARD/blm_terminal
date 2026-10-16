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
from app.services.ai_config import get_dynamic_ai_provider, get_dynamic_ai_api_key
from app.services.antigravity_auth import get_antigravity_token
from app.services.document_service import (
    DocumentError,
    attach_documents,
    build_document_context,
    create_document,
    delete_document,
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
    """Return the current provider configuration status."""
    provider = await get_dynamic_ai_provider()
    is_configured = False
    free_tier = False

    if provider == "gemini":
        token = await get_antigravity_token()
        is_configured = token is not None
    elif provider == "zen-free":
        # Free tier needs no key — always usable.
        is_configured = True
        free_tier = True
    elif provider == "codex":
        from app.services.codex_auth import get_codex_status
        status = await get_codex_status()
        is_configured = bool(status.get("logged_in"))
    elif provider == "copilot":
        from app.services.llm_provider import get_copilot_inference_token
        gh_token = await get_dynamic_ai_api_key("copilot")
        token, _, _ = await get_copilot_inference_token(gh_token or "none")
        is_configured = token is not None
    else:
        api_key = await get_dynamic_ai_api_key(provider)
        is_configured = bool(api_key and api_key != "none")

    return {
        "provider": provider,
        "is_configured": is_configured,
        "free_tier": free_tier,
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
    """Fetch OpenCode Zen models, listing free models at the top followed by paid models.

    The /models endpoint is publicly readable, so even callers without a key
    get the live list. With free_only=True (zen-free provider) only the free
    models are returned.
    """
    import time

    now = time.monotonic()
    if _ZEN_MODELS_CACHE["models"] and (now - _ZEN_MODELS_CACHE["ts"]) < 600.0:
        cached = _ZEN_MODELS_CACHE["models"]
        return [m for m in cached if m.get("is_free")] if free_only else cached

    credential = api_key.strip() if api_key else ""
    if not credential or credential == "none":
        credential = "public"

    url = "https://opencode.ai/zen/v1/models"
    headers = {
        "Authorization": f"Bearer {credential}",
        "User-Agent": "opencode/1.18.31",
        "x-opencode-client": "cli",
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            models_data = data.get("data", [])

            free_list: list[dict[str, Any]] = []
            paid_list: list[dict[str, Any]] = []
            for m in models_data:
                mid = m.get("id", "")
                if not mid:
                    continue
                if "-free" in mid.lower():
                    free_list.append({"id": mid, "label": f"[FREE] {mid}", "is_free": True})
                else:
                    paid_list.append({"id": mid, "label": mid, "is_free": False})

            free_list.sort(key=lambda x: x["id"])
            paid_list.sort(key=lambda x: x["id"])
            sorted_models = free_list + paid_list
            if sorted_models:
                _ZEN_MODELS_CACHE["models"] = sorted_models
                _ZEN_MODELS_CACHE["ts"] = now
                return free_list if free_only else sorted_models
    except Exception as e:
        logger.warning("Failed to fetch dynamic Zen models: %s", e)

    if free_only:
        return [m for m in FALLBACK_ZEN_MODELS if m.get("is_free")]
    return FALLBACK_ZEN_MODELS


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


async def fetch_aistudio_models(api_key: str = "") -> list[dict[str, Any]]:
    """Fetch the live model list from Google AI Studio (live fetch only).

    Returns [] when no key is configured or the fetch fails. The /models
    endpoint returns IDs with a "models/" prefix which the chat endpoint does
    not accept, so the prefix is stripped. Retired (1.x/2.x) models are
    excluded — only models that accept chat requests are listed.
    """
    key = api_key.strip() if api_key else ""
    if not key or key == "none":
        return []
    url = "https://generativelanguage.googleapis.com/v1beta/openai/models"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers={"Authorization": f"Bearer {key}"})
            resp.raise_for_status()
            data = resp.json()
            result: list[dict[str, Any]] = []
            for m in data.get("data", []):
                mid = m.get("id", "")
                if not mid:
                    continue
                if mid.startswith("models/"):
                    mid = mid[len("models/"):]
                if any(t in mid.lower() for t in _AISTUDIO_NONCHAT):
                    continue
                if mid.lower().startswith(_AISTUDIO_RETIRED_PREFIXES):
                    continue
                label = m.get("display_name") or mid
                result.append({"id": mid, "label": label})
            result.sort(key=lambda x: x["id"])
            return result
    except Exception as e:
        logger.warning("Failed to fetch AI Studio models: %s", e)
    return []


async def fetch_groq_models(api_key: str = "") -> list[dict[str, Any]]:
    """Fetch the live model list from Groq (live fetch only).

    Returns [] when no key is configured or the fetch fails. Speech,
    transcription, and guard models are filtered out.
    """
    key = api_key.strip() if api_key else ""
    if not key or key == "none":
        return []
    url = "https://api.groq.com/openai/v1/models"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers={"Authorization": f"Bearer {key}"})
            resp.raise_for_status()
            data = resp.json()
            result: list[dict[str, Any]] = []
            for m in data.get("data", []):
                mid = m.get("id", "")
                if not mid:
                    continue
                if any(t in mid.lower() for t in _GROQ_NONCHAT):
                    continue
                out_modalities = m.get("output_modalities") or []
                if out_modalities and "text" not in out_modalities:
                    continue
                label = m.get("name") or mid
                result.append({"id": mid, "label": label})
            result.sort(key=lambda x: x["id"])
            return result
    except Exception as e:
        logger.warning("Failed to fetch Groq models: %s", e)
    return []


async def fetch_nvidia_models(api_key: str = "") -> list[dict[str, Any]]:
    """Fetch the live model list from NVIDIA NIM (live fetch only).

    Returns [] when no key is configured or the fetch fails. Embedding,
    vision, guard, and other non-chat models are filtered out.
    """
    key = api_key.strip() if api_key else ""
    if not key or key == "none":
        return []
    url = "https://integrate.api.nvidia.com/v1/models"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers={"Authorization": f"Bearer {key}"})
            resp.raise_for_status()
            data = resp.json()
            result: list[dict[str, Any]] = []
            for m in data.get("data", []):
                mid = m.get("id", "")
                if not mid:
                    continue
                if any(t in mid.lower() for t in _NVIDIA_NONCHAT):
                    continue
                owner = m.get("owned_by") or ""
                label = f"{mid} ({owner})" if owner else mid
                result.append({"id": mid, "label": label})
            result.sort(key=lambda x: x["id"])
            return result
    except Exception as e:
        logger.warning("Failed to fetch NVIDIA models: %s", e)
    return []


# --- Multi-provider model catalogs -------------------------------------------

# Static list for Anthropic direct + Claude Code OAuth (the /v1/models endpoint
# is cursor-paginated and OAuth tokens can't use it reliably — curated instead).
ANTHROPIC_MODELS_STATIC = [
    {"id": "claude-opus-4-7", "label": "[Anthropic] claude-opus-4-7 (flagship)"},
    {"id": "claude-sonnet-4-6", "label": "[Anthropic] claude-sonnet-4-6 (balanced)"},
    {"id": "claude-haiku-4-5-20251001", "label": "[Anthropic] claude-haiku-4-5 (fast)"},
]

# Static list for DeepSeek (tiny catalog — live fetch adds nothing).
DEEPSEEK_MODELS_STATIC = [
    {"id": "deepseek-chat", "label": "[DeepSeek] deepseek-chat (V4)"},
    {"id": "deepseek-reasoner", "label": "[DeepSeek] deepseek-reasoner (thinking)"},
]


async def _fetch_openai_compat_models(
    base_url: str,
    api_key: str,
    *,
    label: str,
    log_name: str,
    extra_headers: dict[str, str] | None = None,
    keep: Any = None,
    drop_substrings: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    """Generic live fetch for OpenAI-compatible /models endpoints.

    ``keep`` is an optional predicate(mid, entry) for allow-listing; entries
    containing any of ``drop_substrings`` (case-insensitive) are excluded.
    """
    key = api_key.strip() if api_key else ""
    if not key or key == "none":
        return []
    headers = {"Authorization": f"Bearer {key}"}
    if extra_headers:
        headers.update(extra_headers)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{base_url}/models", headers=headers)
            resp.raise_for_status()
            data = resp.json()
            result: list[dict[str, Any]] = []
            for m in data.get("data", []):
                mid = m.get("id", "")
                if not mid:
                    continue
                if drop_substrings and any(t in mid.lower() for t in drop_substrings):
                    continue
                if keep is not None and not keep(mid, m):
                    continue
                result.append({"id": mid, "label": f"[{label}] {mid}"})
            result.sort(key=lambda x: x["id"])
            return result
    except Exception as e:
        logger.warning("Failed to fetch %s models: %s", log_name, e)
    return []


async def fetch_openai_models(api_key: str = "") -> list[dict[str, Any]]:
    """Live fetch from api.openai.com — chat models only (gpt-*, o*)."""
    return await _fetch_openai_compat_models(
        "https://api.openai.com/v1", api_key, label="OpenAI", log_name="OpenAI",
        keep=lambda mid, _m: mid.startswith(("gpt-", "o1", "o3", "o4")),
        drop_substrings=("audio", "transcribe", "tts", "image", "realtime", "moderation", "embedding"),
    )


async def fetch_openrouter_models(api_key: str = "") -> list[dict[str, Any]]:
    """Live fetch from OpenRouter — tool-capable models with >= 8k context.

    OpenRouter exposes 300+ models; the capability filter keeps the dropdown
    to models that can actually drive the agentic loop.
    """
    key = api_key.strip() if api_key else ""
    if not key or key == "none":
        return []
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                "https://openrouter.ai/api/v1/models",
                headers={
                    "Authorization": f"Bearer {key}",
                    "HTTP-Referer": "https://localhost:4455",
                    "X-Title": "BLM Terminal",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            result: list[dict[str, Any]] = []
            for m in data.get("data", []):
                mid = m.get("id", "")
                if not mid:
                    continue
                if (m.get("context_length") or 0) < 8192:
                    continue
                params = m.get("supported_parameters") or []
                if params and "tools" not in params:
                    continue
                result.append({"id": mid, "label": f"[OpenRouter] {mid}"})
            result.sort(key=lambda x: x["id"])
            return result
    except Exception as e:
        logger.warning("Failed to fetch OpenRouter models: %s", e)
    return []


async def fetch_xai_models(api_key: str = "") -> list[dict[str, Any]]:
    """Live fetch from api.x.ai — grok-* chat models."""
    return await _fetch_openai_compat_models(
        "https://api.x.ai/v1", api_key, label="xAI", log_name="xAI",
        keep=lambda mid, _m: "grok" in mid.lower(),
        drop_substrings=("image", "embedding"),
    )


async def fetch_together_models(api_key: str = "") -> list[dict[str, Any]]:
    """Live fetch from Together AI — type=chat entries."""
    return await _fetch_openai_compat_models(
        "https://api.together.xyz/v1", api_key, label="Together", log_name="Together AI",
        keep=lambda mid, m: (m.get("type") or "chat") == "chat",
        drop_substrings=("image", "embedding", "audio", "moderation", "rerank"),
    )


async def fetch_copilot_models(gh_token: str = "") -> list[dict[str, Any]]:
    """Live fetch from the Copilot /models endpoint via the exchanged token.

    Handles both the OpenAI-style {"data": [...]} envelope and a bare list
    (endpoint shape varies by account type).
    """
    key = gh_token.strip() if gh_token else ""
    if not key or key == "none":
        return []
    try:
        from app.services.llm_provider import _COPILOT_EDITOR_HEADERS, get_copilot_inference_token
        token, base_url, _ = await get_copilot_inference_token(key)
        if not token:
            return []
        headers = {"Authorization": f"Bearer {token}", **_COPILOT_EDITOR_HEADERS}
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{base_url}/models", headers=headers)
            resp.raise_for_status()
            data = resp.json()
            entries = data.get("data", data) if isinstance(data, dict) else data
            if not isinstance(entries, list):
                return []
            result: list[dict[str, Any]] = []
            for m in entries:
                if not isinstance(m, dict):
                    continue
                mid = m.get("id", "")
                if not mid:
                    continue
                result.append({"id": mid, "label": f"[Copilot] {mid}"})
            result.sort(key=lambda x: x["id"])
            return result
    except Exception as e:
        logger.warning("Failed to fetch Copilot models: %s", e)
    return []


@router.get("/provider-models")
async def get_provider_models(provider: str, api_key: str = "") -> list[dict]:
    """Fetch models dynamically from the provider API."""
    prov = provider.lower().strip()
    if prov == "gemini":
        return [
            {"id": "gemini-3.8-flash-medium", "label": "Gemini 3.8 Flash (Medium)"},
            {"id": "gemini-3.8-flash-low",    "label": "Gemini 3.8 Flash (Fast / Low)"},
            {"id": "gemini-3.8-flash-high",   "label": "Gemini 3.8 Flash (Reasoning / High)"},
        ]

    if prov == "zen-free":
        return await fetch_zen_models("", free_only=True)

    if prov in ("zen-paid", "zen"):
        key = api_key.strip()
        if not key or key == "none":
            key = await get_dynamic_ai_api_key("zen-paid")
        return await fetch_zen_models(key)

    if prov == "aistudio":
        key = api_key.strip()
        if not key or key == "none":
            key = await get_dynamic_ai_api_key("aistudio")
        return await fetch_aistudio_models(key)

    if prov == "groq":
        key = api_key.strip()
        if not key or key == "none":
            key = await get_dynamic_ai_api_key("groq")
        return await fetch_groq_models(key)

    if prov == "nvidia":
        key = api_key.strip()
        if not key or key == "none":
            key = await get_dynamic_ai_api_key("nvidia")
        return await fetch_nvidia_models(key)

    if prov in ("anthropic", "claude-code"):
        # Static curated list (native /v1/models is cursor-paginated and
        # OAuth tokens can't query it reliably).
        prefix = "Claude Code" if prov == "claude-code" else "Anthropic"
        return [
            {"id": m["id"], "label": m["label"].replace("[Anthropic]", f"[{prefix}]")}
            for m in ANTHROPIC_MODELS_STATIC
        ]

    if prov == "openai":
        key = api_key.strip()
        if not key or key == "none":
            key = await get_dynamic_ai_api_key("openai")
        return await fetch_openai_models(key)

    if prov == "openrouter":
        key = api_key.strip()
        if not key or key == "none":
            key = await get_dynamic_ai_api_key("openrouter")
        return await fetch_openrouter_models(key)

    if prov == "deepseek":
        return DEEPSEEK_MODELS_STATIC

    if prov == "xai":
        key = api_key.strip()
        if not key or key == "none":
            key = await get_dynamic_ai_api_key("xai")
        return await fetch_xai_models(key)

    if prov == "together":
        key = api_key.strip()
        if not key or key == "none":
            key = await get_dynamic_ai_api_key("together")
        return await fetch_together_models(key)

    if prov == "copilot":
        key = api_key.strip()
        if not key or key == "none":
            key = await get_dynamic_ai_api_key("copilot")
        return await fetch_copilot_models(key)

    if prov == "codex":
        from app.services.codex_auth import CODEX_MODELS
        return CODEX_MODELS

    if prov == "go":
        key = api_key.strip()
        if not key or key == "none":
            key = await get_dynamic_ai_api_key("go")
        if not key or key == "none":
            return AVAILABLE_MODELS

        base_url = "https://opencode.ai/zen/go/v1"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{base_url}/models",
                    headers={"Authorization": f"Bearer {key}", "User-Agent": "Mozilla/5.0"}
                )
                resp.raise_for_status()
                data = resp.json()
                models = data.get("data", [])
                result = [{"id": m.get("id"), "label": m.get("id")} for m in models if m.get("id")]
                result.sort(key=lambda x: x["id"])
                return result or AVAILABLE_MODELS
        except Exception as e:
            logger.warning("Failed to fetch dynamic models for go: %s", e)
            return AVAILABLE_MODELS

    return []


@router.get("/chat/models")
async def get_chat_models() -> list[dict]:
    """Return available model options dynamically based on the active provider."""
    provider = await get_dynamic_ai_provider()
    if provider == "gemini":
        return [
            {"id": "gemini-3.8-flash-medium", "label": "Gemini 3.8 Flash (Medium)"},
            {"id": "gemini-3.8-flash-low",    "label": "Gemini 3.8 Flash (Fast / Low)"},
            {"id": "gemini-3.8-flash-high",   "label": "Gemini 3.8 Flash (Reasoning / High)"},
        ]

    if provider == "zen-free":
        return await fetch_zen_models("", free_only=True)

    if provider in ("zen-paid", "zen"):
        api_key = await get_dynamic_ai_api_key("zen-paid")
        return await fetch_zen_models(api_key)

    if provider == "aistudio":
        api_key = await get_dynamic_ai_api_key("aistudio")
        return await fetch_aistudio_models(api_key)

    if provider == "groq":
        api_key = await get_dynamic_ai_api_key("groq")
        return await fetch_groq_models(api_key)

    if provider == "nvidia":
        api_key = await get_dynamic_ai_api_key("nvidia")
        return await fetch_nvidia_models(api_key)

    if provider in ("anthropic", "claude-code", "openai", "openrouter", "deepseek",
                    "xai", "together", "copilot", "codex"):
        return await get_provider_models(provider)

    if provider == "go":
        api_key = await get_dynamic_ai_api_key("go")
        models = await get_provider_models("go", api_key)
        return models or AVAILABLE_MODELS

    return AVAILABLE_MODELS


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
    active_model = normalize_gemini_model_id(request.model) if (request.model and request.model.startswith("gemini")) else request.model
    
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
