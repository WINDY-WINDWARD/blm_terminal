"""Tests for audit B.8 — extract ``paginate()`` helper for news endpoints.

``routers/news.py`` had 4 near-identical pagination blocks (count stmt
+ page stmt + ``has_more=(offset+limit) < total``).  The audit asks for a
single ``paginate()`` helper.  This test verifies both the helper
itself and the call sites.
"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any

import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table, select, text
from sqlalchemy.ext.asyncio import create_async_engine

from app.services.pagination import paginate


# ---------------------------------------------------------------------------
# Fixture: fresh in-memory async DB per test
# ---------------------------------------------------------------------------

@pytest.fixture
async def async_db():
    """Yield an ``AsyncSession`` bound to a fresh in-memory aiosqlite DB.

    A ``Base.metadata.create_all`` from a one-off MetaData (not the
    global app Base, which contains news_articles indexes that
    conflict on re-create).
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    md = MetaData()
    items = Table(
        "items", md,
        Column("id", Integer, primary_key=True),
        Column("name", String),
    )

    async with engine.begin() as conn:
        await conn.run_sync(md.create_all)

    from sqlalchemy.ext.asyncio import async_sessionmaker
    Session = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with Session() as session:
        yield session, items

    await engine.dispose()


# ---------------------------------------------------------------------------
# Helper smoke tests
# ---------------------------------------------------------------------------

class TestPaginateHelper:
    """The helper must return ``(total, items, has_more)`` matching the
    inline implementation's behaviour."""

    @pytest.mark.asyncio
    async def test_returns_total_zero_for_empty_table(self, async_db) -> None:
        session, items = async_db
        count_stmt = select(text("count(*)")).select_from(items)
        page_stmt = select(items).order_by(items.c.id).limit(10).offset(0)
        total, rows, has_more = await paginate(
            session, count_stmt, page_stmt, offset=0, limit=10
        )
        assert total == 0
        assert rows == []
        assert has_more is False

    @pytest.mark.asyncio
    async def test_has_more_false_when_last_page(self, async_db) -> None:
        """has_more is False when offset+limit >= total."""
        session, items = async_db
        for i in range(5):
            await session.execute(
                items.insert().values(id=i, name=f"item-{i}")
            )
        await session.commit()

        total, rows, has_more = await paginate(
            session,
            select(text("count(*)")).select_from(items),
            select(items).order_by(items.c.id).limit(10).offset(0),
            offset=0, limit=10,
        )
        assert total == 5
        assert len(rows) == 5
        assert has_more is False  # 0+10=10 >= 5

    @pytest.mark.asyncio
    async def test_has_more_true_when_more_pages(self, async_db) -> None:
        session, items = async_db
        for i in range(15):
            await session.execute(
                items.insert().values(id=i, name=f"item-{i}")
            )
        await session.commit()

        total, rows, has_more = await paginate(
            session,
            select(text("count(*)")).select_from(items),
            select(items).order_by(items.c.id).limit(5).offset(0),
            offset=0, limit=5,
        )
        assert total == 15
        assert len(rows) == 5
        assert has_more is True  # 0+5=5 < 15

    @pytest.mark.asyncio
    async def test_has_more_false_on_exact_boundary(self, async_db) -> None:
        """Edge case: offset+limit == total → has_more is False."""
        session, items = async_db
        for i in range(10):
            await session.execute(
                items.insert().values(id=i, name=f"item-{i}")
            )
        await session.commit()

        total, rows, has_more = await paginate(
            session,
            select(text("count(*)")).select_from(items),
            select(items).order_by(items.c.id).limit(5).offset(5),
            offset=5, limit=5,
        )
        assert total == 10
        assert len(rows) == 5
        assert has_more is False  # 5+5=10, not strictly less


# ---------------------------------------------------------------------------
# Call sites
# ---------------------------------------------------------------------------

class TestNewsRouterUsesPaginate:
    """The 4 pagination call sites in routers/news.py must delegate."""

    def test_news_router_imports_paginate(self) -> None:
        from app.routers import news
        assert hasattr(news, "paginate"), (
            "routers/news.py does not import paginate — B.8 refactor incomplete"
        )

    def test_news_router_has_no_inline_has_more(self) -> None:
        """The duplicated ``has_more=(offset + limit) < total`` must be
        gone from routers/news.py (consolidated into the helper)."""
        from app.routers import news
        source = inspect.getsource(news)
        # We use a simple substring search; "has_more" may appear in
        # NewsPaginatedOut references but the inline ``(offset + limit)
        # < total`` should be gone.
        assert "(offset + limit) < total" not in source, (
            "routers/news.py still has inline 'has_more=(offset+limit)<total' — "
            "consolidate into paginate()"
        )
        assert total == 0
        assert items == []
        assert has_more is False

    @pytest.mark.asyncio
    async def test_has_more_false_when_last_page(
        self, in_memory_db: AsyncSession
    ) -> None:
        """has_more is False when offset+limit >= total."""
        from sqlalchemy import text

        # Build a real table with 5 rows
        await in_memory_db.execute(text(
            "CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT)"
        ))
        for i in range(5):
            await in_memory_db.execute(
                text("INSERT INTO items (id, name) VALUES (:i, :n)"),
                {"i": i, "n": f"item-{i}"},
            )
        await in_memory_db.commit()

        from sqlalchemy import MetaData, Table, Column, Integer, String
        md = MetaData()
        items_table = Table(
            "items", md,
            Column("id", Integer, primary_key=True),
            Column("name", String),
        )

        total, rows, has_more = await paginate(
            in_memory_db,
            select(text("count(*)")).select_from(items_table),
            select(items_table).order_by(items_table.c.id).limit(10).offset(0),
            offset=0, limit=10,
        )
        assert total == 5
        assert len(rows) == 5
        assert has_more is False  # 0+10=10 >= 5

    @pytest.mark.asyncio
    async def test_has_more_true_when_more_pages(
        self, in_memory_db: AsyncSession
    ) -> None:
        from sqlalchemy import text, MetaData, Table, Column, Integer, String

        await in_memory_db.execute(text(
            "CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT)"
        ))
        for i in range(15):
            await in_memory_db.execute(
                text("INSERT INTO items (id, name) VALUES (:i, :n)"),
                {"i": i, "n": f"item-{i}"},
            )
        await in_memory_db.commit()

        md = MetaData()
        items_table = Table(
            "items", md,
            Column("id", Integer, primary_key=True),
            Column("name", String),
        )

        total, rows, has_more = await paginate(
            in_memory_db,
            select(text("count(*)")).select_from(items_table),
            select(items_table).order_by(items_table.c.id).limit(5).offset(0),
            offset=0, limit=5,
        )
        assert total == 15
        assert len(rows) == 5
        assert has_more is True  # 0+5=5 < 15

    @pytest.mark.asyncio
    async def test_has_more_false_on_exact_boundary(
        self, in_memory_db: AsyncSession
    ) -> None:
        """Edge case: offset+limit == total → has_more is False."""
        from sqlalchemy import text, MetaData, Table, Column, Integer, String

        await in_memory_db.execute(text(
            "CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT)"
        ))
        for i in range(10):
            await in_memory_db.execute(
                text("INSERT INTO items (id, name) VALUES (:i, :n)"),
                {"i": i, "n": f"item-{i}"},
            )
        await in_memory_db.commit()

        md = MetaData()
        items_table = Table(
            "items", md,
            Column("id", Integer, primary_key=True),
            Column("name", String),
        )

        total, rows, has_more = await paginate(
            in_memory_db,
            select(text("count(*)")).select_from(items_table),
            select(items_table).order_by(items_table.c.id).limit(5).offset(5),
            offset=5, limit=5,
        )
        assert total == 10
        assert len(rows) == 5
        assert has_more is False  # 5+5=10, not strictly less


# ---------------------------------------------------------------------------
# Call sites
# ---------------------------------------------------------------------------

class TestNewsRouterUsesPaginate:
    """The 4 pagination call sites in routers/news.py must delegate."""

    def test_news_router_imports_paginate(self) -> None:
        from app.routers import news
        assert hasattr(news, "paginate"), (
            "routers/news.py does not import paginate — B.8 refactor incomplete"
        )

    def test_news_router_has_no_inline_has_more(self) -> None:
        """The duplicated ``has_more=(offset + limit) < total`` must be
        gone from routers/news.py (consolidated into the helper)."""
        from app.routers import news
        source = inspect.getsource(news)
        # Allow the helper's own definition (if any).  Look for the
        # pattern in router code, which should now be 0 occurrences.
        # We use a simple substring search; "has_more" may appear in
        # NewsPaginatedOut references but the inline ``(offset + limit)
        # < total`` should be gone.
        assert "(offset + limit) < total" not in source, (
            "routers/news.py still has inline 'has_more=(offset+limit)<total' — "
            "consolidate into paginate()"
        )


class TestPaginatePrecomputedTotal:
    """Regression test for the post-B.8 double-count bug.

    ``get_company_news`` runs the count statement for its 404 check,
    then ``paginate()`` ran the same count statement again.  The fix
    is the ``precomputed_total`` kwarg on :func:`paginate`.
    """

    @pytest.mark.asyncio
    async def test_skips_count_when_precomputed_total_given(self):
        from app.services.pagination import paginate

        count_stmt_calls: list = []
        page_stmt_calls: list = []

        class FakeScalars:
            def all(inner_self):
                return []

        class FakeResult:
            def scalars(inner_self):
                return FakeScalars()

        class FakeSession:
            async def scalar(inner_self, stmt):
                count_stmt_calls.append(stmt)
                return 5

            async def execute(inner_self, stmt):
                page_stmt_calls.append(stmt)
                return FakeResult()

        db = FakeSession()
        total, items, has_more = await paginate(
            db, count_stmt="ignored", page_stmt="page",
            offset=0, limit=10, precomputed_total=5,
        )
        assert total == 5
        assert items == []
        assert has_more is False
        assert count_stmt_calls == [], (
            "count query was run even though precomputed_total was given"
        )
        assert page_stmt_calls == ["page"]

    @pytest.mark.asyncio
    async def test_runs_count_when_no_precomputed_total(self):
        from app.services.pagination import paginate

        count_stmt_calls: list = []

        class FakeSession:
            async def scalar(inner_self, stmt):
                count_stmt_calls.append(stmt)
                return 3

            async def execute(inner_self, stmt):
                class R:
                    def scalars(self_):
                        class S:
                            def all(inner):
                                return []
                        return S()
                return R()

        db = FakeSession()
        await paginate(
            db, count_stmt="count", page_stmt="page",
            offset=0, limit=10,
        )
        assert count_stmt_calls == ["count"], (
            "count query was NOT run when precomputed_total was None"
        )
