"""CLIProxyAPI core update daemon worker.

Checks the upstream CLIProxyAPI release feed daily, stages a newer core,
and never replaces the live core. Another slice promotes the staged core.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select

from app.database import _SyncSessionLocal
from app.models.system_config import SystemConfig

logger = logging.getLogger(__name__)

CLIPROXY_UPDATE_INTERVAL_SECONDS = 24 * 3600
JOB_KEY = "job.cliproxy_update"


def _auto_update_enabled() -> bool:
    """Check if automatic downloading/staging of CLIProxyAPI is enabled.

    Reads system_config key 'cliproxy.auto_update'.
    Returns False when the stored value is one of 'false', '0', 'no', 'off'
    (case-insensitive). Returns True when the row is missing.
    On any exception returns True and logs a warning.
    """
    try:
        with _SyncSessionLocal() as session:
            stmt = select(SystemConfig).where(SystemConfig.key == "cliproxy.auto_update")
            row = session.execute(stmt).scalar_one_or_none()
            if row is None or row.value is None:
                return True
            val = row.value.strip().lower()
            if val in {"false", "0", "no", "off"}:
                return False
            return True
    except Exception as exc:
        logger.warning("Failed to check cliproxy.auto_update config, defaulting to True: %s", exc)
        return True


def _download_mirrors() -> list[str]:
    """Read configured mirrors from system_config key 'cliproxy.download_mirrors'.

    Splits on commas, strips entries, and keeps only those starting with 'https://'.
    Returns an empty list when missing or on exception.
    """
    try:
        with _SyncSessionLocal() as session:
            stmt = select(SystemConfig).where(SystemConfig.key == "cliproxy.download_mirrors")
            row = session.execute(stmt).scalar_one_or_none()
            if row is None or not row.value:
                return []
            parts = [part.strip() for part in row.value.split(",")]
            return [p for p in parts if p.startswith("https://")]
    except Exception as exc:
        logger.warning("Failed to read cliproxy.download_mirrors config: %s", exc)
        return []


async def run_cliproxy_update() -> dict[str, Any]:
    """Check upstream for a newer CLIProxyAPI release and stage it if available.

    Calls app.services.cliproxy_updater.check_and_stage.
    Catches every exception, logs a warning, and returns a dict with keys:
    latest_version, installed_version, update_available, staged, pending_version, error.
    """
    from app.services.cliproxy_updater import check_and_stage

    try:
        mirrors = _download_mirrors()
        allow_download = _auto_update_enabled()
        result = await check_and_stage(mirrors=mirrors, allow_download=allow_download)
        return result
    except Exception as exc:
        logger.warning("run_cliproxy_update failed: %s", exc)
        return {
            "latest_version": None,
            "installed_version": None,
            "update_available": False,
            "staged": False,
            "pending_version": None,
            "error": str(exc),
        }


def cliproxy_update_worker() -> None:
    """Daemon thread loop checking for CLIProxyAPI updates daily."""
    from app.backgroundtasks._runtime import _run_async, _shutdown_event, _sleep_interruptible
    from app.jobs.runner import update_job_status_sync

    logger.info("cliproxy_update_worker: started")
    try:
        while not _shutdown_event.is_set():
            update_job_status_sync(
                JOB_KEY,
                "running",
                progress=0,
                message="Checking for a newer CLIProxyAPI core",
            )
            try:
                result = _run_async(run_cliproxy_update())
            except Exception as exc:
                logger.warning("cliproxy_update_worker: execution error: %s", exc)
                result = {
                    "latest_version": None,
                    "installed_version": None,
                    "update_available": False,
                    "staged": False,
                    "pending_version": None,
                    "error": str(exc),
                }

            if result.get("staged") is True:
                pending_ver = result.get("pending_version")
                logger.info("cliproxy_update_worker: staged new core version %s", pending_ver)
                update_job_status_sync(
                    JOB_KEY,
                    "waiting",
                    progress=100,
                    message=f"Staged core {pending_ver}; it activates on the next app start",
                )
            else:
                if not result.get("update_available", False) and not result.get("error"):
                    msg = "Up to date"
                elif result.get("error"):
                    msg = str(result.get("error"))
                else:
                    msg = "No update staged"

                update_job_status_sync(
                    JOB_KEY,
                    "waiting",
                    progress=100,
                    message=msg,
                )

            if _sleep_interruptible(CLIPROXY_UPDATE_INTERVAL_SECONDS):
                break
    except Exception as exc:
        logger.exception("cliproxy_update_worker encountered unexpected exception: %s", exc)
    finally:
        logger.info("cliproxy_update_worker: stopped")
