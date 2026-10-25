"""Helper functions for route-aware dynamic AI configuration.

Centralizes:
- Active route resolution from `ai.provider` and defaults
- Route configuration validation for OAuth, custom endpoints, and direct providers
- Route-qualified model resolution for hunter/verifier models
- Preserving existing direct provider API keys and GitHub Copilot token discovery
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from sqlalchemy import select

from app.config import settings
from app.services.route_registry import (
    DEFAULT_ROUTE_ID,
    map_legacy_model_to_route,
    provider_to_route_id,
    resolve_active_route_id,
)

logger = logging.getLogger("blm.ai_config")

# Provider identifiers for legacy compatibility
ZEN_FREE = "zen-free"
ZEN_PAID = "zen-paid"
ZEN_PROVIDERS = (ZEN_FREE, ZEN_PAID)
AISTUDIO = "aistudio"
GROQ = "groq"
NVIDIA = "nvidia"
ANTHROPIC = "anthropic"
CLAUDE_CODE = "claude-code"
OPENAI = "openai"
OPENROUTER = "openrouter"
DEEPSEEK = "deepseek"
XAI = "xai"
TOGETHER = "together"
COPILOT = "copilot"
CODEX = "codex"

PROVIDER_DB_KEYS: dict[str, str] = {
    ZEN_PAID: "ai.zen_api_key",
    "zen": "ai.zen_api_key",
    "go": "ai.go_api_key",
    AISTUDIO: "ai.aistudio_api_key",
    GROQ: "ai.groq_api_key",
    NVIDIA: "ai.nvidia_api_key",
    ANTHROPIC: "ai.anthropic_api_key",
    CLAUDE_CODE: "ai.claude_code_token",
    OPENAI: "ai.openai_api_key",
    OPENROUTER: "ai.openrouter_api_key",
    DEEPSEEK: "ai.deepseek_api_key",
    XAI: "ai.xai_api_key",
    TOGETHER: "ai.together_api_key",
    COPILOT: "ai.copilot_gh_token",
}

ALL_PROVIDERS: tuple[str, ...] = (
    ZEN_FREE, ZEN_PAID, "go", "gemini", "antigravity", "zen",
    AISTUDIO, GROQ, NVIDIA,
    ANTHROPIC, CLAUDE_CODE, OPENAI, OPENROUTER, DEEPSEEK, XAI, TOGETHER,
    COPILOT, CODEX,
)


async def get_dynamic_ai_provider() -> str:
    """Fetch active AI provider route ID from settings or dynamic system_config.

    Returns route-qualified identifier: e.g. 'oauth:codex', 'oauth:antigravity',
    'direct:openai', 'direct:zen-paid', or 'endpoint:<uuid>'.
    """
    return await resolve_active_route_id()


async def get_dynamic_ai_api_key(provider: str) -> str:
    """Fetch the correct API key for direct providers or Copilot.

    Accepts both bare provider strings ('openai') and route IDs ('direct:openai').
    """
    prov = provider.strip()
    if prov.startswith("direct:"):
        prov = prov.split(":", 1)[1]

    # Free tier needs no key — Zen gateway accepts "public"
    if prov == ZEN_FREE:
        return "public"

    api_key = settings.ai_api_key
    if prov in (ZEN_PAID, "zen"):
        api_key = settings.opencode_zen_api_key
    elif prov == AISTUDIO:
        api_key = settings.aistudio_api_key
    elif prov == GROQ:
        api_key = settings.groq_api_key
    elif prov == NVIDIA:
        api_key = settings.nvidia_api_key
    elif prov == ANTHROPIC:
        api_key = settings.anthropic_api_key
        if (not api_key or api_key == "none") and os.environ.get("ANTHROPIC_TOKEN"):
            api_key = os.environ["ANTHROPIC_TOKEN"]
    elif prov == CLAUDE_CODE:
        api_key = settings.claude_code_oauth_token
    elif prov == OPENAI:
        api_key = settings.openai_api_key
    elif prov == OPENROUTER:
        api_key = settings.openrouter_api_key
    elif prov == DEEPSEEK:
        api_key = settings.deepseek_api_key
    elif prov == XAI:
        api_key = settings.xai_api_key
    elif prov == TOGETHER:
        api_key = settings.together_api_key
    elif prov == COPILOT:
        api_key = (
            os.environ.get("COPILOT_GITHUB_TOKEN")
            or os.environ.get("GH_TOKEN")
            or os.environ.get("GITHUB_TOKEN")
            or settings.copilot_gh_token
            or settings.gh_token
            or "none"
        )

    db_key = PROVIDER_DB_KEYS.get(prov, "ai.api_key")

    try:
        from app.database import AsyncSessionLocal
        from app.models.system_config import SystemConfig

        async with AsyncSessionLocal() as session:
            res = await session.execute(
                select(SystemConfig.value).where(SystemConfig.key == db_key)
            )
            db_val = res.scalar_one_or_none()
            if db_val and db_val.strip():
                api_key = db_val.strip()
    except Exception as e:
        logger.warning("Failed to read %s from db: %s", db_key, e)

    return api_key


async def is_ai_provider_configured(provider: Optional[str] = None) -> bool:
    """Check if the specified (or active) AI provider route is properly configured."""
    if not provider:
        route_id = await get_dynamic_ai_provider()
    else:
        route_id = provider_to_route_id(provider)

    try:
        from app.database import AsyncSessionLocal
        from app.models.ai_provider import AIProviderCredential, AIProviderRoute

        if route_id.startswith("oauth:"):
            async with AsyncSessionLocal() as session:
                res = await session.execute(
                    select(AIProviderCredential).where(
                        AIProviderCredential.route_id == route_id,
                        AIProviderCredential.enabled == True,
                    )
                )
                creds = res.scalars().all()
                return len(creds) > 0

        elif route_id.startswith("endpoint:"):
            async with AsyncSessionLocal() as session:
                res = await session.execute(
                    select(AIProviderRoute).where(
                        AIProviderRoute.id == route_id,
                        AIProviderRoute.enabled == True,
                    )
                )
                route = res.scalar_one_or_none()
                return route is not None

    except Exception as exc:
        logger.warning("is_ai_provider_configured: DB check failed for %s: %s", route_id, exc)

    # Direct providers and Copilot
    direct_prov = route_id.split(":", 1)[1] if route_id.startswith("direct:") else route_id

    from app.services.direct_proxy_routes import get_direct_route

    spec = get_direct_route(route_id)
    if spec is not None and not spec.supported:
        return False

    if direct_prov == ZEN_FREE:
        return True
    else:
        api_key = await get_dynamic_ai_api_key(direct_prov)
        return bool(api_key and api_key != "none")


async def get_configured_verifier_model() -> str:
    """Return the verifier model, qualifying legacy IDs against the active route."""
    active_route = await resolve_active_route_id()
    verifier_model: str | None = None

    try:
        from app.database import AsyncSessionLocal
        from app.models.system_config import SystemConfig

        async with AsyncSessionLocal() as session:
            res = await session.execute(
                select(SystemConfig.value).where(SystemConfig.key == "ai.verifier_model")
            )
            db_val = res.scalar_one_or_none()
            if db_val and db_val.strip():
                verifier_model = db_val.strip()
    except Exception as e:
        logger.warning("Failed to read ai.verifier_model from db: %s", e)

    return map_legacy_model_to_route(verifier_model, active_route, preserve_qualified=True)


async def get_configured_hunter_model() -> str:
    """Return the hunter model, qualifying legacy IDs against the active route."""
    active_route = await resolve_active_route_id()
    hunter_model: str | None = None

    try:
        from app.database import AsyncSessionLocal
        from app.models.system_config import SystemConfig

        async with AsyncSessionLocal() as session:
            res = await session.execute(
                select(SystemConfig.value).where(SystemConfig.key == "ai.hunter_model")
            )
            db_val = res.scalar_one_or_none()
            if db_val and db_val.strip():
                hunter_model = db_val.strip()
    except Exception as e:
        logger.warning("Failed to read ai.hunter_model from db: %s", e)

    return map_legacy_model_to_route(hunter_model, active_route, preserve_qualified=True)
