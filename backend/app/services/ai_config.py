"""Helper functions for dynamic AI configuration."""

import logging
import os
from typing import Optional

from sqlalchemy import select

from app.config import settings

logger = logging.getLogger(__name__)

# Provider identifiers. "zen" is a legacy alias kept for backward
# compatibility with installs that stored ai.provider="zen" before the
# free/paid split — it resolves to "zen-paid" when a key exists, else "zen-free".
ZEN_FREE = "zen-free"
ZEN_PAID = "zen-paid"
ZEN_PROVIDERS = (ZEN_FREE, ZEN_PAID)
AISTUDIO = "aistudio"
GROQ = "groq"
NVIDIA = "nvidia"
# --- Multi-provider additions (Hermes-style provider registry) ---
ANTHROPIC = "anthropic"      # api.anthropic.com with ANTHROPIC_API_KEY
CLAUDE_CODE = "claude-code"  # api.anthropic.com with CLAUDE_CODE_OAUTH_TOKEN (from `claude setup-token`)
OPENAI = "openai"            # api.openai.com with OPENAI_API_KEY
OPENROUTER = "openrouter"    # openrouter.ai with OPENROUTER_API_KEY
DEEPSEEK = "deepseek"        # api.deepseek.com with DEEPSEEK_API_KEY
XAI = "xai"                  # api.x.ai with XAI_API_KEY
TOGETHER = "together"        # api.together.xyz with TOGETHER_API_KEY
COPILOT = "copilot"          # api.githubcopilot.com via GH token exchange
CODEX = "codex"              # chatgpt.com/backend-api/codex via ChatGPT OAuth (device-code flow)

# Provider -> DB key slot for the credential (env var is read from settings first,
# DB value overrides when present).
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

# All provider ids valid for ai.provider (used by routers/UI for validation).
ALL_PROVIDERS: tuple[str, ...] = (
    ZEN_FREE, ZEN_PAID, "go", "gemini", "antigravity", "zen",
    AISTUDIO, GROQ, NVIDIA,
    ANTHROPIC, CLAUDE_CODE, OPENAI, OPENROUTER, DEEPSEEK, XAI, TOGETHER,
    COPILOT, CODEX,
)

async def get_dynamic_ai_provider() -> str:
    """Fetch AI Provider from settings or fallback to dynamic system_config.

    Returns 'zen-free', 'zen-paid', 'go', 'gemini' (or 'antigravity'),
    'aistudio', 'groq', or 'nvidia'.
    """
    provider = settings.ai_provider
    try:
        from app.database import AsyncSessionLocal
        from app.models.system_config import SystemConfig
        async with AsyncSessionLocal() as session:
            res = await session.execute(
                select(SystemConfig.value).where(SystemConfig.key == "ai.provider")
            )
            db_val = res.scalar_one_or_none()
            if db_val and db_val.strip():
                provider = db_val.strip().lower()
    except Exception as e:
        logger.warning("Failed to read ai.provider from db: %s", e)

    # Normalize legacy antigravity to gemini
    if provider == "antigravity":
        provider = "gemini"

    # Normalize legacy "zen" alias: paid when a key is stored, else free.
    if provider == "zen":
        legacy_key = await get_dynamic_ai_api_key("zen-paid")
        provider = ZEN_PAID if (legacy_key and legacy_key != "none") else ZEN_FREE

    return provider

async def get_dynamic_ai_api_key(provider: str) -> str:
    """Fetch the correct API key based on the dynamically selected provider."""
    # Free tier needs no key — the Zen gateway accepts "public" as the credential.
    if provider == ZEN_FREE:
        return "public"

    # Start with default environment variables based on provider
    api_key = settings.ai_api_key
    if provider in (ZEN_PAID, "zen"):
        api_key = settings.opencode_zen_api_key
    elif provider == AISTUDIO:
        api_key = settings.aistudio_api_key
    elif provider == GROQ:
        api_key = settings.groq_api_key
    elif provider == NVIDIA:
        api_key = settings.nvidia_api_key
    elif provider == ANTHROPIC:
        # ANTHROPIC_TOKEN is a valid alias (Hermes lists both).
        api_key = settings.anthropic_api_key
        if (not api_key or api_key == "none") and os.environ.get("ANTHROPIC_TOKEN"):
            api_key = os.environ["ANTHROPIC_TOKEN"]
    elif provider == CLAUDE_CODE:
        api_key = settings.claude_code_oauth_token
    elif provider == OPENAI:
        api_key = settings.openai_api_key
    elif provider == OPENROUTER:
        api_key = settings.openrouter_api_key
    elif provider == DEEPSEEK:
        api_key = settings.deepseek_api_key
    elif provider == XAI:
        api_key = settings.xai_api_key
    elif provider == TOGETHER:
        api_key = settings.together_api_key
    elif provider == COPILOT:
        # GitHub token aliases in priority order (mirrors Hermes' copilot profile):
        # COPILOT_GITHUB_TOKEN > GH_TOKEN > GITHUB_TOKEN > settings field.
        api_key = (
            os.environ.get("COPILOT_GITHUB_TOKEN")
            or os.environ.get("GH_TOKEN")
            or os.environ.get("GITHUB_TOKEN")
            or settings.copilot_gh_token
            or settings.gh_token
            or "none"
        )

    # Override with database values if present.
    # "zen-paid" (and legacy "zen") share the ai.zen_api_key slot so existing
    # installs keep working with zero migration.
    db_key = PROVIDER_DB_KEYS.get(provider, "ai.api_key")
    
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
