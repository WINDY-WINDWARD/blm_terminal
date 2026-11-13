"""On-disk store for the independently updated CLIProxyAPI sidecar binary."""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any

from app.config import settings
from app.services.private_files import restrict_access

logger = logging.getLogger(__name__)

CORE_ROOT_ENV = "CLIPROXY_CORE_ROOT"
METADATA_FILENAME = "metadata.json"
UPDATE_STATE_FILENAME = "update-state.json"


def core_root() -> Path:
    """Return root directory for cliproxy-core storage."""
    env_val = os.environ.get(CORE_ROOT_ENV)
    if env_val:
        return Path(env_val).resolve()
    return Path(settings.db_path).resolve().parent / "cliproxy-core"


def install_dir() -> Path:
    """Return directory for active core installation."""
    return core_root() / "install"


def staging_dir() -> Path:
    """Return directory for staging update assets."""
    return core_root() / "staging"


def download_dir() -> Path:
    """Return directory for downloading update packages."""
    return core_root() / "download"


def rollback_dir() -> Path:
    """Return directory for previous installed core backup."""
    return core_root() / "rollback"


def binary_name() -> str:
    """Return platform-specific binary name."""
    return "cliproxyapi.exe" if os.name == "nt" else "cliproxyapi"


def _safe_restrict_access(path: Path, directory: bool = False) -> None:
    """Call restrict_access and catch any error to avoid crashing."""
    try:
        restrict_access(path, directory=directory)
    except Exception as exc:
        logger.warning("Failed to restrict access permissions on %s: %s", path, exc)


def ensure_dirs() -> None:
    """Create install, staging, download, and rollback directories with restricted permissions."""
    for d in (install_dir(), staging_dir(), download_dir(), rollback_dir()):
        d.mkdir(parents=True, exist_ok=True)
        _safe_restrict_access(d, directory=True)


def sha256_file(path: Path) -> str:
    """Read file in 64 KiB chunks and return lowercase sha256 hex digest."""
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(64 * 1024):
            hasher.update(chunk)
    return hasher.hexdigest().lower()


@dataclass
class CoreMetadata:
    """Metadata describing an installed CLIProxy core binary."""
    version: str
    asset_name: str
    installed_at: str
    source: str


def read_metadata(directory: Path | None = None) -> CoreMetadata | None:
    """Read metadata.json from directory (defaults to install_dir()). Return None on any error."""
    target_dir = directory if directory is not None else install_dir()
    meta_path = target_dir / METADATA_FILENAME
    if not meta_path.is_file():
        return None
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return None
        return CoreMetadata(
            version=str(data.get("version", "")),
            asset_name=str(data.get("asset_name", "")),
            installed_at=str(data.get("installed_at", "")),
            source=str(data.get("source", "")),
        )
    except Exception as exc:
        logger.warning("Error reading metadata from %s: %s", meta_path, exc)
        return None


def write_metadata(metadata: CoreMetadata, directory: Path | None = None) -> None:
    """Write metadata.json atomically to directory (defaults to install_dir())."""
    target_dir = directory if directory is not None else install_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    meta_path = target_dir / METADATA_FILENAME
    tmp_path = target_dir / f"{METADATA_FILENAME}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(dataclasses.asdict(metadata), f, indent=2)
    os.replace(tmp_path, meta_path)
    _safe_restrict_access(meta_path, directory=False)


@dataclass
class UpdateState:
    """Persistent state of update checks, pending versions, and quarantines."""
    last_check_at: str | None = None
    latest_version: str | None = None
    pending_version: str | None = None
    pending_asset_name: str | None = None
    quarantined: list[str] = field(default_factory=list)
    last_error: str | None = None


def read_update_state() -> UpdateState:
    """Read update-state.json from core_root(). Return default UpdateState on any error."""
    state_path = core_root() / UPDATE_STATE_FILENAME
    if not state_path.is_file():
        return UpdateState()
    try:
        with open(state_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return UpdateState()
        quarantined = data.get("quarantined")
        if not isinstance(quarantined, list):
            quarantined = []
        return UpdateState(
            last_check_at=data.get("last_check_at"),
            latest_version=data.get("latest_version"),
            pending_version=data.get("pending_version"),
            pending_asset_name=data.get("pending_asset_name"),
            quarantined=[str(item) for item in quarantined],
            last_error=data.get("last_error"),
        )
    except Exception as exc:
        logger.warning("Error reading update state from %s: %s", state_path, exc)
        return UpdateState()


def write_update_state(state: UpdateState) -> None:
    """Write update-state.json atomically to core_root()."""
    root = core_root()
    root.mkdir(parents=True, exist_ok=True)
    state_path = root / UPDATE_STATE_FILENAME
    tmp_path = root / f"{UPDATE_STATE_FILENAME}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(dataclasses.asdict(state), f, indent=2)
    os.replace(tmp_path, state_path)
    _safe_restrict_access(state_path, directory=False)


def managed_binary() -> Path | None:
    """Return path to managed binary in install_dir() if it exists as a file, else None."""
    target = install_dir() / binary_name()
    return target if target.is_file() else None


def installed_version() -> str | None:
    """Return version from install_dir metadata if available, else None."""
    meta = read_metadata()
    if meta and meta.version:
        return meta.version
    return None


def bootstrap_core(
    bundled_binary: Path, version: str = "", expected_sha256: str | None = None
) -> Path | None:
    """Bootstrap core binary from bundled fallback if not already managed."""
    existing = managed_binary()
    if existing is not None:
        return existing
    if not bundled_binary.is_file():
        return None

    if expected_sha256 is not None:
        actual_sha256 = sha256_file(bundled_binary)
        if actual_sha256.lower() != expected_sha256.lower():
            raise ValueError(
                f"Checksum mismatch for bundled binary: expected {expected_sha256.lower()}, got {actual_sha256.lower()}"
            )

    inst_dir = install_dir()
    inst_dir.mkdir(parents=True, exist_ok=True)
    _safe_restrict_access(inst_dir, directory=True)

    target_bin = inst_dir / binary_name()
    tmp_bin = inst_dir / f"{binary_name()}.tmp"

    shutil.copy2(bundled_binary, tmp_bin)
    if os.name != "nt":
        try:
            os.chmod(tmp_bin, 0o755)
        except Exception as exc:
            logger.warning("Failed to chmod 0o755 on %s: %s", tmp_bin, exc)

    os.replace(tmp_bin, target_bin)
    _safe_restrict_access(target_bin, directory=False)

    installed_at = datetime.now(timezone.utc).isoformat()
    meta = CoreMetadata(
        version=version,
        asset_name=bundled_binary.name,
        installed_at=installed_at,
        source="bundled",
    )
    write_metadata(meta, directory=inst_dir)

    return target_bin


def promote_staged(staged_dir: Path) -> Path:
    """Promote staged_dir to install_dir, preserving previous install in rollback_dir."""
    staged_bin = staged_dir / binary_name()
    if not staged_bin.is_file():
        raise FileNotFoundError(f"Staged binary not found at {staged_bin}")

    inst_dir = install_dir()
    rb_dir = rollback_dir()

    moved_to_rollback = False
    if inst_dir.exists():
        if rb_dir.exists():
            shutil.rmtree(rb_dir, ignore_errors=True)
        shutil.move(str(inst_dir), str(rb_dir))
        moved_to_rollback = True

    try:
        shutil.move(str(staged_dir), str(inst_dir))
    except Exception:
        if moved_to_rollback and rb_dir.exists() and not inst_dir.exists():
            try:
                shutil.move(str(rb_dir), str(inst_dir))
            except Exception as restore_exc:
                logger.error("Failed to restore rollback_dir after promote failure: %s", restore_exc)
        raise

    return inst_dir


def rollback_install() -> bool:
    """Restore previous install from rollback_dir. Return True if restored, False if nothing to restore."""
    rb_dir = rollback_dir()
    rb_bin = rb_dir / binary_name()
    if not rb_bin.is_file():
        return False

    inst_dir = install_dir()
    root = core_root()
    temp_dir = Path(tempfile.mkdtemp(dir=root, prefix="install_aside_"))

    try:
        if inst_dir.exists():
            shutil.move(str(inst_dir), str(temp_dir / "old_install"))
        shutil.move(str(rb_dir), str(inst_dir))
        return True
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def quarantine_version(version: str) -> None:
    """Add version to update state quarantine list if not present and write state."""
    state = read_update_state()
    if version not in state.quarantined:
        state.quarantined.append(version)
        write_update_state(state)


def is_quarantined(version: str) -> bool:
    """Check if version is present in the update state quarantine list."""
    state = read_update_state()
    return version in state.quarantined


def clear_work_dirs() -> None:
    """Clean and recreate staging_dir and download_dir."""
    for d in (staging_dir(), download_dir()):
        shutil.rmtree(d, ignore_errors=True)
        d.mkdir(parents=True, exist_ok=True)
        _safe_restrict_access(d, directory=True)


def find_staged_core() -> tuple[str | None, Path | None]:
    """Return (version, staged_dir) for the staged core waiting to be activated.

    The version is the name of the staged directory. Returns (None, None) when
    no staged core holds a binary.
    """
    staging = staging_dir()
    if not staging.is_dir():
        return None, None
    try:
        children = sorted(staging.iterdir())
    except OSError:
        return None, None
    for child in children:
        if child.is_dir() and (child / binary_name()).is_file():
            return child.name, child
    return None, None


def promote_pending_core() -> str | None:
    """Promote the staged core and clear the pending update state.

    Returns the promoted version, or None when no staged core was waiting.
    """
    version, staged = find_staged_core()
    if staged is None:
        return None
    promote_staged(staged)
    state = read_update_state()
    state.pending_version = None
    state.pending_asset_name = None
    write_update_state(state)
    logger.info("Promoted staged CLIProxyAPI core %s", version)
    return version
