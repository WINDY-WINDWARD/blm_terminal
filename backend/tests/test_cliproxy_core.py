"""Tests for cliproxy_core on-disk storage and management."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import pytest

from app.services import cliproxy_core
from app.services.cliproxy_core import (
    CORE_ROOT_ENV,
    CoreMetadata,
    UpdateState,
    binary_name,
    bootstrap_core,
    clear_work_dirs,
    core_root,
    download_dir,
    ensure_dirs,
    install_dir,
    installed_version,
    is_quarantined,
    managed_binary,
    promote_staged,
    quarantine_version,
    read_metadata,
    read_update_state,
    rollback_dir,
    rollback_install,
    sha256_file,
    staging_dir,
    write_metadata,
    write_update_state,
)


@pytest.fixture(autouse=True)
def setup_core_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Ensure all tests operate in isolated tmp_path root."""
    core_dir = tmp_path / "cliproxy-core"
    monkeypatch.setenv(CORE_ROOT_ENV, str(core_dir))
    return core_dir


def test_core_root_and_dirs(tmp_path: Path):
    root = core_root()
    assert root == (tmp_path / "cliproxy-core").resolve()
    assert install_dir() == root / "install"
    assert staging_dir() == root / "staging"
    assert download_dir() == root / "download"
    assert rollback_dir() == root / "rollback"


def test_ensure_dirs_creates_all_subdirs():
    ensure_dirs()
    assert install_dir().is_dir()
    assert staging_dir().is_dir()
    assert download_dir().is_dir()
    assert rollback_dir().is_dir()


def test_sha256_file(tmp_path: Path):
    test_file = tmp_path / "sample.bin"
    content = b"cliproxyapi test content " * 5000
    test_file.write_bytes(content)
    expected = hashlib.sha256(content).hexdigest().lower()
    assert sha256_file(test_file) == expected


def test_metadata_roundtrip():
    meta = CoreMetadata(
        version="1.2.3",
        asset_name="cliproxyapi-windows-amd64.exe",
        installed_at="2026-11-13T10:00:00Z",
        source="bundled",
    )
    write_metadata(meta)
    loaded = read_metadata()
    assert loaded is not None
    assert loaded == meta
    assert installed_version() == "1.2.3"


def test_read_metadata_corrupted_or_missing(tmp_path: Path):
    assert read_metadata() is None
    inst = install_dir()
    inst.mkdir(parents=True, exist_ok=True)
    meta_path = inst / "metadata.json"
    meta_path.write_text("{bad json...", encoding="utf-8")
    assert read_metadata() is None

    # Partial json parses with defaults
    meta_path.write_text(json.dumps({"version": "2.0.0"}), encoding="utf-8")
    partial = read_metadata()
    assert partial is not None
    assert partial.version == "2.0.0"
    assert partial.asset_name == ""
    assert partial.source == ""


def test_update_state_roundtrip():
    assert read_update_state() == UpdateState()
    state = UpdateState(
        last_check_at="2026-11-13T12:00:00Z",
        latest_version="2.0.0",
        pending_version="2.0.0",
        pending_asset_name="cliproxyapi.exe",
        quarantined=["1.9.0", "1.9.1"],
        last_error="network timeout",
    )
    write_update_state(state)
    loaded = read_update_state()
    assert loaded == state


def test_update_state_corrupted():
    root = core_root()
    root.mkdir(parents=True, exist_ok=True)
    state_file = root / "update-state.json"
    state_file.write_text("invalid json", encoding="utf-8")
    assert read_update_state() == UpdateState()


def test_bootstrap_core_copies_and_writes_metadata(tmp_path: Path):
    bundled = tmp_path / "bundled_binary"
    bundled_content = b"fake-bundled-binary-bytes"
    bundled.write_bytes(bundled_content)
    expected_hash = hashlib.sha256(bundled_content).hexdigest()

    result = bootstrap_core(bundled, version="0.9.0", expected_sha256=expected_hash)
    assert result is not None
    assert result == install_dir() / binary_name()
    assert result.is_file()
    assert result.read_bytes() == bundled_content

    meta = read_metadata()
    assert meta is not None
    assert meta.version == "0.9.0"
    assert meta.asset_name == bundled.name
    assert meta.source == "bundled"
    assert managed_binary() == result
    assert installed_version() == "0.9.0"


def test_bootstrap_core_idempotent(tmp_path: Path):
    bundled = tmp_path / "bundled_binary"
    bundled.write_bytes(b"v1")
    res1 = bootstrap_core(bundled, version="0.9.0")
    assert res1 is not None

    # Modify bundled file and call bootstrap again
    bundled.write_bytes(b"v2")
    res2 = bootstrap_core(bundled, version="1.0.0")
    assert res2 == res1
    assert res2.read_bytes() == b"v1"
    assert installed_version() == "0.9.0"


def test_bootstrap_core_checksum_mismatch(tmp_path: Path):
    bundled = tmp_path / "bundled_binary"
    bundled.write_bytes(b"content")
    bad_hash = "0000000000000000000000000000000000000000000000000000000000000000"
    with pytest.raises(ValueError, match="Checksum mismatch"):
        bootstrap_core(bundled, version="1.0.0", expected_sha256=bad_hash)
    assert managed_binary() is None


def test_bootstrap_core_missing_bundled(tmp_path: Path):
    missing = tmp_path / "nonexistent"
    assert bootstrap_core(missing, version="1.0.0") is None


def test_promote_staged(tmp_path: Path):
    # Setup initial install
    bundled = tmp_path / "initial"
    bundled.write_bytes(b"version 1.0")
    bootstrap_core(bundled, version="1.0.0")

    # Setup staged directory
    stage = staging_dir()
    stage.mkdir(parents=True, exist_ok=True)
    staged_bin = stage / binary_name()
    staged_bin.write_bytes(b"version 2.0")
    write_metadata(
        CoreMetadata("2.0.0", "new.exe", "2026-11-13T11:00:00Z", "remote"),
        directory=stage,
    )

    promoted = promote_staged(stage)
    assert promoted == install_dir()
    assert (install_dir() / binary_name()).read_bytes() == b"version 2.0"
    assert read_metadata(install_dir()).version == "2.0.0"

    # Verify rollback contains old install
    assert (rollback_dir() / binary_name()).is_file()
    assert (rollback_dir() / binary_name()).read_bytes() == b"version 1.0"
    assert read_metadata(rollback_dir()).version == "1.0.0"


def test_rollback_install(tmp_path: Path):
    # No rollback available
    assert not rollback_install()

    # Create install and rollback
    inst = install_dir()
    inst.mkdir(parents=True, exist_ok=True)
    (inst / binary_name()).write_bytes(b"v2")
    write_metadata(CoreMetadata("2.0.0", "bin2", "", "remote"), inst)

    rb = rollback_dir()
    rb.mkdir(parents=True, exist_ok=True)
    (rb / binary_name()).write_bytes(b"v1")
    write_metadata(CoreMetadata("1.0.0", "bin1", "", "bundled"), rb)

    success = rollback_install()
    assert success is True
    assert (install_dir() / binary_name()).read_bytes() == b"v1"
    assert read_metadata(install_dir()).version == "1.0.0"


def test_quarantine_version():
    assert not is_quarantined("1.5.0")
    quarantine_version("1.5.0")
    assert is_quarantined("1.5.0")
    # Idempotent
    quarantine_version("1.5.0")
    state = read_update_state()
    assert state.quarantined == ["1.5.0"]


def test_clear_work_dirs():
    s = staging_dir()
    d = download_dir()
    s.mkdir(parents=True, exist_ok=True)
    d.mkdir(parents=True, exist_ok=True)
    (s / "leftover.tmp").write_text("hello")
    (d / "package.tar.gz").write_text("world")

    clear_work_dirs()
    assert s.is_dir()
    assert d.is_dir()
    assert not (s / "leftover.tmp").exists()
    assert not (d / "package.tar.gz").exists()
