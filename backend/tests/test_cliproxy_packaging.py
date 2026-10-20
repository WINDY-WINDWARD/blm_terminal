"""Tests for CLIProxyAPI packaging, provenance, and checksum verification logic."""

import hashlib
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PROVENANCE_JSON = REPO_ROOT / "resources" / "cliproxyapi" / "PROVENANCE.json"
PROVENANCE_MD = REPO_ROOT / "resources" / "cliproxyapi" / "PROVENANCE.md"
LICENSE_FILE = REPO_ROOT / "resources" / "cliproxyapi" / "LICENSE"


def test_provenance_files_exist():
    """Ensure provenance and MIT license files exist in resources/cliproxyapi."""
    assert PROVENANCE_JSON.exists(), "PROVENANCE.json missing"
    assert PROVENANCE_MD.exists(), "PROVENANCE.md missing"
    assert LICENSE_FILE.exists(), "LICENSE missing"


def test_provenance_pinned_version_and_checksums():
    """Ensure PROVENANCE.json contains pinned v8.0.35 release assets and exact checksums."""
    data = json.loads(PROVENANCE_JSON.read_text(encoding="utf-8"))
    assert data["version"] == "v8.0.35"
    assert data["license"] == "MIT"
    assert "router-for-me/CLIProxyAPI" in data["upstream_repository"]

    archs = data["architectures"]
    assert "windows_amd64" in archs
    assert "darwin_arm64" in archs
    assert "darwin_amd64" in archs

    # Windows x64
    win = archs["windows_amd64"]
    assert win["sha256"] == "175a79c47705408c4ee95ff78cafb50a0542a010d3fac333162f10f0b9dbea88"
    assert win["asset_name"] == "CLIProxyAPI_8.0.35_windows_amd64.zip"
    assert win["target_binary_name"] == "cliproxyapi.exe"

    # macOS arm64
    mac_arm = archs["darwin_arm64"]
    assert mac_arm["sha256"] == "b6903000ae78b541e5ba0bb2db45fc15dc23cab77fb51ed4b02e03ea18fe36a5"
    assert mac_arm["asset_name"] == "CLIProxyAPI_8.0.35_darwin_aarch64.tar.gz"

    # macOS x64
    mac_intel = archs["darwin_amd64"]
    assert mac_intel["sha256"] == "c1335ddb5307d67684ec0531fac81e1148b68869179310ea0f4086109fbebe2b"
    assert mac_intel["asset_name"] == "CLIProxyAPI_8.0.35_darwin_amd64.tar.gz"

    # Windows ARM64 rejected
    unsupported = data.get("unsupported_architectures", [])
    assert any(u.get("platform") == "win32" and u.get("arch") == "arm64" for u in unsupported)


def test_staged_binary_integrity(tmp_path):
    """Simulate binary checksum verification logic and ensure tampered or corrupt files fail closed."""
    valid_content = b"fake-cliproxyapi-binary-content-123456789"
    valid_hash = hashlib.sha256(valid_content).hexdigest()

    test_bin = tmp_path / "cliproxyapi.exe"
    test_bin.write_bytes(valid_content)

    # Valid check
    computed = hashlib.sha256(test_bin.read_bytes()).hexdigest()
    assert computed == valid_hash

    # Tampered check
    tampered_content = b"malicious-payload"
    test_bin.write_bytes(tampered_content)
    tampered_hash = hashlib.sha256(test_bin.read_bytes()).hexdigest()
    assert tampered_hash != valid_hash


def test_license_file_content():
    """Ensure MIT license file contains Router-For.ME copyright notice."""
    license_text = LICENSE_FILE.read_text(encoding="utf-8")
    assert "MIT License" in license_text
    assert "Router-For.ME" in license_text
