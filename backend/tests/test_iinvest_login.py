"""Tests for iinvest guest-login auth (fetch order + key recovery).

Background: enrichment 401'd on every endpoint because the browser harvest
returns a 24h-cached JWT that had expired ~12h earlier, and "re-login" just
re-harvested the same dead token (`/api/login` existed only as an unused
constant). These tests pin the repaired chain:

- harvest (margin-validated) → guest `/api/login` fallback → raise,
- 401-retry bypasses the harvest cache,
- health requires a live token,
- bundle-rotated keys recover automatically.
"""

from __future__ import annotations

import asyncio
import base64
import json
import sys
import time
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.test_iinvest_client import (
    AES_KEY,
    _encrypt_openssl,
    _make_fake_httpx,
    _make_jwt,
)

AES_STR = AES_KEY.decode()


def _login_blob_for(jwt_token: str, key: bytes = AES_KEY) -> str:
    body = json.dumps({
        "status": True,
        "message": "Successful",
        "response": {
            "token": jwt_token,
            "expiration": "2099-01-01T00:00:00.000Z",
            "apps": "cms,rapi",
            "roles": "view",
            "username": "guest",
        },
    }).encode()
    return _encrypt_openssl(body, key).decode()


@pytest.fixture()
def login_client(monkeypatch: pytest.MonkeyPatch):
    from app.services import iinvest_client as mod

    monkeypatch.setattr(mod, "_iinvest_client", None, raising=False)
    client = mod.IinvestClient()
    client._refresh_ahead_seconds = 60
    yield client
    try:
        asyncio.get_event_loop().run_until_complete(client.close())
    except Exception:
        pass


class TestDecrypt:
    def test_roundtrip_with_documented_key(self):
        from app.services.iinvest_client import _decrypt_salted_blob

        jwt = _make_jwt()
        payload = _decrypt_salted_blob(_login_blob_for(jwt), AES_STR)
        assert payload["response"]["token"] == jwt

    def test_rejects_non_salted_blob(self):
        from app.services.iinvest_client import _decrypt_salted_blob

        with pytest.raises(ValueError):
            _decrypt_salted_blob(base64.b64encode(b"not-a-blob-at-all!!").decode(), AES_STR)

    def test_wrong_key_fails(self):
        from app.services.iinvest_client import _decrypt_salted_blob

        jwt = _make_jwt()
        with pytest.raises(Exception):
            _decrypt_salted_blob(_login_blob_for(jwt), "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")


class TestFetchOrder:
    @pytest.mark.asyncio
    async def test_login_fallback_when_harvest_empty(self, login_client, monkeypatch):
        from app.services import iinvest_client as mod

        jwt = _make_jwt()
        client, _ = _make_fake_httpx([
            (200, {"data": _login_blob_for(jwt)}),
        ])
        monkeypatch.setattr(mod.httpx, "AsyncClient", lambda *a, **kw: client)
        monkeypatch.setattr(mod, "harvest_local_storage", AsyncMock(return_value=None))
        login_client._http = client

        await login_client._fetch_jwt()
        assert login_client._jwt == jwt
        assert login_client.health()["healthy"] is True

    @pytest.mark.asyncio
    async def test_stale_harvest_falls_through_to_login(self, login_client, monkeypatch):
        from app.services import iinvest_client as mod

        stale = _make_jwt(exp_offset_seconds=-3600)
        fresh = _make_jwt()
        client, _ = _make_fake_httpx([
            (200, {"data": _login_blob_for(fresh)}),
        ])
        monkeypatch.setattr(mod.httpx, "AsyncClient", lambda *a, **kw: client)
        monkeypatch.setattr(mod, "harvest_local_storage", AsyncMock(return_value=stale))
        login_client._http = client

        await login_client._fetch_jwt()
        assert login_client._jwt == fresh

    @pytest.mark.asyncio
    async def test_401_retry_bypasses_harvest_cache(self, login_client, monkeypatch):
        """The 401-retry must not be served the same cached token."""
        from app.services import iinvest_client as mod

        calls: list[dict] = []

        async def fake_harvest(url, key, force=False, **kw):
            calls.append({"force": force})
            # First call (init): fresh token. Retry call: fresh token again
            # (proves force reached the harvester; a stale cache would 401 loop).
            return _make_jwt()

        data_resp = {"status": True, "response": {"data": [{"id": 1}]}}
        filters_resp = {"status": True, "message": "ok", "response": {}}
        client, _ = _make_fake_httpx([
            (200, filters_resp),
            (401, {"error": "expired"}),
            (200, data_resp),
        ])
        monkeypatch.setattr(mod.httpx, "AsyncClient", lambda *a, **kw: client)
        monkeypatch.setattr(mod, "harvest_local_storage", fake_harvest)

        await login_client.init()
        result = await login_client.get_announcements("ine002a01018/symbol/ns/reliance/x")
        assert result == data_resp
        assert any(c["force"] for c in calls), "retry must force bypass the harvest cache"

    def test_health_requires_live_token(self, login_client):
        login_client._jwt = _make_jwt(exp_offset_seconds=-10)
        from datetime import datetime, timezone

        login_client._jwt_expires_at = datetime.fromtimestamp(time.time() - 10, tz=timezone.utc)
        h = login_client.health()
        assert h["healthy"] is False
        assert login_client.is_authenticated is False

    @pytest.mark.asyncio
    async def test_zulu_expiration_accepted(self, login_client, monkeypatch):
        """An `expiration` ending in Z must parse, not condemn a fresh token."""
        from app.services import iinvest_client as mod

        jwt = _make_jwt(exp_offset_seconds=86400)
        body = json.dumps({
            "status": True, "message": "Successful",
            "response": {"token": jwt, "expiration": "2099-01-01T00:00:00.000Z"},
        }).encode()
        blob = _encrypt_openssl(body, AES_KEY).decode()
        client, _ = _make_fake_httpx([(200, {"data": blob})])
        monkeypatch.setattr(mod.httpx, "AsyncClient", lambda *a, **kw: client)
        monkeypatch.setattr(mod, "harvest_local_storage", AsyncMock(return_value=None))
        login_client._http = client

        await login_client._fetch_jwt()
        assert login_client._jwt == jwt
        assert login_client.is_authenticated is True

    @pytest.mark.asyncio
    async def test_empty_blob_fails_without_recovery_traffic(self, login_client, monkeypatch):
        """A shape failure must not fire key-recovery GETs + a second login POST."""
        from app.services import iinvest_client as mod

        client, state = _make_fake_httpx([(200, {"data": ""})])
        monkeypatch.setattr(mod.httpx, "AsyncClient", lambda *a, **kw: client)
        login_client._http = client

        with pytest.raises(RuntimeError, match="empty login blob"):
            await login_client._guest_login()
        assert state["idx"] == 1  # exactly the one login POST, nothing more


class TestKeyRecovery:
    @pytest.mark.asyncio
    async def test_rotated_key_recovers_from_bundle(self, login_client, monkeypatch):
        from app.services import iinvest_client as mod

        new_key = b"BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB="
        assert len(new_key.decode()) == 44
        jwt = _make_jwt()
        bad_blob = _login_blob_for(jwt)  # encrypted with the real key
        good_blob = _login_blob_for(jwt, key=new_key)

        bundle_js = 'var x = AES.decrypt(payload, "%s");' % new_key.decode()
        home_html = '<script src="/_next/static/chunks/pages/_app-abc123.js"></script>'

        # First login attempt is fed a blob encrypted with an unknown key:
        # force the mismatch by temporarily swapping the module key.
        monkeypatch.setattr(mod, "_AES_KEY_PASSPHRASE", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
        client, _ = _make_fake_httpx([
            (200, {"data": bad_blob}),   # login attempt 1 → decrypt fails
            (200, home_html),            # recovery: homepage
            (200, bundle_js),            # recovery: bundle with new key
            (200, {"data": good_blob}),  # login attempt 2 → succeeds
        ])
        monkeypatch.setattr(mod.httpx, "AsyncClient", lambda *a, **kw: client)
        monkeypatch.setattr(mod, "harvest_local_storage", AsyncMock(return_value=None))
        login_client._http = client

        await login_client._fetch_jwt()
        assert login_client._jwt == jwt
        assert mod._current_aes_key() == new_key.decode()
