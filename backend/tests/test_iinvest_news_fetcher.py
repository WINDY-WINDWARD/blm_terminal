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

    @pytest.mark.asyncio
    async def test_same_story_for_multiple_symbols_does_not_violate_pk(self, in_memory_db_session):
        """iinvest returns the same story (same URL, same story_id) for several
        unrelated companies. The first symbol writes the row; the second must
        update the row's metadata without raising
        ``UNIQUE constraint failed: news_articles.url``.

        Regression for the runtime warning:
            get_company_news: iinvest fetch failed for WABAG: UNIQUE
            constraint failed: news_articles.url
        which surfaced when the upsert target was ``iinvest_story_id`` and a
        prior MoneyControl global crawl had already claimed the URL.
        """
        from app.services.news_fetcher import fetch_iinvest_company_news
        from app.services import iinvest_client as mod
        from sqlalchemy import select

        SHARED_URL = "https://www.moneycontrol.com/news/business/markets/jio-ipo-13955446.html"
        SHARED_STORY_ID = "Tzn_7Z4BulMo73FspGcq"

        # Two different iinvest payloads that BOTH reference the same URL/story
        payload = lambda sym, isin: {
            "status": True,
            "response": {
                "pagingInfo": {"pageNo": 1, "pageSize": 50, "total": 1},
                "data": [
                    {
                        "id": SHARED_STORY_ID,
                        "headline": "Jio IPO brings Reliance closer to value unlocking",
                        "synopsis": "Brokerages peg valuation at up to $128B",
                        "story": "<p>Full body</p>",
                        "sourceLink": SHARED_URL,
                        "sourceName": "cogencis",
                        "sourceDateTime": "2026-06-22T11:59:05",
                        "isins": [isin],
                        "categories": [],
                    },
                ],
            },
        }

        fake = MagicMock()
        with patch.object(mod, "get_iinvest_client", return_value=fake):
            # Stub the iinvest path resolver for both symbols (they aren't
            # seeded in stock_universe and we don't want to hit NSE).
            async def _resolve(symbol, db=None):
                return {
                    "KIRLOSBROS": ("INE732A01036", "ine732a01036/symbol/ns/kirlosbros/kirlosbros"),
                    "WABAG": ("INE956G01038", "ine956g01038/symbol/ns/wabag/wabag"),
                }[symbol]
            fake.resolve_path = AsyncMock(side_effect=_resolve)

            # Symbol 1 — gets the row created
            fake.get_news = AsyncMock(return_value=payload("KIRLOSBROS", "INE732A01036"))
            await fetch_iinvest_company_news(
                symbol="KIRLOSBROS", db=in_memory_db_session, days=30, limit=50,
            )

            # Symbol 2 — same story_id and same URL but different ISIN.
            # Must NOT raise IntegrityError.
            fake.get_news = AsyncMock(return_value=payload("WABAG", "INE956G01038"))
            await fetch_iinvest_company_news(
                symbol="WABAG", db=in_memory_db_session, days=30, limit=50,
            )

        # Exactly one row should exist (same URL → one PK).
        # Force a fresh read — expire_on_commit=False + the in-memory
        # identity map would otherwise hand back the pre-update row.
        in_memory_db_session.expire_all()
        stmt = select(NewsArticle).where(NewsArticle.url == SHARED_URL)
        result = await in_memory_db_session.execute(stmt)
        rows = list(result.scalars())
        assert len(rows) == 1, f"expected 1 row, got {len(rows)}"

        # The first symbol to write the row owns the company_symbol tag —
        # the second must NOT clobber it.
        row = rows[0]
        assert row.company_symbol == "KIRLOSBROS"
        assert row.iinvest_story_id == SHARED_STORY_ID

    @pytest.mark.asyncio
    async def test_upsert_after_moneycontrol_row_with_same_url(self, in_memory_db_session):
        """If a row with the same URL was already written by a MoneyControl
        global crawl (with ``iinvest_story_id IS NULL``), the iinvest
        upsert-by-iinvest_story_id path used to raise IntegrityError. The
        fix upserts by ``url`` and tolerates the existing row.
        """
        from app.services.news_fetcher import fetch_iinvest_company_news
        from app.services import iinvest_client as mod
        from sqlalchemy import select

        SHARED_URL = "https://www.moneycontrol.com/news/business/markets/reliance-q1-12345678.html"
        SHARED_STORY_ID = "rel-q1-story-001"

        # Pre-seed: a MoneyControl global crawl row for the same URL.
        existing = NewsArticle(
            url=SHARED_URL,
            source="moneycontrol_global",
            title="Old MoneyControl title",
            text="Old body",
            fetched_at=datetime(2026, 6, 21, 0, 0, 0),
            company_symbol=None,
        )
        in_memory_db_session.add(existing)
        await in_memory_db_session.commit()

        iinvest_payload = {
            "status": True,
            "response": {
                "pagingInfo": {"pageNo": 1, "pageSize": 50, "total": 1},
                "data": [
                    {
                        "id": SHARED_STORY_ID,
                        "headline": "Reliance Q1 jumps 12%",
                        "synopsis": "Beats estimates",
                        "story": "<p>Fresh body</p>",
                        "sourceLink": SHARED_URL,
                        "sourceName": "cogencis",
                        "sourceDateTime": "2026-06-22T10:00:00",
                        "isins": ["INE002A01018"],
                        "categories": [],
                    },
                ],
            },
        }

        fake = MagicMock()
        fake.get_news = AsyncMock(return_value=iinvest_payload)
        with patch.object(mod, "get_iinvest_client", return_value=fake):
            # Must NOT raise IntegrityError.
            await fetch_iinvest_company_news(
                symbol="RELIANCE", db=in_memory_db_session, days=30, limit=50,
            )

        # Still one row, now tagged with the iinvest symbol and story_id.
        # Force a fresh read — expire_on_commit=False + the in-memory
        # identity map would otherwise hand back the pre-update row.
        in_memory_db_session.expire_all()
        stmt = select(NewsArticle).where(NewsArticle.url == SHARED_URL)
        result = await in_memory_db_session.execute(stmt)
        rows = list(result.scalars())
        assert len(rows) == 1
        assert rows[0].source == "iinvest:cogencis"
        assert rows[0].iinvest_story_id == SHARED_STORY_ID
        assert rows[0].company_symbol == "RELIANCE"
