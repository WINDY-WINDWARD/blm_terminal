"""Tests for CLIProxyAPI packaging, provenance, and checksum verification logic."""

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PROVENANCE_JSON = REPO_ROOT / "resources" / "cliproxyapi" / "PROVENANCE.json"
PROVENANCE_MD = REPO_ROOT / "resources" / "cliproxyapi" / "PROVENANCE.md"
LICENSE_FILE = REPO_ROOT / "resources" / "cliproxyapi" / "LICENSE"
STAGE_PS1 = REPO_ROOT / "scripts" / "stage_cliproxyapi.ps1"
STAGED_WIN_BIN = REPO_ROOT / "vendor" / "cliproxyapi" / "runtime" / "cliproxyapi.exe"


def test_provenance_files_exist():
    """Ensure provenance and MIT license files exist in resources/cliproxyapi."""
    assert PROVENANCE_JSON.exists(), "PROVENANCE.json missing"
    assert PROVENANCE_MD.exists(), "PROVENANCE.md missing"
    assert LICENSE_FILE.exists(), "LICENSE missing"


def test_provenance_pinned_version_and_checksums():
    """Ensure PROVENANCE.json contains pinned v8.0.35 release assets, archive hashes, and binary hashes."""
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
    assert win["binary_sha256"] == "e142a8bd7c425e3c28026ffd0bf4e9774668bd60ea4a4d52c5057bd4a884738d"
    assert win["asset_name"] == "CLIProxyAPI_8.0.35_windows_amd64.zip"
    assert win["target_binary_name"] == "cliproxyapi.exe"

    # macOS arm64
    mac_arm = archs["darwin_arm64"]
    assert mac_arm["sha256"] == "b6903000ae78b541e5ba0bb2db45fc15dc23cab77fb51ed4b02e03ea18fe36a5"
    assert mac_arm["binary_sha256"] == "2b327650d076752a025c590c463827ada7596bf8b5db610233996e12facf5ea8"
    assert mac_arm["asset_name"] == "CLIProxyAPI_8.0.35_darwin_aarch64.tar.gz"

    # macOS x64
    mac_intel = archs["darwin_amd64"]
    assert mac_intel["sha256"] == "c1335ddb5307d67684ec0531fac81e1148b68869179310ea0f4086109fbebe2b"
    assert mac_intel["binary_sha256"] == "aaaff01623aa6e5db00a11175badd78f9a6b5e8cf6c8270195e6c4fa68dd30eb"
    assert mac_intel["asset_name"] == "CLIProxyAPI_8.0.35_darwin_amd64.tar.gz"

    # Windows ARM64 rejected
    unsupported = data.get("unsupported_architectures", [])
    assert any(u.get("platform") == "win32" and u.get("arch") == "arm64" for u in unsupported)


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell staging script verification on Windows")
def test_staging_script_rejects_missing_binary(tmp_path):
    """Fail closed when verify-only is run on a directory with no binary."""
    res = subprocess.run(
        [
            "powershell",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(STAGE_PS1),
            "-TargetDir",
            str(tmp_path),
            "-VerifyOnly",
        ],
        capture_output=True,
        text=True,
    )
    assert res.returncode != 0
    assert "missing" in (res.stderr + res.stdout).lower()


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell staging script verification on Windows")
def test_staging_script_rejects_tampered_or_oversized_binary(tmp_path):
    """Fail closed when verify-only detects a tampered binary, even if size > 1MB."""
    tampered_file = tmp_path / "cliproxyapi.exe"
    # Write 2MB of dummy data (exceeds size threshold but has wrong hash)
    tampered_file.write_bytes(b"A" * (2 * 1024 * 1024))

    res = subprocess.run(
        [
            "powershell",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(STAGE_PS1),
            "-TargetDir",
            str(tmp_path),
            "-VerifyOnly",
        ],
        capture_output=True,
        text=True,
    )
    assert res.returncode != 0
    assert "checksum verification" in (res.stderr + res.stdout).lower()


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell staging script verification on Windows")
def test_staging_script_verifies_valid_binary(tmp_path):
    """Pass verify-only when the staged binary matches the pinned binary SHA-256."""
    assert STAGED_WIN_BIN.exists(), "Staged Windows binary must exist at vendor/cliproxyapi/runtime/cliproxyapi.exe"
    target = tmp_path / "cliproxyapi.exe"
    shutil.copyfile(STAGED_WIN_BIN, target)

    res = subprocess.run(
        [
            "powershell",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(STAGE_PS1),
            "-TargetDir",
            str(tmp_path),
            "-VerifyOnly",
        ],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0
    assert "verified" in (res.stderr + res.stdout).lower()


def test_license_file_content():
    """Ensure MIT license file contains Router-For.ME copyright notice."""
    license_text = LICENSE_FILE.read_text(encoding="utf-8")
    assert "MIT License" in license_text
    assert "Router-For.ME" in license_text

def test_electron_builder_packages_cliproxyapi_and_notice():
    """Validate electron-builder.json configuration mapping (not built artifacts) packages CLIProxyAPI binary and notices for both Windows and macOS."""
    eb_path = REPO_ROOT / "electron-builder.json"
    assert eb_path.exists(), "electron-builder.json missing"
    eb_config = json.loads(eb_path.read_text(encoding="utf-8"))

    # Windows extraResources
    win_resources = eb_config.get("win", {}).get("extraResources", [])
    win_from_to = {item["from"]: item["to"] for item in win_resources}
    assert "vendor/cliproxyapi/runtime/cliproxyapi.exe" in win_from_to
    assert win_from_to["vendor/cliproxyapi/runtime/cliproxyapi.exe"] == "resources/cliproxyapi/cliproxyapi.exe"
    assert "resources/cliproxyapi" in win_from_to
    assert win_from_to["resources/cliproxyapi"] == "resources/cliproxyapi"

    # macOS extraResources
    mac_resources = eb_config.get("mac", {}).get("extraResources", [])
    mac_from_to = {item["from"]: item["to"] for item in mac_resources}
    assert "vendor/cliproxyapi/runtime/cliproxyapi" in mac_from_to
    assert mac_from_to["vendor/cliproxyapi/runtime/cliproxyapi"] == "resources/cliproxyapi/cliproxyapi"
    assert "resources/cliproxyapi" in mac_from_to
    assert mac_from_to["resources/cliproxyapi"] == "resources/cliproxyapi"

    # Verify notice and provenance files exist in the packaged directory
    pkg_dir = REPO_ROOT / "resources" / "cliproxyapi"
    assert (pkg_dir / "LICENSE").exists()
    assert (pkg_dir / "PROVENANCE.json").exists()
    assert (pkg_dir / "PROVENANCE.md").exists()
