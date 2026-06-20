"""Parity tests for news_fetcher concurrency bugs (audit Phase A item).

Two bugs in the news_fetcher service:

Bug 1 — Shared-client header mutation
    ``NewsFetcher._get_page`` mutates the shared ``httpx.AsyncClient``
    headers via ``client.headers.update(headers)`` before every request.
    If two coroutines call ``_get_page`` concurrently, one can clobber
    the headers of the other, causing requests to be sent with
    wrong/missing headers.

    Fix: pass per-request headers via ``client.get(url, headers=headers)``
    so the shared client's headers are never mutated.

Bug 2 — Sleep inside semaphore
    ``NewsFetcher._fetch_and_parse_article`` does
    ``await asyncio.sleep(REQUEST_DELAY)`` INSIDE the
    ``async with self._get_semaphore()`` block.  The semaphore's
    purpose is to limit CONCURRENT in-flight HTTP requests, but the
    politeness sleep holds the semaphore for the full delay, so
    other tasks cannot acquire it while a successful request is
    sleeping.

    Fix: move the sleep OUTSIDE the ``async with`` so the semaphore
    is released immediately when parsing is done.  The sleep then
    throttles the call rate independently from in-flight concurrency.

These tests are written BEFORE the fix so they fail against the
buggy code, then pass after the fix.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services import news_fetcher
from app.services.news_fetcher import (
    NewsFetcher,
    _ArticleNotFound,
    CONCURRENCY_LIMIT,
    REQUEST_DELAY,
)


MIN_HTML = """\
<html>
<head><title>Test Article Title</title></head>
<body>
<h1>Test Article Heading</h1>
<div class="article_body">
<p>This is the body of a test article. It is intentionally long enough to exceed the one hundred character minimum threshold that the parser enforces. We need to include enough prose to make sure that the text extraction logic considers this a valid article body and continues with the rest of the parsing pipeline.</p>
<p>Additional prose to push past any length thresholds in the validator and ensure that the parser accepts this as a well-formed article with a complete body section. More text helps satisfy any internal checks the parsing logic may perform against the extracted body of the article.</p>
</div>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Fakes — no real I/O, no real httpx
# ---------------------------------------------------------------------------


class FakeResponse:
    """Minimal stand-in for httpx.Response — just the bits _get_page uses."""

    def __init__(self, text: str, status_code: int = 200) -> None:
        self.text = text
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"{self.status_code}",
                request=httpx.Request("GET", "https://example.com"),
                response=self,
            )


class FakeAsyncClient:
    """Minimal httpx.AsyncClient that records .get() calls and .headers.

    Mirrors the bits of the real API that ``_get_page`` uses:
      - ``.headers`` (mutable dict)
      - ``async get(url, **kwargs)``
      - ``async aclose()``
    """

    def __init__(self, body: str = MIN_HTML, status_code: int = 200) -> None:
        self.headers = {"User-Agent": "test-init"}
        self.get_calls: list[tuple[str, dict]] = []
        self.response = FakeResponse(body, status_code)
        self.aclose_called = False
        # If set, get() raises this exception instead of returning a response
        self.raise_from_get: BaseException | None = None

    async def get(self, url: str, **kwargs):
        self.get_calls.append((url, dict(kwargs)))
        if self.raise_from_get is not None:
            raise self.raise_from_get
        return self.response

    async def aclose(self) -> None:
        self.aclose_called = True


class TrackedSemaphore:
    """asyncio.Semaphore that records every acquire/release into `events`.

    Each event is a tuple ``(kind, active_count)`` where ``active_count`` is
    the number of holders immediately after the transition.  Lets us assert
    ordering of sem_release vs other events (like ``asyncio.sleep``).
    """

    def __init__(self, value: int, events: list | None = None) -> None:
        self._sem = asyncio.Semaphore(value)
        self._active = 0
        self.events = events if events is not None else []

    async def __aenter__(self):
        await self._sem.acquire()
        self._active += 1
        self.events.append(("sem_acquire", self._active))
        return self

    async def __aexit__(self, *args):
        self._active -= 1
        self.events.append(("sem_release", self._active))
        self._sem.release()
        return False


def make_fetcher(
    *,
    fake_client: FakeAsyncClient | None = None,
    tracked_sem: TrackedSemaphore | None = None,
) -> NewsFetcher:
    """Build a NewsFetcher wired up with our fakes (no real I/O, no cookie load).

    Critical: we must set both ``_client`` AND ``_client_loop`` (same for
    ``_semaphore``/``_semaphore_loop``) — otherwise the lazy init in
    ``_get_client`` / ``_get_semaphore`` sees a ``None`` loop, treats the
    current loop as mismatched, and recreates the real httpx client /
    semaphore, destroying our fakes and triggering real I/O.
    """
    fetcher = NewsFetcher()
    if fake_client is None:
        fake_client = FakeAsyncClient()
    loop = asyncio.get_event_loop()
    fetcher._client = fake_client
    fetcher._client_loop = loop
    if tracked_sem is not None:
        fetcher._semaphore = tracked_sem
        fetcher._semaphore_loop = loop
    # Bypass _is_valid_response — its 10KB threshold is an implementation
    # detail (heuristic for real MoneyControl pages) and irrelevant to the
    # concurrency contracts under test.
    fetcher._is_valid_response = lambda html, url: (True, "OK")
    return fetcher


def make_failing_get_page(exc: BaseException):
    """Build a ``_get_page`` replacement that raises `exc` on every call.

    Bypasses the real ``_get_page`` retry/backoff so we test the wrapper's
    error handling in isolation.
    """

    async def failing(url: str, max_retries: int = 3):
        raise exc

    return failing


# ═════════════════════════════════════════════════════════════════════════════
# Bug 1: _get_page mutates shared client headers
# ═════════════════════════════════════════════════════════════════════════════


class TestGetPageHeadersParity:
    """``_get_page`` must not mutate the shared httpx client's headers."""

    async def test_per_request_headers_passed_as_kwarg(self) -> None:
        fake = FakeAsyncClient()
        fetcher = make_fetcher(fake_client=fake)
        url = "https://www.moneycontrol.com/news/foo-123456.html"

        await fetcher._get_page(url)

        assert len(fake.get_calls) == 1
        called_url, called_kwargs = fake.get_calls[0]
        assert called_url == url
        assert "headers" in called_kwargs, (
            "Bug 1: headers must be passed as a per-request kwarg, "
            "not via client.headers.update()"
        )
        assert isinstance(called_kwargs["headers"], dict)
        # BROWSER_PRESETS use the literal key ``user_agent`` (with underscore).
        # We only require that a user-agent-like key is present; the exact
        # spelling is a convention, not part of the concurrency contract.
        headers = called_kwargs["headers"]
        assert any("agent" in k.lower() for k in headers), (
            f"per-request headers missing user-agent field: {list(headers.keys())}"
        )

    async def test_shared_client_headers_unchanged_after_call(self) -> None:
        fake = FakeAsyncClient()
        original_headers = dict(fake.headers)
        fetcher = make_fetcher(fake_client=fake)
        url = "https://www.moneycontrol.com/news/foo-123456.html"

        await fetcher._get_page(url)

        assert fake.headers == original_headers, (
            f"Bug 1: client.headers were mutated: "
            f"before={original_headers} after={fake.headers}"
        )

    async def test_concurrent_calls_each_get_correct_headers(self) -> None:
        """Race: two coroutines call _get_page with different URLs.

        With the bug, one call's ``client.headers.update()`` can clobber the
        other's before the other's ``client.get()`` actually sends.  With the
        fix, each call passes its own headers via the kwarg, so they don't
        interfere.
        """
        fake = FakeAsyncClient()
        fetcher = make_fetcher(fake_client=fake)
        url_a = "https://www.moneycontrol.com/news/article-a-111111.html"
        url_b = "https://www.moneycontrol.com/news/article-b-222222.html"

        await asyncio.gather(
            fetcher._get_page(url_a),
            fetcher._get_page(url_b),
        )

        assert len(fake.get_calls) == 2
        for url, kwargs in fake.get_calls:
            assert "headers" in kwargs, f"missing per-request headers for {url}"
        assert fake.headers == {"User-Agent": "test-init"}


# ═════════════════════════════════════════════════════════════════════════════
# Bug 2: _fetch_and_parse_article sleeps while holding the semaphore
# ═════════════════════════════════════════════════════════════════════════════


class TestFetchAndParseSemaphoreSleepParity:
    """``_fetch_and_parse_article`` must not sleep while holding the semaphore."""

    async def test_sleep_happens_after_semaphore_release(self, monkeypatch) -> None:
        """Fix: ``asyncio.sleep(REQUEST_DELAY)`` fires AFTER the sem is released."""
        events: list = []
        fake = FakeAsyncClient()
        sem = TrackedSemaphore(CONCURRENCY_LIMIT, events=events)
        fetcher = make_fetcher(fake_client=fake, tracked_sem=sem)

        sleep_calls: list[float] = []

        async def fake_sleep(delay: float) -> None:
            sleep_calls.append(delay)
            events.append(("sleep", delay))

        monkeypatch.setattr(news_fetcher.asyncio, "sleep", fake_sleep)

        await fetcher._fetch_and_parse_article(
            "https://www.moneycontrol.com/news/article-123456.html"
        )

        first_release_idx = next(
            i for i, e in enumerate(events) if e[0] == "sem_release"
        )
        first_sleep_idx = next(
            i for i, e in enumerate(events) if e[0] == "sleep"
        )

        assert first_release_idx < first_sleep_idx, (
            f"Bug 2: sleep must happen AFTER sem_release, got events={events}"
        )
        assert sleep_calls == [REQUEST_DELAY]

    async def test_semaphore_released_during_sleep(
        self, monkeypatch
    ) -> None:
        """Concrete benefit: while task A is sleeping, the sem is free.

        With the bug, ``sem._active`` would be 1 while the sleep is running
        (the semaphore is held).  With the fix, ``sem._active`` is 0 during
        the sleep — another task can acquire.
        """
        events: list = []
        fake = FakeAsyncClient()
        sem = TrackedSemaphore(CONCURRENCY_LIMIT, events=events)
        fetcher = make_fetcher(fake_client=fake, tracked_sem=sem)

        sleep_started = asyncio.Event()
        sleep_can_finish = asyncio.Event()

        async def fake_sleep(delay: float) -> None:
            events.append(("sleep_start", delay))
            sleep_started.set()
            await sleep_can_finish.wait()
            events.append(("sleep_end", delay))

        monkeypatch.setattr(news_fetcher.asyncio, "sleep", fake_sleep)

        url = "https://www.moneycontrol.com/news/article-123456.html"
        task_a = asyncio.create_task(fetcher._fetch_and_parse_article(url))
        await sleep_started.wait()

        assert sem._active == 0, (
            f"Bug 2: semaphore is still held during sleep, "
            f"active={sem._active}, events={events}"
        )

        sleep_can_finish.set()
        result = await task_a
        assert result is not None

    async def test_success_path_still_sleeps_request_delay(
        self, monkeypatch
    ) -> None:
        """Behavior preserved: successful parse still sleeps REQUEST_DELAY."""
        sleep_calls: list[float] = []

        async def fake_sleep(delay: float) -> None:
            sleep_calls.append(delay)

        monkeypatch.setattr(news_fetcher.asyncio, "sleep", fake_sleep)

        fetcher = make_fetcher()
        result = await fetcher._fetch_and_parse_article(
            "https://www.moneycontrol.com/news/article-123456.html"
        )

        assert result is not None
        assert result["title"] == "Test Article Heading"
        assert sleep_calls == [REQUEST_DELAY]

    async def test_404_skips_sleep(self, monkeypatch) -> None:
        """Behavior preserved: _ArticleNotFound (404) does NOT sleep."""
        sleep_calls: list[float] = []

        async def fake_sleep(delay: float) -> None:
            sleep_calls.append(delay)

        monkeypatch.setattr(news_fetcher.asyncio, "sleep", fake_sleep)

        fetcher = make_fetcher()
        fetcher._get_page = make_failing_get_page(
            _ArticleNotFound("https://www.moneycontrol.com/news/missing-999999.html")
        )

        result = await fetcher._fetch_and_parse_article(
            "https://www.moneycontrol.com/news/missing-999999.html"
        )

        assert result is None
        assert sleep_calls == [], (
            "Behavior preservation: 404 must skip the politeness sleep"
        )

    async def test_generic_exception_skips_sleep(self, monkeypatch) -> None:
        """Behavior preserved: generic parse exception does NOT sleep."""
        sleep_calls: list[float] = []

        async def fake_sleep(delay: float) -> None:
            sleep_calls.append(delay)

        monkeypatch.setattr(news_fetcher.asyncio, "sleep", fake_sleep)

        fetcher = make_fetcher()
        fetcher._get_page = make_failing_get_page(
            RuntimeError("simulated parse failure")
        )

        result = await fetcher._fetch_and_parse_article(
            "https://www.moneycontrol.com/news/article-123456.html"
        )

        assert result is None
        assert sleep_calls == [], (
            "Behavior preservation: exception must skip the politeness sleep"
        )

    async def test_semaphore_released_on_404(self, monkeypatch) -> None:
        """On 404, the semaphore must be released so other tasks can run."""
        events: list = []
        sem = TrackedSemaphore(CONCURRENCY_LIMIT, events=events)
        fetcher = make_fetcher(tracked_sem=sem)
        fetcher._get_page = make_failing_get_page(
            _ArticleNotFound("https://www.moneycontrol.com/news/missing-999999.html")
        )

        async def fake_sleep(delay: float) -> None:
            pass

        monkeypatch.setattr(news_fetcher.asyncio, "sleep", fake_sleep)

        await fetcher._fetch_and_parse_article(
            "https://www.moneycontrol.com/news/missing-999999.html"
        )

        acquires = [e for e in events if e[0] == "sem_acquire"]
        releases = [e for e in events if e[0] == "sem_release"]
        assert acquires == [("sem_acquire", 1)]
        assert releases == [("sem_release", 0)]

@pytest.mark.perf
async def test_news_fetcher_perf_streaming(monkeypatch, in_memory_db):
    """Test that stream processing consumes less memory."""
    import tracemalloc
    from app.database import AsyncSessionLocal
    
    fake = FakeAsyncClient()
    fetcher = make_fetcher(fake_client=fake)
    
    def mock_extract(*args):
        return [f"https://www.moneycontrol.com/news/article-{i:06d}.html" for i in range(500)]
        
    async def mock_fetch_listing(*args):
        return "html"
        
    fetcher._extract_article_urls = mock_extract
    fetcher._fetch_listing_page = mock_fetch_listing
    
    tracemalloc.start()
    start_mem, _ = tracemalloc.get_traced_memory()
    
    async with AsyncSessionLocal() as db:
        await fetcher.crawl_and_store(pages=1, db=db)
        
    end_mem, _ = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    
    diff_mb = (end_mem - start_mem) / (1024 * 1024)
    assert diff_mb < 10.0, f"Memory leaked {diff_mb:.2f} MB"
