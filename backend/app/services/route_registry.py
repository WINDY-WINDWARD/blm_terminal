"""Route and model registry helpers for CLIProxyAPI provider management.

Centralizes:
- Active route resolution from `ai.provider` and defaults
- Normalization of legacy provider identifiers
- Route-qualified model ID formatting and parsing (`blm:<route_id>/<upstream_model>`)
- Mapping legacy model strings to route-qualified models
- Validating that models belong to the active route
- Idempotent route seeding for the eight supported OAuth providers
"""

from __future__ import annotations

import hashlib
import logging
from typing import Sequence

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.ai_provider import AIProviderRoute

logger = logging.getLogger(__name__)

# The eight approved OAuth providers supported via CLIProxyAPI
OAUTH_PROVIDERS: tuple[str, ...] = (
    "codex",
    "antigravity",
    "claude",
    "xai",
    "kimi",
    "kimi-ai",
    "meta",
    "devin",
)

OAUTH_PROVIDER_LABELS: dict[str, str] = {
    "codex": "Codex",
    "antigravity": "Antigravity",
    "claude": "Claude",
    "xai": "xAI",
    "kimi": "Kimi",
    "kimi-ai": "Kimi AI",
    "meta": "Meta",
    "devin": "Devin",
}

# Direct API-key providers supported on BLM native paths
DIRECT_PROVIDERS: tuple[str, ...] = (
    "zen-paid",
    "go",
    "aistudio",
    "groq",
    "nvidia",
    "anthropic",
    "claude-code",
    "openai",
    "openrouter",
    "deepseek",
    "xai",
    "together",
    "copilot",
)

DEFAULT_ROUTE_ID = "direct:aistudio"

# Default upstream model fallbacks per route kind/provider
DEFAULT_ROUTE_MODELS: dict[str, str] = {
    "oauth:codex": "gpt-4o",
    "oauth:antigravity": "gemini-3.8-flash-low",
    "oauth:claude": "claude-3-5-haiku-latest",
    "oauth:xai": "grok-2-latest",
    "oauth:kimi": "moonshot-v1-8k",
    "oauth:kimi-ai": "kimi-latest",
    "oauth:meta": "llama-3.3-70b-instruct",
    "oauth:devin": "devin-latest",
    "direct:aistudio": "gemini-2.5-flash",
    "direct:groq": "llama-3.3-70b-versatile",
    "direct:nvidia": "meta/llama-3.1-70b-instruct",
    "direct:anthropic": "claude-3-5-haiku-latest",
    "direct:claude-code": "claude-3-5-haiku-latest",
    "direct:openai": "gpt-4o-mini",
    "direct:openrouter": "deepseek/deepseek-chat",
    "direct:deepseek": "deepseek-chat",
    "direct:xai": "grok-2-latest",
    "direct:together": "meta-llama/Llama-3-70b-chat-hf",
    "direct:copilot": "gpt-4o",
    "direct:zen-paid": "minimax-m2.5",
    "direct:go": "minimax-m2.5",
}


def compute_oauth_proxy_prefix(route_id: str) -> str:
    """Compute stable proxy prefix: blm-<first 16 hex of sha256(route_id)>."""
    digest = hashlib.sha256(route_id.encode("utf-8")).hexdigest()[:16]
    return f"blm-{digest}"


def normalize_legacy_provider_id(raw_provider: str | None) -> str:
    """Normalize legacy provider identifiers.

    - None or empty string -> default 'aistudio'
    - 'gemini' -> 'antigravity' (Google OAuth proxy)
    - 'zen', 'zen-free' -> 'zen-paid'
    """
    if not raw_provider:
        return "aistudio"

    p = raw_provider.strip().lower()

    if p == "gemini":
        return "antigravity"
    elif p in ("zen", "zen-free"):
        return "zen-paid"

    return p


def provider_to_route_id(provider: str | None) -> str:
    """Map a provider string (legacy or modern) to a canonical route ID.

    Format:
    - Already-qualified route ID ('oauth:...', 'endpoint:...', 'direct:...') -> returned as-is
    - OAuth provider name ('codex', 'antigravity', etc.) -> 'oauth:<provider>'
    - Direct provider name ('openai', 'aistudio', etc.) -> 'direct:<provider>'
    - None or empty -> DEFAULT_ROUTE_ID ('direct:aistudio')
    """
    if not provider:
        return DEFAULT_ROUTE_ID

    p = provider.strip()
    if p.startswith("oauth:") or p.startswith("endpoint:") or p.startswith("direct:"):
        return p

    norm = normalize_legacy_provider_id(p)
    if norm in OAUTH_PROVIDERS:
        return f"oauth:{norm}"
    return f"direct:{norm}"


def format_route_model_id(route_id: str, upstream_model: str) -> str:
    """Format a public route-qualified model ID: blm:<route_id>/<upstream_model>."""
    route_clean = route_id.strip()
    model_clean = upstream_model.strip()
    if not route_clean:
        raise ValueError("route_id cannot be empty")
    if not model_clean:
        raise ValueError("upstream_model cannot be empty")
    return f"blm:{route_clean}/{model_clean}"


def parse_route_model_id(public_model_id: str) -> tuple[str, str]:
    """Parse a route-qualified model ID at the first slash after 'blm:'.

    Model IDs have format: blm:<route_id>/<upstream_model>
    Upstream model names may contain slashes (e.g. 'meta-llama/llama-3-70b-instruct').
    """
    if not isinstance(public_model_id, str):
        raise ValueError(f"Model ID must be a string, got {type(public_model_id).__name__}")

    raw = public_model_id.strip()
    if not raw.startswith("blm:"):
        raise ValueError(f"Invalid route-qualified model ID (missing 'blm:' prefix): {public_model_id}")

    remainder = raw[4:]  # len("blm:") == 4
    if "/" not in remainder:
        raise ValueError(f"Invalid route-qualified model ID (missing slash separator): {public_model_id}")

    route_id, upstream_model = remainder.split("/", 1)
    route_id = route_id.strip()
    upstream_model = upstream_model.strip()

    if not route_id:
        raise ValueError(f"Invalid route-qualified model ID (empty route): {public_model_id}")
    if not upstream_model:
        raise ValueError(f"Invalid route-qualified model ID (empty model): {public_model_id}")

    return route_id, upstream_model


def is_route_model_id(model_id: str | None) -> bool:
    """Check whether a model ID is formatted as a route-qualified model."""
    if not model_id or not isinstance(model_id, str):
        return False
    try:
        parse_route_model_id(model_id)
        return True
    except ValueError:
        return False


def map_legacy_model_to_route(model_str: str | None, route_id: str) -> str:
    """Map a legacy bare model string or stale route model to the target route."""
    if not model_str or not model_str.strip():
        default_model = DEFAULT_ROUTE_MODELS.get(route_id, "gpt-4o-mini")
        return format_route_model_id(route_id, default_model)

    raw = model_str.strip()
    if is_route_model_id(raw):
        parsed_route, upstream = parse_route_model_id(raw)
        if parsed_route == route_id:
            return raw
        # Remap upstream model to the requested route
        return format_route_model_id(route_id, upstream)

    # Bare model string (e.g. 'gpt-4o', 'gemini-3.8-flash-low', 'minimax-m2.5')
    return format_route_model_id(route_id, raw)


def validate_model_for_route(
    model_id: str | None,
    active_route_id: str,
    allowed_models: Sequence[str] | None = None,
) -> bool:
    """Validate that a model belongs to the active route and (optionally) is allowed."""
    if not model_id or not isinstance(model_id, str):
        return False

    try:
        route_id, upstream_model = parse_route_model_id(model_id)
    except ValueError:
        return False

    if route_id != active_route_id:
        return False

    if allowed_models is not None:
        if upstream_model not in allowed_models and model_id not in allowed_models:
            return False

    return True


def ensure_model_belongs_to_route(
    model_id: str,
    active_route_id: str,
    allowed_models: Sequence[str] | None = None,
) -> tuple[str, str]:
    """Ensure that a model belongs to the active route, raising ValueError on mismatch."""
    route_id, upstream_model = parse_route_model_id(model_id)
    if route_id != active_route_id:
        raise ValueError(
            f"Model '{model_id}' belongs to route '{route_id}', expected active route '{active_route_id}'"
        )

    if allowed_models is not None:
        if upstream_model not in allowed_models and model_id not in allowed_models:
            raise ValueError(
                f"Model '{upstream_model}' is not in the allowed catalog for route '{active_route_id}'"
            )

    return route_id, upstream_model


async def resolve_active_route_id(session: AsyncSession | None = None) -> str:
    """Resolve active route ID from `ai.provider` in system_config or schema defaults."""
    raw_provider: str | None = None

    if session is not None:
        from app.models.system_config import SystemConfig

        res = await session.execute(
            select(SystemConfig.value).where(SystemConfig.key == "ai.provider")
        )
        val = res.scalar_one_or_none()
        if val and val.strip():
            raw_provider = val.strip()
    else:
        try:
            from app.database import AsyncSessionLocal
            from app.models.system_config import SystemConfig

            async with AsyncSessionLocal() as db:
                res = await db.execute(
                    select(SystemConfig.value).where(SystemConfig.key == "ai.provider")
                )
                val = res.scalar_one_or_none()
                if val and val.strip():
                    raw_provider = val.strip()
        except Exception as exc:
            logger.warning("resolve_active_route_id: failed to query system_config: %s", exc)

    if not raw_provider:
        raw_provider = settings.ai_provider

    return provider_to_route_id(raw_provider)


async def seed_oauth_routes(session: AsyncSession) -> list[AIProviderRoute]:
    """Seed the eight OAuth routes idempotently with stable prefixes."""
    routes: list[AIProviderRoute] = []

    for provider in OAUTH_PROVIDERS:
        route_id = f"oauth:{provider}"
        display_label = OAUTH_PROVIDER_LABELS.get(provider, provider.capitalize())
        prefix = compute_oauth_proxy_prefix(route_id)

        stmt = select(AIProviderRoute).where(AIProviderRoute.id == route_id)
        res = await session.execute(stmt)
        existing = res.scalar_one_or_none()

        if existing is None:
            route = AIProviderRoute(
                id=route_id,
                kind="oauth",
                provider=provider,
                display_label=display_label,
                proxy_prefix=prefix,
                enabled=True,
                config_json="{}",
            )
            session.add(route)
            routes.append(route)
        else:
            routes.append(existing)

    await session.commit()
    return routes


def seed_oauth_routes_sync(engine_or_conn) -> None:
    """Seed the eight OAuth routes synchronously (used by migrations and lifespan)."""
    for provider in OAUTH_PROVIDERS:
        route_id = f"oauth:{provider}"
        display_label = OAUTH_PROVIDER_LABELS.get(provider, provider.capitalize())
        prefix = compute_oauth_proxy_prefix(route_id)

        sql = text(
            """
            INSERT OR IGNORE INTO ai_provider_routes (
                id, kind, provider, display_label, proxy_prefix, enabled, config_json, created_at, updated_at
            ) VALUES (
                :id, 'oauth', :provider, :display_label, :proxy_prefix, 1, '{}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            """
        )
        if hasattr(engine_or_conn, "connect"):
            with engine_or_conn.begin() as conn:
                conn.execute(
                    sql,
                    {
                        "id": route_id,
                        "provider": provider,
                        "display_label": display_label,
                        "proxy_prefix": prefix,
                    },
                )
        else:
            engine_or_conn.execute(
                sql,
                {
                    "id": route_id,
                    "provider": provider,
                    "display_label": display_label,
                    "proxy_prefix": prefix,
                },
            )
