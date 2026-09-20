"""FastAPI router for editable system configuration values."""

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
        # Trigger on-demand binary preparation in the background
        from app.services.browser_harvester import (
            ensure_warm_browser,
            trigger_harvester_download,
        )
        trigger_harvester_download()
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
        values[key] = str_row if str_row is not None else ""

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

    return {"key": key, "value": payload.value}
