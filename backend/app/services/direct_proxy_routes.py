"""Proxy configuration support for BLM's legacy ``direct:`` provider routes.

Each direct provider is mapped onto a CLIProxyAPI v8.0.39 configuration section so
that inference can be served by the bundled sidecar alone.  The mapping is derived
from empirical probes of the bundled binary, not from upstream documentation:

* ``openai-compatibility`` requires an explicit ``models`` list; undeclared models
  are rejected by the proxy with ``model_not_found``.
* ``gemini-api-key`` and ``claude-api-key`` accept ``api-key`` + ``prefix`` and omit
  ``models`` to expose the proxy's built-in catalog.
* Copilot is absent from the binary and Claude Code OAuth tokens (``sk-ant-oat``)
  cannot be used as static Claude keys, so both routes are unsupported.

Public model IDs (``blm:direct:<provider>/<model>``) and saved route selections are
unchanged; only the transport that serves them changes.
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from typing import Any, Literal

from app.services.route_registry import compute_oauth_proxy_prefix, get_disabled_direct_routes

logger = logging.getLogger(__name__)

Section = Literal["openai-compatibility", "gemini-api-key", "claude-api-key"]


@dataclass(frozen=True)
class DirectRouteSpec:
    route_id: str
    provider: str
    display_name: str
    section: Section | None
    base_url: str | None
    models: tuple[str, ...]
    unavailable_reason: str | None = None
    # OpenCode Go refuses chat requests without an ``x-opencode-session``
    # header (``MissingSessionID``). The sidecar never adds it, so it is
    # declared here and written into the openai-compatibility entry.
    requires_opencode_session: bool = False

    @property
    def supported(self) -> bool:
        return self.unavailable_reason is None


DIRECT_ROUTES: dict[str, DirectRouteSpec] = {
    "direct:aistudio": DirectRouteSpec(
        route_id="direct:aistudio",
        provider="aistudio",
        display_name="Google AI Studio",
        section="gemini-api-key",
        base_url=None,
        models=(),
    ),
    "direct:anthropic": DirectRouteSpec(
        route_id="direct:anthropic",
        provider="anthropic",
        display_name="Anthropic",
        section="claude-api-key",
        base_url=None,
        models=(),
    ),
    "direct:openai": DirectRouteSpec(
        route_id="direct:openai",
        provider="openai",
        display_name="OpenAI",
        section="openai-compatibility",
        base_url="https://api.openai.com/v1",
        models=(
            "gpt-4o",
            "gpt-4o-mini",
            "gpt-4.1",
            "gpt-4.1-mini",
            "gpt-4.1-nano",
            "o3",
            "o3-mini",
            "o4-mini",
        ),
    ),
    "direct:zen-paid": DirectRouteSpec(
        route_id="direct:zen-paid",
        provider="zen-paid",
        display_name="OpenCode Zen",
        section="openai-compatibility",
        base_url="https://opencode.ai/zen/v1",
        models=(
            "big-pickle",
            "mimo-v2.6-flash-free",
            "deepseek-v4.1-flash-free",
            "claude-fable-5",
            "claude-fable-5-1",
            "claude-haiku-4-5",
            "claude-haiku-5-5",
            "claude-opus-4-5",
            "claude-opus-4-6",
            "claude-opus-4-7",
            "claude-opus-4-8",
            "claude-opus-5",
            "claude-opus-5-5",
            "claude-sonnet-4-5",
            "claude-sonnet-4-6",
            "claude-sonnet-5",
            "claude-sonnet-5-5",
            "deepseek-v4.1-flash",
            "deepseek-v4-pro",
            "gemini-3.5-flash",
            "gemini-3.5-flash-lite",
            "gemini-3.6-flash",
            "gemini-3.7-flash",
            "gemini-3.8-flash",
            "gemini-4-argon",
            "glm-5.3",
            "glm-5.3-flash",
            "gpt-5",
            "gpt-5-codex",
            "gpt-5-nano",
            "gpt-5.1",
            "gpt-5.1-codex",
            "gpt-5.1-codex-max",
            "gpt-5.1-codex-mini",
            "gpt-5.2",
            "gpt-5.2-codex",
            "gpt-5.3-codex",
            "gpt-5.3-codex-spark",
            "gpt-5.4",
            "gpt-5.4-mini",
            "gpt-5.4-nano",
            "gpt-5.4-pro",
            "gpt-5.5",
            "gpt-5.5-pro",
            "gpt-5.6-luna",
            "gpt-5.6-sol",
            "gpt-6-astra",
            "gpt-6-sol",
            "gpt-6.1-sol",
            "gpt-6-luna",
            "gpt-5.6-terra",
            "grok-4.5",
            "grok-4.6",
            "grok-4.7",
            "grok-build-0.1",
            "kimi-k2.7-code",
            "kimi-k3",
            "minimax-m2.5",
            "minimax-m2.7",
            "minimax-m3",
            "muse-spark-1.2",
            "muse-spark-1.3",
            "muse-wonder-1.0",
            "mistral-large-4",
            "qwen3.5-plus",
            "qwen3.6-plus",
            "qwen3.8-flash",
            "qwen3.8-max",
            "iceman-free",
            "beam-free",
            "flint-40b-free",
            "nemotron-3.5-super-vl-free",
            "nemotron-3.5-lightning-free",
            "muse-ember-1.0",
            "claude-fable-5-2",
            "gemini-4-carbon",
            "gemini-4-hydrogen",
            "hy4-flash-free",
            "gpt-6.2-sol",
            "gpt-6.2-astra",
            "gemini-4-neon",
            "kimi-k3.1-pro",
            "seaglass-alpha-free",
        ),
    ),
    "direct:go": DirectRouteSpec(
        route_id="direct:go",
        provider="go",
        display_name="OpenCode Go",
        section="openai-compatibility",
        base_url="https://opencode.ai/zen/go/v1",
        models=(
            "deepseek-v4.1-flash",
            "deepseek-v4-pro",
            "glm-5.3",
            "grok-4.7",
            "muse-spark-1.2-contributor",
            "muse-spark-1.3-contributor",
            "glm-5.3-flash",
            "gpt-5.6-luna",
            "gpt-6-luna",
            "claude-haiku-5-5",
            "hy3",
            "hy4-preview",
            "kimi-k2.7-code",
            "kimi-k3",
            "mimo-v2.6-flash",
            "mimo-v2.6-pro",
            "minimax-m3",
            "minimax-m3.1-flash",
            "step-5-preview",
            "beam-free",
            "qwen3.8-max",
            "qwen3.8-flash",
            "qwen3.7-plus",
            "kimi-k3.1-pro",
            "iceman-contributor-free",
            "gemini-4-argon",
            "hy4",
            "hy4-flash-free",
            "qwen4-max",
            "longcat-2.5",
            "hungerg-free",
        ),
        requires_opencode_session=True,
    ),
    "direct:groq": DirectRouteSpec(
        route_id="direct:groq",
        provider="groq",
        display_name="Groq",
        section="openai-compatibility",
        base_url="https://api.groq.com/openai/v1",
        models=(
            "llama-3.3-70b-versatile",
            "llama-3.1-8b-instant",
            "openai/gpt-oss-120b",
            "openai/gpt-oss-20b",
            "qwen/qwen3-32b",
        ),
    ),
    "direct:nvidia": DirectRouteSpec(
        route_id="direct:nvidia",
        provider="nvidia",
        display_name="NVIDIA NIM",
        section="openai-compatibility",
        base_url="https://integrate.api.nvidia.com/v1",
        models=(
            "meta/llama-3.3-70b-instruct",
            "meta/llama-3.1-405b-instruct",
            "nvidia/llama-3.3-nemotron-super-49b-v1",
            "qwen/qwen2.5-72b-instruct",
            "deepseek-ai/deepseek-r1",
        ),
    ),
    "direct:openrouter": DirectRouteSpec(
        route_id="direct:openrouter",
        provider="openrouter",
        display_name="OpenRouter",
        section="openai-compatibility",
        base_url="https://openrouter.ai/api/v1",
        models=(
            "openai/gpt-4o-mini",
            "openai/gpt-4.1-mini",
            "anthropic/claude-sonnet-4.5",
            "google/gemini-2.5-flash",
            "deepseek/deepseek-chat",
            "meta-llama/llama-3.3-70b-instruct",
        ),
    ),
    "direct:deepseek": DirectRouteSpec(
        route_id="direct:deepseek",
        provider="deepseek",
        display_name="DeepSeek",
        section="openai-compatibility",
        base_url="https://api.deepseek.com/v1",
        models=("deepseek-chat", "deepseek-reasoner"),
    ),
    "direct:xai": DirectRouteSpec(
        route_id="direct:xai",
        provider="xai",
        display_name="xAI",
        section="openai-compatibility",
        base_url="https://api.x.ai/v1",
        models=("grok-4", "grok-3", "grok-3-mini", "grok-2-vision-1212"),
    ),
    "direct:together": DirectRouteSpec(
        route_id="direct:together",
        provider="together",
        display_name="Together AI",
        section="openai-compatibility",
        base_url="https://api.together.xyz/v1",
        models=(
            "meta-llama/Llama-3.3-70B-Instruct-Turbo",
            "meta-llama/Meta-Llama-3.1-405B-Instruct-Turbo",
            "Qwen/Qwen2.5-72B-Instruct-Turbo",
            "deepseek-ai/DeepSeek-V3",
        ),
    ),
    "direct:copilot": DirectRouteSpec(
        route_id="direct:copilot",
        provider="copilot",
        display_name="GitHub Copilot",
        section=None,
        base_url=None,
        models=(),
        unavailable_reason="CLIProxyAPI 8.0.39 has no GitHub Copilot provider",
    ),
    "direct:claude-code": DirectRouteSpec(
        route_id="direct:claude-code",
        provider="claude-code",
        display_name="Claude Code",
        section=None,
        base_url=None,
        models=(),
        unavailable_reason=(
            "CLIProxyAPI 8.0.39 rejects Claude Code OAuth tokens (sk-ant-oat) as static API keys"
        ),
    ),
}

SUPPORTED_ROUTE_IDS: tuple[str, ...] = (
    "direct:aistudio",
    "direct:anthropic",
    "direct:openai",
    "direct:zen-paid",
    "direct:go",
    "direct:groq",
    "direct:nvidia",
    "direct:openrouter",
    "direct:deepseek",
    "direct:xai",
    "direct:together",
)


def get_direct_route(route_id: str) -> DirectRouteSpec | None:
    return DIRECT_ROUTES.get(route_id)


def direct_proxy_prefix(route_id: str) -> str:
    """Stable model prefix for a direct route, shared with its config entry."""
    return compute_oauth_proxy_prefix(route_id)


def is_supported_direct_route(route_id: str) -> bool:
    spec = DIRECT_ROUTES.get(route_id)
    return bool(spec and spec.supported)


_GO_SESSION_KEY = "ai.go_session_id"
_GO_SESSION_FALLBACK = "blm-terminal-default-session"


async def _get_go_session_id() -> str:
    """Return a stable per-install session id for OpenCode Go.

    The value is created once and then reused, so gateway session affinity and
    prompt caching stay stable across proxy restarts.
    """
    try:
        from sqlalchemy import select
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        from app.database import AsyncSessionLocal
        from app.models.system_config import SystemConfig

        async with AsyncSessionLocal() as db_session:
            result = await db_session.execute(
                select(SystemConfig.value).where(SystemConfig.key == _GO_SESSION_KEY)
            )
            existing = result.scalar_one_or_none()
            if existing:
                return str(existing)

            new_value = f"blm-{secrets.token_hex(12)}"
            stmt = sqlite_insert(SystemConfig).values(
                key=_GO_SESSION_KEY,
                value=new_value,
            )
            await db_session.execute(stmt.on_conflict_do_nothing(index_elements=["key"]))
            await db_session.commit()
            return new_value
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Go session id unavailable (%s)", type(exc).__name__)
        return _GO_SESSION_FALLBACK


async def build_direct_proxy_entries(session: Any = None) -> list[dict[str, Any]]:
    """Build CLIProxyAPI config entries for every configured direct provider.

    Keys are read from the existing settings/SystemConfig sources and only exist in
    memory here; the caller writes them into the 0600 runtime config.
    """
    from app.services.ai_config import get_dynamic_ai_api_key

    disabled_routes: set[str] = set()
    if session is not None:
        disabled_routes = await get_disabled_direct_routes(session)
    else:
        from app.database import AsyncSessionLocal

        async with AsyncSessionLocal() as db_session:
            disabled_routes = await get_disabled_direct_routes(db_session)

    entries: list[dict[str, Any]] = []
    for route_id in SUPPORTED_ROUTE_IDS:
        if route_id in disabled_routes:
            continue
        spec = DIRECT_ROUTES[route_id]
        try:
            api_key = await get_dynamic_ai_api_key(spec.provider)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(
                "Direct route %s key lookup failed (%s)", route_id, type(exc).__name__
            )
            api_key = ""

        if not api_key or api_key == "none":
            continue

        entry: dict[str, Any] = {
            "section": spec.section,
            "name": spec.provider,
            "prefix": direct_proxy_prefix(route_id),
        }
        if spec.models:
            entry["models"] = [{"name": model} for model in spec.models]

        if spec.section == "openai-compatibility":
            entry["base-url"] = spec.base_url
            entry["api-key-entries"] = [{"api-key": api_key}]
        else:
            entry["api-key"] = api_key
            if spec.base_url:
                entry["base-url"] = spec.base_url

        if spec.requires_opencode_session:
            entry["headers"] = {"x-opencode-session": await _get_go_session_id()}

        entries.append(entry)

    return entries
