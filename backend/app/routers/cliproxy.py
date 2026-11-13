"""HTTP API for the independently updated CLIProxyAPI core."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
import httpx
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.system_config import SystemConfig
from app.models.user import User
from app.services import cliproxy_core, cliproxy_updater
from app.services.proxy_supervisor import get_proxy_supervisor

logger = logging.getLogger("blm.cliproxy")

router = APIRouter(tags=["cliproxy"], dependencies=[Depends(get_current_user)])


class CheckRequest(BaseModel):
    """Payload for checking updates."""

    download: bool = True


class InstallRequest(BaseModel):
    """Payload for installing a specific core version."""

    version: str | None = None


def _find_staged_version_and_dir() -> tuple[str | None, Path | None]:
    """Look for a directory under cliproxy_core.staging_dir() holding the core binary.

    Returns:
        tuple[str | None, Path | None]: (version, staged_dir) if found, else (None, None).
    """
    return cliproxy_core.find_staged_core()


async def _read_auto_update_setting(db: AsyncSession) -> bool:
    """Read the auto_update setting from the system_config table."""
    try:
        res = await db.execute(
            select(SystemConfig.value).where(SystemConfig.key == "cliproxy.auto_update")
        )
        val = res.scalar_one_or_none()
        if val is None:
            return True
        return val.strip().lower() not in {"false", "0", "no", "off"}
    except Exception as exc:
        logger.warning("Failed to read cliproxy.auto_update config, defaulting to True: %s", exc)
        return True


async def _read_download_mirrors(db: AsyncSession) -> list[str]:
    """Read mirrors from the system_config table starting with https://."""
    try:
        res = await db.execute(
            select(SystemConfig.value).where(SystemConfig.key == "cliproxy.download_mirrors")
        )
        val = res.scalar_one_or_none()
        if not val:
            return []
        mirrors: list[str] = []
        for item in val.split(","):
            cleaned = item.strip()
            if cleaned.startswith("https://"):
                mirrors.append(cleaned)
        return mirrors
    except Exception as exc:
        logger.warning("Failed to read cliproxy.download_mirrors config: %s", exc)
        return []


async def _build_status_dict(db: AsyncSession) -> dict[str, Any]:
    """Build the dictionary of current cliproxy core status."""
    staged_version, _ = _find_staged_version_and_dir()
    state = cliproxy_core.read_update_state()
    installed_ver = cliproxy_core.installed_version()
    managed_bin = cliproxy_core.managed_binary()
    supervisor_status = get_proxy_supervisor().get_status()
    auto_update = await _read_auto_update_setting(db)

    latest_ver = state.latest_version
    update_available = bool(
        latest_ver and cliproxy_updater.is_newer(latest_ver, installed_ver)
    )

    return {
        "installed_version": installed_ver,
        "running_version": supervisor_status.get("version"),
        "latest_version": latest_ver,
        "update_available": update_available,
        "staged_version": staged_version,
        "pending_version": state.pending_version,
        "last_check_at": state.last_check_at,
        "last_error": state.last_error,
        "quarantined": list(state.quarantined),
        "auto_update": auto_update,
        "core_root": str(cliproxy_core.core_root()),
        "binary_path": str(managed_bin) if managed_bin is not None else None,
        "rollback_available": (
            cliproxy_core.rollback_dir() / cliproxy_core.binary_name()
        ).is_file(),
        "supervisor_state": supervisor_status.get("state"),
    }


@router.get("/cliproxy/status")
async def get_cliproxy_status(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Report the current cliproxy-core status, update state, and supervisor details."""
    return await _build_status_dict(db)


@router.post("/cliproxy/check")
async def check_cliproxy_updates(
    body: CheckRequest | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Check for upstream CLIProxyAPI updates and optionally stage when available."""
    allow_download = True if body is None else body.download
    mirrors = await _read_download_mirrors(db)

    try:
        check_result = await cliproxy_updater.check_and_stage(
            mirrors=mirrors,
            allow_download=allow_download,
        )
    except Exception as exc:
        logger.exception("Error checking for CLIProxyAPI updates")
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    status_dict = await _build_status_dict(db)
    merged = {**status_dict, **check_result}
    return {"result": merged}


@router.post("/cliproxy/install")
async def install_cliproxy_version(
    body: InstallRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Download and stage a specific CLIProxyAPI core version."""
    if not body.version:
        raise HTTPException(status_code=400, detail="version is required")

    mirrors = await _read_download_mirrors(db)

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            release = await cliproxy_updater.fetch_release(client, version=body.version)
            platform_tuple = cliproxy_updater.current_platform()
            asset = cliproxy_updater.select_asset(release, platform_tuple)
            staged_dir = await cliproxy_updater.stage_release(
                release, asset, mirrors=mirrors
            )

        state = cliproxy_core.read_update_state()
        state.pending_version = release.version
        state.pending_asset_name = asset.name
        cliproxy_core.write_update_state(state)

        return {
            "staged": True,
            "version": release.version,
            "asset_name": asset.name,
            "staged_dir": str(staged_dir),
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to install/stage CLIProxyAPI version %s", body.version)
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/cliproxy/activate")
async def activate_staged_core(
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Promote the currently staged CLIProxyAPI core and restart the proxy supervisor."""
    _, staged_dir = _find_staged_version_and_dir()
    if staged_dir is None:
        raise HTTPException(
            status_code=409,
            detail="no staged core is waiting to be activated",
        )

    try:
        cliproxy_core.promote_staged(staged_dir)
    except Exception as exc:
        logger.exception("Failed to promote staged CLIProxyAPI core")
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    # The staged core is live now. Clear the pending marker so the startup
    # promotion does not run again.
    state = cliproxy_core.read_update_state()
    state.pending_version = None
    state.pending_asset_name = None
    cliproxy_core.write_update_state(state)

    supervisor = get_proxy_supervisor()
    try:
        await supervisor.restart()
    except Exception as exc:
        logger.warning(
            "Supervisor restart failed after activating staged core (ignoring): %s",
            exc,
        )

    return {"activated": True, "version": cliproxy_core.installed_version()}


@router.post("/cliproxy/rollback")
async def rollback_cliproxy_core(
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Roll back to the previous CLIProxyAPI installation and restart the proxy supervisor."""
    if not cliproxy_core.rollback_install():
        raise HTTPException(
            status_code=409,
            detail="no previous core is available to restore",
        )

    supervisor = get_proxy_supervisor()
    try:
        await supervisor.restart()
    except Exception as exc:
        logger.warning(
            "Supervisor restart failed after rolling back core (ignoring): %s",
            exc,
        )

    return {"rolled_back": True, "version": cliproxy_core.installed_version()}
