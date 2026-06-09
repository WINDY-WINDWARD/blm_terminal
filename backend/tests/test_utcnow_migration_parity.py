"""Parity tests for audit Phase A.5 — ``datetime.utcnow()`` sweep.

Audit citation: ``BACKEND_AUDIT.md`` §5 L349, Phase A.5 ("``datetime.utcnow()``
→ ``now(timezone.utc)``").

Contract locked here:
1. ``app.backgroundtasks._should_trigger_full_sync`` computes a naive UTC
   "now" that is subtracted from the (naive) DB column
   ``StockUniverse.fair_value_updated_at``. Behaviour must be identical
   before and after the swap from ``datetime.utcnow()`` to
   ``datetime.now(timezone.utc).replace(tzinfo=None)``.
2. ``app.services.news_aggregator._parsed_article_to_db_dict`` writes a
   naive UTC ``fetched_at`` into the DB dict. Behaviour must be identical
   after the swap.
3. Neither module contains any ``datetime.utcnow()`` call anymore
   (locks the deletion contract).

Frozen-datetime test pattern follows ``test_timezone_migration.py:90-120``
(``BACKEND_AUDIT_IMPL_CONTEXT.md`` §3.2 / §4.4) — subclass ``datetime``
(not ``Mock``) so ``isinstance(..., datetime)`` checks pass; override
``now()`` to return the frozen value; preserve the ``tz`` argument.
"""
from __future__ import annotations

import inspect
from datetime import datetime, timedelta, timezone

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_frozen_datetime_class(frozen: datetime):
    """Build a ``datetime`` subclass whose ``now()`` AND ``utcnow()``
    return the frozen value.

    The class preserves the ``tz`` argument so callers that use
    ``datetime.now(IST_ZONE)`` / ``datetime.now(timezone.utc)`` still work
    (returns the frozen value in the requested timezone).

    ``utcnow()`` is also overridden because the audit-cited code path
    (``_should_trigger_full_sync``) uses ``datetime.utcnow()`` — Python
    classmethod dispatch on a subclass would otherwise call the real
    ``datetime.utcnow()`` and return actual wall-clock time.
    """
    class _FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return frozen.replace(tzinfo=None)
            return frozen.astimezone(tz)

        @classmethod
        def utcnow(cls):
            return frozen.replace(tzinfo=None)

    return _FrozenDateTime


# ---------------------------------------------------------------------------
# backgroundtasks._should_trigger_full_sync
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_should_trigger_full_sync_returns_true_when_no_last_update(monkeypatch):
    """No fair_value_updated_at row in DB -> always trigger."""
    from app import backgroundtasks
    from app.services import fair_value

    # Mock the AsyncSessionLocal context manager to return a session that
    # yields no max() (None). We can't easily patch AsyncSessionLocal here
    # without DB access, so use a direct patch on the function: replace
    # the inner session-execution with a stub that returns None for max().
    class _StubResult:
        def scalar(self):
            return None

    class _StubSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def execute(self, stmt):
            return _StubResult()

        async def commit(self):
            pass

    # After Phase C.1 A.12 part 2, the implementation lives in
    # ``app.services.fair_value`` — patch there because functions
    # defined in ``fair_value`` look up their own module globals,
    # not the package's.
    monkeypatch.setattr(fair_value, "AsyncSessionLocal", lambda: _StubSession())

    frozen = datetime(2026, 6, 5, 12, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(fair_value, "datetime", _make_frozen_datetime_class(frozen))

    assert await backgroundtasks._should_trigger_full_sync() is True


@pytest.mark.asyncio
async def test_should_trigger_full_sync_returns_true_when_stale(monkeypatch):
    """last_update > 24h ago -> trigger sync."""
    from app import backgroundtasks
    from app.services import fair_value

    # last_update 25 hours before the frozen "now"
    frozen = datetime(2026, 6, 5, 12, 0, 0, tzinfo=timezone.utc)
    last_update = (frozen - timedelta(hours=25)).replace(tzinfo=None)

    class _StubResult:
        def __init__(self, value):
            self._value = value

        def scalar(self):
            return self._value

    class _StubSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def execute(self, stmt):
            return _StubResult(last_update)

        async def commit(self):
            pass

    monkeypatch.setattr(fair_value, "AsyncSessionLocal", lambda: _StubSession())
    monkeypatch.setattr(fair_value, "datetime", _make_frozen_datetime_class(frozen))

    assert await backgroundtasks._should_trigger_full_sync() is True


@pytest.mark.asyncio
async def test_should_trigger_full_sync_returns_false_when_recent(monkeypatch):
    """last_update within 24h -> skip sync."""
    from app import backgroundtasks
    from app.services import fair_value

    # last_update 23 hours before the frozen "now" (within 24h)
    frozen = datetime(2026, 6, 5, 12, 0, 0, tzinfo=timezone.utc)
    last_update = (frozen - timedelta(hours=23)).replace(tzinfo=None)

    class _StubResult:
        def __init__(self, value):
            self._value = value

        def scalar(self):
            return self._value

    class _StubSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def execute(self, stmt):
            return _StubResult(last_update)

        async def commit(self):
            pass

    # After Phase C.1 A.12 part 2, the implementation lives in
    # ``app.services.fair_value`` — patch there because functions
    # defined in ``fair_value`` look up their own module globals,
    # not the package's.
    monkeypatch.setattr(fair_value, "AsyncSessionLocal", lambda: _StubSession())
    monkeypatch.setattr(fair_value, "datetime", _make_frozen_datetime_class(frozen))

    assert await backgroundtasks._should_trigger_full_sync() is False


# ---------------------------------------------------------------------------
# news_aggregator._parsed_article_to_db_dict
# ---------------------------------------------------------------------------

def test_parsed_article_to_db_dict_fetched_at_is_frozen_naive_utc(monkeypatch):
    """``fetched_at`` in the returned dict equals the frozen datetime, naive."""
    from app.services import news_aggregator
    from app.services.rss_parser import ParsedArticle

    # Stub the NLP service so we don't hit the real model
    def _fake_nlp(headline: str, summary: str, source_name: str | None) -> dict:
        return {
            "sentiment": "NEUTRAL",
            "sentiment_score": 0.0,
            "confidence": 0.5,
            "language": "en",
            "entities": [],
            "threat_level": "LOW",
            "threat_category": None,
            "source_credibility": 0.5,
        }

    monkeypatch.setattr(news_aggregator, "analyze_article_dict", _fake_nlp)

    # Freeze datetime to a known UTC instant
    frozen = datetime(2026, 6, 5, 12, 34, 56, tzinfo=timezone.utc)
    monkeypatch.setattr(news_aggregator, "datetime", _make_frozen_datetime_class(frozen))

    article = ParsedArticle(
        url="https://example.com/article-1",
        title="A title",
        summary="A summary",
        published=datetime(2026, 6, 5, 11, 0, 0, tzinfo=timezone.utc),
        author="Alice",
        source_id="src-1",
        source_name="Example",
        source_category="news",
        source_tier=1,
    )

    result = news_aggregator._parsed_article_to_db_dict(article)

    assert result["fetched_at"] == frozen.replace(tzinfo=None)
    assert result["fetched_at"].tzinfo is None
    assert result["fetched_at"] == datetime(2026, 6, 5, 12, 34, 56)


# ---------------------------------------------------------------------------
# Locks: no remaining datetime.utcnow() in the two refactored modules
# ---------------------------------------------------------------------------

def test_no_utcnow_in_backgroundtasks() -> None:
    """The audit's contract: all ``datetime.utcnow()`` calls in
    ``backgroundtasks.py`` have been replaced."""
    from app import backgroundtasks

    source = inspect.getsource(backgroundtasks)
    assert "datetime.utcnow()" not in source, (
        "backgroundtasks.py still contains datetime.utcnow() — "
        "audit A.5 contract is not satisfied"
    )


def test_no_utcnow_in_news_aggregator() -> None:
    """The audit's contract: all ``datetime.utcnow()`` calls in
    ``news_aggregator.py`` have been replaced."""
    from app.services import news_aggregator

    source = inspect.getsource(news_aggregator)
    assert "datetime.utcnow()" not in source, (
        "news_aggregator.py still contains datetime.utcnow() — "
        "audit A.5 contract is not satisfied"
    )
