"""Tests for CLIProxyAPI packaging, provenance, and checksum verification logic."""

import hashlib
import json
import re
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
STAGE_SH = REPO_ROOT / "scripts" / "stage_cliproxyapi.sh"
STAGED_WIN_BIN = REPO_ROOT / "vendor" / "cliproxyapi" / "runtime" / "cliproxyapi.exe"


def test_provenance_files_exist():
    """Ensure provenance and MIT license files exist in resources/cliproxyapi."""
    assert PROVENANCE_JSON.exists(), "PROVENANCE.json missing"
    assert PROVENANCE_MD.exists(), "PROVENANCE.md missing"
    assert LICENSE_FILE.exists(), "LICENSE missing"


def test_provenance_pinned_version_and_checksums():
    """Ensure PROVENANCE.json contains valid semantic version release assets, archive hashes, and binary hashes."""
    data = json.loads(PROVENANCE_JSON.read_text(encoding="utf-8"))
    version = data.get("version", "")
    assert re.match(r"^v\d+\.\d+\.\d+$", version), f"Invalid version pattern: {version}"
    assert data.get("release_tag") == version
    assert data.get("license") == "MIT"
    assert "router-for-me/CLIProxyAPI" in data.get("upstream_repository", "")

    archs = data.get("architectures", {})
    assert "windows_amd64" in archs
    assert "darwin_arm64" in archs
    assert "darwin_amd64" in archs

    hex64_re = re.compile(r"^[0-9a-f]{64}$")
    version_no_v = version.lstrip("v")

    for key in ("windows_amd64", "darwin_arm64", "darwin_amd64"):
        entry = archs[key]
        asset_name = entry.get("asset_name", "")
        download_url = entry.get("download_url", "")
        sha256 = entry.get("sha256", "")
        binary_sha256 = entry.get("binary_sha256", "")

        assert version_no_v in asset_name, f"Asset name {asset_name} missing {version_no_v}"
        assert asset_name in download_url, f"Download URL {download_url} missing asset {asset_name}"
        assert version in download_url, f"Download URL {download_url} missing version {version}"
        assert hex64_re.match(sha256), f"Invalid sha256 in {key}: {sha256}"
        assert hex64_re.match(binary_sha256), f"Invalid binary_sha256 in {key}: {binary_sha256}"
        assert "archive_binary_name" in entry and entry["archive_binary_name"]
        assert "target_binary_name" in entry and entry["target_binary_name"]

    # Windows ARM64 rejected
    unsupported = data.get("unsupported_architectures", [])
    assert any(u.get("platform") == "win32" and u.get("arch") == "arm64" for u in unsupported)


def test_staging_scripts_read_provenance_without_hardcoded_version():
    """Ensure staging scripts read PROVENANCE.json and do not hard-code 8.0.39."""
    assert STAGE_PS1.exists(), "stage_cliproxyapi.ps1 missing"
    assert STAGE_SH.exists(), "stage_cliproxyapi.sh missing"

    ps1_text = STAGE_PS1.read_text(encoding="utf-8")
    sh_text = STAGE_SH.read_text(encoding="utf-8")

    assert "8.0.39" not in ps1_text, "Hard-coded version 8.0.39 found in stage_cliproxyapi.ps1"
    assert "8.0.39" not in sh_text, "Hard-coded version 8.0.39 found in stage_cliproxyapi.sh"

    assert "PROVENANCE.json" in ps1_text, "stage_cliproxyapi.ps1 must mention PROVENANCE.json"
    assert "PROVENANCE.json" in sh_text, "stage_cliproxyapi.sh must mention PROVENANCE.json"


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
    if not STAGED_WIN_BIN.exists():
        pytest.skip(f"Staged Windows binary not present at {STAGED_WIN_BIN}")
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
