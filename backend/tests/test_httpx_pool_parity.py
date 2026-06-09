"""Parity tests for the shared httpx client refactor.

Audit win #10: replace per-call `async with httpx.AsyncClient(...)` with
a module-level shared client to enable connection pooling and avoid
repeated TLS handshakes on hot paths (rss_parser, ai_chat_service).

This test file pins behavior for the shared-client factory used in both
services. The factory must:
  - return the SAME httpx.AsyncClient instance across calls on the same loop
  - recreate the client if the running event loop changes
  - be safe under concurrent access (lazy-init must not race)
  - preserve the original per-request config (timeout, follow_redirects)
  - NOT change the per-request timeout (caller can still override)
"""

from __future__ import annotations

import asyncio
import inspect

import httpx
import pytest

from app.services import rss_parser
from app.services import ai_chat_service


# --- helpers ---------------------------------------------------------------


class _RecordingTransport(httpx.AsyncBaseTransport):
    """Captures outgoing requests; returns a minimal RSS body for the rss_parser path."""

    def __init__(self, body: str = "<rss></rss>") -> None:
        self.requests: list[httpx.Request] = []
        self._body = body

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(200, text=self._body)


def _reset_rss_shared_client() -> None:
    """Drop the module-level shared client so the next call rebuilds it."""
    rss_parser._shared_client = None
    rss_parser._shared_client_loop = None


def _attach_transport(client: httpx.AsyncClient, transport: httpx.AsyncBaseTransport) -> None:
    """Swap a client's transport for a fake. Bypasses real I/O."""
    client._transport = transport


# --- rss_parser factory ----------------------------------------------------


def test_rss_parser_exposes_get_shared_client() -> None:
    """The factory must exist at module level on rss_parser."""
    assert hasattr(rss_parser, "_get_shared_client"), (
        "rss_parser must expose _get_shared_client factory for the pool refactor"
    )
    assert callable(rss_parser._get_shared_client)


def test_rss_parser_get_shared_client_returns_httpx_async_client() -> None:
    _reset_rss_shared_client()
    factory = rss_parser._get_shared_client
    if not inspect.iscoroutinefunction(factory):
        client = factory()
    else:
        client = asyncio.get_event_loop().run_until_complete(factory())
    assert isinstance(client, httpx.AsyncClient)
    _reset_rss_shared_client()


def test_rss_parser_shared_client_is_reused_across_calls() -> None:
    """Two calls on the same event loop must return the SAME client instance."""
    _reset_rss_shared_client()
    client_a = rss_parser._get_shared_client()
    client_b = rss_parser._get_shared_client()
    assert client_a is client_b, "shared client must be reused, not recreated"
    _reset_rss_shared_client()


def test_rss_parser_shared_client_config_preserves_follow_redirects_and_timeout() -> None:
    """The shared client must keep follow_redirects=True and a sane default timeout."""
    _reset_rss_shared_client()
    client = rss_parser._get_shared_client()
    assert client.follow_redirects is True, "rss_parser historically uses follow_redirects=True"
    # httpx stores timeout as httpx.Timeout; connect/read/write/pool all set on the default 15.0
    timeout = client.timeout
    assert timeout.connect == 15.0
    assert timeout.read == 15.0
    assert timeout.write == 15.0
    assert timeout.pool == 15.0
    _reset_rss_shared_client()


@pytest.mark.asyncio
async def test_rss_parser_shared_client_recreated_on_loop_change() -> None:
    """If the running event loop changes, the factory must build a new client.

    Inside an async context the factory compares `_shared_client_loop`
    against `asyncio.get_running_loop()`. Stash a sentinel as the
    recorded loop so the comparison fails and a fresh client is built.
    """
    _reset_rss_shared_client()
    client_a = rss_parser._get_shared_client()
    # Pretend the client was bound to some other loop
    rss_parser._shared_client_loop = object()  # any non-equal sentinel
    client_b = rss_parser._get_shared_client()
    assert client_a is not client_b, "loop change must trigger a fresh client"
    _reset_rss_shared_client()


@pytest.mark.asyncio
async def test_rss_parser_fetch_feed_uses_shared_client() -> None:
    """End-to-end: fetch_feed must funnel HTTP through the shared client (one client, N requests)."""
    _reset_rss_shared_client()

    # Pre-create the shared client and inject a recording transport
    client = rss_parser._get_shared_client()
    transport = _RecordingTransport(body="<rss><channel></channel></rss>")
    _attach_transport(client, transport)

    # Build a minimal NewsSource via the public data class
    from app.services.news_sources import NewsSource, SourceCategory, SourceTier

    src = NewsSource(
        id="test_src",
        name="Test Source",
        url="https://example.test/feed.xml",
        category=SourceCategory.GEOPOLITICS,
        tier=SourceTier.TIER_1,
    )

    result1 = await rss_parser.fetch_feed(src, timeout=15.0)
    result2 = await rss_parser.fetch_feed(src, timeout=15.0)

    # Two requests went out on the same transport (i.e., same client)
    assert len(transport.requests) == 2
    # The shared client is the one we pre-created
    assert rss_parser._shared_client is client
    # No errors raised
    assert result1.error is None
    assert result2.error is None

    _reset_rss_shared_client()


@pytest.mark.asyncio
async def test_rss_parser_per_request_timeout_override_still_works() -> None:
    """Parity: caller can still override the per-request timeout."""
    _reset_rss_shared_client()

    client = rss_parser._get_shared_client()
    transport = _RecordingTransport(body="<rss></rss>")
    _attach_transport(client, transport)

    from app.services.news_sources import NewsSource, SourceCategory, SourceTier

    src = NewsSource(
        id="t",
        name="T",
        url="https://example.test/feed",
        category=SourceCategory.GEOPOLITICS,
        tier=SourceTier.TIER_1,
    )

    # Override with a different timeout; must not raise
    await rss_parser.fetch_feed(src, timeout=5.0)
    assert len(transport.requests) == 1

    _reset_rss_shared_client()


@pytest.mark.asyncio
async def test_rss_parser_concurrent_calls_share_one_client() -> None:
    """Concurrent fetch_feed calls must all funnel through the same shared client."""
    _reset_rss_shared_client()

    client = rss_parser._get_shared_client()
    transport = _RecordingTransport(body="<rss></rss>")
    _attach_transport(client, transport)

    from app.services.news_sources import NewsSource, SourceCategory, SourceTier

    sources = [
        NewsSource(
            id=f"s{i}",
            name=f"S{i}",
            url=f"https://example.test/feed{i}",
            category=SourceCategory.GEOPOLITICS,
            tier=SourceTier.TIER_1,
        )
        for i in range(8)
    ]

    await asyncio.gather(*(rss_parser.fetch_feed(s) for s in sources))

    # All 8 went through the same transport (i.e., same shared client)
    assert len(transport.requests) == 8
    assert rss_parser._shared_client is client


# --- ai_chat_service factory ------------------------------------------------


def _reset_ai_chat_shared_client() -> None:
    """Drop the module-level shared client so the next call rebuilds it."""
    ai_chat_service._shared_client = None
    ai_chat_service._shared_client_loop = None


def test_ai_chat_service_exposes_get_shared_client() -> None:
    """The factory must exist at module level on ai_chat_service."""
    assert hasattr(ai_chat_service, "_get_shared_client"), (
        "ai_chat_service must expose _get_shared_client factory for the pool refactor"
    )
    assert callable(ai_chat_service._get_shared_client)


def test_ai_chat_service_get_shared_client_returns_httpx_async_client() -> None:
    _reset_ai_chat_shared_client()
    factory = ai_chat_service._get_shared_client
    if not inspect.iscoroutinefunction(factory):
        client = factory()
    else:
        client = asyncio.get_event_loop().run_until_complete(factory())
    assert isinstance(client, httpx.AsyncClient)
    _reset_ai_chat_shared_client()


def test_ai_chat_service_shared_client_is_reused_across_calls() -> None:
    _reset_ai_chat_shared_client()
    client_a = ai_chat_service._get_shared_client()
    client_b = ai_chat_service._get_shared_client()
    assert client_a is client_b
    _reset_ai_chat_shared_client()


def test_ai_chat_service_shared_client_config_preserves_timeout_120() -> None:
    """Both streaming call sites historically use timeout=120.0 — preserve it."""
    _reset_ai_chat_shared_client()
    client = ai_chat_service._get_shared_client()
    timeout = client.timeout
    assert timeout.connect == 120.0
    assert timeout.read == 120.0
    assert timeout.write == 120.0
    assert timeout.pool == 120.0
    _reset_ai_chat_shared_client()


@pytest.mark.asyncio
async def test_ai_chat_service_shared_client_recreated_on_loop_change() -> None:
    _reset_ai_chat_shared_client()
    client_a = ai_chat_service._get_shared_client()
    ai_chat_service._shared_client_loop = object()
    client_b = ai_chat_service._get_shared_client()
    assert client_a is not client_b
    _reset_ai_chat_shared_client()


# --- call site verification -------------------------------------------------


def test_ai_chat_service_openai_loop_uses_shared_factory() -> None:
    """_run_openai_loop must call _get_shared_client (not build a fresh client)."""
    import inspect

    src = inspect.getsource(ai_chat_service._run_openai_loop)
    # The new pattern replaces `async with httpx.AsyncClient(...) as client:`
    # with `client = _get_shared_client()`.
    assert "async with httpx.AsyncClient" not in src, (
        "_run_openai_loop must no longer use a fresh `async with httpx.AsyncClient`"
    )
    assert "_get_shared_client" in src, (
        "_run_openai_loop must call _get_shared_client"
    )


def test_ai_chat_service_anthropic_loop_uses_shared_factory() -> None:
    """_run_anthropic_loop must call _get_shared_client (not build a fresh client)."""
    import inspect

    src = inspect.getsource(ai_chat_service._run_anthropic_loop)
    assert "async with httpx.AsyncClient" not in src, (
        "_run_anthropic_loop must no longer use a fresh `async with httpx.AsyncClient`"
    )
    assert "_get_shared_client" in src, (
        "_run_anthropic_loop must call _get_shared_client"
    )


# --- rss_parser call site --------------------------------------------------


def test_rss_parser_fetch_feed_uses_shared_factory() -> None:
    """fetch_feed must call _get_shared_client (not build a fresh client)."""
    import inspect

    src = inspect.getsource(rss_parser.fetch_feed)
    assert "async with httpx.AsyncClient" not in src, (
        "fetch_feed must no longer use a fresh `async with httpx.AsyncClient`"
    )
    assert "_get_shared_client" in src, (
        "fetch_feed must call _get_shared_client"
    )

    _reset_rss_shared_client()
