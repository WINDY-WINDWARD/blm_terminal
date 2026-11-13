"""Downloader, verifier, and stager for CLIProxyAPI upstream binaries.

This module fetches releases from GitHub / GitCode, validates archive checksums
and signatures, extracts the binary safely, and stages it for installation.
It does not execute the binary or replace the running install.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import os
import platform as _platform
import re
import sys
import tarfile
import zipfile
import dataclasses as _dataclasses
from pathlib import Path
from typing import Any

import httpx

from app.services import cliproxy_core

GITHUB_REPO: str = "router-for-me/CLIProxyAPI"
GITHUB_API_LATEST: str = "https://api.github.com/repos/router-for-me/CLIProxyAPI/releases/latest"
GITHUB_API_RELEASE: str = "https://api.github.com/repos/router-for-me/CLIProxyAPI/releases/tags/{tag}"
GITHUB_ATOM: str = "https://github.com/router-for-me/CLIProxyAPI/releases.atom"
GITCODE_API_LATEST: str = "https://api.gitcode.com/api/v5/repos/router-for-me/CLIProxyAPI/releases/latest"
CHECKSUMS_ASSET_NAME: str = "checksums.txt"
MIN_SUPPORTED_VERSION: str = "8.0.39"
USER_AGENT: str = "BLM-Terminal-CliProxyAPI-Updater"

_VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:-(.+))?$")
_ATOM_TAG_RE = re.compile(r"/releases/tag/(?:v)?(\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?)")


@_dataclasses.dataclass
class ReleaseAsset:
    """Metadata describing a downloadable release artifact."""

    name: str
    size: int
    digest: str | None
    download_url: str


@_dataclasses.dataclass
class Release:
    """Metadata describing an upstream release."""

    tag: str
    version: str
    assets: list[ReleaseAsset]


def normalize_version(value: str) -> str:
    """Strip surrounding whitespace and a leading 'v' or 'V' character."""
    cleaned = value.strip()
    if cleaned.startswith(("v", "V")):
        cleaned = cleaned[1:]
    return cleaned


def parse_version(value: str) -> tuple[int, int, int, str | None]:
    """Parse a semantic version string into (major, minor, patch, prerelease).

    Raises:
        ValueError: When the version string does not conform to <digits>.<digits>.<digits>.
    """
    normalized = normalize_version(value)
    match = _VERSION_RE.match(normalized)
    if not match:
        raise ValueError(f"Invalid semantic version: {value!r}")
    major, minor, patch, prerelease = match.groups()
    return int(major), int(minor), int(patch), prerelease


def compare_versions(a: str, b: str) -> int:
    """Compare two semantic version strings.

    Returns:
        -1 if a < b, 0 if a == b, 1 if a > b. A prerelease sorts below the
        same release without a prerelease tag.
    """
    maj_a, min_a, pat_a, pre_a = parse_version(a)
    maj_b, min_b, pat_b, pre_b = parse_version(b)

    num_tuple_a = (maj_a, min_a, pat_a)
    num_tuple_b = (maj_b, min_b, pat_b)

    if num_tuple_a < num_tuple_b:
        return -1
    if num_tuple_a > num_tuple_b:
        return 1

    # Numeric parts are identical: check prerelease
    if pre_a is None and pre_b is None:
        return 0
    if pre_a is not None and pre_b is None:
        # a is a prerelease of b, so a < b
        return -1
    if pre_a is None and pre_b is not None:
        # b is a prerelease of a, so a > b
        return 1

    # Both have prereleases: lexicographical/dot-separated comparison
    if pre_a == pre_b:
        return 0
    return -1 if pre_a < pre_b else 1


def is_newer(candidate: str, current: str | None) -> bool:
    """Return True when candidate version is strictly newer than current version."""
    if not current:
        return True
    return compare_versions(candidate, current) > 0


def current_platform() -> tuple[str, str, str]:
    """Identify the host platform for matching upstream release assets.

    Returns:
        (asset_os, asset_arch, archive_kind) tuple.

    Raises:
        ValueError: For unsupported platforms or architectures.
    """
    system = sys.platform
    machine = _platform.machine().lower()

    if system == "win32":
        asset_os = "windows"
        archive_kind = "zip"
    elif system == "darwin":
        asset_os = "darwin"
        archive_kind = "tar.gz"
    elif system.startswith("linux"):
        asset_os = "linux"
        archive_kind = "tar.gz"
    else:
        raise ValueError(f"Unsupported operating system: {sys.platform}")

    if machine in ("amd64", "x86_64"):
        asset_arch = "amd64"
    elif machine in ("arm64", "aarch64"):
        asset_arch = "aarch64"
    else:
        raise ValueError(f"Unsupported architecture: {_platform.machine()}")

    if asset_os == "windows" and asset_arch == "aarch64":
        raise ValueError("Windows on ARM64 is not supported for CLIProxyAPI")

    return asset_os, asset_arch, archive_kind


def asset_name(version: str, platform: tuple[str, str, str]) -> str:
    """Format the canonical archive name expected for a version and platform."""
    ver_clean = normalize_version(version)
    asset_os, asset_arch, archive_kind = platform
    return f"CLIProxyAPI_{ver_clean}_{asset_os}_{asset_arch}.{archive_kind}"


def select_asset(release: Release, platform: tuple[str, str, str]) -> ReleaseAsset:
    """Find the matching ReleaseAsset for the given platform, rejecting '_no-plugin'.

    Raises:
        ValueError: When no suitable asset matches the platform specification.
    """
    target_name = asset_name(release.version, platform)
    for candidate in release.assets:
        if candidate.name == target_name:
            if "_no-plugin" in candidate.name:
                continue
            return candidate
    raise ValueError(f"Asset {target_name!r} not found in release {release.tag}")


async def fetch_release(client: httpx.AsyncClient, version: str | None = None) -> Release:
    """Fetch release metadata from GitHub API for latest or a specific tag.

    Raises:
        RuntimeError: When HTTP request fails or payload lacks a tag name.
    """
    # Upstream tags carry a leading "v" ("v8.0.69"). A caller that passes a
    # bare version must still address the right release.
    tag = version
    if tag and not tag.startswith(("v", "V")):
        tag = f"v{tag}"
    url = GITHUB_API_RELEASE.format(tag=tag) if version else GITHUB_API_LATEST
    headers = {"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"}
    try:
        response = await client.get(url, headers=headers)
        response.raise_for_status()
    except Exception as exc:
        raise RuntimeError(f"Failed to fetch release from {url}: {exc}") from exc

    data = response.json()
    tag_name = data.get("tag_name")
    if not tag_name:
        raise RuntimeError(f"GitHub release payload from {url} is missing 'tag_name'")

    assets_raw = data.get("assets", [])
    assets: list[ReleaseAsset] = []
    for item in assets_raw:
        name = item.get("name", "")
        size = item.get("size", 0)
        digest = item.get("digest")
        download_url = item.get("browser_download_url", "")
        if name and download_url:
            assets.append(ReleaseAsset(name=name, size=size, digest=digest, download_url=download_url))

    return Release(
        tag=tag_name,
        version=normalize_version(tag_name),
        assets=assets,
    )


async def fetch_latest_version(client: httpx.AsyncClient) -> str:
    """Discover the newest version string across GitHub API, GitHub Atom feed, and GitCode.

    Raises:
        RuntimeError: If all upstream discovery mechanisms fail.
    """
    errors: list[str] = []

    # 1. GitHub API
    try:
        release = await fetch_release(client, version=None)
        return release.version
    except Exception as exc:
        errors.append(f"GitHub API: {exc}")

    # 2. GitHub Atom feed
    try:
        atom_resp = await client.get(GITHUB_ATOM, headers={"User-Agent": USER_AGENT})
        atom_resp.raise_for_status()
        matches = _ATOM_TAG_RE.findall(atom_resp.text)
        if matches:
            candidates: list[str] = []
            for tag_str in matches:
                clean = normalize_version(tag_str)
                try:
                    parse_version(clean)
                    candidates.append(clean)
                except ValueError:
                    continue
            if candidates:
                # Pick the highest according to compare_versions
                def _cmp_key(v: str) -> tuple[int, int, int, int, str]:
                    maj, mi, pa, pre = parse_version(v)
                    return (maj, mi, pa, 0 if pre is not None else 1, pre or "")

                candidates.sort(key=_cmp_key)
                return candidates[-1]
            errors.append("GitHub Atom: No valid semantic version tags found in feed")
        else:
            errors.append("GitHub Atom: No release tag patterns matched in feed")
    except Exception as exc:
        errors.append(f"GitHub Atom: {exc}")

    # 3. GitCode API
    try:
        gitcode_resp = await client.get(GITCODE_API_LATEST, headers={"User-Agent": USER_AGENT})
        gitcode_resp.raise_for_status()
        data = gitcode_resp.json()
        tag = data.get("tag_name") or data.get("name")
        if tag:
            return normalize_version(tag)
        errors.append("GitCode API: Missing tag_name or name in payload")
    except Exception as exc:
        errors.append(f"GitCode API: {exc}")

    raise RuntimeError(f"All version discovery sources failed: {'; '.join(errors)}")


async def download_asset(
    client: httpx.AsyncClient,
    asset: ReleaseAsset,
    dest: Path,
    mirrors: list[str] | None = None,
) -> Path:
    """Download an asset streaming to a temporary file before renaming to dest.

    Raises:
        RuntimeError: If all candidate download URLs fail.
    """
    candidate_urls: list[str] = []
    if mirrors:
        for m in mirrors:
            prefix = m.rstrip("/")
            candidate_urls.append(f"{prefix}/{asset.name}")
    candidate_urls.append(asset.download_url)

    dest.parent.mkdir(parents=True, exist_ok=True)
    part_path = dest.with_name(f"{dest.name}.part")

    errors: list[str] = []
    for url in candidate_urls:
        if part_path.exists():
            try:
                part_path.unlink()
            except OSError:
                pass
        try:
            async with client.stream("GET", url, headers={"User-Agent": USER_AGENT}, follow_redirects=True) as resp:
                resp.raise_for_status()
                with open(part_path, "wb") as f:
                    async for chunk in resp.aiter_bytes(chunk_size=65536):
                        f.write(chunk)
            os.replace(part_path, dest)
            return dest
        except Exception as exc:
            errors.append(f"{url}: {exc}")
            if part_path.exists():
                try:
                    part_path.unlink()
                except OSError:
                    pass

    raise RuntimeError(f"Failed to download asset {asset.name} from all sources: {'; '.join(errors)}")


def parse_checksums(text: str) -> dict[str, str]:
    """Parse a checksums.txt file containing '<sha256> [*]<name>' lines."""
    result: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(maxsplit=1)
        if len(parts) == 2:
            digest, filename = parts[0].strip().lower(), parts[1].strip()
            if filename.startswith("*"):
                filename = filename[1:]
            result[filename] = digest
    return result


def verify_asset(path: Path, asset: ReleaseAsset, checksums: dict[str, str] | None = None) -> None:
    """Verify archive size and cryptographic checksums against the asset metadata.

    Raises:
        ValueError: When size or checksum verification fails.
    """
    stat = path.stat()
    if asset.size > 0 and stat.st_size != asset.size:
        raise ValueError(f"Asset size mismatch for {path.name}: expected {asset.size}, got {stat.st_size}")

    file_sha256 = cliproxy_core.sha256_file(path).lower()

    if asset.digest:
        expected_digest = asset.digest.lower()
        if expected_digest.startswith("sha256:"):
            expected_digest = expected_digest.split(":", 1)[1]
        if file_sha256 != expected_digest:
            raise ValueError(f"Asset digest mismatch for {path.name}: expected {expected_digest}, got {file_sha256}")

    if checksums and asset.name in checksums:
        expected_cs = checksums[asset.name].lower()
        if file_sha256 != expected_cs:
            raise ValueError(f"Checksum mismatch for {path.name}: expected {expected_cs}, got {file_sha256}")


def extract_archive(path: Path, dest: Path) -> None:
    """Safely extract a .zip or .tar.gz archive into dest, preventing zip-slip.

    Raises:
        ValueError: When an entry attempts to escape the destination directory.
    """
    dest.mkdir(parents=True, exist_ok=True)
    resolved_dest = dest.resolve()

    def _is_inside(member_name: str) -> bool:
        # Compare path parts. A plain string prefix would accept
        # "<dest>-evil" because it starts with the destination text.
        try:
            member_path = (dest / member_name).resolve()
        except OSError:
            return False
        return member_path == resolved_dest or resolved_dest in member_path.parents

    if path.name.endswith(".zip"):
        with zipfile.ZipFile(path, "r") as zf:
            for member in zf.infolist():
                if not _is_inside(member.filename):
                    raise ValueError(f"Illegal path escape in zip archive: {member.filename}")
            zf.extractall(dest)
    elif path.name.endswith((".tar.gz", ".tgz")):
        with tarfile.open(path, "r:*") as tf:
            for member in tf.getmembers():
                if not _is_inside(member.name):
                    raise ValueError(f"Illegal path escape in tar archive: {member.name}")
            try:
                # "data" rejects absolute paths, links that escape, and special
                # files. Python 3.11.4 and newer accept the filter argument.
                tf.extractall(dest, filter="data")
            except TypeError:
                tf.extractall(dest)
    else:
        raise ValueError(f"Unsupported archive format: {path.name}")


def locate_binary(directory: Path) -> Path | None:
    """Locate the extracted CLIProxyAPI executable within the target directory."""
    target_names = {"cli-proxy-api", "cli-proxy-api.exe"}
    fallback_candidates: list[Path] = []

    for root, _, files in os.walk(directory):
        for f in files:
            f_lower = f.lower()
            full_path = Path(root) / f
            if f_lower in target_names:
                return full_path
            if f_lower.startswith("cliproxyapi"):
                fallback_candidates.append(full_path)

    if fallback_candidates:
        return fallback_candidates[0]
    return None


async def stage_release(
    release: Release,
    asset: ReleaseAsset,
    mirrors: list[str] | None = None,
) -> Path:
    """Download, verify, extract, and stage a release artifact.

    Raises:
        RuntimeError: If download, verification, extraction, or staging fails.
    """
    cliproxy_core.ensure_dirs()
    cliproxy_core.clear_work_dirs()

    download_dest = cliproxy_core.download_dir() / asset.name
    staged_ver_dir = cliproxy_core.staging_dir() / release.version

    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            await download_asset(client, asset, download_dest, mirrors=mirrors)

            # Look for checksums.txt in the release
            checksums_dict: dict[str, str] | None = None
            checksums_asset = next((a for a in release.assets if a.name == CHECKSUMS_ASSET_NAME), None)
            if checksums_asset:
                cs_dest = cliproxy_core.download_dir() / CHECKSUMS_ASSET_NAME
                try:
                    await download_asset(client, checksums_asset, cs_dest, mirrors=mirrors)
                    checksums_dict = parse_checksums(cs_dest.read_text(encoding="utf-8", errors="replace"))
                except Exception:
                    checksums_dict = None

            verify_asset(download_dest, asset, checksums_dict)

            extract_archive(download_dest, staged_ver_dir)

            found_bin = locate_binary(staged_ver_dir)
            if not found_bin:
                raise RuntimeError(f"Executable not found in extracted archive {asset.name}")

            expected_bin_name = cliproxy_core.binary_name()
            final_bin_path = staged_ver_dir / expected_bin_name
            if found_bin.resolve() != final_bin_path.resolve():
                if final_bin_path.exists():
                    final_bin_path.unlink()
                os.replace(found_bin, final_bin_path)

            now_iso = _dt.datetime.now(_dt.timezone.utc).isoformat()
            meta = cliproxy_core.CoreMetadata(
                version=release.version,
                asset_name=asset.name,
                installed_at=now_iso,
                source="upstream",
            )
            cliproxy_core.write_metadata(meta, staged_ver_dir)
            return staged_ver_dir
        except Exception as exc:
            # Clean staging directory on failure
            if staged_ver_dir.exists():
                for root, dirs, files in os.walk(staged_ver_dir, topdown=False):
                    for name in files:
                        try:
                            os.unlink(os.path.join(root, name))
                        except OSError:
                            pass
                    for name in dirs:
                        try:
                            os.rmdir(os.path.join(root, name))
                        except OSError:
                            pass
                try:
                    staged_ver_dir.rmdir()
                except OSError:
                    pass
            raise RuntimeError(f"Failed to stage release {release.version}: {exc}") from exc


async def check_and_stage(
    *,
    mirrors: list[str] | None = None,
    allow_download: bool = True,
) -> dict[str, Any]:
    """Check for upstream updates, download and stage when permitted, and update state."""
    cliproxy_core.ensure_dirs()
    installed_ver = cliproxy_core.installed_version()
    state = cliproxy_core.read_update_state()

    latest_ver: str | None = None
    update_available = False
    staged = False
    pending_ver = state.pending_version if state else None
    error_msg: str | None = None
    now_iso = _dt.datetime.now(_dt.timezone.utc).isoformat()

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            latest_ver = await fetch_latest_version(client)
            if state:
                state.latest_version = latest_ver

            if cliproxy_core.is_quarantined(latest_ver):
                error_msg = f"Version {latest_ver} is quarantined and cannot be installed"
                update_available = False
            elif is_newer(latest_ver, installed_ver):
                update_available = True
                if allow_download:
                    rel = await fetch_release(client, version=latest_ver)
                    plat = current_platform()
                    asset = select_asset(rel, plat)
                    await stage_release(rel, asset, mirrors=mirrors)
                    staged = True
                    pending_ver = latest_ver
                    if state:
                        state.pending_version = latest_ver
                        state.pending_asset_name = asset.name
    except Exception as exc:
        error_msg = str(exc)

    if state:
        state.last_check_at = now_iso
        state.last_error = error_msg
        cliproxy_core.write_update_state(state)

    return {
        "latest_version": latest_ver,
        "installed_version": installed_ver,
        "update_available": update_available,
        "staged": staged,
        "pending_version": pending_ver,
        "error": error_msg,
    }
