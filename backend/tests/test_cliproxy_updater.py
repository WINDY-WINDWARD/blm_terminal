"""Unit tests for the CLIProxyAPI core updater module."""
from __future__ import annotations

import io
import os
from pathlib import Path
import platform as _platform
import sys
import tarfile
import zipfile
import pytest
import httpx

from app.services import cliproxy_core
from app.services import cliproxy_updater


@pytest.fixture(autouse=True)
def setup_core_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Ensure all tests operate in isolated tmp_path root."""
    core_dir = tmp_path / "cliproxy-core"
    monkeypatch.setenv(cliproxy_core.CORE_ROOT_ENV, str(core_dir))
    return core_dir


def test_normalize_version():
    """1. normalize_version strips a leading v/V and whitespace."""
    assert cliproxy_updater.normalize_version("  v8.0.69  ") == "8.0.69"
    assert cliproxy_updater.normalize_version("V8.0.70\n") == "8.0.70"
    assert cliproxy_updater.normalize_version("8.0.71") == "8.0.71"


def test_parse_version():
    """2. parse_version parses semantic versions and raises ValueError for invalid versions."""
    assert cliproxy_updater.parse_version("8.0.69") == (8, 0, 69, None)
    assert cliproxy_updater.parse_version("v8.0.69-beta.1") == (8, 0, 69, "beta.1")

    with pytest.raises(ValueError, match="Invalid semantic version"):
        cliproxy_updater.parse_version("abc")

    with pytest.raises(ValueError, match="Invalid semantic version"):
        cliproxy_updater.parse_version("1.2")


def test_compare_versions():
    """3. compare_versions orders 8.0.10 above 8.0.9, prerelease below release, and returns 0 for equal."""
    assert cliproxy_updater.compare_versions("8.0.10", "8.0.9") == 1
    assert cliproxy_updater.compare_versions("8.0.9", "8.0.10") == -1
    assert cliproxy_updater.compare_versions("8.0.69", "8.0.69") == 0

    # Prerelease sorts below release without prerelease
    assert cliproxy_updater.compare_versions("8.0.69-beta", "8.0.69") == -1
    assert cliproxy_updater.compare_versions("8.0.69", "8.0.69-beta") == 1
    assert cliproxy_updater.compare_versions("8.0.69-alpha", "8.0.69-beta") == -1
    assert cliproxy_updater.compare_versions("8.0.69-rc1", "8.0.69-rc1") == 0


def test_is_newer():
    """4. is_newer returns True when current is None and False when candidate is older."""
    assert cliproxy_updater.is_newer("8.0.69", None) is True
    assert cliproxy_updater.is_newer("8.0.69", "") is True
    assert cliproxy_updater.is_newer("8.0.10", "8.0.9") is True
    assert cliproxy_updater.is_newer("8.0.9", "8.0.10") is False
    assert cliproxy_updater.is_newer("8.0.69", "8.0.69") is False


def test_current_platform(monkeypatch: pytest.MonkeyPatch):
    """5. current_platform returns ('windows', 'amd64', 'zip') and raises ValueError for windows/aarch64."""
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(_platform, "machine", lambda: "AMD64")
    assert cliproxy_updater.current_platform() == ("windows", "amd64", "zip")

    # Windows on ARM64 raises ValueError
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(_platform, "machine", lambda: "aarch64")
    with pytest.raises(ValueError, match="Windows on ARM64 is not supported"):
        cliproxy_updater.current_platform()

    # Unsupported OS raises ValueError
    monkeypatch.setattr(sys, "platform", "freebsd")
    with pytest.raises(ValueError, match="Unsupported operating system"):
        cliproxy_updater.current_platform()

    # Unsupported arch raises ValueError
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(_platform, "machine", lambda: "mips64")
    with pytest.raises(ValueError, match="Unsupported architecture"):
        cliproxy_updater.current_platform()


def test_asset_name():
    """6. asset_name builds expected archive name for version and platform."""
    name = cliproxy_updater.asset_name("8.0.69", ("windows", "amd64", "zip"))
    assert name == "CLIProxyAPI_8.0.69_windows_amd64.zip"

    name_v = cliproxy_updater.asset_name("v8.0.70", ("linux", "amd64", "tar.gz"))
    assert name_v == "CLIProxyAPI_8.0.70_linux_amd64.tar.gz"


def test_select_asset():
    """7. select_asset picks exact asset, ignores '_no-plugin', and raises ValueError when missing."""
    plat = ("windows", "amd64", "zip")
    target_name = "CLIProxyAPI_8.0.69_windows_amd64.zip"

    asset_exact = cliproxy_updater.ReleaseAsset(
        name=target_name, size=1024, digest=None, download_url="https://dl/exact.zip"
    )
    asset_no_plugin = cliproxy_updater.ReleaseAsset(
        name="CLIProxyAPI_8.0.69_windows_amd64_no-plugin.zip", size=1024, digest=None, download_url="https://dl/np.zip"
    )
    asset_linux = cliproxy_updater.ReleaseAsset(
        name="CLIProxyAPI_8.0.69_linux_amd64.tar.gz", size=1024, digest=None, download_url="https://dl/linux.tar.gz"
    )

    rel_with_both = cliproxy_updater.Release(
        tag="v8.0.69", version="8.0.69", assets=[asset_no_plugin, asset_exact, asset_linux]
    )
    selected = cliproxy_updater.select_asset(rel_with_both, plat)
    assert selected == asset_exact

    # Release missing target asset raises ValueError
    rel_missing = cliproxy_updater.Release(
        tag="v8.0.69", version="8.0.69", assets=[asset_linux]
    )
    with pytest.raises(ValueError, match="not found in release"):
        cliproxy_updater.select_asset(rel_missing, plat)


def test_parse_checksums():
    """8. parse_checksums parses standard checksums lines into a dict."""
    text = (
        "abc123  file.zip\n"
        "def456 *binary.tar.gz\n"
        "\n"
        "789ghi   spaced_file.zip \n"
    )
    parsed = cliproxy_updater.parse_checksums(text)
    assert parsed == {
        "file.zip": "abc123",
        "binary.tar.gz": "def456",
        "spaced_file.zip": "789ghi",
    }


def test_verify_asset(tmp_path: Path):
    """9. verify_asset checks size, digest, and checksums.txt, and raises ValueError on mismatch."""
    sample = tmp_path / "sample.bin"
    content = b"sample archive payload bytes"
    sample.write_bytes(content)
    actual_size = len(content)
    actual_sha = cliproxy_core.sha256_file(sample)

    asset = cliproxy_updater.ReleaseAsset(
        name="sample.bin", size=actual_size, digest=f"sha256:{actual_sha}", download_url="http://fake"
    )

    # Valid asset passes with no exceptions
    cliproxy_updater.verify_asset(sample, asset, checksums={asset.name: actual_sha})

    # Wrong size
    bad_size_asset = cliproxy_updater.ReleaseAsset(
        name="sample.bin", size=actual_size + 10, digest=actual_sha, download_url="http://fake"
    )
    with pytest.raises(ValueError, match="size mismatch"):
        cliproxy_updater.verify_asset(sample, bad_size_asset)

    # Wrong digest
    bad_digest_asset = cliproxy_updater.ReleaseAsset(
        name="sample.bin", size=actual_size, digest="sha256:00000000000000000000000000000000", download_url="http://fake"
    )
    with pytest.raises(ValueError, match="digest mismatch"):
        cliproxy_updater.verify_asset(sample, bad_digest_asset)

    # Wrong checksums.txt entry
    with pytest.raises(ValueError, match="Checksum mismatch"):
        cliproxy_updater.verify_asset(sample, asset, checksums={asset.name: "ffffffffffffffffff"})


def test_extract_archive_valid(tmp_path: Path):
    """10. extract_archive extracts both zip and tar.gz into destination."""
    # Test ZIP extraction
    zip_path = tmp_path / "archive.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("subdir/file1.txt", "content1")
        zf.writestr("file2.txt", "content2")

    dest_zip = tmp_path / "extracted_zip"
    cliproxy_updater.extract_archive(zip_path, dest_zip)
    assert (dest_zip / "subdir" / "file1.txt").read_text() == "content1"
    assert (dest_zip / "file2.txt").read_text() == "content2"

    # Test TAR.GZ extraction
    tar_path = tmp_path / "archive.tar.gz"
    with tarfile.open(tar_path, "w:gz") as tf:
        data = b"content tar"
        ti = tarfile.TarInfo(name="sub/file_tar.txt")
        ti.size = len(data)
        tf.addfile(ti, io.BytesIO(data))

    dest_tar = tmp_path / "extracted_tar"
    cliproxy_updater.extract_archive(tar_path, dest_tar)
    assert (dest_tar / "sub" / "file_tar.txt").read_bytes() == data


def test_extract_archive_escape(tmp_path: Path):
    """11. extract_archive raises ValueError for member escaping destination."""
    zip_path = tmp_path / "malicious.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("../escape.txt", "malicious payload")

    dest = tmp_path / "safe_dir"
    with pytest.raises(ValueError, match="Illegal path escape in zip archive"):
        cliproxy_updater.extract_archive(zip_path, dest)

    tar_path = tmp_path / "malicious.tar.gz"
    with tarfile.open(tar_path, "w:gz") as tf:
        data = b"malicious"
        ti = tarfile.TarInfo(name="../escape.txt")
        ti.size = len(data)
        tf.addfile(ti, io.BytesIO(data))

    with pytest.raises(ValueError, match="Illegal path escape in tar archive"):
        cliproxy_updater.extract_archive(tar_path, dest)


def test_locate_binary(tmp_path: Path):
    """12. locate_binary finds 'cli-proxy-api.exe' and returns None for empty dir."""
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    assert cliproxy_updater.locate_binary(empty_dir) is None

    # Exact binary name
    bin_dir = tmp_path / "bin_dir" / "nested"
    bin_dir.mkdir(parents=True)
    target_bin = bin_dir / "cli-proxy-api.exe"
    target_bin.write_bytes(b"dummy binary")
    assert cliproxy_updater.locate_binary(tmp_path / "bin_dir") == target_bin

    # Fallback binary name starting with cliproxyapi
    fallback_dir = tmp_path / "fallback"
    fallback_dir.mkdir()
    fb_bin = fallback_dir / "cliproxyapi_v8.exe"
    fb_bin.write_bytes(b"fallback")
    assert cliproxy_updater.locate_binary(fallback_dir) == fb_bin


async def test_fetch_release():
    """13. fetch_release builds tag URL 'v8.0.69' for version '8.0.69' and parses assets."""
    def handler(request: httpx.Request) -> httpx.Response:
        url_str = str(request.url)
        if url_str == "https://api.github.com/repos/router-for-me/CLIProxyAPI/releases/tags/v8.0.69":
            payload = {
                "tag_name": "v8.0.69",
                "assets": [
                    {
                        "name": "CLIProxyAPI_8.0.69_windows_amd64.zip",
                        "size": 12345,
                        "digest": "sha256:abc",
                        "browser_download_url": "https://github.com/download/asset.zip",
                    }
                ],
            }
            return httpx.Response(200, json=payload)
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        release = await cliproxy_updater.fetch_release(client, version="8.0.69")
        assert release.tag == "v8.0.69"
        assert release.version == "8.0.69"
        assert len(release.assets) == 1
        assert release.assets[0].name == "CLIProxyAPI_8.0.69_windows_amd64.zip"
        assert release.assets[0].size == 12345
        assert release.assets[0].digest == "sha256:abc"


async def test_fetch_latest_version():
    """14. fetch_latest_version falls back to Atom feed when GitHub API fails, then raises RuntimeError when all fail."""
    atom_feed_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <id>tag:github.com,2008:Repository/123/v8.0.50</id>
        <link rel="alternate" type="text/html" href="https://github.com/router-for-me/CLIProxyAPI/releases/tag/v8.0.50"/>
        <title>v8.0.50</title>
      </entry>
      <entry>
        <id>tag:github.com,2008:Repository/123/v8.0.70</id>
        <link rel="alternate" type="text/html" href="https://github.com/router-for-me/CLIProxyAPI/releases/tag/v8.0.70"/>
        <title>v8.0.70</title>
      </entry>
    </feed>
    """

    # Scenario A: GitHub API fails (500), Atom feed succeeds
    def handler_atom(request: httpx.Request) -> httpx.Response:
        url_str = str(request.url)
        if url_str == cliproxy_updater.GITHUB_API_LATEST:
            return httpx.Response(500)
        if url_str == cliproxy_updater.GITHUB_ATOM:
            return httpx.Response(200, text=atom_feed_xml)
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler_atom)) as client:
        latest = await cliproxy_updater.fetch_latest_version(client)
        assert latest == "8.0.70"

    # Scenario B: All three fail -> raises RuntimeError
    def handler_all_fail(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler_all_fail)) as client:
        with pytest.raises(RuntimeError, match="All version discovery sources failed"):
            await cliproxy_updater.fetch_latest_version(client)


async def test_download_asset(tmp_path: Path):
    """15. download_asset writes the file and returns the destination."""
    dest = tmp_path / "downloads" / "CLIProxyAPI_8.0.69_windows_amd64.zip"
    payload = b"dummy zip payload data"

    def handler(request: httpx.Request) -> httpx.Response:
        url_str = str(request.url)
        if url_str == "https://mirror1.local/CLIProxyAPI_8.0.69_windows_amd64.zip":
            return httpx.Response(500)
        if url_str == "https://github.com/download/asset.zip":
            return httpx.Response(200, content=payload)
        return httpx.Response(404)

    asset = cliproxy_updater.ReleaseAsset(
        name="CLIProxyAPI_8.0.69_windows_amd64.zip",
        size=len(payload),
        digest=None,
        download_url="https://github.com/download/asset.zip",
    )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        saved_path = await cliproxy_updater.download_asset(
            client, asset, dest, mirrors=["https://mirror1.local"]
        )
        assert saved_path == dest
        assert saved_path.is_file()
        assert saved_path.read_bytes() == payload
        # Ensure temporary .part file was cleaned up
        assert not dest.with_name(f"{dest.name}.part").exists()


async def test_check_and_stage_update_flow(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """16. check_and_stage reports update_available when newer, stages True, writes pending_version."""
    # Create valid dummy zip archive with cli-proxy-api.exe inside
    zip_bytes_io = io.BytesIO()
    with zipfile.ZipFile(zip_bytes_io, "w") as zf:
        zf.writestr("cli-proxy-api.exe", b"fake binary executable content")
    zip_data = zip_bytes_io.getvalue()
    zip_sha = cliproxy_core.sha256_file(tmp_path / "dummy") if False else None
    import hashlib
    zip_sha = hashlib.sha256(zip_data).hexdigest().lower()

    # Create dummy checksums.txt
    cs_text = f"{zip_sha} *CLIProxyAPI_8.0.69_windows_amd64.zip\n".encode("utf-8")

    plat_asset_name = "CLIProxyAPI_8.0.69_windows_amd64.zip"

    payload_release = {
        "tag_name": "v8.0.69",
        "assets": [
            {
                "name": plat_asset_name,
                "size": len(zip_data),
                "digest": f"sha256:{zip_sha}",
                "browser_download_url": f"https://github.com/download/{plat_asset_name}",
            },
            {
                "name": cliproxy_updater.CHECKSUMS_ASSET_NAME,
                "size": len(cs_text),
                "digest": None,
                "browser_download_url": f"https://github.com/download/{cliproxy_updater.CHECKSUMS_ASSET_NAME}",
            },
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        url_str = str(request.url)
        if url_str in (
            cliproxy_updater.GITHUB_API_LATEST,
            "https://api.github.com/repos/router-for-me/CLIProxyAPI/releases/tags/v8.0.69",
        ):
            return httpx.Response(200, json=payload_release)
        if url_str == f"https://github.com/download/{plat_asset_name}":
            return httpx.Response(200, content=zip_data)
        if url_str == f"https://github.com/download/{cliproxy_updater.CHECKSUMS_ASSET_NAME}":
            return httpx.Response(200, content=cs_text)
        return httpx.Response(404)

    mock_transport = httpx.MockTransport(handler)

    # Route httpx.AsyncClient creations inside check_and_stage and stage_release to mock transport
    original_async_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda *args, **kwargs: original_async_client(*args, transport=mock_transport, **{k: v for k, v in kwargs.items() if k != "transport"}),
    )

    # Initial state: no installed version (or older version)
    result = await cliproxy_updater.check_and_stage()

    assert result["latest_version"] == "8.0.69"
    assert result["installed_version"] is None
    assert result["update_available"] is True
    assert result["staged"] is True
    assert result["pending_version"] == "8.0.69"
    assert result["error"] is None

    # Check update state on disk
    state = cliproxy_core.read_update_state()
    assert state.latest_version == "8.0.69"
    assert state.pending_version == "8.0.69"
    assert state.pending_asset_name == plat_asset_name

    # Check staged directory has binary and metadata
    staged_dir = cliproxy_core.staging_dir() / "8.0.69"
    assert (staged_dir / cliproxy_core.binary_name()).is_file()
    meta = cliproxy_core.read_metadata(staged_dir)
    assert meta is not None
    assert meta.version == "8.0.69"
    assert meta.asset_name == plat_asset_name


async def test_check_and_stage_quarantined(monkeypatch: pytest.MonkeyPatch):
    """17. check_and_stage skips a quarantined version and returns an error naming it."""
    # Quarantine 8.0.75
    cliproxy_core.quarantine_version("8.0.75")

    def handler(request: httpx.Request) -> httpx.Response:
        url_str = str(request.url)
        if url_str == cliproxy_updater.GITHUB_API_LATEST:
            payload = {
                "tag_name": "v8.0.75",
                "assets": [],
            }
            return httpx.Response(200, json=payload)
        return httpx.Response(404)

    mock_transport = httpx.MockTransport(handler)
    original_async_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda *args, **kwargs: original_async_client(*args, transport=mock_transport, **{k: v for k, v in kwargs.items() if k != "transport"}),
    )

    result = await cliproxy_updater.check_and_stage()

    assert result["latest_version"] == "8.0.75"
    assert result["update_available"] is False
    assert result["staged"] is False
    assert "quarantined" in result["error"]
    assert "8.0.75" in result["error"]

    state = cliproxy_core.read_update_state()
    assert state.latest_version == "8.0.75"
    assert "quarantined" in (state.last_error or "")
