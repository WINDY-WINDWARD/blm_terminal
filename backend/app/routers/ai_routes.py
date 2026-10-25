"""FastAPI router for AI provider route management, OAuth flows, and custom endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import time
from typing import Any
import uuid

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import get_current_user
from app.database import get_db
from app.models.ai_provider import AIProviderCredential, AIProviderRoute
from app.models.system_config import SystemConfig
from app.models.user import User
from app.schemas.ai_provider import (
    AccountPatchRequest,
    CreateEndpointRequest,
    CredentialSummary,
    EndpointKeyInput,
    EndpointKeyUpdate,
    ModelPreviewRequest,
    OAuthCallbackRequest,
    OAuthCancelRequest,
    OAuthStartRequest,
    RouteSettingsUpdate,
    RouteSummary,
    RoutesListResponse,
    UpdateEndpointRequest,
)
from app.services.ai_config import is_ai_provider_configured
from app.services.endpoint_validator import (
    mask_api_key,
    mask_identity,
    validate_custom_endpoint_url,
)
from app.services.llm_provider import get_proxy_traces
from app.services.oauth_session_manager import OAuthPortConflictError, get_oauth_session_manager
from app.services.provider_vault import (
    ProviderVault,
    VaultState,
    get_provider_vault,
)
from app.services.proxy_supervisor import (
    ProxySupervisor,
    get_proxy_supervisor,
    load_routing_settings,
    routing_config,
)
from app.services.route_registry import (
    DEFAULT_ROUTE_ID,
    DEFAULT_ROUTE_MODELS,
    DIRECT_PROVIDERS,
    OAUTH_PROVIDERS,
    OAUTH_PROVIDER_LABELS,
    compute_oauth_proxy_prefix,
    format_route_model_id,
    provider_to_route_id,
    resolve_active_route_id,
    seed_oauth_routes,
)

logger = logging.getLogger("blm.ai_routes")

router = APIRouter(
    prefix="/ai/routes",
    tags=["ai-routes"],
    dependencies=[Depends(get_current_user)],
)


def _serialize_credential(cred: AIProviderCredential) -> CredentialSummary:
    """Format credential into redacted CredentialSummary."""
    return CredentialSummary(
        id=cred.id,
        route_id=cred.route_id,
        kind=cred.kind,
        masked_identity=cred.masked_identity,
        priority=cred.priority,
        weight=cred.weight,
        enabled=cred.enabled,
        status=cred.status,
        cooldown=cred.cooldown,
        last_redacted_error=cred.last_redacted_error,
        created_at=cred.created_at,
        updated_at=cred.updated_at,
    )


def _route_health(
    is_active: bool,
    is_configured: bool,
    proxy_status: dict[str, Any],
    *,
    is_healthy: bool,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Derive standardized health payload for a route summary."""
    status_label = "active" if is_active else ("configured" if is_configured else "unconfigured")
    health = {
        "healthy": is_healthy,
        "status": status_label,
        "proxy_status": proxy_status.get("state", "stopped"),
    }
    if extra:
        health.update(extra)
    return health


def _oauth_route_summary(
    r: AIProviderRoute,
    is_active: bool,
    proxy_status: dict[str, Any],
    vault: ProviderVault,
    recovery_state: str | None,
) -> RouteSummary:
    """Build RouteSummary for an OAuth provider route."""
    creds = r.credentials or []
    active_creds = [c for c in creds if c.enabled]
    accounts = [_serialize_credential(c) for c in creds]
    models = [DEFAULT_ROUTE_MODELS.get(r.id, "default")]
    is_healthy = bool(active_creds) and proxy_status.get("state") != "crashed" and vault.is_available
    health = _route_health(
        is_active=is_active,
        is_configured=bool(active_creds),
        proxy_status=proxy_status,
        is_healthy=is_healthy,
        extra={"account_count": len(accounts)},
    )
    return RouteSummary(
        id=r.id,
        kind="oauth",
        provider=r.provider,
        display_label=r.display_label,
        proxy_prefix=r.proxy_prefix,
        enabled=r.enabled,
        is_active=is_active,
        health=health,
        accounts=accounts,
        keys=[],
        config={},
        models=models,
        recovery_state=recovery_state if not vault.is_available else None,
    )


def _parse_custom_config(config_json: str | None) -> tuple[dict[str, Any], list[str]]:
    """Parse custom endpoint config_json into (config_summary, models)."""
    cfg: dict[str, Any] = {}
    if config_json:
        try:
            cfg = json.loads(config_json)
        except Exception:
            pass
    summary = {
        "base_url": cfg.get("base_url", ""),
        "warning_flags": cfg.get("warning_flags", []),
        "has_headers": bool(cfg.get("header_names", [])),
        "header_names": cfg.get("header_names", []),
    }
    return summary, cfg.get("models") or ["default"]


def _custom_route_summary(
    r: AIProviderRoute,
    is_active: bool,
    proxy_status: dict[str, Any],
    vault: ProviderVault,
    recovery_state: str | None,
) -> RouteSummary:
    """Build RouteSummary for a custom endpoint route."""
    creds = r.credentials or []
    active_creds = [c for c in creds if c.enabled]
    keys = [_serialize_credential(c) for c in creds]
    config_summary, models = _parse_custom_config(r.config_json)
    is_healthy = bool(active_creds) and proxy_status.get("state") != "crashed" and vault.is_available
    health = _route_health(
        is_active=is_active,
        is_configured=bool(active_creds),
        proxy_status=proxy_status,
        is_healthy=is_healthy,
        extra={"key_count": len(keys)},
    )
    return RouteSummary(
        id=r.id,
        kind="endpoint",
        provider="custom",
        display_label=r.display_label,
        proxy_prefix=r.proxy_prefix,
        enabled=r.enabled,
        is_active=is_active,
        health=health,
        accounts=[],
        keys=keys,
        config=config_summary,
        models=models,
        recovery_state=recovery_state if not vault.is_available else None,
    )


async def _direct_route_summary(
    route_id: str,
    spec: Any,
    is_active: bool,
    proxy_status: dict[str, Any],
    db: AsyncSession,
) -> RouteSummary:
    """Build RouteSummary for a supported direct route."""
    from app.services.direct_proxy_routes import direct_proxy_prefix
    from app.services.route_catalog import get_route_models

    is_configured = False
    try:
        is_configured = await is_ai_provider_configured(route_id)
    except Exception:
        pass

    models = (await get_route_models(route_id, db)) or list(spec.models)
    health = _route_health(
        is_active=is_active,
        is_configured=is_configured,
        proxy_status=proxy_status,
        is_healthy=bool(is_configured and models and proxy_status.get("state") != "crashed"),
        extra={"transport": "proxy"},
    )
    return RouteSummary(
        id=route_id,
        kind="direct",
        provider=spec.provider,
        display_label=spec.display_name,
        proxy_prefix=direct_proxy_prefix(route_id),
        enabled=True,
        is_active=is_active,
        health=health,
        accounts=[],
        keys=[],
        config={"is_configured": is_configured, "transport": "proxy"},
        models=models,
        recovery_state=None,
    )


async def _load_routing_settings_summary(db: AsyncSession) -> dict[str, Any]:
    """Query routing settings from SystemConfig with default fallback values."""
    settings_dict = {
        "strategy": "fill-first",
        "session_affinity": True,
        "session_affinity_ttl": "1h",
        "request_retry": 3,
        "max_retry_credentials": 0,
        "max_retry_interval": 30,
    }
    keys_to_fetch = [
        "ai.routing_strategy",
        "ai.session_affinity",
        "ai.session_affinity_ttl",
        "ai.request_retry",
        "ai.max_retry_credentials",
        "ai.max_retry_interval",
    ]
    try:
        stmt = select(SystemConfig).where(SystemConfig.key.in_(keys_to_fetch))
        res = await db.execute(stmt)
        for row in res.scalars().all():
            if row.key == "ai.routing_strategy" and row.value:
                settings_dict["strategy"] = row.value.strip()
            elif row.key == "ai.session_affinity" and row.value:
                settings_dict["session_affinity"] = row.value.strip().lower() in ("true", "1", "yes")
            elif row.key == "ai.session_affinity_ttl" and row.value:
                settings_dict["session_affinity_ttl"] = row.value.strip()
            elif row.key == "ai.request_retry" and row.value:
                try:
                    settings_dict["request_retry"] = int(row.value)
                except ValueError:
                    pass
            elif row.key == "ai.max_retry_credentials" and row.value:
                try:
                    settings_dict["max_retry_credentials"] = int(row.value)
                except ValueError:
                    pass
            elif row.key == "ai.max_retry_interval" and row.value:
                try:
                    settings_dict["max_retry_interval"] = int(row.value)
                except ValueError:
                    pass
    except Exception as exc:
        logger.debug("Failed querying routing settings: %s", exc)
    return settings_dict


# ---------------------------------------------------------------------------
# Route Listing and Status
# ---------------------------------------------------------------------------

@router.get("", response_model=RoutesListResponse)
@router.get("/", response_model=RoutesListResponse)
async def list_routes(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RoutesListResponse:
    """List all AI provider routes with redacted credential summaries and health status."""
    from app.services.direct_proxy_routes import SUPPORTED_ROUTE_IDS, get_direct_route

    active_route_id = await resolve_active_route_id(db)
    vault = get_provider_vault()
    await vault.get_state()
    vault_state = vault.state.value
    recovery_state = (
        f"Provider vault is {vault_state}. OAuth and custom endpoints are operating in degraded mode; "
        "direct providers remain fully usable."
        if not vault.is_available else None
    )

    proxy_status = get_proxy_supervisor().get_status()
    settings_dict = await _load_routing_settings_summary(db)

    db_routes: list[AIProviderRoute] = []
    try:
        r_stmt = select(AIProviderRoute).options(selectinload(AIProviderRoute.credentials))
        db_routes = list((await db.execute(r_stmt)).scalars().all())
    except Exception as exc:
        logger.warning("Failed querying ai_provider_routes: %s", exc)

    routes_out: list[RouteSummary] = []
    for r in db_routes:
        is_active = (r.id == active_route_id)
        if r.kind == "oauth":
            routes_out.append(_oauth_route_summary(r, is_active, proxy_status, vault, recovery_state))
        elif r.kind == "endpoint":
            routes_out.append(_custom_route_summary(r, is_active, proxy_status, vault, recovery_state))

    db_route_ids = {r.id for r in db_routes}
    for route_id in SUPPORTED_ROUTE_IDS:
        if route_id in db_route_ids:
            continue
        spec = get_direct_route(route_id)
        if spec is not None and spec.supported:
            routes_out.append(await _direct_route_summary(route_id, spec, route_id == active_route_id, proxy_status, db))

    return RoutesListResponse(
        routes=routes_out,
        active_route_id=active_route_id,
        proxy_status=proxy_status,
        vault_state=vault_state,
        recovery_state=recovery_state,
        settings=settings_dict,
    )


class RouteModelItem(BaseModel):
    id: str
    label: str


class RouteModelsEntry(BaseModel):
    route_id: str
    label: str
    kind: str
    provider: str
    models: list[RouteModelItem]


class RouteModelWarning(BaseModel):
    route_id: str
    code: str
    message: str


class RouteModelsResponse(BaseModel):
    routes: list[RouteModelsEntry]
    warnings: list[RouteModelWarning] = []


@router.get("/models", response_model=RouteModelsResponse)
async def get_routes_models(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RouteModelsResponse:
    """Return aggregated model catalog across all configured routes with partial results and warnings."""
    from app.services.route_catalog import get_all_route_catalogs
    routes, warnings = await get_all_route_catalogs(session=db)
    return RouteModelsResponse(routes=routes, warnings=warnings)


# ---------------------------------------------------------------------------
# Route Activation and Settings
# ---------------------------------------------------------------------------

@router.post("/{route_id}/activate")
async def activate_route(
    route_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Activate an AI provider route as the active BLM inference route."""
    clean_id = route_id.strip()

    # Validate route_id existence and validity
    if clean_id.startswith("oauth:"):
        prov = clean_id.split(":", 1)[1]
        if prov not in OAUTH_PROVIDERS:
            raise HTTPException(status_code=400, detail=f"Invalid OAuth provider: {prov}")
        res = await db.execute(select(AIProviderRoute).where(AIProviderRoute.id == clean_id))
        r = res.scalar_one_or_none()
        if not r or not r.enabled:
            raise HTTPException(status_code=404, detail=f"OAuth route '{clean_id}' is not configured or disabled.")
    elif clean_id.startswith("endpoint:"):
        res = await db.execute(select(AIProviderRoute).where(AIProviderRoute.id == clean_id))
        r = res.scalar_one_or_none()
        if not r or not r.enabled:
            raise HTTPException(status_code=404, detail=f"Custom endpoint route '{clean_id}' not found or disabled.")
    elif clean_id.startswith("direct:"):
        from app.services.direct_proxy_routes import get_direct_route, is_supported_direct_route
        spec = get_direct_route(clean_id)
        if spec is None or not is_supported_direct_route(clean_id):
            reason = (spec.unavailable_reason if spec else None) or f"Direct route '{clean_id}' is unsupported by the proxy."
            raise HTTPException(status_code=400, detail=reason)
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid route_id '{clean_id}'. Must start with 'oauth:', 'endpoint:', or 'direct:'.",
        )

    # Update or insert ai.provider in SystemConfig
    res = await db.execute(select(SystemConfig).where(SystemConfig.key == "ai.provider"))
    row = res.scalar_one_or_none()
    if row is not None:
        row.value = clean_id
    else:
        db.add(SystemConfig(key="ai.provider", value=clean_id))
    await db.commit()

    # Ensure proxy is ready for active route (oauth, endpoint, or supported direct)
    supervisor = get_proxy_supervisor()
    if not supervisor.is_running:
        try:
            await supervisor.ensure_started()
        except Exception as exc:
            logger.warning("Proxy supervisor start failed during route activation: %s", exc)

    return {"status": "activated", "active_route_id": clean_id}


@router.patch("/settings")
async def update_route_settings(
    body: RouteSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Update global routing settings (strategy, session affinity, retry parameters)."""
    updates: dict[str, str] = {}
    if body.strategy is not None:
        updates["ai.routing_strategy"] = body.strategy.strip()
    if body.session_affinity is not None:
        updates["ai.session_affinity"] = "true" if body.session_affinity else "false"
    if body.session_affinity_ttl is not None:
        updates["ai.session_affinity_ttl"] = body.session_affinity_ttl.strip()
    if body.request_retry is not None:
        updates["ai.request_retry"] = str(body.request_retry)
    if body.max_retry_credentials is not None:
        updates["ai.max_retry_credentials"] = str(body.max_retry_credentials)
    if body.max_retry_interval is not None:
        updates["ai.max_retry_interval"] = str(body.max_retry_interval)

    for k, v in updates.items():
        res = await db.execute(select(SystemConfig).where(SystemConfig.key == k))
        row = res.scalar_one_or_none()
        if row is not None:
            row.value = v
        else:
            db.add(SystemConfig(key=k, value=v))
    await db.commit()

    # Patch live supervisor if running
    supervisor = get_proxy_supervisor()
    if supervisor.is_running:
        try:
            await supervisor.get_management_client().patch_config({"routing": routing_config(await load_routing_settings(db))})
        except Exception as exc:
            raise HTTPException(status_code=502, detail="Failed to apply routing settings to proxy") from exc

    return {"status": "updated", "updated_settings": updates}


# ---------------------------------------------------------------------------
# OAuth Flows (Device & Browser)
# ---------------------------------------------------------------------------

@router.post("/oauth/start")
async def start_oauth(
    body: OAuthStartRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Start an OAuth authorization flow (browser only)."""
    if body.flow == "device":
        raise HTTPException(
            status_code=400,
            detail="Device flow is not supported; use browser OAuth.",
        )
    mgr = get_oauth_session_manager()
    try:
        return await mgr.start_session(
            provider=body.provider,
            replace_account_id=body.replace_account_id,
            db_session=db,
        )
    except OAuthPortConflictError as pe:
        raise HTTPException(status_code=503, detail="callback_port_unavailable") from pe
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve)) from ve
    except RuntimeError as re:
        if "callback_port_unavailable" in str(re):
            raise HTTPException(status_code=503, detail="callback_port_unavailable") from re
        raise HTTPException(status_code=503, detail=str(re)) from re


@router.get("/oauth/poll")
async def poll_oauth(
    state: str = Query(..., description="OAuth session state token"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Poll the status of an ongoing OAuth flow and reconcile accounts on completion."""
    mgr = get_oauth_session_manager()
    try:
        return await mgr.poll_session(state=state, db_session=db)
    except KeyError as ke:
        raise HTTPException(status_code=404, detail=str(ke)) from ke


@router.post("/oauth/cancel")
async def cancel_oauth(
    body: OAuthCancelRequest,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Cancel a pending OAuth authorization session."""
    mgr = get_oauth_session_manager()
    return await mgr.cancel_session(body.state)


@router.post("/oauth/callback")
async def oauth_callback(
    body: OAuthCallbackRequest | None = None,
    state: str | None = Query(None, description="OAuth state"),
    code: str | None = Query(None, description="OAuth authorization code"),
    redirect_url: str | None = Query(None, description="OAuth redirect URL"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Process incoming OAuth callback without logging query strings or tokens."""
    req_state = (body.state if body else None) or state
    if not req_state:
        raise HTTPException(status_code=400, detail="Missing required 'state'")
    req_code = (body.code if body else None) or code
    req_redirect_url = (body.redirect_url if body else None) or redirect_url

    mgr = get_oauth_session_manager()
    try:
        return await mgr.handle_callback(
            state=req_state,
            code=req_code,
            redirect_url=req_redirect_url,
            db_session=db,
        )
    except KeyError as ke:
        raise HTTPException(status_code=404, detail="OAuth session not found") from ke
    except Exception as exc:
        logger.debug("OAuth callback submission failed: %s", type(exc).__name__)
        raise HTTPException(
            status_code=502 if isinstance(exc, (httpx.HTTPError, RuntimeError)) else 400,
            detail=f"OAuth callback submission failed: {type(exc).__name__}",
        ) from exc


# ---------------------------------------------------------------------------
# Account Management (Credentials)
# ---------------------------------------------------------------------------

@router.get("/accounts/{account_id}", response_model=CredentialSummary)
async def get_account(
    account_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CredentialSummary:
    """Get a single account by ID with redacted summary."""
    res = await db.execute(select(AIProviderCredential).where(AIProviderCredential.id == account_id))
    cred = res.scalar_one_or_none()
    if cred is None:
        raise HTTPException(status_code=404, detail=f"Account '{account_id}' not found.")
    return _serialize_credential(cred)


@router.patch("/accounts/{account_id}", response_model=CredentialSummary)
async def patch_account(
    account_id: str,
    body: AccountPatchRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CredentialSummary:
    """Update priority, weight, enabled status, or operational status of an account."""
    res = await db.execute(select(AIProviderCredential).where(AIProviderCredential.id == account_id))
    cred = res.scalar_one_or_none()
    if cred is None:
        raise HTTPException(status_code=404, detail=f"Account '{account_id}' not found.")

    if body.priority is not None:
        cred.priority = body.priority
    if body.weight is not None:
        cred.weight = body.weight
    if body.enabled is not None:
        cred.enabled = body.enabled
    if body.status is not None:
        cred.status = body.status
    cred.updated_at = datetime.now(timezone.utc)

    if cred.kind == "oauth":
        supervisor = get_proxy_supervisor()
        await supervisor.ensure_started()
        name = cred.proxy_credential_name
        name = name if name.endswith(".json") else f"{name}.json"
        try:
            await supervisor.get_management_client().update_credential(
                name, enabled=cred.enabled and cred.status != "disabled", priority=cred.priority,
                weight=cred.weight, prefix=compute_oauth_proxy_prefix(cred.route_id),
            )
            await supervisor.sync_now()
        except Exception as exc:
            await db.rollback()
            raise HTTPException(status_code=502, detail="Failed to apply account controls to proxy") from exc

    await db.commit()
    await db.refresh(cred)
    return _serialize_credential(cred)


@router.post("/accounts/{account_id}/refresh", response_model=CredentialSummary)
async def refresh_account(
    account_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CredentialSummary:
    """Trigger a credential status check or token refresh for an account."""
    res = await db.execute(select(AIProviderCredential).where(AIProviderCredential.id == account_id))
    cred = res.scalar_one_or_none()
    if cred is None:
        raise HTTPException(status_code=404, detail=f"Account '{account_id}' not found.")

    if cred.kind == "oauth":
        supervisor = get_proxy_supervisor()
        await supervisor.ensure_started()
        name = cred.proxy_credential_name
        name = name if name.endswith(".json") else f"{name}.json"
        try:
            await supervisor.get_management_client().refresh_credential(name)
            await supervisor.sync_now()
        except Exception as exc:
            raise HTTPException(status_code=502, detail="Credential refresh failed; reauthentication may be required") from exc

    cred.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(cred)
    return _serialize_credential(cred)


@router.post("/accounts/{account_id}/test")
async def test_account(
    account_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Test connectivity and authentication validity of an account via live verification."""
    res = await db.execute(select(AIProviderCredential).where(AIProviderCredential.id == account_id))
    cred = res.scalar_one_or_none()
    if cred is None:
        raise HTTPException(status_code=404, detail=f"Account '{account_id}' not found.")

    t0 = time.perf_counter()
    if cred.kind == "oauth":
        supervisor = get_proxy_supervisor()
        if not supervisor.is_running:
            try:
                await supervisor.ensure_started()
            except Exception as exc:
                latency_ms = round((time.perf_counter() - t0) * 1000.0, 1)
                return {
                    "status": "error",
                    "account_id": account_id,
                    "masked_identity": cred.masked_identity,
                    "error": "Proxy supervisor is not running",
                    "latency_ms": latency_ms,
                }

        mgmt = supervisor.get_management_client()
        try:
            is_healthy = await mgmt.health()
        except Exception as exc:
            latency_ms = round((time.perf_counter() - t0) * 1000.0, 1)
            return {
                "status": "error",
                "account_id": account_id,
                "masked_identity": cred.masked_identity,
                "error": "Proxy management API is unreachable",
                "latency_ms": latency_ms,
            }

        if not is_healthy:
            latency_ms = round((time.perf_counter() - t0) * 1000.0, 1)
            return {
                "status": "error",
                "account_id": account_id,
                "masked_identity": cred.masked_identity,
                "error": "Proxy management API reported unhealthy",
                "latency_ms": latency_ms,
            }

        try:
            proxy_creds = await mgmt.get_credentials()
            matched_pcred = None
            for pc in proxy_creds:
                if str(pc.get("name", "")).removesuffix(".json") == cred.proxy_credential_name.removesuffix(".json"):
                    matched_pcred = pc
                    break

            latency_ms = round((time.perf_counter() - t0) * 1000.0, 1)
            if matched_pcred is not None:
                p_status = str(matched_pcred.get("status", "active")).lower()
                if p_status in ("active", "ready", "ok") and not matched_pcred.get("disabled") and cred.enabled:
                    return {
                        "status": "ok",
                        "account_id": account_id,
                        "masked_identity": cred.masked_identity,
                        "proxy_status": p_status,
                        "latency_ms": latency_ms,
                    }
                else:
                    return {
                        "status": "error",
                        "account_id": account_id,
                        "masked_identity": cred.masked_identity,
                        "proxy_status": p_status,
                        "error": f"Credential is in '{p_status}' state in proxy",
                        "latency_ms": latency_ms,
                    }
            else:
                if cred.status == "error":
                    return {
                        "status": "error",
                        "account_id": account_id,
                        "masked_identity": cred.masked_identity,
                        "error": cred.last_redacted_error or "Credential has error status",
                        "latency_ms": latency_ms,
                    }
                return {
                    "status": "error",
                    "account_id": account_id,
                    "masked_identity": cred.masked_identity,
                    "error": "Credential is not loaded in proxy",
                    "latency_ms": latency_ms,
                }
        except Exception as exc:
            latency_ms = round((time.perf_counter() - t0) * 1000.0, 1)
            return {
                "status": "error",
                "account_id": account_id,
                "masked_identity": cred.masked_identity,
                "error": f"Failed to verify credential in proxy: {type(exc).__name__}",
                "latency_ms": latency_ms,
            }
    else:
        latency_ms = round((time.perf_counter() - t0) * 1000.0, 1)
        if cred.status == "error":
            return {
                "status": "error",
                "account_id": account_id,
                "error": cred.last_redacted_error or "Credential has error status",
                "latency_ms": latency_ms,
            }
        return {
            "status": "ok",
            "account_id": account_id,
            "status": cred.status,
            "latency_ms": latency_ms,
        }


@router.post("/accounts/{account_id}/reauth")
async def reauth_account(
    account_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Begin reauthentication for an existing account with identity reconciliation."""
    res = await db.execute(select(AIProviderCredential).where(AIProviderCredential.id == account_id))
    cred = res.scalar_one_or_none()
    if cred is None:
        raise HTTPException(status_code=404, detail=f"Account '{account_id}' not found.")

    if cred.kind != "oauth":
        raise HTTPException(
            status_code=400,
            detail=f"Account '{account_id}' has kind '{cred.kind}', only OAuth accounts can be reauthenticated.",
        )

    prov = cred.route_id.split(":", 1)[1] if cred.route_id.startswith("oauth:") else cred.route_id
    mgr = get_oauth_session_manager()
    try:
        return await mgr.start_session(
            provider=prov,
            replace_account_id=account_id,
            db_session=db,
        )
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve)) from ve
    except RuntimeError as re:
        raise HTTPException(status_code=503, detail=str(re)) from re
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Reauthentication failed: {exc}") from exc


@router.post("/accounts/{account_id}/reset-cooldown")
async def reset_account_cooldown(
    account_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Clear cooldown status and reset cooldown timers for an account."""
    res = await db.execute(select(AIProviderCredential).where(AIProviderCredential.id == account_id))
    cred = res.scalar_one_or_none()
    if cred is None:
        raise HTTPException(status_code=404, detail=f"Account '{account_id}' not found.")

    cred.cooldown = None
    cred.status = "active"
    cred.last_redacted_error = None
    cred.updated_at = datetime.now(timezone.utc)
    await db.commit()

    # Reset in proxy supervisor
    supervisor = get_proxy_supervisor()
    if supervisor.is_running:
        try:
            await supervisor.get_management_client().reset_cooldown(channel=cred.proxy_credential_name)
        except Exception as exc:
            logger.debug("Failed resetting cooldown on proxy: %s", exc)

    # Remove snapshot in vault
    vault = get_provider_vault()
    await vault.get_state()
    if vault.is_available:
        await vault.remove_cooldown_snapshot(cred.proxy_credential_name)

    return {"status": "ok", "account_id": account_id}


async def _restart_proxy_after_account_removal(supervisor) -> None:
    """Restart the sidecar after a credential is removed, off the request path."""
    try:
        await supervisor.restart()
    except Exception as exc:
        logger.warning(
            "Failed restarting proxy after account removal (%s)", type(exc).__name__
        )


@router.delete("/accounts/{account_id}")
async def remove_account(
    account_id: str,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Delete an account and its encrypted vault credentials."""
    res = await db.execute(select(AIProviderCredential).where(AIProviderCredential.id == account_id))
    cred = res.scalar_one_or_none()
    if cred is None:
        raise HTTPException(status_code=404, detail=f"Account '{account_id}' not found.")

    supervisor = get_proxy_supervisor()
    proxy_synced = True
    if supervisor.is_running:
        name = cred.proxy_credential_name
        name = name if name.endswith(".json") else f"{name}.json"
        try:
            await supervisor.get_management_client().delete_credential(name)
            await supervisor.sync_now()
        except Exception as exc:
            # The sidecar may be wedged or already gone. Local removal must still
            # succeed; the restart below makes the process drop the credential.
            proxy_synced = False
            logger.warning(
                "Failed deleting credential from proxy (%s); continuing with local removal",
                type(exc).__name__,
            )
        if supervisor._credential_keys is not None:
            supervisor._credential_keys.pop(name, None)
    vault = get_provider_vault()
    await vault.get_state()
    if vault.is_available:
        await vault.delete_secret(cred.vault_reference)
        await vault.remove_oauth_auth(cred.vault_reference.removeprefix("oauth_auth:"))
        await vault.remove_cooldown_snapshot(cred.proxy_credential_name)

    # 3. Delete from DB
    await db.delete(cred)
    await db.commit()

    # 4. Restart the sidecar so it cannot keep serving the removed credential.
    # Do it after responding: a full restart takes seconds and the deletion
    # itself has already succeeded locally.
    if supervisor.is_running:
        background.add_task(_restart_proxy_after_account_removal, supervisor)

    return {"status": "deleted", "account_id": account_id, "proxy_synced": proxy_synced}


# ---------------------------------------------------------------------------
# Custom Endpoints CRUD & Key CRUD
# ---------------------------------------------------------------------------

@router.post("/endpoints", response_model=RouteSummary)
async def create_endpoint(
    body: CreateEndpointRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RouteSummary:
    """Create a new custom endpoint route with validated URL and vault-only secrets."""
    # 1. Validate URL and headers
    try:
        clean_url, warnings = validate_custom_endpoint_url(body.base_url, body.headers)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve)) from ve

    vault = get_provider_vault()
    await vault.get_state()
    if not vault.is_available:
        raise HTTPException(
            status_code=503,
            detail=f"Provider vault is unavailable ({vault.state.value}). Cannot store endpoint credentials.",
        )

    # 2. Generate route and credentials
    route_uuid = str(uuid.uuid4())
    route_id = f"endpoint:{route_uuid}"
    prefix = compute_oauth_proxy_prefix(route_id)
    models = body.models or ["default"]
    header_names = list(body.headers.keys()) if body.headers else []

    config_dict = {
        "base_url": clean_url,
        "models": models,
        "warning_flags": warnings,
        "header_names": header_names,
    }

    # Store headers in vault only
    if body.headers:
        await vault.set_endpoint_headers(route_id, body.headers)

    route = AIProviderRoute(
        id=route_id,
        kind="endpoint",
        provider="custom",
        display_label=body.display_label.strip(),
        proxy_prefix=prefix,
        enabled=True,
        config_json=json.dumps(config_dict),
    )
    db.add(route)

    # 3. Store initial keys in vault and create credential rows
    created_creds: list[AIProviderCredential] = []
    if body.keys:
        for k in body.keys:
            raw_key = k.api_key.strip()
            if not raw_key:
                continue
            cred_id = str(uuid.uuid4())
            vault_ref = f"endpoint_key:{route_id}:{cred_id}"
            await vault.set_secret(vault_ref, raw_key)
            masked = mask_api_key(raw_key)

            cred = AIProviderCredential(
                id=cred_id,
                route_id=route_id,
                kind="custom_endpoint_key",
                vault_reference=vault_ref,
                proxy_credential_name=f"custom_{cred_id[:8]}",
                masked_identity=masked,
                priority=k.priority,
                weight=k.weight,
                enabled=True,
                status="active",
            )
            db.add(cred)
            created_creds.append(cred)

    await db.commit()
    await db.refresh(route)

    # 4. Materialize into running supervisor
    supervisor = get_proxy_supervisor()
    if supervisor.is_running:
        try:
            await supervisor.reload_custom_endpoints()
        except Exception as exc:
            logger.warning("Failed reloading proxy after custom endpoint creation: %s", exc)

    keys_summary = [_serialize_credential(c) for c in created_creds]
    active_id = await resolve_active_route_id(db)
    return RouteSummary(
        id=route.id,
        kind="endpoint",
        provider="custom",
        display_label=route.display_label,
        proxy_prefix=route.proxy_prefix,
        enabled=route.enabled,
        is_active=(route.id == active_id),
        health={"healthy": bool(created_creds), "status": "configured" if created_creds else "unconfigured"},
        accounts=[],
        keys=keys_summary,
        config={
            "base_url": clean_url,
            "warning_flags": warnings,
            "has_headers": bool(header_names),
            "header_names": header_names,
        },
        models=models,
        recovery_state=None,
    )


@router.get("/endpoints/{endpoint_id}", response_model=RouteSummary)
async def get_endpoint(
    endpoint_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RouteSummary:
    """Get a single custom endpoint route with redacted keys and summary."""
    route_id = endpoint_id if endpoint_id.startswith("endpoint:") else f"endpoint:{endpoint_id}"
    res = await db.execute(
        select(AIProviderRoute)
        .options(selectinload(AIProviderRoute.credentials))
        .where(AIProviderRoute.id == route_id)
    )
    route = res.scalar_one_or_none()
    if route is None:
        raise HTTPException(status_code=404, detail=f"Custom endpoint '{route_id}' not found.")

    active_route_id = await resolve_active_route_id(db)
    vault = get_provider_vault()
    await vault.get_state()
    cfg = {}
    if route.config_json:
        try:
            cfg = json.loads(route.config_json)
        except Exception:
            pass

    creds = route.credentials or []
    keys_summary = [_serialize_credential(c) for c in creds]
    return RouteSummary(
        id=route.id,
        kind="endpoint",
        provider="custom",
        display_label=route.display_label,
        proxy_prefix=route.proxy_prefix,
        enabled=route.enabled,
        is_active=(route.id == active_route_id),
        health={"healthy": bool(creds), "status": "configured" if creds else "unconfigured"},
        accounts=[],
        keys=keys_summary,
        config={
            "base_url": cfg.get("base_url", ""),
            "warning_flags": cfg.get("warning_flags", []),
            "has_headers": bool(cfg.get("header_names")),
            "header_names": cfg.get("header_names", []),
        },
        models=cfg.get("models", ["default"]),
        recovery_state=None if vault.is_available else f"Provider vault is {vault.state.value}",
    )


@router.patch("/endpoints/{endpoint_id}", response_model=RouteSummary)
async def update_endpoint(
    endpoint_id: str,
    body: UpdateEndpointRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RouteSummary:
    """Update custom endpoint properties, base URL, headers, or model list."""
    route_id = endpoint_id if endpoint_id.startswith("endpoint:") else f"endpoint:{endpoint_id}"
    res = await db.execute(
        select(AIProviderRoute)
        .options(selectinload(AIProviderRoute.credentials))
        .where(AIProviderRoute.id == route_id)
    )
    route = res.scalar_one_or_none()
    if route is None:
        raise HTTPException(status_code=404, detail=f"Custom endpoint '{route_id}' not found.")

    vault = get_provider_vault()
    await vault.get_state()
    cfg = {}
    if route.config_json:
        try:
            cfg = json.loads(route.config_json)
        except Exception:
            pass

    # URL and header validation if provided
    if body.base_url is not None or body.headers is not None:
        target_url = body.base_url if body.base_url is not None else cfg.get("base_url", "")
        try:
            clean_url, warnings = validate_custom_endpoint_url(target_url, body.headers)
            cfg["base_url"] = clean_url
            cfg["warning_flags"] = warnings
        except ValueError as ve:
            raise HTTPException(status_code=400, detail=str(ve)) from ve

    if body.headers is not None:
        if not vault.is_available:
            raise HTTPException(
                status_code=503,
                detail=f"Provider vault is unavailable ({vault.state.value}). Cannot store endpoint headers.",
            )
        await vault.set_endpoint_headers(route_id, body.headers)
        cfg["header_names"] = list(body.headers.keys())

    if body.display_label is not None:
        route.display_label = body.display_label.strip()

    if body.models is not None:
        cfg["models"] = body.models

    if body.enabled is not None:
        route.enabled = body.enabled

    route.config_json = json.dumps(cfg)
    route.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(route)

    supervisor = get_proxy_supervisor()
    if supervisor.is_running:
        try:
            await supervisor.reload_custom_endpoints()
        except Exception as exc:
            logger.warning("Failed reloading proxy after endpoint update: %s", exc)

    creds = route.credentials or []
    active_id = await resolve_active_route_id(db)
    keys_summary = [_serialize_credential(c) for c in creds]
    return RouteSummary(
        id=route.id,
        kind="endpoint",
        provider="custom",
        display_label=route.display_label,
        proxy_prefix=route.proxy_prefix,
        enabled=route.enabled,
        is_active=(route.id == active_id),
        health={"healthy": bool(creds), "status": "configured" if creds else "unconfigured"},
        accounts=[],
        keys=keys_summary,
        config={
            "base_url": cfg.get("base_url", ""),
            "warning_flags": cfg.get("warning_flags", []),
            "has_headers": bool(cfg.get("header_names")),
            "header_names": cfg.get("header_names", []),
        },
        models=cfg.get("models", ["default"]),
        recovery_state=None,
    )


@router.delete("/endpoints/{endpoint_id}")
async def delete_endpoint(
    endpoint_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Delete a custom endpoint route and clear its vault-stored secrets."""
    route_id = endpoint_id if endpoint_id.startswith("endpoint:") else f"endpoint:{endpoint_id}"
    res = await db.execute(select(AIProviderRoute).where(AIProviderRoute.id == route_id))
    route = res.scalar_one_or_none()
    if route is None:
        raise HTTPException(status_code=404, detail=f"Custom endpoint '{route_id}' not found.")

    # If this was active route, switch back to DEFAULT_ROUTE_ID
    active_id = await resolve_active_route_id(db)
    if active_id == route_id:
        cfg_res = await db.execute(select(SystemConfig).where(SystemConfig.key == "ai.provider"))
        cfg_row = cfg_res.scalar_one_or_none()
        if cfg_row is not None:
            cfg_row.value = DEFAULT_ROUTE_ID
        else:
            db.add(SystemConfig(key="ai.provider", value=DEFAULT_ROUTE_ID))

    # Delete vault secrets
    vault = get_provider_vault()
    await vault.get_state()
    if vault.is_available:
        await vault.remove_endpoint_headers(route_id)
        # Remove all keys for this route
        c_res = await db.execute(select(AIProviderCredential).where(AIProviderCredential.route_id == route_id))
        for cred in c_res.scalars().all():
            await vault.delete_secret(cred.vault_reference)

    # Delete route from DB
    await db.delete(route)
    await db.commit()

    supervisor = get_proxy_supervisor()
    if supervisor.is_running:
        try:
            await supervisor.reload_custom_endpoints()
        except Exception as exc:
            logger.debug("Failed reloading proxy after endpoint delete: %s", exc)

    return {"status": "deleted", "route_id": route_id}


# ---------------------------------------------------------------------------
# Key CRUD on Custom Endpoints
# ---------------------------------------------------------------------------

@router.post("/endpoints/{endpoint_id}/keys", response_model=CredentialSummary)
async def add_endpoint_key(
    endpoint_id: str,
    body: EndpointKeyInput,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CredentialSummary:
    """Add a new API key to a custom endpoint (key stored only in provider vault)."""
    route_id = endpoint_id if endpoint_id.startswith("endpoint:") else f"endpoint:{endpoint_id}"
    res = await db.execute(select(AIProviderRoute).where(AIProviderRoute.id == route_id))
    route = res.scalar_one_or_none()
    if route is None:
        raise HTTPException(status_code=404, detail=f"Custom endpoint '{route_id}' not found.")

    raw_key = body.api_key.strip()
    if not raw_key:
        raise HTTPException(status_code=400, detail="API key cannot be empty.")

    vault = get_provider_vault()
    await vault.get_state()
    if not vault.is_available:
        raise HTTPException(
            status_code=503,
            detail=f"Provider vault is unavailable ({vault.state.value}). Cannot store key.",
        )

    cred_id = str(uuid.uuid4())
    vault_ref = f"endpoint_key:{route_id}:{cred_id}"
    await vault.set_secret(vault_ref, raw_key)
    masked = mask_api_key(raw_key)

    cred = AIProviderCredential(
        id=cred_id,
        route_id=route_id,
        kind="custom_endpoint_key",
        vault_reference=vault_ref,
        proxy_credential_name=f"custom_{cred_id[:8]}",
        masked_identity=masked,
        priority=body.priority,
        weight=body.weight,
        enabled=True,
        status="active",
    )
    db.add(cred)
    await db.commit()
    await db.refresh(cred)

    supervisor = get_proxy_supervisor()
    if supervisor.is_running:
        try:
            await supervisor.reload_custom_endpoints()
        except Exception as exc:
            logger.debug("Failed reloading proxy after key addition: %s", exc)

    return _serialize_credential(cred)


@router.get("/endpoints/{endpoint_id}/keys", response_model=list[CredentialSummary])
async def list_endpoint_keys(
    endpoint_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[CredentialSummary]:
    """List all keys for a custom endpoint with masked summaries."""
    route_id = endpoint_id if endpoint_id.startswith("endpoint:") else f"endpoint:{endpoint_id}"
    res = await db.execute(select(AIProviderRoute).where(AIProviderRoute.id == route_id))
    route = res.scalar_one_or_none()
    if route is None:
        raise HTTPException(status_code=404, detail=f"Custom endpoint '{route_id}' not found.")

    c_res = await db.execute(
        select(AIProviderCredential).where(AIProviderCredential.route_id == route_id)
    )
    return [_serialize_credential(c) for c in c_res.scalars().all()]


@router.get("/endpoints/{endpoint_id}/keys/{key_id}", response_model=CredentialSummary)
async def get_endpoint_key(
    endpoint_id: str,
    key_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CredentialSummary:
    """Get a single key for a custom endpoint with masked summary."""
    route_id = endpoint_id if endpoint_id.startswith("endpoint:") else f"endpoint:{endpoint_id}"
    res = await db.execute(select(AIProviderCredential).where(AIProviderCredential.id == key_id))
    cred = res.scalar_one_or_none()
    if cred is None or cred.route_id != route_id:
        raise HTTPException(status_code=404, detail=f"Key '{key_id}' not found on endpoint '{route_id}'.")
    return _serialize_credential(cred)


@router.patch("/endpoints/{endpoint_id}/keys/{key_id}", response_model=CredentialSummary)
async def patch_endpoint_key(
    endpoint_id: str,
    key_id: str,
    body: EndpointKeyUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CredentialSummary:
    """Update priority, weight, enabled, or status of an endpoint key."""
    route_id = endpoint_id if endpoint_id.startswith("endpoint:") else f"endpoint:{endpoint_id}"
    res = await db.execute(select(AIProviderCredential).where(AIProviderCredential.id == key_id))
    cred = res.scalar_one_or_none()
    if cred is None or cred.route_id != route_id:
        raise HTTPException(status_code=404, detail=f"Key '{key_id}' not found on endpoint '{route_id}'.")

    if body.priority is not None:
        cred.priority = body.priority
    if body.weight is not None:
        cred.weight = body.weight
    if body.enabled is not None:
        cred.enabled = body.enabled
    if body.status is not None:
        cred.status = body.status
    cred.updated_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(cred)

    supervisor = get_proxy_supervisor()
    if supervisor.is_running:
        try:
            await supervisor.reload_custom_endpoints()
        except Exception as exc:
            logger.debug("Failed reloading proxy after key update: %s", exc)

    return _serialize_credential(cred)


@router.delete("/endpoints/{endpoint_id}/keys/{key_id}")
async def delete_endpoint_key(
    endpoint_id: str,
    key_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Delete an API key from an endpoint and remove it from the vault."""
    route_id = endpoint_id if endpoint_id.startswith("endpoint:") else f"endpoint:{endpoint_id}"
    res = await db.execute(select(AIProviderCredential).where(AIProviderCredential.id == key_id))
    cred = res.scalar_one_or_none()
    if cred is None or cred.route_id != route_id:
        raise HTTPException(status_code=404, detail=f"Key '{key_id}' not found on endpoint '{route_id}'.")

    vault = get_provider_vault()
    await vault.get_state()
    if vault.is_available:
        await vault.delete_secret(cred.vault_reference)

    await db.delete(cred)
    await db.commit()

    supervisor = get_proxy_supervisor()
    if supervisor.is_running:
        try:
            await supervisor.reload_custom_endpoints()
        except Exception as exc:
            logger.debug("Failed reloading proxy after key deletion: %s", exc)

    return {"status": "deleted", "key_id": key_id}


# ---------------------------------------------------------------------------
# Endpoint Model Preview / Refresh / Test
# ---------------------------------------------------------------------------

@router.post("/endpoints/models/preview")
async def preview_endpoint_models(
    body: ModelPreviewRequest,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Validate endpoint URL locally without network call."""
    try:
        clean_url, _ = validate_custom_endpoint_url(body.base_url, body.headers)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve)) from ve

    return {
        "models": [],
        "notice": "preview is local; configure endpoint models explicitly or refresh after saving",
    }


@router.post("/endpoints/{endpoint_id}/models/refresh")
async def refresh_endpoint_models(
    endpoint_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Refresh the stored model catalog for a saved custom endpoint via proxy supervisor."""
    route_id = endpoint_id if endpoint_id.startswith("endpoint:") else f"endpoint:{endpoint_id}"
    res = await db.execute(select(AIProviderRoute).where(AIProviderRoute.id == route_id))
    route = res.scalar_one_or_none()
    if route is None:
        raise HTTPException(status_code=404, detail=f"Endpoint '{route_id}' not found.")

    cfg = {}
    if route.config_json:
        try:
            cfg = json.loads(route.config_json)
        except Exception:
            pass

    prefix = route.proxy_prefix or compute_oauth_proxy_prefix(route_id)
    supervisor = get_proxy_supervisor()
    try:
        await supervisor.reload_custom_endpoints()
    except Exception as exc:
        logger.warning("Failed to reload custom endpoints on supervisor: %s", exc)

    proxy_models = await supervisor.list_proxy_models(prefix)
    if proxy_models:
        cfg["models"] = proxy_models
        route.config_json = json.dumps(cfg)
        await db.commit()
        return {"models": proxy_models}

    return {"models": cfg.get("models", ["default"])}


@router.post("/endpoints/{endpoint_id}/test")
async def test_endpoint(
    endpoint_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Test connectivity to a saved custom endpoint via proxy supervisor."""
    route_id = endpoint_id if endpoint_id.startswith("endpoint:") else f"endpoint:{endpoint_id}"
    res = await db.execute(select(AIProviderRoute).where(AIProviderRoute.id == route_id))
    route = res.scalar_one_or_none()
    if route is None:
        raise HTTPException(status_code=404, detail=f"Endpoint '{route_id}' not found.")

    cfg = {}
    if route.config_json:
        try:
            cfg = json.loads(route.config_json)
        except Exception:
            pass

    prefix = route.proxy_prefix or compute_oauth_proxy_prefix(route_id)
    t0 = time.perf_counter()
    supervisor = get_proxy_supervisor()
    try:
        await supervisor.reload_custom_endpoints()
        proxy_models = await supervisor.list_proxy_models(prefix)
        latency_ms = round((time.perf_counter() - t0) * 1000.0, 1)
        if proxy_models:
            cfg["models"] = proxy_models
            route.config_json = json.dumps(cfg)
            await db.commit()
            return {
                "status": "ok",
                "route_id": route_id,
                "models": proxy_models,
                "latency_ms": latency_ms,
            }
        else:
            return {
                "status": "error",
                "route_id": route_id,
                "error": "No models returned by proxy for endpoint",
                "latency_ms": latency_ms,
            }
    except Exception as exc:
        latency_ms = round((time.perf_counter() - t0) * 1000.0, 1)
        clean_err = f"Proxy test failed: {type(exc).__name__}"
        return {
            "status": "error",
            "route_id": route_id,
            "error": clean_err,
            "latency_ms": latency_ms,
        }


# ---------------------------------------------------------------------------
# Diagnostics (Bounded, Non-Content)
# ---------------------------------------------------------------------------

@router.get("/diagnostics")
async def get_diagnostics(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Retrieve bounded provider diagnostics with non-content proxy trace data."""
    active_route_id = await resolve_active_route_id(db)
    supervisor = get_proxy_supervisor()
    status_summary = supervisor.get_status()
    vault = get_provider_vault()
    await vault.get_state()

    traces = get_proxy_traces(limit=50)

    route_count = 0
    cred_count = 0
    try:
        r_cnt = await db.execute(select(AIProviderRoute.id))
        route_count = len(r_cnt.scalars().all())
        c_cnt = await db.execute(select(AIProviderCredential.id))
        cred_count = len(c_cnt.scalars().all())
    except Exception:
        pass

    return {
        "active_route_id": active_route_id,
        "proxy_status": status_summary,
        "vault_state": vault.state.value,
        "route_count": route_count,
        "credential_count": cred_count,
        "traces": traces,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Explicit Provider-Only Vault Reset
# ---------------------------------------------------------------------------

@router.post("/vault/reset")
async def reset_provider_vault(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Explicit provider-only vault reset.

    Scope:
    - Clears encrypted OAuth tokens, endpoint keys, endpoint headers, and cooldown snapshots in vault.
    - Deletes all credentials in ai_provider_credentials.
    - Deletes all custom endpoint routes in ai_provider_routes.
    - Re-seeds fresh empty OAuth routes.
    - Resets active provider to default ('direct:aistudio') if an OAuth or custom route was active.
    - Stops proxy supervisor.
    - Leaves direct provider API keys and all other database tables intact.
    """
    supervisor = get_proxy_supervisor()
    await get_oauth_session_manager().cancel_all_sessions()
    await supervisor.stop(sync=False)

    # 1. Reset encrypted provider vault
    vault = get_provider_vault()
    await vault.get_state()
    await vault.reset_vault()

    # 2. Clear credentials from database
    await db.execute(delete(AIProviderCredential))

    # 3. Clear custom endpoints from database
    await db.execute(delete(AIProviderRoute).where(AIProviderRoute.kind == "endpoint"))

    # 4. Re-seed clean OAuth routes
    await seed_oauth_routes(db)

    # 5. If active route was OAuth or endpoint, fallback to default direct route
    active_route = await resolve_active_route_id(db)
    if active_route.startswith("oauth:") or active_route.startswith("endpoint:"):
        cfg_res = await db.execute(select(SystemConfig).where(SystemConfig.key == "ai.provider"))
        cfg_row = cfg_res.scalar_one_or_none()
        if cfg_row is not None:
            cfg_row.value = DEFAULT_ROUTE_ID
        else:
            db.add(SystemConfig(key="ai.provider", value=DEFAULT_ROUTE_ID))
        await db.commit()
        active_route = DEFAULT_ROUTE_ID

    await db.commit()

    return {
        "status": "reset",
        "vault_state": vault.state.value,
        "active_route_id": active_route,
    }
