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
    """Ensure PROVENANCE.json contains pinned v8.0.39 release assets, archive hashes, and binary hashes."""
    data = json.loads(PROVENANCE_JSON.read_text(encoding="utf-8"))
    assert data["version"] == "v8.0.39"
    assert data["license"] == "MIT"
    assert "router-for-me/CLIProxyAPI" in data["upstream_repository"]

    archs = data["architectures"]
    assert "windows_amd64" in archs
    assert "darwin_arm64" in archs
    assert "darwin_amd64" in archs

    # Windows x64
    win = archs["windows_amd64"]
    assert win["sha256"] == "41ab6cdde60e9c190ded5f7fce27e5b3090a83b75895d7fbb879675f563936e0"
    assert win["binary_sha256"] == "42574a2a028058ab0e7473e15b99cbb5e5370a46c70839c830758ee549b7a052"
    assert win["asset_name"] == "CLIProxyAPI_8.0.39_windows_amd64.zip"
    assert win["target_binary_name"] == "cliproxyapi.exe"

    # macOS arm64
    mac_arm = archs["darwin_arm64"]
    assert mac_arm["sha256"] == "1febf0f15bef7cc70630496a4f5b145d1faafedf2c8bf0ae4d5648f0972b24be"
    assert mac_arm["binary_sha256"] == "510a1f974a5b409bd9ee016d6f9ebcf6eb0b0f2a562858543d15af0e8deb5275"
    assert mac_arm["asset_name"] == "CLIProxyAPI_8.0.39_darwin_aarch64.tar.gz"

    # macOS x64
    mac_intel = archs["darwin_amd64"]
    assert mac_intel["sha256"] == "1cb6ab8893811b5838d59b22a11bf4c9332cdbc40e66de18edbd4c926f2635ea"
    assert mac_intel["binary_sha256"] == "f1fef944619f05781f06d2286610291565a5924c10a1beda650774e473555bb2"
    assert mac_intel["asset_name"] == "CLIProxyAPI_8.0.39_darwin_amd64.tar.gz"

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
