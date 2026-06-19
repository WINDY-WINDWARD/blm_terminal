"""Tests for fetch_iinvest_company_news — the iinvest → news_articles pipeline.

Covers the behavior the news router actually depends on:
  - The iinvest news payload (no sentiment/threat) is normalized with NLP
    via nlp_service.analyze_article_dict after fetch.
  - Stories are upserted by iinvest_story_id (unique constraint).
  - Re-fetching the same story updates the row (not creates a new one).
  - If the symbol has no ISIN cached, returns 0 (no error).
  - If the iinvest client raises, returns 0 (no crash).
  - The source prefix is "iinvest:<sourceName>" so the global news filter
    can distinguish iinvest articles from RSS/MoneyControl ones.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import Base, _set_sqlite_pragma
from app.models.news import NewsArticle
from app.models.stockuniverse import StockUniverse


# ── In-memory DB fixture ──────────────────────────────────────────────────────


@pytest.fixture
async def in_memory_db_session():
    """An in-memory SQLite AsyncSession with the news + stock_universe schema."""
    import app.models  # noqa: F401
    import app.models.news  # noqa: F401
    import app.models.stockuniverse  # noqa: F401
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    eng = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )

    # Apply the SQLite PRAGMA (foreign_keys=ON, etc.)
    @sa.event.listens_for(eng.sync_engine, "connect")
    def _on_connect(dbapi_con, _):
        _set_sqlite_pragma(dbapi_con, _)

    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    Session = async_sessionmaker(eng, expire_on_commit=False)
    async with Session() as session:
        # Seed: a stock_universe row with an ISIN so the news fetch has a key
        su = StockUniverse(
            symbol="RELIANCE",
            company_name="Reliance Industries Limited",
            segment="EQ",
            industry="Refineries",
            industry_info={},
            ticker_failure_count=0,
            isin="INE002A01018",
        )
        session.add(su)
        await session.commit()
        yield session
    await eng.dispose()


# ── Helpers ──────────────────────────────────────────────────────────────────


IINVEST_NEWS_RESPONSE = {
    "status": True,
    "response": {
        "pagingInfo": {"pageNo": 1, "pageSize": 50, "total": 2},
        "columns": [],
        "data": [
            {
                "id": "cog-12345",
                "headline": "Reliance Q1 profit jumps 12%",
                "synopsis": "Reliance Industries beat estimates",
                "story": "<p>Full HTML body of the story...</p>",
                "sourceLink": "https://cogencis.com/news/12345",
                "sourceName": "Cogencis",
                "sourceDateTime": "2026-06-17T10:00:00",
                "isins": ["INE002A01018"],
                "categories": ["results"],
                "thumbNailImage": "https://example.com/img.jpg",
            },
            {
                "id": "cog-67890",
                "headline": "Reliance announces new capex",
                "synopsis": "Reliance Industries plans $5B capex",
                "story": "<p>Another full HTML body</p>",
                "sourceLink": "https://cogencis.com/news/67890",
                "sourceName": "Cogencis",
                "sourceDateTime": "2026-06-16T15:00:00",
                "isins": ["INE002A01018"],
                "categories": [],
            },
        ],
    },
}


# ── Tests ────────────────────────────────────────────────────────────────────


class TestFetchIinvestCompanyNews:
    @pytest.mark.asyncio
    async def test_returns_zero_when_no_isin_and_unresolvable(self, in_memory_db_session):
        """Symbol with no cached ISIN AND no path resolution → 0 articles, no error."""
        from app.services.news_fetcher import fetch_iinvest_company_news
        from app.services import iinvest_client as mod

        # iinvest client can't resolve the path (returns None for both)
        fake = MagicMock()
        fake.resolve_path = AsyncMock(return_value=(None, None))
        with patch.object(mod, "get_iinvest_client", return_value=fake):
            count = await fetch_iinvest_company_news(
                symbol="NEWSTOCK", db=in_memory_db_session, days=30, limit=50,
            )
        assert count == 0

    @pytest.mark.asyncio
    async def test_resolves_isin_on_demand_when_missing_from_db(self, in_memory_db_session):
        """When stock_universe has no ISIN, fetch_iinvest_company_news should
        fall back to the iinvest client's path resolver (which uses NSE
        GetQuoteApi as tier 3) to get the ISIN on demand. This is the fix for
        symbols whose stock_universe row was never enriched with an ISIN.
        """
        from app.services.news_fetcher import fetch_iinvest_company_news
        from app.services import iinvest_client as mod

        fake = MagicMock()
        fake.resolve_path = AsyncMock(return_value=("INE002A01018", "ine002a01018/symbol/ns/reliance/reliance"))
        fake.get_news = AsyncMock(return_value=IINVEST_NEWS_RESPONSE)
        with patch.object(mod, "get_iinvest_client", return_value=fake):
            # Use a symbol that's NOT in the seeded stock_universe
            count = await fetch_iinvest_company_news(
                symbol="UNENRICHED", db=in_memory_db_session, days=30, limit=50,
            )
        assert count == 2
        # resolve_path was called as the fallback
        fake.resolve_path.assert_awaited()
        fake.get_news.assert_awaited()

    @pytest.mark.asyncio
    async def test_returns_zero_when_iinvest_unavailable(self, in_memory_db_session):
        """If iinvest raises, function returns 0 (does not crash)."""
        from app.services.news_fetcher import fetch_iinvest_company_news
        from app.services import iinvest_client as mod

        # Mock the singleton's get_news to raise
        fake = MagicMock()
        fake.resolve_path = AsyncMock(return_value=("INE002A01018", "ine002a01018/symbol/ns/reliance/reliance"))
        fake.get_news = AsyncMock(side_effect=RuntimeError("iinvest down"))
        with patch.object(mod, "get_iinvest_client", return_value=fake):
            count = await fetch_iinvest_company_news(
                symbol="RELIANCE", db=in_memory_db_session, days=30, limit=50,
            )
        assert count == 0

    @pytest.mark.asyncio
    async def test_fetches_and_normalizes_articles(self, in_memory_db_session):
        """Articles are stored with NLP fields populated, source prefix, and iinvest_story_id."""
        from app.services.news_fetcher import fetch_iinvest_company_news
        from app.services import iinvest_client as mod

        fake = MagicMock()
        fake.get_news = AsyncMock(return_value=IINVEST_NEWS_RESPONSE)
        with patch.object(mod, "get_iinvest_client", return_value=fake):
            count = await fetch_iinvest_company_news(
                symbol="RELIANCE", db=in_memory_db_session, days=30, limit=50,
            )

        assert count == 2

        # Verify the articles were stored
        from sqlalchemy import select
        stmt = select(NewsArticle).where(NewsArticle.company_symbol == "RELIANCE")
        result = await in_memory_db_session.execute(stmt)
        rows = list(result.scalars())
        assert len(rows) == 2

        first = next(r for r in rows if r.iinvest_story_id == "cog-12345")
        # Headline + body from the iinvest payload
        assert first.title == "Reliance Q1 profit jumps 12%"
        assert first.text is not None and "Full HTML body" in first.text
        # NLP fields populated by nlp_service
        assert first.sentiment in ("BULLISH", "BEARISH", "NEUTRAL")
        assert first.threat_level in ("CRITICAL", "HIGH", "MEDIUM", "LOW")
        assert first.language == "en"
        # Source prefix lets news/all filter distinguish iinvest from RSS
        assert first.source == "iinvest:Cogencis"
        # ISIN is propagated into the entities JSON
        assert "INE002A01018" in str(first.entities)

    @pytest.mark.asyncio
    async def test_upsert_dedupes_by_iinvest_story_id(self, in_memory_db_session):
        """Re-fetching the same story updates the row (no duplicate)."""
        from app.services.news_fetcher import fetch_iinvest_company_news
        from app.services import iinvest_client as mod
        from sqlalchemy import select, func

        fake = MagicMock()
        fake.get_news = AsyncMock(return_value=IINVEST_NEWS_RESPONSE)
        with patch.object(mod, "get_iinvest_client", return_value=fake):
            await fetch_iinvest_company_news(
                symbol="RELIANCE", db=in_memory_db_session, days=30, limit=50,
            )
            # Second fetch — same stories
            await fetch_iinvest_company_news(
                symbol="RELIANCE", db=in_memory_db_session, days=30, limit=50,
            )

        # Should still be 2 rows (upsert, not insert)
        stmt = select(func.count()).select_from(NewsArticle).where(
            NewsArticle.company_symbol == "RELIANCE"
        )
        result = await in_memory_db_session.execute(stmt)
        assert result.scalar() == 2

    @pytest.mark.asyncio
    async def test_handles_empty_news_response(self, in_memory_db_session):
        """Empty iinvest response → 0 articles, no error."""
        from app.services.news_fetcher import fetch_iinvest_company_news
        from app.services import iinvest_client as mod

        empty = {"status": True, "response": {"data": []}}
        fake = MagicMock()
        fake.get_news = AsyncMock(return_value=empty)
        with patch.object(mod, "get_iinvest_client", return_value=fake):
            count = await fetch_iinvest_company_news(
                symbol="RELIANCE", db=in_memory_db_session, days=30, limit=50,
            )
        assert count == 0
