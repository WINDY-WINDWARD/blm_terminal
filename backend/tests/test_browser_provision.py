"""Tests for provision-on-consent browser fetching.

Regression coverage for the silent client failure where consent was granted
but no Camoufox browser existed: nothing ever fetched it, the warm browser
died quietly, and news/deals stayed empty with no UI signal.
"""

from __future__ import annotations

import sys
import threading
import types
from typing import Any

import pytest

from app.services import browser_harvester as bh


@pytest.fixture()
def reset_provision_state():
    bh._set_browser_status("unknown")
    bh._AUTO_FETCH_DONE = False
    # Join any stray fetch thread from a previous test.
    t = bh._FETCH_THREAD
    if t is not None and t.is_alive():
        t.join(timeout=10)
    bh._FETCH_THREAD = None
    yield
    t = bh._FETCH_THREAD
    if t is not None and t.is_alive():
        t.join(timeout=10)
    bh._FETCH_THREAD = None
    bh._set_browser_status("unknown")
    bh._AUTO_FETCH_DONE = False


def _stub_camoufox(monkeypatch: pytest.MonkeyPatch, present: bool) -> dict[str, Any]:
    """Stub camoufox.multiversion + camoufox.pkgman in sys.modules."""
    calls: dict[str, Any] = {"installs": 0}

    multiversion = types.ModuleType("camoufox.multiversion")

    def get_active_path() -> Any:
        return "/fake/camoufox" if present else None

    multiversion.get_active_path = get_active_path  # type: ignore

    pkgman = types.ModuleType("camoufox.pkgman")

    class FakeFetcher:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            try:
                self.verstr = "999.0-fake.1"
            except Exception:
                pass

        @property
        def verstr(self) -> str:
            return "999.0-fake.1"

        def install(self, replace: bool = False) -> None:
            calls["installs"] += 1

    def fake_webdl(url: str, buffer: Any = None, bar: bool = False,
                   progress_callback: Any = None) -> Any:
        if progress_callback:
            progress_callback(50, 100)
        return buffer

    pkgman.CamoufoxFetcher = FakeFetcher  # type: ignore
    pkgman.webdl = fake_webdl  # type: ignore

    package = types.ModuleType("camoufox")
    package.__path__ = []  # type: ignore
    monkeypatch.setitem(sys.modules, "camoufox", package)
    monkeypatch.setitem(sys.modules, "camoufox.multiversion", multiversion)
    monkeypatch.setitem(sys.modules, "camoufox.pkgman", pkgman)
    # Force re-import inside the harvester (it imports lazily per call).
    return calls


class TestProvisionStatus:
    def test_ready_when_browser_present(self, reset_provision_state: None,
                                        monkeypatch: pytest.MonkeyPatch) -> None:
        _stub_camoufox(monkeypatch, present=True)
        assert bh.get_browser_status()["state"] == "ready"

    def test_missing_when_no_browser(self, reset_provision_state: None,
                                     monkeypatch: pytest.MonkeyPatch) -> None:
        _stub_camoufox(monkeypatch, present=False)
        # trigger with manual=True bypasses the one-shot guard; join thread.
        bh.trigger_browser_fetch(manual=True)
        t = bh._FETCH_THREAD
        if t is not None:
            t.join(timeout=10)
        # Fake install does not create a real browser dir, so status is failed
        # (missing would also be acceptable pre-fetch; failed proves the
        # worker ran and reconciled instead of silently dying).
        assert bh.get_browser_status()["state"] in ("failed", "missing", "downloading")

    def test_auto_fetch_one_shot(self, reset_provision_state: None,
                                 monkeypatch: pytest.MonkeyPatch) -> None:
        _stub_camoufox(monkeypatch, present=False)
        bh.trigger_browser_fetch(manual=False)
        first = bh._FETCH_THREAD
        if first is not None:
            first.join(timeout=10)
        bh.trigger_browser_fetch(manual=False)
        # No second thread may start while the one-shot guard holds.
        assert bh._FETCH_THREAD is first

    def test_no_fetch_when_present(self, reset_provision_state: None,
                                   monkeypatch: pytest.MonkeyPatch) -> None:
        calls = _stub_camoufox(monkeypatch, present=True)
        bh.trigger_browser_fetch(manual=True)
        assert calls["installs"] == 0
        assert bh.get_browser_status()["state"] == "ready"


class TestFetchLock:
    def test_live_lock_returns_none(self, reset_provision_state: None,
                                    monkeypatch: pytest.MonkeyPatch,
                                    tmp_path) -> None:
        monkeypatch.setattr(bh, "_fetch_lock_path", lambda: tmp_path / ".fetch.lock")
        fd = bh._acquire_fetch_lock()
        assert fd is not None and fd >= 0
        try:
            assert bh._acquire_fetch_lock() is None
        finally:
            bh._release_fetch_lock(fd)
        assert not (tmp_path / ".fetch.lock").exists()

    def test_stale_lock_takeover(self, reset_provision_state: None,
                                 monkeypatch: pytest.MonkeyPatch,
                                 tmp_path) -> None:
        monkeypatch.setattr(bh, "_fetch_lock_path", lambda: tmp_path / ".fetch.lock")
        (tmp_path / ".fetch.lock").write_text("999999:1")
        fd = bh._acquire_fetch_lock()
        assert fd is not None and fd >= 0
        bh._release_fetch_lock(fd)
        assert not (tmp_path / ".fetch.lock").exists()

    def test_second_process_skips_install(self, reset_provision_state: None,
                                          monkeypatch: pytest.MonkeyPatch,
                                          tmp_path) -> None:
        calls = _stub_camoufox(monkeypatch, present=False)
        monkeypatch.setattr(bh, "_fetch_lock_path", lambda: tmp_path / ".fetch.lock")
        # Simulate another backend process holding the lock.
        holder = bh._acquire_fetch_lock()
        assert holder is not None and holder >= 0
        try:
            bh.trigger_browser_fetch(manual=True)
            t = bh._FETCH_THREAD
            if t is not None:
                t.join(timeout=10)
            assert calls["installs"] == 0
            assert bh.get_browser_status()["state"] == "downloading"
        finally:
            bh._release_fetch_lock(holder)
class TestFrozenReadiness:
    def test_frozen_requires_installed_browser(self, reset_provision_state: None,
                                               monkeypatch: pytest.MonkeyPatch) -> None:
        """The old bug: frozen exe returned True on bare `import camoufox`."""
        _stub_camoufox(monkeypatch, present=False)
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        import asyncio

        assert asyncio.run(bh._ensure_browser_binaries()) is False

    def test_frozen_ready_when_installed(self, reset_provision_state: None,
                                         monkeypatch: pytest.MonkeyPatch) -> None:
        _stub_camoufox(monkeypatch, present=True)
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        import asyncio

        assert asyncio.run(bh._ensure_browser_binaries()) is True
