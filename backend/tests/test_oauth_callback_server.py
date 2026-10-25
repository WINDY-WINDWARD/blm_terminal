import asyncio
import logging
import socket
from typing import Any
import httpx
import pytest

from app.services.oauth_callback_server import (
    OAuthCallbackError,
    OAuthCallbackServer,
    parse_loopback_redirect,
)


def get_free_port() -> int:
    """Find an available loopback port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ---------------------------------------------------------------------------
# parse_loopback_redirect tests
# ---------------------------------------------------------------------------


def test_parse_loopback_redirect_valid_paths():
    assert parse_loopback_redirect("http://localhost:51121/oauth-callback") == (
        "localhost",
        51121,
        "/oauth-callback",
    )
    assert parse_loopback_redirect("http://127.0.0.1:8080/callback") == (
        "127.0.0.1",
        8080,
        "/callback",
    )
    assert parse_loopback_redirect("http://[::1]:9090/custom/provider/callback") == (
        "::1",
        9090,
        "/custom/provider/callback",
    )
    assert parse_loopback_redirect("http://localhost:12345/auth/callback") == (
        "localhost",
        12345,
        "/auth/callback",
    )


def test_parse_loopback_redirect_rejects_non_http_schemes():
    with pytest.raises(OAuthCallbackError):
        parse_loopback_redirect("https://localhost:51121/oauth-callback")
    with pytest.raises(OAuthCallbackError):
        parse_loopback_redirect("ftp://127.0.0.1:8080/callback")
    with pytest.raises(OAuthCallbackError):
        parse_loopback_redirect("ws://localhost:51121/callback")


def test_parse_loopback_redirect_rejects_non_loopback_hosts():
    with pytest.raises(OAuthCallbackError):
        parse_loopback_redirect("http://example.com:8080/callback")
    with pytest.raises(OAuthCallbackError):
        parse_loopback_redirect("http://0.0.0.0:8080/callback")
    with pytest.raises(OAuthCallbackError):
        parse_loopback_redirect("http://192.168.1.100:8080/callback")
    with pytest.raises(OAuthCallbackError):
        parse_loopback_redirect("http://10.0.0.1:8080/callback")


def test_parse_loopback_redirect_rejects_missing_ports():
    with pytest.raises(OAuthCallbackError):
        parse_loopback_redirect("http://localhost/callback")
    with pytest.raises(OAuthCallbackError):
        parse_loopback_redirect("http://127.0.0.1/oauth-callback")
    with pytest.raises(OAuthCallbackError):
        parse_loopback_redirect("http://[::1]/callback")


def test_parse_loopback_redirect_rejects_malformed_paths():
    with pytest.raises(OAuthCallbackError):
        parse_loopback_redirect("http://localhost:8080")
    with pytest.raises(OAuthCallbackError):
        parse_loopback_redirect("http://localhost:8080/")
    with pytest.raises(OAuthCallbackError):
        parse_loopback_redirect("http://localhost:8080/path/../secret")
    with pytest.raises(OAuthCallbackError):
        parse_loopback_redirect("http://localhost:8080/callback#fragment")
    with pytest.raises(OAuthCallbackError):
        parse_loopback_redirect("not-a-valid-url")
    with pytest.raises(OAuthCallbackError):
        parse_loopback_redirect("http://localhost:70000/callback")


# ---------------------------------------------------------------------------
# OAuthCallbackServer lifecycle and request handling tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_loopback_bind_ipv4_and_ipv6():
    port = get_free_port()
    server = OAuthCallbackServer()
    state = "state-bind-test"
    on_code_called = False

    async def on_code(st: str, code: str) -> None:
        nonlocal on_code_called
        on_code_called = True

    async def on_error(err: str) -> None:
        pass

    try:
        registered_url = await server.register(
            state=state,
            redirect_uri=f"http://127.0.0.1:{port}/oauth-callback",
            on_code=on_code,
            on_error=on_error,
        )
        assert registered_url == f"http://127.0.0.1:{port}/oauth-callback"

        # Check IPv4 connection
        async with httpx.AsyncClient(trust_env=False) as client:
            resp_ipv4 = await client.get(
                f"http://127.0.0.1:{port}/oauth-callback?code=c1&state={state}"
            )
            assert resp_ipv4.status_code == 200
            assert "text/html" in resp_ipv4.headers.get("content-type", "")
            assert resp_ipv4.headers.get("connection", "").lower() == "close"
            assert resp_ipv4.headers.get("cache-control", "").lower() == "no-store"

        # Check IPv6 connection
        async with httpx.AsyncClient(trust_env=False) as client:
            resp_ipv6 = await client.get(
                f"http://[::1]:{port}/oauth-callback?code=c2&state={state}"
            )
            assert resp_ipv6.status_code == 200
            assert "text/html" in resp_ipv6.headers.get("content-type", "")
            assert resp_ipv6.headers.get("connection", "").lower() == "close"
            assert resp_ipv6.headers.get("cache-control", "").lower() == "no-store"
    finally:
        await server.shutdown()


@pytest.mark.asyncio
async def test_success_redirect_calls_on_code_once_and_returns_200():
    port = get_free_port()
    server = OAuthCallbackServer()
    state = "state-success-xyz"
    code_received = []

    async def on_code(st: str, code: str) -> None:
        code_received.append((st, code))

    async def on_error(err: str) -> None:
        pass

    try:
        await server.register(
            state=state,
            redirect_uri=f"http://localhost:{port}/provider/callback",
            on_code=on_code,
            on_error=on_error,
        )

        async with httpx.AsyncClient(trust_env=False) as client:
            resp = await client.get(
                f"http://127.0.0.1:{port}/provider/callback?code=auth-code-123&state={state}"
            )
            assert resp.status_code == 200
            assert "text/html" in resp.headers.get("content-type", "")
            assert resp.headers.get("connection", "").lower() == "close"
            assert resp.headers.get("cache-control", "").lower() == "no-store"
            assert "Authorization Successful" in resp.text
            assert len(code_received) == 1
            assert code_received[0] == (state, "auth-code-123")

            # Second request should return 200 HTML without re-calling handler
            resp2 = await client.get(
                f"http://127.0.0.1:{port}/provider/callback?code=auth-code-123&state={state}"
            )
            assert resp2.status_code == 200
            assert len(code_received) == 1
    finally:
        await server.shutdown()


@pytest.mark.asyncio
async def test_unknown_state_returns_400_and_does_not_call_handler():
    port = get_free_port()
    server = OAuthCallbackServer()
    state = "registered-state"
    handler_called = False

    async def on_code(st: str, code: str) -> None:
        nonlocal handler_called
        handler_called = True

    async def on_error(err: str) -> None:
        nonlocal handler_called
        handler_called = True

    try:
        await server.register(
            state=state,
            redirect_uri=f"http://127.0.0.1:{port}/callback",
            on_code=on_code,
            on_error=on_error,
        )

        async with httpx.AsyncClient(trust_env=False) as client:
            # Different state
            resp = await client.get(
                f"http://127.0.0.1:{port}/callback?code=c&state=unknown-state"
            )
            assert resp.status_code == 400
            assert "text/html" in resp.headers.get("content-type", "")
            assert resp.headers.get("connection", "").lower() == "close"
            assert resp.headers.get("cache-control", "").lower() == "no-store"
            assert not handler_called

            # Missing state
            resp2 = await client.get(f"http://127.0.0.1:{port}/callback?code=c")
            assert resp2.status_code == 400
            assert not handler_called
    finally:
        await server.shutdown()


@pytest.mark.asyncio
async def test_non_get_returns_405():
    port = get_free_port()
    server = OAuthCallbackServer()
    state = "state-post-test"

    async def on_code(st: str, code: str) -> None:
        pass

    async def on_error(err: str) -> None:
        pass

    try:
        await server.register(
            state=state,
            redirect_uri=f"http://127.0.0.1:{port}/callback",
            on_code=on_code,
            on_error=on_error,
        )

        async with httpx.AsyncClient(trust_env=False) as client:
            resp_post = await client.post(
                f"http://127.0.0.1:{port}/callback",
                json={"state": state, "code": "xyz"},
            )
            assert resp_post.status_code == 405
            assert resp_post.headers.get("allow", "").upper() == "GET"
            assert resp_post.headers.get("connection", "").lower() == "close"
            assert resp_post.headers.get("cache-control", "").lower() == "no-store"

            resp_put = await client.put(f"http://127.0.0.1:{port}/callback")
            assert resp_put.status_code == 405
    finally:
        await server.shutdown()


@pytest.mark.asyncio
async def test_exact_registered_path_and_state_matching():
    port = get_free_port()
    server = OAuthCallbackServer()
    state = "state-path-matching"
    called = False

    async def on_code(st: str, code: str) -> None:
        nonlocal called
        called = True

    async def on_error(err: str) -> None:
        pass

    try:
        await server.register(
            state=state,
            redirect_uri=f"http://127.0.0.1:{port}/exact/path/oauth",
            on_code=on_code,
            on_error=on_error,
        )

        async with httpx.AsyncClient(trust_env=False) as client:
            # Wrong path with matching state
            resp_wrong = await client.get(
                f"http://127.0.0.1:{port}/wrong/path?code=c&state={state}"
            )
            assert resp_wrong.status_code in (404, 400)
            assert not called

            # Exact path with matching state
            resp_exact = await client.get(
                f"http://127.0.0.1:{port}/exact/path/oauth?code=c&state={state}"
            )
            assert resp_exact.status_code == 200
            assert called
    finally:
        await server.shutdown()


@pytest.mark.asyncio
async def test_two_states_on_one_port_route_independently():
    port = get_free_port()
    server = OAuthCallbackServer()
    state_a = "state-alpha-111"
    state_b = "state-beta-222"
    called_a = []
    called_b = []

    async def on_code_a(st: str, code: str) -> None:
        called_a.append((st, code))

    async def on_code_b(st: str, code: str) -> None:
        called_b.append((st, code))

    async def noop_error(err: str) -> None:
        pass

    try:
        await server.register(
            state=state_a,
            redirect_uri=f"http://127.0.0.1:{port}/callback-a",
            on_code=on_code_a,
            on_error=noop_error,
        )
        await server.register(
            state=state_b,
            redirect_uri=f"http://127.0.0.1:{port}/callback-b",
            on_code=on_code_b,
            on_error=noop_error,
        )

        async with httpx.AsyncClient(trust_env=False) as client:
            # Trigger State B
            resp_b = await client.get(
                f"http://127.0.0.1:{port}/callback-b?code=code-b&state={state_b}"
            )
            assert resp_b.status_code == 200
            assert called_b == [(state_b, "code-b")]
            assert called_a == []

            # Trigger State A
            resp_a = await client.get(
                f"http://127.0.0.1:{port}/callback-a?code=code-a&state={state_a}"
            )
            assert resp_a.status_code == 200
            assert called_a == [(state_a, "code-a")]
    finally:
        await server.shutdown()


@pytest.mark.asyncio
async def test_unregister_stops_listener_when_last_state_removed():
    port = get_free_port()
    server = OAuthCallbackServer()
    state_1 = "state-unreg-1"
    state_2 = "state-unreg-2"

    async def dummy_code(st: str, code: str) -> None:
        pass

    async def dummy_error(err: str) -> None:
        pass

    try:
        await server.register(
            state=state_1,
            redirect_uri=f"http://127.0.0.1:{port}/cb",
            on_code=dummy_code,
            on_error=dummy_error,
        )
        await server.register(
            state=state_2,
            redirect_uri=f"http://127.0.0.1:{port}/cb",
            on_code=dummy_code,
            on_error=dummy_error,
        )

        # Unregister state 1: state 2 should still be reachable
        await server.unregister(state_1)
        async with httpx.AsyncClient(trust_env=False) as client:
            resp = await client.get(f"http://127.0.0.1:{port}/cb?code=c&state={state_2}")
            assert resp.status_code == 200

        # Unregister state 2: port should be closed
        await server.unregister(state_2)

        # Confirm listener is stopped (connection refused)
        with pytest.raises(httpx.ConnectError):
            async with httpx.AsyncClient(trust_env=False) as client:
                await client.get(f"http://127.0.0.1:{port}/cb?code=c&state={state_2}")
    finally:
        await server.shutdown()


@pytest.mark.asyncio
async def test_port_already_in_use_raises_oauth_callback_error():
    port = get_free_port()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", port))
    sock.listen(1)

    server = OAuthCallbackServer()

    async def dummy_code(st: str, code: str) -> None:
        pass

    async def dummy_error(err: str) -> None:
        pass

    try:
        with pytest.raises(OAuthCallbackError):
            await server.register(
                state="state-conflict",
                redirect_uri=f"http://127.0.0.1:{port}/callback",
                on_code=dummy_code,
                on_error=dummy_error,
            )
    finally:
        sock.close()
        await server.shutdown()


@pytest.mark.asyncio
async def test_handler_exception_returns_500_without_leaking_details():
    port = get_free_port()
    server = OAuthCallbackServer()
    state = "state-exc-test"
    secret_leak_phrase = "UltraSecretInternalToken42"

    async def exploding_code(st: str, code: str) -> None:
        raise RuntimeError(f"Database error with credentials: {secret_leak_phrase}")

    async def noop_error(err: str) -> None:
        pass

    try:
        await server.register(
            state=state,
            redirect_uri=f"http://127.0.0.1:{port}/callback",
            on_code=exploding_code,
            on_error=noop_error,
        )

        async with httpx.AsyncClient(trust_env=False) as client:
            resp = await client.get(
                f"http://127.0.0.1:{port}/callback?code=c&state={state}"
            )
            assert resp.status_code == 500
            assert "text/html" in resp.headers.get("content-type", "")
            assert resp.headers.get("connection", "").lower() == "close"
            assert resp.headers.get("cache-control", "").lower() == "no-store"
            assert secret_leak_phrase not in resp.text
            assert "RuntimeError" not in resp.text
            assert "Traceback" not in resp.text
    finally:
        await server.shutdown()


@pytest.mark.asyncio
async def test_provider_error_calls_on_error_and_returns_html():
    port = get_free_port()
    server = OAuthCallbackServer()
    state = "state-err-test"
    errors_received = []

    async def noop_code(st: str, code: str) -> None:
        pass

    async def on_error(err: str) -> None:
        errors_received.append(err)

    try:
        await server.register(
            state=state,
            redirect_uri=f"http://127.0.0.1:{port}/callback",
            on_code=noop_code,
            on_error=on_error,
        )

        async with httpx.AsyncClient(trust_env=False) as client:
            resp = await client.get(
                f"http://127.0.0.1:{port}/callback?error=access_denied&state={state}"
            )
            assert resp.status_code == 200
            assert "text/html" in resp.headers.get("content-type", "")
            assert resp.headers.get("connection", "").lower() == "close"
            assert resp.headers.get("cache-control", "").lower() == "no-store"
            assert "Authorization Denied" in resp.text or "cancelled" in resp.text.lower()
            assert errors_received == ["access_denied"]
    finally:
        await server.shutdown()


@pytest.mark.asyncio
async def test_request_line_cap_8kib():
    port = get_free_port()
    server = OAuthCallbackServer()
    state = "state-8k-test"

    async def noop_code(st: str, code: str) -> None:
        pass

    async def noop_error(err: str) -> None:
        pass

    try:
        await server.register(
            state=state,
            redirect_uri=f"http://127.0.0.1:{port}/callback",
            on_code=noop_code,
            on_error=noop_error,
        )

        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        huge_query = "x" * 9000
        raw_req = f"GET /callback?q={huge_query} HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n".encode()
        writer.write(raw_req)
        await writer.drain()

        response_data = await reader.read(4096)
        writer.close()
        await writer.wait_closed()

        assert (
            b"414 URI Too Long" in response_data
            or b"400 Bad Request" in response_data
        )
    finally:
        await server.shutdown()


@pytest.mark.asyncio
async def test_zero_secret_or_token_logging(caplog):
    port = get_free_port()
    server = OAuthCallbackServer()
    secret_state = "secret-state-token-abc"
    secret_code = "secret-code-token-xyz"

    async def noop_code(st: str, code: str) -> None:
        pass

    async def noop_error(err: str) -> None:
        pass

    caplog.set_level(logging.DEBUG)

    try:
        await server.register(
            state=secret_state,
            redirect_uri=f"http://127.0.0.1:{port}/callback",
            on_code=noop_code,
            on_error=noop_error,
        )

        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        req = f"GET /callback?code={secret_code}&state={secret_state} HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n".encode()
        writer.write(req)
        await writer.drain()
        await reader.read(4096)
        writer.close()
        await writer.wait_closed()

        # Inspect all captured blm log text
        blm_records = [r for r in caplog.records if r.name.startswith("blm")]
        full_log_text = " ".join(record.getMessage() for record in blm_records)
        assert secret_state not in full_log_text
        assert secret_code not in full_log_text
        assert f"code={secret_code}" not in full_log_text
        assert f"state={secret_state}" not in full_log_text
    finally:
        await server.shutdown()


@pytest.mark.asyncio
async def test_incomplete_request_line_stall_times_out(monkeypatch):
    import time
    from app.services import oauth_callback_server

    monkeypatch.setattr(oauth_callback_server, "REQUEST_READ_TIMEOUT_SECONDS", 0.15)

    port = get_free_port()
    server = OAuthCallbackServer()
    state = "state-stall-line"
    code_called = False

    async def on_code(st: str, cd: str) -> None:
        nonlocal code_called
        code_called = True

    async def on_error(err: str) -> None:
        pass

    try:
        await server.register(
            state=state,
            redirect_uri=f"http://127.0.0.1:{port}/callback",
            on_code=on_code,
            on_error=on_error,
        )

        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        start_time = time.monotonic()

        # Send partial request-line without terminating newline and stall
        writer.write(b"GET /callback?state=" + state.encode())
        await writer.drain()

        resp_data = await asyncio.wait_for(reader.read(4096), timeout=2.0)
        elapsed = time.monotonic() - start_time

        assert elapsed < 1.0
        assert b"408 Request Timeout" in resp_data
        assert b"REQUEST TIMEOUT" in resp_data

        eof_data = await asyncio.wait_for(reader.read(), timeout=1.0)
        assert eof_data == b""
        assert not code_called
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass
        await server.shutdown()


@pytest.mark.asyncio
async def test_incomplete_header_stall_times_out(monkeypatch):
    import time
    from app.services import oauth_callback_server

    monkeypatch.setattr(oauth_callback_server, "REQUEST_READ_TIMEOUT_SECONDS", 0.15)

    port = get_free_port()
    server = OAuthCallbackServer()
    state = "state-stall-hdr"
    code_called = False

    async def on_code(st: str, cd: str) -> None:
        nonlocal code_called
        code_called = True

    async def on_error(err: str) -> None:
        pass

    try:
        await server.register(
            state=state,
            redirect_uri=f"http://127.0.0.1:{port}/callback",
            on_code=on_code,
            on_error=on_error,
        )

        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        start_time = time.monotonic()

        # Send complete request-line and partial header without terminating \r\n\r\n
        raw_req = (
            f"GET /callback?code=somecode&state={state} HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{port}\r\n"
            f"X-Partial-Header: stall"
        ).encode("utf-8")
        writer.write(raw_req)
        await writer.drain()

        resp_data = await asyncio.wait_for(reader.read(4096), timeout=2.0)
        elapsed = time.monotonic() - start_time

        assert elapsed < 1.0
        assert b"408 Request Timeout" in resp_data
        assert b"REQUEST TIMEOUT" in resp_data

        eof_data = await asyncio.wait_for(reader.read(), timeout=1.0)
        assert eof_data == b""
        assert not code_called
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass
        await server.shutdown()


# ---------------------------------------------------------------------------
# Regressions for OAuth flow fixes (Defects A, B, C, D)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_port_conflict_releases_hold_and_cancels_session(monkeypatch):
    """Regression A: Forced port conflict raises OAuthPortConflictError, releases hold, and cancels session."""
    from unittest.mock import AsyncMock, MagicMock
    from app.services.oauth_session_manager import OAuthSessionManager, OAuthPortConflictError

    cb_server = OAuthCallbackServer()
    async def fake_register(*args, **kwargs):
        raise OAuthCallbackError("Port 51121 is already in use or cannot be bound")

    monkeypatch.setattr(cb_server, "register", fake_register)

    mock_mgmt = MagicMock()
    mock_mgmt.start_oauth = AsyncMock(return_value={
        "state": "conflict-state-1",
        "auth_url": "http://127.0.0.1:51121/callback?state=conflict-state-1",
        "redirect_uri": "http://127.0.0.1:51121/callback",
    })
    mock_mgmt.cancel_oauth_session = AsyncMock()

    mock_supervisor = MagicMock()
    mock_supervisor.auth_dir = None
    mock_supervisor.ensure_started = AsyncMock()
    mock_supervisor.get_management_client.return_value = mock_mgmt
    mock_supervisor._oauth_flow_deadline = 0.0

    def fake_hold(seconds=600.0):
        mock_supervisor._oauth_flow_deadline = 999999.0
    def fake_release():
        mock_supervisor._oauth_flow_deadline = 0.0

    mock_supervisor.hold_oauth_flow.side_effect = fake_hold
    mock_supervisor.release_oauth_flow.side_effect = fake_release

    from app.services import oauth_session_manager
    monkeypatch.setattr(oauth_session_manager, "get_proxy_supervisor", lambda: mock_supervisor)

    mock_vault = MagicMock()
    mock_vault.get_state = AsyncMock()
    mock_vault.is_available = True
    monkeypatch.setattr(oauth_session_manager, "get_provider_vault", lambda: mock_vault)

    mgr = OAuthSessionManager(callback_server=cb_server)

    with pytest.raises(OAuthPortConflictError):
        await mgr.start_session("codex")

    assert mock_supervisor._oauth_flow_deadline == 0.0
    mock_supervisor.release_oauth_flow.assert_called()
    mock_mgmt.cancel_oauth_session.assert_awaited_once_with("conflict-state-1")


@pytest.mark.asyncio
async def test_hold_spans_token_exchange(monkeypatch):
    """Regression B: Hold is maintained while poll_session reports pending, released after terminal status or deadline."""
    from unittest.mock import AsyncMock, MagicMock
    from app.services.oauth_session_manager import OAuthSessionManager, PendingOAuthSession

    mock_supervisor = MagicMock()
    mock_supervisor.is_running = True
    released = False
    def fake_release():
        nonlocal released
        released = True

    mock_supervisor.release_oauth_flow.side_effect = fake_release

    from app.services import oauth_session_manager
    monkeypatch.setattr(oauth_session_manager, "get_proxy_supervisor", lambda: mock_supervisor)

    mgr = OAuthSessionManager()
    state = "exchange-state-1"
    mgr._sessions[state] = PendingOAuthSession(
        state=state,
        provider="codex",
        status="pending",
    )

    poll_calls = 0
    async def fake_poll(state: str, db_session=None):
        nonlocal poll_calls
        poll_calls += 1
        assert not released, "Hold was released prematurely during exchange"
        if poll_calls < 3:
            return {"status": "pending"}
        return {"status": "completed"}

    monkeypatch.setattr(mgr, "poll_session", fake_poll)

    await mgr._complete_loopback_session(state)
    assert poll_calls == 3
    assert released, "Hold was not released after terminal status"

    # Also test bounded grace timeout with permanently pending status
    released = False
    poll_calls = 0
    async def fake_poll_pending(state: str, db_session=None):
        nonlocal poll_calls
        poll_calls += 1
        assert not released
        return {"status": "pending"}

    monkeypatch.setattr(mgr, "poll_session", fake_poll_pending)

    fake_time = 100.0
    async def fast_sleep(sec):
        nonlocal fake_time
        fake_time += 1.0

    monkeypatch.setattr(oauth_session_manager.time, "monotonic", lambda: fake_time)
    monkeypatch.setattr(oauth_session_manager.asyncio, "sleep", fast_sleep)

    await mgr._complete_loopback_session(state)
    assert released, "Hold was not released at grace deadline"


@pytest.mark.asyncio
async def test_duplicate_callback_concurrent_single_execution():
    """Regression C: Concurrent requests for same registered state invoke on_code exactly once."""
    port = get_free_port()
    server = OAuthCallbackServer()
    state = "state-concurrent-test"
    call_count = 0

    async def on_code(st: str, code: str) -> None:
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(0.05)

    async def on_error(err: str) -> None:
        pass

    try:
        await server.register(
            state=state,
            redirect_uri=f"http://127.0.0.1:{port}/callback",
            on_code=on_code,
            on_error=on_error,
        )

        async with httpx.AsyncClient(trust_env=False) as client:
            req1 = client.get(f"http://127.0.0.1:{port}/callback?code=c1&state={state}")
            req2 = client.get(f"http://127.0.0.1:{port}/callback?code=c2&state={state}")
            resp1, resp2 = await asyncio.gather(req1, req2)

            assert resp1.status_code == 200
            assert resp2.status_code == 200
            assert "Authorization Successful" in resp1.text
            assert "Authorization Successful" in resp2.text
            assert call_count == 1
    finally:
        await server.shutdown()


@pytest.mark.asyncio
async def test_ipv4_only_bind_fallback(monkeypatch):
    """Regression D: If ::1 bind raises OSError, register succeeds with IPv4 only. Real IPv4 failure raises."""
    port = get_free_port()
    server = OAuthCallbackServer()
    state = "state-ipv4-only"

    orig_start_server = asyncio.start_server
    async def mock_start_server(client_connected_cb, host=None, port=None, **kwargs):
        if host == "::1":
            raise OSError("IPv6 not supported on this host")
        return await orig_start_server(client_connected_cb, host=host, port=port, **kwargs)

    monkeypatch.setattr(asyncio, "start_server", mock_start_server)

    async def on_code(st: str, code: str) -> None:
        pass
    async def on_error(err: str) -> None:
        pass

    try:
        url = await server.register(
            state=state,
            redirect_uri=f"http://127.0.0.1:{port}/callback",
            on_code=on_code,
            on_error=on_error,
        )
        assert url == f"http://127.0.0.1:{port}/callback"

        # Check IPv4 connection works
        async with httpx.AsyncClient(trust_env=False) as client:
            resp = await client.get(f"http://127.0.0.1:{port}/callback?code=c1&state={state}")
            assert resp.status_code == 200
    finally:
        await server.shutdown()

    # Also verify real IPv4 failure raises OAuthCallbackError with expected message
    server_fail = OAuthCallbackServer()
    async def mock_start_server_fail(client_connected_cb, host=None, port=None, **kwargs):
        raise OSError("Port in use")
    monkeypatch.setattr(asyncio, "start_server", mock_start_server_fail)

    with pytest.raises(OAuthCallbackError) as exc_info:
        await server_fail.register(
            state="fail-state",
            redirect_uri=f"http://127.0.0.1:{port}/callback",
            on_code=on_code,
            on_error=on_error,
        )
    assert f"Port {port} is already in use or cannot be bound" in str(exc_info.value)
