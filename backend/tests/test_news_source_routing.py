"""Tests for the news router's source-routing (auto/iinvest/moneycontrol/merged).

The new ``source`` query param controls which backend the company news
endpoint uses. Behavior:

  - source="iinvest"      → fetch from iinvest, tag source_used="iinvest"
  - source="moneycontrol" → fetch from MoneyControl (existing behavior)
  - source="merged"       → fetch from both, dedupe by URL
  - source="auto" (default)
      → iinvest first; if empty/error AND days>7 → fall back to MoneyControl
      → iinvest first; if empty/error AND days<=7 → still return empty
        (MoneyControl fallback only kicks in for deep history)
      → tag source_used with the actual source that delivered results
"""

from __future__ import annotations

import contextlib
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.models  # noqa: F401
import app.models.news  # noqa: F401
import app.models.stockuniverse  # noqa: F401

from app.database import Base, _set_sqlite_pragma


# ── In-memory DB ─────────────────────────────────────────────────────────────


@pytest.fixture
async def in_memory_db_session():
    import sqlalchemy as sa
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from app.models.stockuniverse import StockUniverse
    from app.models.news import NewsArticle

    eng = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )

    @sa.event.listens_for(eng.sync_engine, "connect")
    def _on_connect(dbapi_con, _):
        _set_sqlite_pragma(dbapi_con, _)

    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    Session = async_sessionmaker(eng, expire_on_commit=False)
    async with Session() as session:
        su = StockUniverse(
            symbol="RELIANCE",
            company_name="Reliance Industries",
            segment="EQ",
            industry="Refineries",
            industry_info={},
            ticker_failure_count=0,
            isin="INE002A01018",
        )
        session.add(su)

        # Two articles: one iinvest-sourced, one moneycontrol
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        session.add_all([
            NewsArticle(
                url="https://iinvest.example/1",
                source="iinvest:Cogencis",
                title="Reliance Q1 beats",
                text="body 1",
                publish_date=now,
                fetched_at=now,
                company_symbol="RELIANCE",
                iinvest_story_id="cog-1",
            ),
            NewsArticle(
                url="https://mc.example/1",
                source="moneycontrol_company",
                title="Reliance shares up",
                text="body 2",
                publish_date=now,
                fetched_at=now,
                company_symbol="RELIANCE",
            ),
        ])
        await session.commit()
        yield session
    await eng.dispose()


# ── Fake clients (module-level, pattern from test_iinvest_routes) ───────────


_fake_iinvest = MagicMock()
_fake_iinvest.get_news = AsyncMock(return_value={
    "status": True, "response": {"data": [
        {"id": "cog-1", "headline": "Reliance Q1", "sourceLink": "https://iinvest.example/1",
         "sourceName": "Cogencis", "sourceDateTime": "2026-06-17T10:00:00",
         "synopsis": "beat", "story": "body 1", "isins": ["INE002A01018"]},
    ]},
})


@contextlib.contextmanager
def _wire_iinvest():
    from app.services import iinvest_client as mod
    saved = mod.get_iinvest_client
    mod.get_iinvest_client = lambda: _fake_iinvest
    try:
        yield
    finally:
        mod.get_iinvest_client = saved


@pytest.fixture
async def no_iinvest_seed(in_memory_db_session):
    """Clear seeded iinvest articles so the iinvest-empty assertion holds."""
    from app.models.news import NewsArticle
    from sqlalchemy import delete as sa_delete
    await in_memory_db_session.execute(
        sa_delete(NewsArticle).where(NewsArticle.source.like("iinvest:%"))
    )
    await in_memory_db_session.commit()
    return in_memory_db_session


@pytest.fixture
def app(in_memory_db_session):
    """Build a fresh FastAPI app with the news router + in-memory DB."""
    from app.database import get_db

    async def _override_get_db():
        yield in_memory_db_session

    app = FastAPI()
    from app.routers.news import router as news_router
    app.include_router(news_router, prefix="/api")
    app.dependency_overrides[get_db] = _override_get_db
    return app


@pytest.fixture
def client(app):
    return TestClient(app)


# ── Tests ────────────────────────────────────────────────────────────────────


class TestNewsCompanySourceRouting:
    def test_default_source_is_auto(self, client):
        """No `source` param → behaves as auto (iinvest first, fallback as appropriate)."""
        with _wire_iinvest():
            resp = client.get("/api/news/company/RELIANCE?limit=10")
        assert resp.status_code == 200
        data = resp.json()
        # iinvest returned data → source_used should be "iinvest"
        assert data["source_used"] == "iinvest"

    def test_source_iinvest_explicit(self, client):
        with _wire_iinvest():
            resp = client.get("/api/news/company/RELIANCE?limit=10&source=iinvest")
        assert resp.status_code == 200
        data = resp.json()
        assert data["source_used"] == "iinvest"

    def test_source_moneycontrol_explicit(self, client):
        """source=moneycontrol should NOT call iinvest at all."""
        # MoneyControl's actual fetch is a network call. We just verify the
        # source_used is tagged correctly. The articles returned are from
        # our seeded DB.
        with _wire_iinvest():
            resp = client.get("/api/news/company/RELIANCE?limit=10&source=moneycontrol")
        assert resp.status_code == 200
        data = resp.json()
        assert data["source_used"] == "moneycontrol"

    def test_source_merged_returns_both(self, client):
        """source=merged → articles from both iinvest and MoneyControl, source_used='merged'."""
        with _wire_iinvest():
            resp = client.get("/api/news/company/RELIANCE?limit=10&source=merged")
        assert resp.status_code == 200
        data = resp.json()
        # Both articles should be present (one iinvest, one moneycontrol)
        assert data["source_used"] == "merged"
        sources = {a["source"] for a in data["articles"]}
        assert "iinvest:Cogencis" in sources
        assert "moneycontrol_company" in sources

    def test_auto_falls_back_when_iinvest_empty(self, client, no_iinvest_seed):
        """If iinvest returns 0 articles AND days>7, fall back to MoneyControl."""
        from app.services import iinvest_client as mod

        empty = MagicMock()
        empty.get_news = AsyncMock(return_value={"status": True, "response": {"data": []}})
        with patch.object(mod, "get_iinvest_client", return_value=empty):
            resp = client.get("/api/news/company/RELIANCE?days=30&limit=10")
        assert resp.status_code == 200
        data = resp.json()
        # days=30 > 7 → fall back to MoneyControl (which we seeded)
        assert data["source_used"] == "moneycontrol"
        assert data["total"] >= 1

    def test_auto_does_not_fall_back_for_recent_news(self, client, no_iinvest_seed):
        """If iinvest returns 0 articles AND days<=7, do NOT fall back (return empty)."""
        from app.services import iinvest_client as mod

        empty = MagicMock()
        empty.get_news = AsyncMock(return_value={"status": True, "response": {"data": []}})
        with patch.object(mod, "get_iinvest_client", return_value=empty):
            resp = client.get("/api/news/company/RELIANCE?days=3&limit=10")
        assert resp.status_code == 200
        data = resp.json()
        # days=3 <= 7 → do NOT fall back; iinvest is preferred for recent
        assert data["source_used"] == "iinvest"
        assert data["articles"] == []

    def test_invalid_source_returns_422(self, client):
        resp = client.get("/api/news/company/RELIANCE?source=garbage")
        assert resp.status_code == 422
