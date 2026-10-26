"""Tests for the market_local sync persistence strategy.

Background: market_local_sync used ``ON CONFLICT (symbol) DO UPDATE`` for
market_category_stocks, but DBs built through Alembic never got the
``uq_market_stock_symbol`` unique index (only a plain non-unique index), so
every sync cycle raised ``ON CONFLICT clause does not match any PRIMARY KEY
or UNIQUE constraint`` and the single commit rolled back both market tables
to zero rows (empty Analysis tab).

The fix persists with delete-then-insert per batch (no arbiter needed) and
commits categories independently of stocks. These tests pin that:

- the OLD upsert fails on a constraint-less table (exact live repro),
- the NEW delete-then-insert works with AND without the unique index,
- the convergence migration's pre-dedupe keeps the latest row per symbol.
"""
from __future__ import annotations

import importlib.util
import sys
from datetime import datetime
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy import delete, insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import create_async_engine

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _stocks_table(metadata: sa.MetaData, *, unique_symbol: bool) -> sa.Table:
    table = sa.Table(
        "market_category_stocks",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("company_name", sa.String(255), nullable=False),
        sa.Column("last_updated", sa.DateTime(), nullable=False),
    )
    if unique_symbol:
        sa.UniqueConstraint(table.c.symbol, name="uq_market_stock_symbol")
    else:
        sa.Index("ix_market_category_stocks_symbol", table.c.symbol)
    return table


def _row(symbol: str, name: str, ts: datetime) -> dict:
    return {"symbol": symbol, "company_name": name, "last_updated": ts}


async def _replace_batch(conn, table: sa.Table, vals: list[dict]) -> None:
    """Mirror of the delete-then-insert-per-batch strategy in market_local.py."""
    await conn.execute(
        delete(table).where(table.c.symbol.in_([v["symbol"] for v in vals]))
    )
    await conn.execute(insert(table).values(vals))
    await conn.commit()


@pytest.fixture()
def anyio_backend():
    return "asyncio"


class TestOldUpsertRepro:
    async def test_on_conflict_symbol_fails_without_unique_index(self):
        """Exact reproduction of the live failure on old Alembic-built DBs."""
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        metadata = sa.MetaData()
        table = _stocks_table(metadata, unique_symbol=False)
        async with engine.begin() as conn:
            await conn.run_sync(metadata.create_all)
            stmt = sqlite_insert(table).values(
                [_row("RELIANCE", "Reliance", datetime(2026, 9, 21))]
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["symbol"],
                set_={"company_name": stmt.excluded.company_name},
            )
            with pytest.raises(OperationalError, match="ON CONFLICT"):
                await conn.execute(stmt)
        await engine.dispose()

    async def test_on_conflict_symbol_works_with_unique_index(self):
        """Control case: the old upsert is fine once the index exists."""
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        metadata = sa.MetaData()
        table = _stocks_table(metadata, unique_symbol=True)
        async with engine.begin() as conn:
            await conn.run_sync(metadata.create_all)
            stmt = sqlite_insert(table).values(
                [_row("RELIANCE", "Reliance", datetime(2026, 9, 21))]
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["symbol"],
                set_={"company_name": stmt.excluded.company_name},
            )
            await conn.execute(stmt)
            count = await conn.scalar(sa.select(sa.func.count()).select_from(table))
            assert count == 1
        await engine.dispose()


class TestDeleteThenInsert:
    @pytest.mark.parametrize("unique_symbol", [False, True])
    async def test_replace_is_idempotent_without_arbiter(self, unique_symbol: bool):
        """The new strategy works with AND without the unique index."""
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        metadata = sa.MetaData()
        table = _stocks_table(metadata, unique_symbol=unique_symbol)
        async with engine.begin() as conn:
            await conn.run_sync(metadata.create_all)
        async with engine.connect() as conn:
            batch1 = [
                _row("RELIANCE", "Reliance", datetime(2026, 9, 21)),
                _row("TCS", "TCS", datetime(2026, 9, 21)),
            ]
            await _replace_batch(conn, table, batch1)
            # Second cycle with an updated name: no dupes, values converge.
            batch2 = [
                _row("RELIANCE", "Reliance Industries", datetime(2026, 9, 22)),
                _row("TCS", "TCS", datetime(2026, 9, 22)),
            ]
            await _replace_batch(conn, table, batch2)
            count = await conn.scalar(sa.select(sa.func.count()).select_from(table))
            assert count == 2
            name = await conn.scalar(
                sa.select(table.c.company_name).where(table.c.symbol == "RELIANCE")
            )
            assert name == "Reliance Industries"
        await engine.dispose()


def _categories_table(metadata: sa.MetaData) -> sa.Table:
    """Live shape: composite PK, no separate unique constraint."""
    return sa.Table(
        "market_categories",
        metadata,
        sa.Column("category_type", sa.String(32), primary_key=True),
        sa.Column("slug", sa.String(128), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("last_updated", sa.DateTime(), nullable=False),
    )


class TestIntraBatchCollisions:
    async def test_plain_insert_rejects_slug_collision(self):
        """Distinct raw names can slug-collide; plain INSERT then fails."""
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        metadata = sa.MetaData()
        table = _categories_table(metadata)
        async with engine.begin() as conn:
            await conn.run_sync(metadata.create_all)
            vals = [
                {"category_type": "industry", "slug": "bank-private",
                 "name": "Bank - Private", "last_updated": datetime(2026, 9, 22)},
                {"category_type": "industry", "slug": "bank-private",
                 "name": "Bank Private", "last_updated": datetime(2026, 9, 22)},
            ]
            with pytest.raises(IntegrityError, match="UNIQUE constraint failed"):
                await conn.execute(insert(table).values(vals))
        await engine.dispose()

    async def test_keyed_dedupe_last_wins(self):
        """The persistence strategy (keyed dict, last wins) absorbs it."""
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        metadata = sa.MetaData()
        table = _categories_table(metadata)
        async with engine.begin() as conn:
            await conn.run_sync(metadata.create_all)
        async with engine.connect() as conn:
            vals = [
                {"category_type": "industry", "slug": "bank-private",
                 "name": "Bank - Private", "last_updated": datetime(2026, 9, 22)},
                {"category_type": "industry", "slug": "bank-private",
                 "name": "Bank Private", "last_updated": datetime(2026, 9, 22)},
                {"category_type": "sector", "slug": "banks",
                 "name": "Banks", "last_updated": datetime(2026, 9, 22)},
            ]
            deduped: dict = {}
            for v in vals:
                deduped[(v["category_type"], v["slug"])] = v
            await conn.execute(delete(table))
            await conn.execute(insert(table).values(list(deduped.values())))
            await conn.commit()
            count = await conn.scalar(sa.select(sa.func.count()).select_from(table))
            assert count == 2
            name = await conn.scalar(
                sa.select(table.c.name).where(
                    (table.c.category_type == "industry")
                    & (table.c.slug == "bank-private")
                )
            )
            assert name == "Bank Private"
        await engine.dispose()


def _load_migration_dedupe_sql() -> str:
    path = (
        ROOT / "alembic" / "versions" / "f44444444444_add_uq_market_stock_symbol.py"
    )
    assert path.exists(), f"migration not found at {path}"
    spec = importlib.util.spec_from_file_location("uq_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._DEDUPE_SQL


class TestMigrationDedupe:
    async def test_dedupe_keeps_latest_per_symbol(self):
        import sqlite3

        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE market_category_stocks ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, symbol VARCHAR(32) NOT NULL, "
            "company_name VARCHAR(255) NOT NULL, last_updated DATETIME NOT NULL)"
        )
        conn.executemany(
            "INSERT INTO market_category_stocks (symbol, company_name, last_updated)"
            " VALUES (?, ?, ?)",
            [
                ("RELIANCE", "old", "2026-09-20 00:00:00"),
                ("RELIANCE", "new", "2026-09-22 00:00:00"),
                ("RELIANCE", "mid", "2026-09-21 00:00:00"),
                ("TCS", "only", "2026-09-21 00:00:00"),
            ],
        )
        conn.executescript(_load_migration_dedupe_sql())
        rows = conn.execute(
            "SELECT symbol, company_name FROM market_category_stocks ORDER BY symbol"
        ).fetchall()
        assert rows == [("RELIANCE", "new"), ("TCS", "only")]
        conn.close()


class TestCapWeightedReturn:
    def test_two_unequal_cap_members(self):
        from app.services.data_sync.market_local import _cap_weighted_return

        r_a, mcap_a = 5.0, 100.0
        r_b, mcap_b = 15.0, 300.0
        pairs = [(r_a, mcap_a), (r_b, mcap_b)]
        res = _cap_weighted_return(pairs)
        expected = (mcap_a * r_a + mcap_b * r_b) / (mcap_a + mcap_b)
        plain_mean = (r_a + r_b) / 2.0

        assert res == pytest.approx(expected)
        assert res != pytest.approx(plain_mean)

    def test_one_member_with_none_return(self):
        from app.services.data_sync.market_local import _cap_weighted_return

        pairs = [(None, 500.0), (10.0, 200.0), (20.0, 300.0)]
        res = _cap_weighted_return(pairs)
        expected = (200.0 * 10.0 + 300.0 * 20.0) / (200.0 + 300.0)
        assert res == pytest.approx(expected)

    def test_all_returns_none(self):
        from app.services.data_sync.market_local import _cap_weighted_return

        pairs = [(None, 100.0), (None, None), (None, 0.0)]
        res = _cap_weighted_return(pairs)
        assert res is None

    def test_scores_present_but_every_market_cap_missing_or_zero(self):
        from app.services.data_sync.market_local import _cap_weighted_return

        pairs = [(4.0, None), (6.0, 0.0), (8.0, -10.0)]
        res = _cap_weighted_return(pairs)
        expected_equal_weight = (4.0 + 6.0 + 8.0) / 3.0
        assert res == pytest.approx(expected_equal_weight)

    def test_category_horizons_including_1d(self):
        from app.services.data_sync.market_local import _cap_weighted_return

        mcap_a, mcap_b = 100.0, 300.0
        pairs_1d = [(2.0, mcap_a), (4.0, mcap_b)]
        pairs_1w = [(5.0, mcap_a), (15.0, mcap_b)]
        pairs_1m = [(10.0, mcap_a), (20.0, mcap_b)]
        pairs_6m = [(20.0, mcap_a), (30.0, mcap_b)]

        assert _cap_weighted_return(pairs_1d) == pytest.approx(
            (mcap_a * 2.0 + mcap_b * 4.0) / (mcap_a + mcap_b)
        )
        assert _cap_weighted_return(pairs_1w) == pytest.approx(
            (mcap_a * 5.0 + mcap_b * 15.0) / (mcap_a + mcap_b)
        )
        assert _cap_weighted_return(pairs_1m) == pytest.approx(
            (mcap_a * 10.0 + mcap_b * 20.0) / (mcap_a + mcap_b)
        )
        assert _cap_weighted_return(pairs_6m) == pytest.approx(
            (mcap_a * 20.0 + mcap_b * 30.0) / (mcap_a + mcap_b)
        )

    def test_category_member_with_no_1d_change_returns_none(self):
        from app.services.data_sync.market_local import _cap_weighted_return

        pairs_1d = [(None, 500.0)]
        res = _cap_weighted_return(pairs_1d)
        assert res is None
        assert res != 0


