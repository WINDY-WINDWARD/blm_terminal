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
    "ai.opencode_zen_api_key",
    "ai.api_key",
}


class SystemConfigUpdate(BaseModel):
    value: Any = Field(..., description="Configuration value (numeric or string)")


@router.get("/system-config")
async def get_system_config(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
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
