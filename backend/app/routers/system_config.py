"""FastAPI router for editable system configuration values."""

import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_admin_user, get_current_user
from app.database import get_db
from app.models.system_config import SystemConfig
from app.models.user import User

router = APIRouter(tags=["system-config"], dependencies=[Depends(get_current_user)])

# First-boot state lives in the same config table (key below) but MUST work
# pre-login on a fresh machine — so it gets its own router with no user
# dependency. Still protected by the per-launch token middleware (local-only).
first_boot_router = APIRouter(tags=["first-boot"])

ONBOARDING_COMPLETED_KEY = "app.onboarding_completed"

# EULA acceptance: one-way record in the same config table. The API only ever
# accepts agreement — there is deliberately no un-accept route. The stored
# value is "<version>|<unix-ms>"; any mismatch/absence (including a hand-edited
# or deleted row) reads as NOT accepted and re-prompts on the next launch.
EULA_KEY = "app.eula_accepted"
EULA_VERSION = "eula-v1"


class EulaAcceptRequest(BaseModel):
    version: str = Field(..., description="EULA version the user was shown")


def _parse_eula(raw: str | None) -> tuple[bool, int | None]:
    if not raw:
        return False, None
    version, _, ts = raw.partition("|")
    if version != EULA_VERSION:
        return False, None
    try:
        return True, int(ts)
    except ValueError:
        return True, None


@first_boot_router.get("/eula-status")
async def get_eula_status(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Whether the CURRENT EULA version has been accepted. Token-gated, pre-login.

    Only an exact stored match counts — tampered/stale rows re-prompt."""
    stmt = select(SystemConfig.value).where(SystemConfig.key == EULA_KEY)
    row = (await db.execute(stmt)).first()
    accepted, accepted_at = _parse_eula(row[0] if row else None)
    return {
        "accepted": accepted,
        "version": EULA_VERSION,
        "accepted_at": accepted_at,
    }


@first_boot_router.post("/eula/accept")
async def accept_eula(
    body: EulaAcceptRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Record EULA agreement. Idempotent, one-way (no inverse endpoint).
    Rejects a version mismatch so a stale client can't accept unseen text."""
    if body.version != EULA_VERSION:
        raise HTTPException(status_code=409, detail=f"EULA version mismatch: current is {EULA_VERSION}")
    now_ms = int(time.time() * 1000)
    stmt = sqlite_insert(SystemConfig).values(key=EULA_KEY, value=f"{EULA_VERSION}|{now_ms}")
    stmt = stmt.on_conflict_do_update(
        index_elements=["key"],
        set_={"value": stmt.excluded.value},
    )
    await db.execute(stmt)
    await db.commit()
    return {"accepted": True, "version": EULA_VERSION, "accepted_at": now_ms}


@first_boot_router.get("/first-boot")
async def get_first_boot(db: AsyncSession = Depends(get_db)) -> dict[str, bool]:
    """First-boot/onboarding flag. Token-gated, no user login required."""
    stmt = select(SystemConfig.value).where(SystemConfig.key == ONBOARDING_COMPLETED_KEY)
    result = await db.execute(stmt)
    row = result.first()
    return {"onboarding_completed": (row[0] == "1") if row else False}


@first_boot_router.post("/first-boot/complete")
async def complete_first_boot(db: AsyncSession = Depends(get_db)) -> dict[str, bool]:
    """Persist onboarding completion. Idempotent. Token-gated, no login required."""
    stmt = sqlite_insert(SystemConfig).values(key=ONBOARDING_COMPLETED_KEY, value="1")
    stmt = stmt.on_conflict_do_update(
        index_elements=["key"],
        set_={"value": stmt.excluded.value},
    )
    await db.execute(stmt)
    await db.commit()
    return {"onboarding_completed": True}

DEFAULT_NOTIF_CONFIG: dict[str, float] = {
    "notif.rsi_oversold_threshold": 30.0,
    "notif.rsi_overbought_threshold": 70.0,
    "notif.volatility_spike_ratio": 1.5,
    "notif.atr_expansion_threshold": 4.0,
    "notif.momentum_surge_threshold": 70.0,
    "notif.return_1w_spike_threshold": 10.0,
    "notif.streak_days_threshold": 5.0,
    "notif.near_52w_threshold": 3.0,
    # Deal significance: fraction of market cap (e.g. 0.05 = 5%)
    "notif.deal_significance_pct": 0.05,
    # Absolute fallback threshold in Rs Cr when market cap is unknown
    "notif.deal_absolute_threshold_cr": 2.0,
}

def normalize_gemini_worker_model(model: str, default_tier: str = "high") -> str:
    """Normalize legacy/deprecated Gemini models for background workers."""
    m = model.strip() if model else ""
    if not m or not m.startswith("gemini"):
        return model
    if m in ("gemini-3.8-flash-high", "gemini-3.8-flash-medium", "gemini-3.8-flash-low"):
        return m
    if m.endswith("-high"):
        return "gemini-3.8-flash-high"
    if m.endswith("-medium"):
        return "gemini-3.8-flash-medium"
    if m.endswith("-low"):
        return "gemini-3.8-flash-low"
    return f"gemini-3.8-flash-{default_tier}"


ALLOWED_STRING_KEYS: set[str] = {
    "openalgo.url",
    "openalgo.api_key",
    "ai.provider",
    "ai.zen_api_key",
    "ai.go_api_key",
    "ai.aistudio_api_key",
    "ai.groq_api_key",
    "ai.nvidia_api_key",
    "ai.anthropic_api_key",
    "ai.claude_code_token",
    "ai.openai_api_key",
    "ai.openrouter_api_key",
    "ai.deepseek_api_key",
    "ai.xai_api_key",
    "ai.together_api_key",
    "ai.copilot_gh_token",
    "ai.codex_access_token",
    "ai.codex_refresh_token",
    "ai.hunter_model",
    "ai.verifier_model",
}


class SystemConfigUpdate(BaseModel):
    value: Any = Field(..., description="Configuration value (numeric or string)")


class AppStateRequest(BaseModel):
    is_active: bool


class ConsentRequest(BaseModel):
    consent: bool


@router.post("/system_config/consent")
@router.post("/system-config/consent")
async def update_scraping_consent(
    body: ConsentRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Record user consent for advanced web extraction / browser harvesting."""
    stmt = sqlite_insert(SystemConfig).values(
        key="scraping.advanced_consent",
        value="true" if body.consent else "false",
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["key"],
        set_={"value": stmt.excluded.value},
    )
    await db.execute(stmt)
    await db.commit()

    # Invalidate in-memory consent cache immediately
    from app.services.browser_harvester import invalidate_consent_cache
    invalidate_consent_cache()

    if body.consent:
        # Trigger provision-on-consent browser fetching in the background,
        # then start the warm browser (starts immediately when a browser is
        # already installed, or once the fetch lands).
        from app.services.browser_harvester import (
            ensure_warm_browser,
            trigger_browser_fetch,
        )
        trigger_browser_fetch()
        try:
            ensure_warm_browser()
        except Exception:
            pass
    else:
        # Consent revoked: tear down the warm browser (off the event loop so the 10s join doesn't block).
        try:
            import asyncio
            from app.services.browser_harvester import shutdown_warm_browser
            loop = asyncio.get_running_loop()
            loop.run_in_executor(None, shutdown_warm_browser)
        except Exception:
            pass

    return {"status": "ok", "consent": body.consent}


@router.get("/system_config/browser-status")
@router.get("/system-config/browser-status")
async def browser_status(user: User = Depends(get_current_user)) -> dict[str, Any]:
    """Live headless-browser provisioning status for the Settings UI."""
    from app.services.browser_harvester import get_browser_status, get_consent_status

    status = get_browser_status()
    return {"consent": await get_consent_status(), **status}


@router.post("/system_config/browser-fetch")
@router.post("/system-config/browser-fetch")
async def browser_fetch(user: User = Depends(get_current_user)) -> dict[str, Any]:
    """Manually (re)trigger the Camoufox browser download (Retry button)."""
    from app.services.browser_harvester import ensure_warm_browser, trigger_browser_fetch

    status = trigger_browser_fetch(manual=True)
    try:
        ensure_warm_browser()
    except Exception:
        pass
    return status


@router.post("/system-config/app-state")
async def update_app_state(body: AppStateRequest, user: User = Depends(get_current_user)) -> dict[str, str]:
    """Electron pushes active/idle state here."""
    from app.backgroundtasks._runtime import set_app_active_state
    set_app_active_state(body.is_active)
    return {"status": "ok"}


@router.get("/system-config")
async def get_system_config(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Return editable configuration thresholds, runtime API keys, and read-only app metadata."""
    stmt = select(SystemConfig.key, SystemConfig.value).where(
        (SystemConfig.key.like("notif.%"))
        | (SystemConfig.key == "app.version")
        | (SystemConfig.key.like("openalgo.%"))
        | (SystemConfig.key.like("ai.%"))
    )
    result = await db.execute(stmt)
    rows = result.fetchall()

    values: dict[str, Any] = {}

    # Notification thresholds (editable, numeric)
    for key, default in DEFAULT_NOTIF_CONFIG.items():
        raw = next((row[1] for row in rows if row[0] == key), None)
        if raw is None:
            values[key] = default
            continue
        try:
            values[key] = float(raw)
        except (TypeError, ValueError):
            values[key] = default

    # App version (read-only, string)
    version_row = next((row[1] for row in rows if row[0] == "app.version"), None)
    values["app.version"] = version_row if version_row is not None else "1.0.0"

    # Runtime string configs (OpenAlgo, AI keys)
    for key in ALLOWED_STRING_KEYS:
        str_row = next((row[1] for row in rows if row[0] == key), None)
        val = str_row if str_row is not None else ""
        if key == "ai.hunter_model" and val.startswith("gemini"):
            val = normalize_gemini_worker_model(val, default_tier="high")
        elif key == "ai.verifier_model" and val.startswith("gemini"):
            val = normalize_gemini_worker_model(val, default_tier="low")
        values[key] = val

    return values


@router.put("/system-config/{key}", dependencies=[Depends(get_admin_user)])
async def update_system_config(
    key: str,
    payload: SystemConfigUpdate,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Upsert a single system configuration value."""
    if key not in DEFAULT_NOTIF_CONFIG and key not in ALLOWED_STRING_KEYS:
        raise HTTPException(status_code=404, detail=f"Unknown system config key: {key}")

    val_str = str(payload.value).strip() if payload.value is not None else ""
    if key == "ai.hunter_model" and val_str.startswith("gemini"):
        val_str = normalize_gemini_worker_model(val_str, default_tier="high")
    elif key == "ai.verifier_model" and val_str.startswith("gemini"):
        val_str = normalize_gemini_worker_model(val_str, default_tier="low")
    stmt = sqlite_insert(SystemConfig).values(
        key=key,
        value=val_str,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["key"],
        set_={"value": stmt.excluded.value},
    )
    await db.execute(stmt)
    await db.commit()

    return {"key": key, "value": val_str}


import asyncio
import os
import secrets
from typing import Annotated
from fastapi import Request

async def require_admin_or_launch_token(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Verify caller is an authenticated admin user or the Electron desktop host with valid launch token."""
    token_header = request.headers.get("x-blm-token", "")
    auth_header = request.headers.get("Authorization", "")

    try:
        import main as _main
        launch_token = getattr(_main, "LAUNCH_TOKEN", None)
    except ImportError:
        launch_token = os.environ.get("BLM_LAUNCH_TOKEN")

    if launch_token and token_header and secrets.compare_digest(token_header, launch_token):
        if not auth_header.startswith("Bearer "):
            return

    try:
        user = await get_admin_user(await get_current_user(request, db))
        if user and user.is_admin:
            return
    except HTTPException:
        pass

    raise HTTPException(
        status_code=403,
        detail="Admin privileges or host launch token required",
    )


admin_shutdown_router = APIRouter(tags=["admin"])

@admin_shutdown_router.post("/admin/shutdown")
@admin_shutdown_router.post("/system/shutdown")
async def shutdown_endpoint(
    request: Request,
    _auth: None = Depends(require_admin_or_launch_token),
) -> dict[str, str]:
    """Graceful shutdown endpoint for admin users and desktop host."""
    import logging
    _log = logging.getLogger("blm.shutdown")
    _log.info("Graceful shutdown triggered via shutdown endpoint")

    async def _perform_shutdown() -> None:
        await asyncio.sleep(0.1)
        server = getattr(request.app.state, "server", None)
        if server is not None:
            server.should_exit = True
            return

        try:
            import signal
            if hasattr(signal, "SIGINT"):
                os.kill(os.getpid(), signal.SIGINT)
        except Exception:
            pass

    asyncio.create_task(_perform_shutdown())
    return {"status": "shutting_down"}
