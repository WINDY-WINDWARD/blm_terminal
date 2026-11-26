"""Live model discovery for direct AI providers.

Each direct provider publishes a model list. This module holds the endpoint,
auth style, and response shape for every provider, then returns a normalized
``[{"id": ..., "label": ...}]`` catalog.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

logger = logging.getLogger("blm.direct_model_catalog")

_USER_AGENT = "BLM-Terminal/1.0"


class ProviderCredentialError(Exception):
    """The provider rejected the supplied API key."""


class ProviderCatalogError(Exception):
    """The model catalog could not be fetched or parsed."""


ENDPOINTS: dict[str, tuple[str, str, str]] = {
    "zen-paid": ("https://opencode.ai/zen/v1/models", "bearer", "openai"),
    "go": ("https://opencode.ai/zen/go/v1/models", "bearer", "openai"),
    "openai": ("https://api.openai.com/v1/models", "bearer", "openai"),
    "groq": ("https://api.groq.com/openai/v1/models", "bearer", "openai"),
    "nvidia": ("https://integrate.api.nvidia.com/v1/models", "bearer", "openai"),
    "openrouter": ("https://openrouter.ai/api/v1/models", "bearer", "openai"),
    "deepseek": ("https://api.deepseek.com/models", "bearer", "openai"),
    "xai": ("https://api.x.ai/v1/models", "bearer", "openai"),
    "together": ("https://api.together.xyz/v1/models", "bearer", "openai"),
    "aistudio": (
        "https://generativelanguage.googleapis.com/v1beta/models",
        "x-goog-api-key",
        "gemini",
    ),
    "anthropic": (
        "https://api.anthropic.com/v1/models?limit=1000",
        "anthropic",
        "anthropic",
    ),
}

# Model families that cannot answer a chat turn. Substring match, lowercased.
_NON_CHAT_TOKENS: tuple[str, ...] = (
    "embed",
    "rerank",
    "guard",
    "whisper",
    "tts",
    "dall-e",
    "imagen",
    "moderation",
    "realtime",
    "transcribe",
    "sora",
    "ocr",
    "audio",
    "vision-guard",
    "reward",
)

_OPENAI_EXTRA_TOKENS: tuple[str, ...] = (
    "text-embedding",
    "tts-",
    "whisper",
    "dall-e",
    "omni-moderation",
)

_AISTUDIO_EXTRA_TOKENS: tuple[str, ...] = (
    "tts",
    "image",
    "veo",
    "lyria",
    "aqa",
    "robotics",
    "computer-use",
    "deep-research",
    "antigravity",
    "embedding",
    "transcribe",
    "live",
)

# Providers whose payload carries a `type` field we must honor instead of
# filtering by name.
_TYPE_FILTERED_PROVIDERS = frozenset({"zen-paid", "go"})

# Small display-name map for ids that carry no provider-supplied label.
_HUMAN_LABELS: dict[str, str] = {
    "gpt-5": "GPT-5",
    "gpt-5-mini": "GPT-5 Mini",
    "gpt-4o": "GPT-4o",
    "gpt-4.1": "GPT-4.1",
    "claude-sonnet-4-5": "Claude Sonnet 4.5",
    "claude-opus-4-1": "Claude Opus 4.1",
    "gemini-3.8-flash": "Gemini 3.8 Flash",
    "deepseek-chat": "DeepSeek Chat",
    "deepseek-reasoner": "DeepSeek Reasoner",
}


async def fetch_live_models(
    provider: str,
    api_key: str = "",
    *,
    timeout: float = 8.0,
) -> list[dict[str, str]]:
    """Fetch the live model catalog for a direct provider.

    Returns deduplicated ``[{"id": ..., "label": ...}]`` entries in the order
    the provider sent them.
    """
    endpoint = ENDPOINTS.get(provider)
    if endpoint is None:
        raise ProviderCatalogError(
            f"No model catalog endpoint for provider '{provider}'"
        )

    url, auth_style, shape = endpoint
    key = api_key or ""
    headers = _build_headers(auth_style, key)

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url, headers=headers)
    except (httpx.TimeoutException, httpx.RequestError) as exc:
        logger.warning(
            "Timed out fetching models from %s: %s",
            provider,
            _redact(str(exc), key),
        )
        raise ProviderCatalogError(
            f"Timed out fetching models from {provider}"
        ) from exc

    status = response.status_code

    if status in (401, 403):
        message = _redact(_error_message(response), key)
        logger.warning(
            "Credential rejected by %s (HTTP %s): %s", provider, status, message
        )
        raise ProviderCredentialError(message)

    if status == 400 and key:
        # A models endpoint rejects a bad key with 400 on several providers
        # (Anthropic, xAI, Together). With a key present this is a credential
        # failure, not a catalog failure.
        message = _redact(_error_message(response), key)
        logger.warning("Invalid API key for %s: %s", provider, message)
        raise ProviderCredentialError(message)

    if not 200 <= status < 300:
        logger.warning("HTTP %s from %s", status, provider)
        raise ProviderCatalogError(f"HTTP {status} from {provider}")

    try:
        payload = response.json()
    except Exception as exc:
        logger.warning(
            "Malformed model catalog from %s: %s", provider, type(exc).__name__
        )
        raise ProviderCatalogError(
            f"Malformed model catalog response from {provider}"
        ) from exc

    items = _parse_shape(shape, payload, provider)
    filtered = _filter_items(provider, items)

    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in filtered:
        model_id = item["id"]
        if model_id in seen:
            continue
        seen.add(model_id)
        result.append({"id": model_id, "label": item.get("label") or model_id})

    return result


def _build_headers(auth_style: str, api_key: str) -> dict[str, str]:
    if auth_style == "bearer":
        if not api_key:
            return {}
        return {
            "Authorization": f"Bearer {api_key}",
            "User-Agent": _USER_AGENT,
        }
    if auth_style == "x-goog-api-key":
        return {"x-goog-api-key": api_key}
    if auth_style == "anthropic":
        return {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "User-Agent": _USER_AGENT,
        }
    return {}


def _parse_shape(shape: str, payload: Any, provider: str) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        raise ProviderCatalogError(
            f"Malformed model catalog response from {provider}"
        )
    if shape == "gemini":
        return _parse_gemini(payload, provider)
    if shape == "anthropic":
        return _parse_anthropic(payload, provider)
    return _parse_openai(payload, provider)


def _parse_openai(payload: dict[str, Any], provider: str) -> list[dict[str, Any]]:
    entries = payload.get("data")
    if not isinstance(entries, list):
        raise ProviderCatalogError(
            f"Malformed model catalog response from {provider}"
        )

    items: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        raw_id = entry.get("id")
        if not isinstance(raw_id, str) or not raw_id.strip():
            continue
        model_id = raw_id.strip()
        label = _entry_label(entry) or _HUMAN_LABELS.get(model_id, model_id)
        item: dict[str, Any] = {"id": model_id, "label": label}
        if "type" in entry:
            item["type"] = entry["type"]
        items.append(item)
    return items


def _parse_gemini(payload: dict[str, Any], provider: str) -> list[dict[str, Any]]:
    entries = payload.get("models")
    if not isinstance(entries, list):
        raise ProviderCatalogError(
            f"Malformed model catalog response from {provider}"
        )

    items: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        raw_name = entry.get("name")
        if not isinstance(raw_name, str) or not raw_name.strip():
            continue
        model_id = raw_name.strip()
        if model_id.startswith("models/"):
            model_id = model_id[len("models/"):]
        if not model_id:
            continue
        methods = entry.get("supportedGenerationMethods")
        if not isinstance(methods, list) or "generateContent" not in methods:
            continue
        display_name = entry.get("displayName")
        label = (
            display_name.strip()
            if isinstance(display_name, str) and display_name.strip()
            else model_id
        )
        items.append({"id": model_id, "label": label})
    return items


def _parse_anthropic(payload: dict[str, Any], provider: str) -> list[dict[str, Any]]:
    entries = payload.get("data")
    if not isinstance(entries, list):
        raise ProviderCatalogError(
            f"Malformed model catalog response from {provider}"
        )

    items: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        raw_id = entry.get("id")
        if not isinstance(raw_id, str) or not raw_id.strip():
            continue
        model_id = raw_id.strip()
        display_name = entry.get("display_name")
        label = (
            display_name.strip()
            if isinstance(display_name, str) and display_name.strip()
            else model_id
        )
        items.append({"id": model_id, "label": label})
    return items


def _entry_label(entry: dict[str, Any]) -> str:
    for key in ("name", "display_name"):
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _filter_items(provider: str, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if provider in _TYPE_FILTERED_PROVIDERS:
        return [
            item
            for item in items
            if not isinstance(item.get("type"), str) or item["type"] == "chat"
        ]

    tokens = _NON_CHAT_TOKENS
    if provider == "openai":
        tokens = tokens + _OPENAI_EXTRA_TOKENS
    elif provider == "aistudio":
        tokens = tokens + _AISTUDIO_EXTRA_TOKENS

    return [item for item in items if not _has_token(item["id"], tokens)]


def _has_token(model_id: str, tokens: tuple[str, ...]) -> bool:
    lowered = model_id.lower()
    return any(token in lowered for token in tokens)


def _response_text(response: Any) -> str:
    text = getattr(response, "text", "") or ""
    if text:
        return text
    try:
        return json.dumps(response.json())
    except Exception:
        return ""


def _extract_error_text(payload: Any) -> str:
    if isinstance(payload, str):
        return payload.strip()
    if not isinstance(payload, dict):
        return ""

    error = payload.get("error")
    if isinstance(error, dict):
        for key in ("message", "detail", "type"):
            value = error.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    elif isinstance(error, str) and error.strip():
        return error.strip()

    for key in ("message", "detail"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _error_message(response: Any) -> str:
    status = response.status_code
    try:
        payload = response.json()
    except Exception:
        payload = None

    if payload is None:
        return f"HTTP {status}"

    message = _extract_error_text(payload)
    if not message:
        message = _response_text(response).strip()
    if not message:
        return f"HTTP {status}"
    return message[:200]


def _redact(message: str, api_key: str) -> str:
    if api_key and api_key in message:
        return message.replace(api_key, "***")
    return message
