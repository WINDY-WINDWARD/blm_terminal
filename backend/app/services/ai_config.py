"""Helper functions for dynamic AI configuration."""

import logging
import os
from typing import Optional

from sqlalchemy import select

from app.config import settings

logger = logging.getLogger(__name__)

# Provider identifiers. "zen" is a legacy alias kept for backward
# compatibility with installs that stored ai.provider="zen" before the
# free/paid split — it now always resolves to "zen-paid". "zen-free" is
# likewise a retired alias (OpenCode gated the external free tier); stored
# values resolve to "zen-paid" so old installs land on an honest
# not-configured state instead of a dead option.
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

    Returns 'zen-paid', 'go', 'gemini' (or 'antigravity'), 'aistudio',
    'groq', 'nvidia', etc. Retired aliases ('zen', 'zen-free') resolve to
    'zen-paid'.
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

    # Normalize retired aliases to "zen-paid" (same key slot): legacy "zen"
    # and the retired "zen-free" (external free tier is gated by OpenCode).
    if provider in ("zen", ZEN_FREE):
        provider = ZEN_PAID

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


async def is_ai_provider_configured(provider: Optional[str] = None) -> bool:
    """Check if the specified (or active) AI provider is properly configured."""
    if not provider:
        provider = await get_dynamic_ai_provider()

    if provider == "gemini":
        from app.services.antigravity_auth import get_antigravity_token
        token = await get_antigravity_token()
        return token is not None
    elif provider == "zen-free":
        # Free tier needs no key — always usable.
        return True
    elif provider == "codex":
        from app.services.codex_auth import get_codex_status
        status = await get_codex_status()
        return bool(status.get("logged_in"))
    elif provider == "copilot":
        from app.services.llm_provider import get_copilot_inference_token
        gh_token = await get_dynamic_ai_api_key("copilot")
        token, _, _ = await get_copilot_inference_token(gh_token or "none")
        return token is not None
    else:
        api_key = await get_dynamic_ai_api_key(provider)
        return bool(api_key and api_key != "none")


async def get_configured_verifier_model() -> str:
    """Return the user-configured verifier model, normalized for the active provider."""
    provider = await get_dynamic_ai_provider()
    verifier_model = None

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

    if provider == "gemini":
        from app.routers.system_config import normalize_gemini_worker_model
        return normalize_gemini_worker_model(verifier_model or "gemini-3.8-flash-low", default_tier="low")

    if verifier_model:
        return verifier_model

    # Sensible lightweight defaults per provider when unconfigured
    if provider == "zen-free":
        return "deepseek-v4-flash-free"
    elif provider in (ZEN_PAID, "zen"):
        return "minimax-m2.5"
    elif provider == AISTUDIO:
        return "gemini-2.5-flash"
    elif provider in (ANTHROPIC, CLAUDE_CODE):
        return "claude-3-5-haiku-latest"
    elif provider == CODEX:
        return "gpt-4o"
    elif provider == GROQ:
        return "llama-3.3-70b-versatile"
    elif provider == DEEPSEEK:
        return "deepseek-chat"
    else:
        return settings.ai_model or "gpt-4o-mini"
