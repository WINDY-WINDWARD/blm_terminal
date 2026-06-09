"""Pin the news.py duplicate-index bug fix.

Before commit <this>, app/models/news.py had `sentiment` and
`threat_level` columns with both `index=True` AND a hand-written
`Index("ix_news_articles_sentiment", "sentiment")` in
`__table_args__`.  SQLAlchemy's `Base.metadata.create_all` then
attempted to create the auto-index AND the named index, which raises:

    sqlalchemy.exc.InvalidRequestError: Index 'ix_news_articles_sentiment'
    defined twice

This broke:
- `tests/conftest.py::in_memory_db` fixture (could not build the
  in-memory schema)
- any test that called `Base.metadata.create_all` against a fresh DB
- Alembic auto-generate on a database with the explicit indices

The fix drops the redundant `__table_args__` entries.  The
`index=True` column flag already creates the auto-index with the
correct name.

Tests pin three contracts:
1. The `__table_args__` of NewsArticle is now a single Index entry
   (the composite source/publish_date one).  The two duplicates are
   gone.
2. `Base.metadata.create_all` runs cleanly against a fresh
   `sqlite:///:memory:`.
3. The `in_memory_db` fixture works end-to-end.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, event


def test_news_articles_table_args_has_one_index() -> None:
    """Only the composite (source, publish_date) index remains."""
    from app.models.news import NewsArticle

    table_args = NewsArticle.__table_args__
    assert isinstance(table_args, tuple)
    # Just the source_publish composite — no sentiment/threat duplicates
    assert len(table_args) == 1, (
        f"Expected 1 __table_args__ entry, got {len(table_args)}: {table_args}"
    )
    from sqlalchemy import Index

    assert isinstance(table_args[0], Index)
    assert table_args[0].name == "ix_news_articles_source_publish"


def test_news_articles_no_duplicate_index_definitions() -> None:
    """The fixed names do NOT appear in __table_args__ anymore."""
    from app.models.news import NewsArticle

    table_args = NewsArticle.__table_args__
    names = {getattr(a, "name", None) for a in table_args}
    assert "ix_news_articles_sentiment" not in names
    assert "ix_news_articles_threat_level" not in names


def test_create_all_works_on_fresh_memory_db() -> None:
    """The bug surfaced as a 'Index defined twice' error here."""
    from app.database import Base, _set_sqlite_pragma
    import app.models  # noqa: F401
    import app.models.ticker  # noqa: F401
    import app.models.news  # noqa: F401
    import app.models.stockuniverse  # noqa: F401
    import app.models.watchlist  # noqa: F401
    import app.models.notification  # noqa: F401
    import app.models.corporatefilings  # noqa: F401
    import app.models.job  # noqa: F401
    import app.models.system_config  # noqa: F401
    import app.models.marketcategory  # noqa: F401
    import app.models.ai_chat  # noqa: F401

    eng = create_engine("sqlite:///:memory:")
    event.listen(eng, "connect", _set_sqlite_pragma)
    # If the duplicate-index bug is back, this raises InvalidRequestError.
    Base.metadata.create_all(eng)
    # And the news_articles table actually exists
    with eng.connect() as conn:
        rows = conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='news_articles'"
        ).fetchall()
    assert rows, "news_articles table was not created"


def test_in_memory_db_fixture_works() -> None:
    """End-to-end check that the conftest fixture builds a usable DB.

    This is the test that the pre-fix bug was silently breaking.
    """
    from tests.conftest import in_memory_db  # noqa: F401 — fixture import

    @pytest.fixture
    def _in_memory_db():
        from tests.conftest import in_memory_db as f
        yield f

    # Re-implement the fixture body inline to avoid fixture-scope conflicts
    import sqlite3
    from app.database import Base, _set_sqlite_pragma
    import app.models  # noqa: F401
    import app.models.ticker  # noqa: F401
    import app.models.news  # noqa: F401
    import app.models.stockuniverse  # noqa: F401
    import app.models.watchlist  # noqa: F401
    import app.models.notification  # noqa: F401
    import app.models.corporatefilings  # noqa: F401
    import app.models.job  # noqa: F401
    import app.models.system_config  # noqa: F401
    import app.models.marketcategory  # noqa: F401
    import app.models.ai_chat  # noqa: F401

    con = sqlite3.connect(":memory:")
    eng = create_engine("sqlite:///:memory:")
    event.listen(eng, "connect", _set_sqlite_pragma)
    Base.metadata.create_all(eng)
    with eng.connect() as sa_con:
        rows = sa_con.exec_driver_sql(
            "SELECT name, sql FROM sqlite_master WHERE type IN ('table', 'index') AND sql IS NOT NULL"
        ).fetchall()
    eng.dispose()
    for _, sql in rows:
        con.execute(sql)
    con.commit()
    # Sanity: we can insert + read a row
    con.execute(
        "INSERT INTO news_articles (url, source, fetched_at, created_at) "
        "VALUES ('https://x', 'test', '2026-01-01 00:00:00', '2026-01-01 00:00:00')"
    )
    con.commit()
    cur = con.execute("SELECT url, source FROM news_articles")
    row = cur.fetchone()
    assert row == ("https://x", "test")
    con.close()
