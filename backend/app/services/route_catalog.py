"""Model catalog resolution for AI provider routes."""

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.models.ai_provider import AIProviderCredential, AIProviderRoute
from app.services.proxy_supervisor import get_proxy_supervisor
from app.services.route_registry import (
    DIRECT_PROVIDERS,
    compute_oauth_proxy_prefix,
    format_route_model_id,
)
import app.services.ai_config as ai_config_module

logger = logging.getLogger(__name__)

ANTIGRAVITY_STATIC_MODELS = [
    "gemini-3.8-flash-high",
    "gemini-3.8-flash-medium",
    "gemini-3.8-flash-low",
]


# Model families that providers advertise but that cannot serve a chat turn.
# Image generators show up in the Codex/OpenAI credential list, and selecting
# one from a dropdown only ever produces a failed request.
_NONCHAT_MODEL_TOKENS = ("image", "dall-e", "imagen")


def is_chat_capable_model(model_id: str) -> bool:
    """Return False for models that cannot answer a chat completion."""
    lowered = (model_id or "").lower()
    return not any(token in lowered for token in _NONCHAT_MODEL_TOKENS)


def _filter_chat_models(models: list[str]) -> list[str]:
    """Drop non-chat model ids, preserving order and deduplicating."""
    kept: list[str] = []
    for model in models:
        if model and model not in kept and is_chat_capable_model(model):
            kept.append(model)
    return kept


def _clean_model_prefix(model: str, route: AIProviderRoute) -> str:
    """Strip route-specific proxy prefix or provider prefix from a model name."""
    prefix = (route.proxy_prefix or compute_oauth_proxy_prefix(route.id))
    prefix_slash = prefix if prefix.endswith("/") else f"{prefix}/"
    if model.startswith(prefix_slash):
        return model[len(prefix_slash):]
    if model.startswith(prefix):
        return model[len(prefix):].lstrip("/")
    if route.provider and model.startswith(f"{route.provider}/"):
        return model[len(route.provider) + 1:]
    return model


def _read_auth_file_hints(supervisor, route: AIProviderRoute, credentials: list[AIProviderCredential]) -> list[str]:
    """Extract model hints from local auth files without inspecting secrets or tokens."""
    auth_dir = getattr(supervisor, "auth_dir", None)
    if not auth_dir or not isinstance(auth_dir, Path) or not auth_dir.is_dir():
        return []
    try:
        auth_root = auth_dir.resolve()
    except (OSError, RuntimeError):
        return []

    hint_files: list[str] = []
    for cred in credentials:
        name = cred.proxy_credential_name
        name = name if name.endswith(".json") else f"{name}.json"
        if name not in hint_files:
            hint_files.append(name)

    default_name = f"{route.provider}.json"
    if default_name not in hint_files:
        hint_files.append(default_name)

    extracted: list[str] = []
    for fname in hint_files:
        fpath = auth_dir / fname
        try:
            if not fpath.is_file() or fpath.is_symlink() or not fpath.resolve().is_relative_to(auth_root):
                continue
            raw = fpath.read_text(encoding="utf-8")
            data = json.loads(raw)
        except (OSError, RuntimeError, ValueError):
            continue

        if not isinstance(data, dict):
            continue

        model_ids = None
        if "antigravity_capability_hints" in data and isinstance(data["antigravity_capability_hints"], dict):
            model_ids = data["antigravity_capability_hints"].get("model_ids")
        elif f"{route.provider}_capability_hints" in data and isinstance(data[f"{route.provider}_capability_hints"], dict):
            model_ids = data[f"{route.provider}_capability_hints"].get("model_ids")
        elif "capability_hints" in data and isinstance(data["capability_hints"], dict):
            model_ids = data["capability_hints"].get("model_ids")
        elif "model_ids" in data:
            model_ids = data.get("model_ids")
        else:
            for k, v in data.items():
                if k.endswith("_capability_hints") and isinstance(v, dict) and "model_ids" in v:
                    model_ids = v.get("model_ids")
                    break

        if isinstance(model_ids, list):
            for m in model_ids:
                if isinstance(m, str) and m.strip():
                    cleaned = _clean_model_prefix(m.strip(), route)
                    if cleaned and cleaned not in extracted and is_chat_capable_model(cleaned):
                        extracted.append(cleaned)

    return sorted(extracted)


async def _fetch_credential_models(management, name: str, timeout: float) -> list[str]:
    fname = name if name.endswith(".json") else f"{name}.json"
    return await asyncio.wait_for(management.get_credential_models(fname), timeout=timeout)


async def _fetch_live_models(
    route: AIProviderRoute,
    credentials: list[AIProviderCredential],
    live_timeout: float = 5.0,
) -> tuple[list[str], bool, bool]:
    """Fetch live models for an OAuth route without starting the sidecar."""
    supervisor = get_proxy_supervisor()
    management = None
    any_timeout = False
    any_error = False
    live_models: list[str] = []

    if not credentials:
        return live_models, any_timeout, any_error

    try:
        is_running = getattr(supervisor, "is_running", False)
        if callable(is_running):
            is_running = is_running()
        if not is_running:
            return live_models, False, True
        management = supervisor.get_management_client()
    except Exception as e:
        logger.debug("Failed obtaining management client for route %s: %s", route.id, e)
        err_str = str(e).lower()
        if "timeout" in err_str or "readtimeout" in err_str:
            any_timeout = True
        else:
            any_error = True

    if management is not None:
        tasks = [_fetch_credential_models(management, c.proxy_credential_name, live_timeout) for c in credentials]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for res in results:
            if isinstance(res, (asyncio.TimeoutError, TimeoutError)):
                any_timeout = True
            elif isinstance(res, Exception):
                err_str = str(res).lower()
                if "timeout" in err_str or "readtimeout" in err_str:
                    any_timeout = True
                else:
                    any_error = True
            elif isinstance(res, list):
                for raw in res:
                    if isinstance(raw, str) and raw.strip():
                        cleaned = _clean_model_prefix(raw.strip(), route)
                        if cleaned and cleaned not in live_models and is_chat_capable_model(cleaned):
                            live_models.append(cleaned)

    return live_models, any_timeout, any_error


async def _persist_cached_models(
    route: AIProviderRoute,
    session,
    models: list[str],
) -> None:
    """Best-effort persistence of discovered models into route's config_json."""
    if not models or session is None:
        return
    try:
        cfg = json.loads(route.config_json or "{}")
        cfg["cached_models"] = models
        route.config_json = json.dumps(cfg)
        await session.commit()
    except Exception as e:
        logger.debug("Failed writing cached_models for route %s: %s", route.id, e)
        try:
            await session.rollback()
        except Exception as rollback_error:
            logger.debug(
                "Failed rolling back cached_models write for route %s (%s)",
                route.id,
                type(rollback_error).__name__,
            )


def _build_model_warning(
    route_id: str,
    any_timeout: bool,
    any_error: bool,
) -> dict:
    """Build standardized warning dict following precedence: timeout > error > unavailable."""
    if any_timeout:
        code = "model_list_timeout"
        message = "Model list timed out"
    elif any_error:
        code = "model_list_error"
        message = "Model list discovery failed"
    else:
        code = "model_list_unavailable"
        message = "Model list unavailable"
    return {
        "route_id": route_id,
        "code": code,
        "message": message,
    }


def _resolve_fallback_models(
    route: AIProviderRoute,
    credentials: list[AIProviderCredential],
    supervisor,
) -> list[str]:
    """Resolve models from route config cached_models, auth file hints, or static fallbacks."""
    # Step 2: cached_models from route config
    try:
        cfg = json.loads(route.config_json or "{}")
        cached = cfg.get("cached_models") or []
        if isinstance(cached, list) and cached:
            cleaned_cached = []
            for m in cached:
                if isinstance(m, str) and m.strip():
                    cleaned = _clean_model_prefix(m.strip(), route)
                    if cleaned and cleaned not in cleaned_cached and is_chat_capable_model(cleaned):
                        cleaned_cached.append(cleaned)
            if cleaned_cached:
                return sorted(cleaned_cached)
    except Exception:
        pass

    # Step 3: Local auth-file hints
    hints = _read_auth_file_hints(supervisor, route, credentials)
    if hints:
        return _filter_chat_models(hints)

    # Step 4: Static Antigravity fallback
    if route.provider == "antigravity" or route.id == "oauth:antigravity":
        return _filter_chat_models(list(ANTIGRAVITY_STATIC_MODELS))

    # Curated Codex fallback
    if route.provider == "codex" or route.id == "oauth:codex":
        try:
            from app.services.codex_auth import CODEX_MODELS
            curated = [m["id"] for m in CODEX_MODELS if isinstance(m, dict) and m.get("id")]
            if curated:
                return _filter_chat_models(list(dict.fromkeys(curated)))
        except Exception:
            pass

    return []


async def _resolve_oauth_route_models(
    route: AIProviderRoute,
    session,
    credentials: list[AIProviderCredential] | None = None,
    live_timeout: float = 5.0,
) -> tuple[list[str], dict | None]:
    """Resolve models for an OAuth route using the resilient fallback chain."""
    if credentials is None:
        creds = list((await session.execute(
            select(AIProviderCredential).where(
                AIProviderCredential.route_id == route.id,
                AIProviderCredential.enabled == True,
                AIProviderCredential.kind == "oauth",
            )
        )).scalars().all())
    else:
        creds = credentials

    live_models, any_timeout, any_error = await _fetch_live_models(route, creds, live_timeout)

    if live_models:
        final_live = sorted(live_models)
        await _persist_cached_models(route, session, final_live)
        return final_live, None

    supervisor = get_proxy_supervisor()
    fallback = _resolve_fallback_models(route, creds, supervisor)
    if fallback:
        return fallback, None

    return [], _build_model_warning(route.id, any_timeout, any_error)


async def get_route_models(route_id: str, session=None, *, live_timeout: float = 5.0) -> list[str]:
    """Return model IDs for a single route with resilient fallback."""
    if route_id.startswith("direct:"):
        from app.services.direct_proxy_routes import (
            direct_proxy_prefix,
            get_direct_route,
            is_supported_direct_route,
        )
        from app.services.route_registry import get_disabled_direct_routes

        if session is not None:
            disabled_direct = await get_disabled_direct_routes(session)
        else:
            try:
                from app.database import AsyncSessionLocal

                async with AsyncSessionLocal() as database:
                    disabled_direct = await get_disabled_direct_routes(database)
            except Exception:
                disabled_direct = set()

        if route_id in disabled_direct:
            raise ValueError("Selected provider route is unavailable")

        if not is_supported_direct_route(route_id):
            return []

        spec = get_direct_route(route_id)
        if spec is None:
            return []

        if spec.models:
            return _filter_chat_models(list(spec.models))

        # Aistudio/anthropic carry no static list; only ask the proxy when the
        # route actually has credentials. Unconfigured routes must not start or
        # query the sidecar just to render the provider list.
        from app.services.ai_config import is_ai_provider_configured

        if not await is_ai_provider_configured(route_id):
            return []

        supervisor = get_proxy_supervisor()
        return _filter_chat_models(await supervisor.list_proxy_models(direct_proxy_prefix(route_id)))

    if session is None:
        try:
            from app.database import AsyncSessionLocal
            async with AsyncSessionLocal() as database:
                return await get_route_models(route_id, database, live_timeout=live_timeout)
        except Exception:
            if route_id == "oauth:antigravity":
                return _filter_chat_models(list(ANTIGRAVITY_STATIC_MODELS))
            raise

    route = (await session.execute(select(AIProviderRoute).where(AIProviderRoute.id == route_id))).scalar_one_or_none()
    if route is None or not route.enabled:
        if route_id == "oauth:antigravity":
            return _filter_chat_models(list(ANTIGRAVITY_STATIC_MODELS))
        raise ValueError("Selected provider route is unavailable")

    if route.kind == "endpoint":
        cfg = json.loads(route.config_json or "{}")
        return _filter_chat_models(list(cfg.get("models") or cfg.get("cached_models") or []))

    models, _ = await _resolve_oauth_route_models(route, session, live_timeout=live_timeout)
    return _filter_chat_models(models)


async def get_route_catalog(route_id: str, session=None, *, live_timeout: float = 5.0) -> list[dict[str, str]]:
    """Return formatted route models for chat/selectors."""
    try:
        models = await get_route_models(route_id, session=session, live_timeout=live_timeout)
        return [{"id": format_route_model_id(route_id, model), "label": model} for model in models]
    except Exception as exc:
        logger.warning("get_route_catalog failed for %s: %s", route_id, exc)
        return []


async def get_all_route_catalogs(
    session=None,
    *,
    live_timeout: float = 5.0,
    total_timeout: float = 10.0,
) -> tuple[list[dict], list[dict]]:
    """Return catalog of all configured routes and safe warnings."""
    if session is None:
        from app.database import AsyncSessionLocal
        async with AsyncSessionLocal() as database:
            return await get_all_route_catalogs(
                database,
                live_timeout=live_timeout,
                total_timeout=total_timeout,
            )

    routes_out: list[dict] = []
    warnings_out: list[dict] = []

    stmt = select(AIProviderRoute).where(AIProviderRoute.enabled == True)
    res = await session.execute(stmt)
    db_routes = list(res.scalars().all())

    db_route_ids = set()
    oauth_work: list[tuple[AIProviderRoute, list[AIProviderCredential]]] = []
    endpoint_routes: list[tuple[AIProviderRoute, list[str]]] = []

    for route in db_routes:
        db_route_ids.add(route.id)
        if route.kind == "oauth":
            creds = list((await session.execute(
                select(AIProviderCredential).where(
                    AIProviderCredential.route_id == route.id,
                    AIProviderCredential.enabled == True,
                    AIProviderCredential.kind == "oauth",
                )
            )).scalars().all())
            # Skip unconfigured OAuth routes
            if creds:
                oauth_work.append((route, creds))

        elif route.kind == "endpoint":
            cfg = json.loads(route.config_json or "{}")
            stored = _filter_chat_models(list(cfg.get("models") or cfg.get("cached_models") or []))
            if stored:
                endpoint_routes.append((route, stored))

    # Concurrently fetch live models for all OAuth routes under a shared total budget
    fetch_coros = [_fetch_live_models(route, creds, live_timeout) for route, creds in oauth_work]
    results: list = []
    if fetch_coros:
        try:
            results = await asyncio.wait_for(
                asyncio.gather(*fetch_coros, return_exceptions=True),
                timeout=total_timeout,
            )
        except (asyncio.TimeoutError, TimeoutError):
            results = [asyncio.TimeoutError() for _ in oauth_work]

    supervisor = get_proxy_supervisor()
    oauth_output: dict[str, dict] = {}
    oauth_warnings: dict[str, dict] = {}

    # Resolve OAuth routes serially (DB writes only); network work already ran
    # concurrently above.
    for idx, (route, creds) in enumerate(oauth_work):
        res = results[idx] if idx < len(results) else asyncio.TimeoutError()

        if isinstance(res, (asyncio.TimeoutError, TimeoutError)):
            live_models, any_timeout, any_error = [], True, False
        elif isinstance(res, Exception):
            err_str = str(res).lower()
            if "timeout" in err_str or "readtimeout" in err_str:
                live_models, any_timeout, any_error = [], True, False
            else:
                live_models, any_timeout, any_error = [], False, True
        else:
            live_models, any_timeout, any_error = res

        if live_models:
            final_live = sorted(live_models)
            await _persist_cached_models(route, session, final_live)
            oauth_output[route.id] = {
                "route_id": route.id,
                "label": route.display_label,
                "kind": "oauth",
                "provider": route.provider,
                "models": [{"id": format_route_model_id(route.id, m), "label": m} for m in final_live],
            }
            continue

        fallback = _resolve_fallback_models(route, creds, supervisor)
        if fallback:
            oauth_output[route.id] = {
                "route_id": route.id,
                "label": route.display_label,
                "kind": "oauth",
                "provider": route.provider,
                "models": [{"id": format_route_model_id(route.id, m), "label": m} for m in fallback],
            }
        else:
            oauth_warnings[route.id] = _build_model_warning(route.id, any_timeout, any_error)

    # Emit OAuth and endpoint routes in their original database order.
    endpoint_stored = {route.id: stored for route, stored in endpoint_routes}
    for route in db_routes:
        if route.kind == "oauth":
            entry = oauth_output.get(route.id)
            if entry is not None:
                routes_out.append(entry)
                continue
            warning = oauth_warnings.get(route.id)
            if warning is not None:
                warnings_out.append(warning)
        elif route.kind == "endpoint":
            stored = endpoint_stored.get(route.id)
            if not stored:
                continue
            routes_out.append({
                "route_id": route.id,
                "label": route.display_label,
                "kind": "endpoint",
                "provider": route.provider or "custom",
                "models": [{"id": format_route_model_id(route.id, m), "label": m} for m in stored],
            })

    from app.services.direct_proxy_routes import (
        SUPPORTED_ROUTE_IDS,
        direct_proxy_prefix,
        get_direct_route,
    )
    from app.services.route_registry import get_disabled_direct_routes

    disabled_direct = await get_disabled_direct_routes(session)

    for route_id in SUPPORTED_ROUTE_IDS:
        if route_id in db_route_ids or route_id in disabled_direct:
            continue

        spec = get_direct_route(route_id)
        if spec is None or not spec.supported:
            continue

        try:
            configured = await ai_config_module.is_ai_provider_configured(route_id)
        except Exception:
            configured = False

        if not configured:
            continue

        try:
            prefix = direct_proxy_prefix(route_id)
            if spec.models:
                resolved_models = list(spec.models)
            else:
                resolved_models = await supervisor.list_proxy_models(prefix)
            resolved_models = _filter_chat_models(list(resolved_models))
            model_entries = []
            for mid in resolved_models:
                if mid:
                    model_entries.append({
                        "id": format_route_model_id(route_id, mid),
                        "label": mid,
                    })
            if model_entries:
                routes_out.append({
                    "route_id": route_id,
                    "label": spec.display_name,
                    "kind": "direct",
                    "provider": spec.provider,
                    "models": model_entries,
                })
        except Exception as exc:
            logger.warning("Failed fetching models for direct route %s: %s", route_id, exc)

    return routes_out, warnings_out
