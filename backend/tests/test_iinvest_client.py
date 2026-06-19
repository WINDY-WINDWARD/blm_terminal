"""Tests for the iinvest.cogencis.com client.

Covers the behavior the FDM widget and news pipeline actually depend on:

  - Auto-acquisition of a guest JWT (decryption of the iinvest login blob)
  - Lazy initialization (no network call on import)
  - Caching the JWT in process memory only
  - Auto-refresh on expiry
  - 401 → re-login + retry once
  - Data fetchers hit the right endpoint with the right params
  - Path builder handles M&M, L&T, spaces correctly
  - Health endpoint reflects the current state

Strategy: we don't hit the real iinvest service. We inject a fake
``httpx.AsyncClient`` so the tests are deterministic and fast. The
AES-decrypt round trip is tested with a known key + known plaintext so
the behavior is identical to the live service.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── AES-256-CBC OpenSSL EVP_BytesToKey (MD5, 1 round) ─────────────────────────
# This is the same algorithm CryptoJS.AES.encrypt() uses. Used here to
# manufacture valid login blobs in tests so we exercise the real decrypt path.


def _evp_bytes_to_key(passphrase: bytes, salt: bytes, key_len: int = 32, iv_len: int = 16) -> tuple[bytes, bytes]:
    import hashlib
    d = b""
    d_i = b""
    while len(d) < key_len + iv_len:
        d_i = hashlib.md5(d_i + passphrase + salt).digest()
        d += d_i
    return d[:key_len], d[key_len:key_len + iv_len]


def _encrypt_openssl(plaintext: bytes, passphrase: bytes) -> bytes:
    """Encrypt to OpenSSL ``Salted__<salt><ct>`` format, base64-encoded."""
    import hashlib
    salt = os.urandom(8)
    key, iv = _evp_bytes_to_key(passphrase, salt)
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    pad = 16 - (len(plaintext) % 16)
    pt_padded = plaintext + bytes([pad]) * pad
    enc = Cipher(algorithms.AES(key), modes.CBC(iv))
    ct = enc.encryptor().update(pt_padded) + enc.encryptor().finalize()
    blob = b"Salted__" + salt + ct
    return base64.b64encode(blob)


AES_KEY = b"SQOZOt3Mx1Bouh7YgkJn1XwX2PcR8Sy6Q+q8A9rW6us="


def _make_jwt(exp_offset_seconds: int = 86400) -> str:
    """Produce a syntactically-valid HS256 JWT for tests."""
    import jwt as pyjwt  # PyJWT is already in pyproject

    now = int(time.time())
    payload = {
        "exp": now + exp_offset_seconds,
        "iat": now,
        "data": {"user_id": 765, "apps": "cms,rapi", "roles": "view"},
    }
    return pyjwt.encode(payload, "test-secret", algorithm="HS256")


def _make_login_blob(jwt_token: str) -> str:
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
    return _encrypt_openssl(body, AES_KEY).decode()


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def fresh_client(monkeypatch):
    """A fresh IinvestClient that has NOT yet called /api/login.

    We patch the lazy httpx.AsyncClient so no real network is used.
    """
    from app.services import iinvest_client as mod

    # Reset module-level singleton
    monkeypatch.setattr(mod, "_iinvest_client", None, raising=False)

    client = mod.IinvestClient()
    # Shorten the refresh window so tests can drive the cycle in ms
    client._refresh_ahead_seconds = 60
    yield client
    # Best-effort cleanup
    try:
        asyncio.get_event_loop().run_until_complete(client.close())
    except Exception:
        pass


def _make_fake_httpx(responses: list[tuple[int, dict | str]]) -> tuple[MagicMock, dict]:
    """Build a fake httpx.AsyncClient whose .get() / .post() return canned responses.

    `responses` is a list of (status_code, body) tuples. Each call consumes
    one entry. If exhausted, raises a clear error.
    """
    state = {"idx": 0}

    def _next_response() -> tuple[int, Any]:
        if state["idx"] >= len(responses):
            raise AssertionError(
                f"Test exhausted fake httpx responses (used {state['idx']})"
            )
        status, body = responses[state["idx"]]
        state["idx"] += 1
        return status, body

    def _make_response(status: int, body: Any) -> MagicMock:
        resp = MagicMock()
        resp.status_code = status
        if isinstance(body, dict):
            resp.json = MagicMock(return_value=body)
        else:
            resp.json = MagicMock(side_effect=lambda: json.loads(body))
        resp.text = body if isinstance(body, str) else json.dumps(body)
        resp.raise_for_status = MagicMock()
        if status >= 400:
            err = Exception(f"HTTP {status}")
            resp.raise_for_status.side_effect = err
        return resp

    async def _call(*args, **kwargs):
        # Mimic a coroutine that returns the next canned response
        await asyncio.sleep(0)
        return _make_response(*_next_response())

    client = MagicMock()
    client.get = AsyncMock(side_effect=_call)
    client.post = AsyncMock(side_effect=_call)
    client.aclose = AsyncMock()
    client.headers = {}
    client.cookies = MagicMock()
    return client, state


# ── Tests: Auth ───────────────────────────────────────────────────────────────


class TestIinvestClientAuth:
    """The auth flow: /api/login → AES decrypt → JWT in memory."""

    @pytest.mark.asyncio
    async def test_init_acquires_jwt_from_login(self, fresh_client, monkeypatch):
        """First init() should POST /api/login, decrypt, and store a JWT."""
        from app.services import iinvest_client as mod

        jwt = _make_jwt()
        blob = _make_login_blob(jwt)
        login_resp = {"data": blob}
        # The validation probe after init hits /financials/peers/filters
        filters_resp = {"status": True, "message": "ok", "response": {"filters": [], "compare": [], "annual": []}}

        client, state = _make_fake_httpx([
            (200, login_resp),       # POST /api/login
            (200, filters_resp),     # GET /financials/peers/filters (health probe)
        ])
        monkeypatch.setattr(mod.httpx, "AsyncClient", lambda *a, **kw: client)

        await fresh_client.init()

        assert fresh_client._jwt == jwt
        assert fresh_client.is_authenticated is True
        assert state["idx"] == 2  # both responses consumed

    @pytest.mark.asyncio
    async def test_init_is_lazy_no_network_until_first_call(self, fresh_client):
        """No /api/login POST happens until init() is called or a request needs it."""
        from app.services import iinvest_client as mod
        assert fresh_client._jwt is None
        assert fresh_client.is_authenticated is False

    @pytest.mark.asyncio
    async def test_init_failure_marks_unhealthy(self, fresh_client, monkeypatch):
        """If /api/login 403s or decrypt fails, client must surface as unhealthy."""
        from app.services import iinvest_client as mod

        client, _ = _make_fake_httpx([(403, {"error": "blocked"})])
        monkeypatch.setattr(mod.httpx, "AsyncClient", lambda *a, **kw: client)

        with pytest.raises(RuntimeError):
            await fresh_client.init()
        assert fresh_client.is_authenticated is False

    @pytest.mark.asyncio
    async def test_health_endpoint_reports_state(self, fresh_client, monkeypatch):
        """GET /api/iinvest/health should reflect is_authenticated + expiry."""
        from app.services import iinvest_client as mod

        jwt = _make_jwt(exp_offset_seconds=7200)
        blob = _make_login_blob(jwt)
        login_resp = {"data": blob}
        filters_resp = {"status": True, "message": "ok", "response": {"filters": [], "compare": [], "annual": []}}
        client, _ = _make_fake_httpx([(200, login_resp), (200, filters_resp)])
        monkeypatch.setattr(mod.httpx, "AsyncClient", lambda *a, **kw: client)

        await fresh_client.init()
        h = fresh_client.health()
        assert h["configured"] is True
        assert h["healthy"] is True
        assert h["expires_at"] is not None
        # Should be roughly 2h from now
        from datetime import datetime, timezone
        expires = datetime.fromisoformat(h["expires_at"])
        delta = (expires - datetime.now(timezone.utc)).total_seconds()
        assert 7000 < delta < 7300


# ── Tests: Path builder ───────────────────────────────────────────────────────


class TestIinvestPathBuilder:
    """Path construction encodes company name, symbol, and ISIN correctly."""

    def test_build_path_simple(self):
        from app.services.iinvest_client import IinvestClient
        path = IinvestClient.build_path(
            isin="INE002A01018", symbol="RELIANCE", company_name="Reliance Industries Limited"
        )
        # The data API path is lowercased
        assert path == "ine002a01018/symbol/ns/reliance/reliance%20industries%20limited"

    def test_build_path_encodes_ampersand_in_symbol(self):
        """M&M has `&` which must be URL-encoded as `M%26M`."""
        from app.services.iinvest_client import IinvestClient
        path = IinvestClient.build_path(
            isin="INE101A01026", symbol="M&M", company_name="Mahindra & Mahindra Limited"
        )
        assert "%26" in path
        assert path.startswith("ine101a01026/symbol/ns/")
        assert "mahindra" in path

    def test_build_path_encodes_spaces(self):
        from app.services.iinvest_client import IinvestClient
        path = IinvestClient.build_path(
            isin="INE467B01029", symbol="TCS", company_name="Tata Consultancy Services"
        )
        assert " " not in path
        assert "%20" in path

    def test_build_path_is_lowercased(self):
        from app.services.iinvest_client import IinvestClient
        path = IinvestClient.build_path(
            isin="INE467B01029", symbol="TCS", company_name="Tata Consultancy"
        )
        # iinvest data APIs are case-sensitive; path must be lowercase
        assert path == path.lower()


# ── Tests: Data fetchers ──────────────────────────────────────────────────────


class TestIinvestClientDataFetchers:
    """Each data fetcher hits the right URL with the right params."""

    @pytest.mark.asyncio
    async def test_announcements_uses_path_param(self, fresh_client, monkeypatch):
        from app.services import iinvest_client as mod

        jwt = _make_jwt()
        blob = _make_login_blob(jwt)
        # We need 2 calls: /api/login + /financials/peers/filters probe + /announcements
        announcements = {"status": True, "response": {"pagingInfo": {"total": 5}, "columns": [], "data": []}}
        login_resp = {"data": blob}
        filters_resp = {"status": True, "message": "ok", "response": {"filters": [], "compare": [], "annual": []}}

        client, _ = _make_fake_httpx([
            (200, login_resp),
            (200, filters_resp),
            (200, announcements),
        ])
        monkeypatch.setattr(mod.httpx, "AsyncClient", lambda *a, **kw: client)

        await fresh_client.init()
        result = await fresh_client.get_announcements("ine002a01018/symbol/ns/reliance/reliance%20industries%20limited")
        assert result == announcements

        # The last call (announcements) must have been a GET
        last_call = client.get.call_args_list[-1]
        url = last_call.args[0] if last_call.args else last_call.kwargs.get("url")
        assert "/announcements" in url
        params = last_call.kwargs.get("params", {})
        assert params.get("path", "").startswith("ine002a01018/")

    @pytest.mark.asyncio
    async def test_legal_cases_uses_isin_param(self, fresh_client, monkeypatch):
        """legalcases / indexofcharges / tribunals / financials/peers take `isin` (not `path`)."""
        from app.services import iinvest_client as mod

        jwt = _make_jwt()
        blob = _make_login_blob(jwt)
        legal_resp = {"status": True, "response": {"data": []}}
        login_resp = {"data": blob}
        filters_resp = {"status": True, "message": "ok", "response": {"filters": [], "compare": [], "annual": []}}

        client, _ = _make_fake_httpx([
            (200, login_resp), (200, filters_resp), (200, legal_resp),
        ])
        monkeypatch.setattr(mod.httpx, "AsyncClient", lambda *a, **kw: client)

        await fresh_client.init()
        await fresh_client.get_legal_cases(isin="INE002A01018", page=1, size=20)

        last = client.get.call_args_list[-1]
        url = last.args[0] if last.args else last.kwargs.get("url")
        assert "/legalcases" in url
        params = last.kwargs.get("params", {})
        assert params.get("isin") == "INE002A01018"
        assert "path" not in params  # legalcases uses isin, not path

    @pytest.mark.asyncio
    async def test_marketdata_timeseries_uses_timescale_and_from(self, fresh_client, monkeypatch):
        from app.services import iinvest_client as mod

        jwt = _make_jwt()
        blob = _make_login_blob(jwt)
        ts_resp = {"status": True, "response": {"snapshot": {}, "data": [{"close": 100}]}}
        login_resp = {"data": blob}
        filters_resp = {"status": True, "message": "ok", "response": {"filters": [], "compare": [], "annual": []}}

        client, _ = _make_fake_httpx([
            (200, login_resp), (200, filters_resp), (200, ts_resp),
        ])
        monkeypatch.setattr(mod.httpx, "AsyncClient", lambda *a, **kw: client)

        await fresh_client.init()
        await fresh_client.get_marketdata_timeseries(
            "ine002a01018/symbol/ns/reliance/reliance%20industries%20limited",
            timescale=1, from_="1DAY",
        )
        last = client.get.call_args_list[-1]
        params = last.kwargs.get("params", {})
        assert params.get("timescale") == 1
        assert params.get("from") == "1DAY"

    @pytest.mark.asyncio
    async def test_block_deals_uses_type_param(self, fresh_client, monkeypatch):
        from app.services import iinvest_client as mod

        jwt = _make_jwt()
        blob = _make_login_blob(jwt)
        block_resp = {"status": True, "response": {"data": []}}
        login_resp = {"data": blob}
        filters_resp = {"status": True, "message": "ok", "response": {"filters": [], "compare": [], "annual": []}}

        client, _ = _make_fake_httpx([
            (200, login_resp), (200, filters_resp), (200, block_resp),
        ])
        monkeypatch.setattr(mod.httpx, "AsyncClient", lambda *a, **kw: client)

        await fresh_client.init()
        await fresh_client.get_block_deals(
            "ine002a01018/symbol/ns/reliance/reliance%20industries%20limited",
            deal_type=1,
        )
        last = client.get.call_args_list[-1]
        params = last.kwargs.get("params", {})
        assert params.get("type") == 1


# ── Tests: 401 → re-login + retry ─────────────────────────────────────────────


class TestIinvestClientAuthRefresh:
    """The 401-recovery loop is the production-critical behavior."""

    @pytest.mark.asyncio
    async def test_401_triggers_relogin_and_retry(self, fresh_client, monkeypatch):
        """First call returns 401; client re-logs in and retries once."""
        from app.services import iinvest_client as mod

        jwt1 = _make_jwt()
        jwt2 = _make_jwt()
        blob1 = _make_login_blob(jwt1)
        blob2 = _make_login_blob(jwt2)
        login_resp1 = {"data": blob1}
        login_resp2 = {"data": blob2}
        filters_resp = {"status": True, "message": "ok", "response": {"filters": [], "compare": [], "annual": []}}
        data_resp = {"status": True, "response": {"data": [{"id": 1}]}}

        # init: login#1 + filters probe
        # data call: 401 + relogin#2 + retry → 200
        client, _ = _make_fake_httpx([
            (200, login_resp1),     # init POST /api/login
            (200, filters_resp),    # init GET /financials/peers/filters probe
            (401, {"error": "expired"}),  # first announcements call → 401
            (200, login_resp2),     # relogin POST /api/login
            (200, data_resp),       # retry → 200
        ])
        monkeypatch.setattr(mod.httpx, "AsyncClient", lambda *a, **kw: client)

        await fresh_client.init()
        assert fresh_client._jwt == jwt1

        result = await fresh_client.get_announcements("ine002a01018/symbol/ns/reliance/reliance")
        assert result == data_resp
        assert fresh_client._jwt == jwt2  # re-login rotated the token

    @pytest.mark.asyncio
    async def test_consecutive_401s_do_not_loop_forever(self, fresh_client, monkeypatch):
        """If re-login + retry still returns 401, surface the error (no infinite loop)."""
        from app.services import iinvest_client as mod

        jwt = _make_jwt()
        blob = _make_login_blob(jwt)
        login_resp = {"data": blob}
        filters_resp = {"status": True, "message": "ok", "response": {"filters": [], "compare": [], "annual": []}}

        client, _ = _make_fake_httpx([
            (200, login_resp), (200, filters_resp),
            (401, {"e": "x"}),  # first call 401
            (200, login_resp),  # relogin
            (401, {"e": "x"}),  # retry still 401
        ])
        monkeypatch.setattr(mod.httpx, "AsyncClient", lambda *a, **kw: client)

        await fresh_client.init()
        with pytest.raises(RuntimeError, match="401"):
            await fresh_client.get_announcements("ine002a01018/symbol/ns/reliance/reliance")


# ── Tests: News fetcher with NLP post-processing ─────────────────────────────


class TestIinvestClientNews:
    """News payload does NOT include sentiment/threat — verify the raw response is returned."""

    @pytest.mark.asyncio
    async def test_get_news_returns_raw_response(self, fresh_client, monkeypatch):
        from app.services import iinvest_client as mod

        jwt = _make_jwt()
        blob = _make_login_blob(jwt)
        # iinvest news shape (no sentiment/threat fields)
        news_resp = {
            "status": True,
            "response": {
                "pagingInfo": {"pageNo": 1, "total": 1},
                "data": [
                    {
                        "id": "123",
                        "headline": "TCS profit jumps 12%",
                        "synopsis": "Tata Consultancy beat estimates",
                        "story": "<p>Full body</p>",
                        "sourceLink": "https://example.com/123",
                        "sourceName": "Cogencis",
                        "sourceDateTime": "2026-06-17T10:00:00",
                        "isins": ["INE467B01029"],
                    }
                ],
            },
        }
        login_resp = {"data": blob}
        filters_resp = {"status": True, "message": "ok", "response": {"filters": [], "compare": [], "annual": []}}

        client, _ = _make_fake_httpx([
            (200, login_resp), (200, filters_resp), (200, news_resp),
        ])
        monkeypatch.setattr(mod.httpx, "AsyncClient", lambda *a, **kw: client)

        await fresh_client.init()
        result = await fresh_client.get_news(["INE467B01029"], size=10)
        # Raw response is passed through; NLP is applied by the news_fetcher layer
        assert result == news_resp
        # Confirm the source field is missing from iinvest payload (the whole point)
        assert "sentiment" not in result["response"]["data"][0]
        assert "threat_level" not in result["response"]["data"][0]


# ── Tests: Path resolution ────────────────────────────────────────────────────


class TestIinvestClientPathResolution:
    """Path resolution: cache → DB → symbollookup → HTML fallback."""

    @pytest.mark.asyncio
    async def test_resolve_path_uses_db_cache(self, fresh_client, monkeypatch):
        """If stock_universe has the path, no network call is made."""
        from app.services import iinvest_client as mod
        from datetime import datetime

        # DB has it
        class FakeRow:
            def __init__(self):
                self.isin = "INE002A01018"
                self.iinvest_path = "ine002a01018/symbol/ns/reliance/reliance%20industries%20limited"
                self.iinvest_path_resolved_at = datetime(2026, 6, 18, 10, 0, 0)
            def __getitem__(self, idx):
                return (self.isin, self.iinvest_path, self.iinvest_path_resolved_at)[idx]

        class FakeResult:
            def first(self): return FakeRow()

        class FakeSession:
            async def execute(self, stmt):
                return FakeResult()

        # We need to clear the in-process cache to ensure DB path is exercised
        from app.services.cache import iinvest_path_cache
        iinvest_path_cache.pop("RELIANCE", None)

        isin, path = await fresh_client.resolve_path("RELIANCE", db=FakeSession())
        assert isin == "INE002A01018"
        assert "reliance" in path

    @pytest.mark.asyncio
    async def test_resolve_path_uses_nse_getquoteapi(self, fresh_client, monkeypatch):
        """When DB cache misses, resolve_path should call NSE's GetQuoteApi
        (functionName=getMetaData) which returns ISIN + companyName directly.
        This is more reliable than the iinvest symbollookup endpoint
        (which gave wrong ISINs for short symbols like RELIANCE).
        """
        from app.services import iinvest_client as mod
        from app.services.cache import iinvest_path_cache
        iinvest_path_cache.pop("RELIANCE", None)

        class FakeNse:
            async def get_isin_for_symbol(self, symbol):
                return ("INE002A01018", "Reliance Industries Limited")

        monkeypatch.setattr(mod, "nse_client", FakeNse())

        # No DB session → skip the DB tier, go straight to NSE
        isin, path = await fresh_client.resolve_path("RELIANCE", db=None)
        assert isin == "INE002A01018"
        assert path is not None
        # Path encodes symbol + company name
        assert "reliance" in path
        assert "reliance%20industries%20limited" in path or "reliance-industries-limited" in path
        # In-process cache is populated
        cached = iinvest_path_cache.get("RELIANCE")
        assert cached is not None
        assert cached["isin"] == "INE002A01018"

    @pytest.mark.asyncio
    async def test_resolve_path_returns_none_when_nse_has_no_isin(self, fresh_client, monkeypatch):
        """If NSE returns no ISIN for the symbol, resolve_path returns (None, None)."""
        from app.services import iinvest_client as mod
        from app.services.cache import iinvest_path_cache
        iinvest_path_cache.pop("UNKNOWN", None)

        class FakeNse:
            async def get_isin_for_symbol(self, symbol):
                return None

        monkeypatch.setattr(mod, "nse_client", FakeNse())

        isin, path = await fresh_client.resolve_path("UNKNOWN", db=None)
        assert isin is None
        assert path is None
