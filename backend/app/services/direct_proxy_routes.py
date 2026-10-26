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
        models=("minimax-m2.5",),
    ),
    "direct:go": DirectRouteSpec(
        route_id="direct:go",
        provider="go",
        display_name="OpenCode Go",
        section="openai-compatibility",
        base_url="https://opencode.ai/zen/go/v1",
        models=("minimax-m2.5",),
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

        entries.append(entry)

    return entries
