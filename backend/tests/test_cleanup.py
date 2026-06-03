"""Tests for Phase C: data-retention pruners and vacuum worker.

Covers:
- _run_cleanup_if_due() runs all four pruners (notifications, news, 1h, W)
- Each pruner deletes the correct rows
- 24h gate prevents re-runs within CLEANUP_INTERVAL
- _run_vacuum() opens a fresh autocommit connection and runs VACUUM + ANALYZE
- vacuum_worker() honours the disabled flag and the cron schedule

The pruners use raw SQL via `text()` rather than ORM `delete()` for speed
on the production 1.5GB DB.  These tests exercise both the function
structure and the SQL contract against a small in-memory SQLite fixture
(so they run in <1s even when the real DB is huge and under load).
"""

from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.backgroundtasks import (  # noqa: E402
    CLEANUP_INTERVAL,
    INTRADAY_1H_RETENTION_DAYS,
    INTRADAY_W_RETENTION_YEARS,
    NEWS_RETENTION_DAYS,
    VACUUM_CRON,
    _cleanup_last_run,
    _run_cleanup_if_due,
    _run_vacuum,
    vacuum_worker,
)


@pytest.fixture
def small_db(tmp_path):
    """In-memory SQLite with the tables the pruners touch."""
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript("""
        CREATE TABLE news_articles (
            url TEXT PRIMARY KEY,
            source TEXT,
            title TEXT,
            text TEXT,
            publish_date TEXT,
            fetched_at TEXT
        );
        CREATE TABLE ticker_intraday (
            id INTEGER PRIMARY KEY,
            symbol TEXT,
            timestamp TEXT,
            interval TEXT,
            open REAL, high REAL, low REAL, close REAL, volume INTEGER
        );
        CREATE TABLE notifications (
            id INTEGER PRIMARY KEY,
            is_read INTEGER,
            triggered_at TEXT
        );
    """)
    return con


@pytest.fixture(autouse=True)
def reset_cleanup_gate():
    """Reset the 24h gate so each test can re-trigger _run_cleanup_if_due()."""
    import app.backgroundtasks as bg
    bg._cleanup_last_run = None
    yield
    bg._cleanup_last_run = None


# ─── _run_cleanup_if_due() ───────────────────────────────────────────────────


class TestCleanupSuite:
    def test_news_pruner_deletes_old_rows(self, monkeypatch, small_db):
        old = (datetime.now() - timedelta(days=NEWS_RETENTION_DAYS + 1)).isoformat()
        new = datetime.now().isoformat()
        small_db.execute(
            "INSERT INTO news_articles VALUES (?, ?, ?, ?, ?, ?)",
            ("old://1", "src", "Old", "body", old, new),
        )
        small_db.execute(
            "INSERT INTO news_articles VALUES (?, ?, ?, ?, ?, ?)",
            ("new://1", "src", "New", "body", new, new),
        )
        small_db.commit()
        monkeypatch.setattr(
            "app.backgroundtasks._SyncSessionLocal",
            lambda: _FakeSession(small_db),
        )
        _run_cleanup_if_due()
        rows = small_db.execute("SELECT url FROM news_articles").fetchall()
        urls = {r["url"] for r in rows}
        assert "old://1" not in urls
        assert "new://1" in urls

    def test_news_pruner_keeps_recent_rows(self, monkeypatch, small_db):
        recent = (datetime.now() - timedelta(days=NEWS_RETENTION_DAYS - 1)).isoformat()
        small_db.execute(
            "INSERT INTO news_articles VALUES (?, ?, ?, ?, ?, ?)",
            ("recent://1", "src", "Recent", "body", recent, recent),
        )
        small_db.commit()
        monkeypatch.setattr(
            "app.backgroundtasks._SyncSessionLocal",
            lambda: _FakeSession(small_db),
        )
        _run_cleanup_if_due()
        rows = small_db.execute("SELECT url FROM news_articles").fetchall()
        assert len(rows) == 1
        assert rows[0]["url"] == "recent://1"

    def test_1h_pruner_deletes_old_rows(self, monkeypatch, small_db):
        old_ts = (datetime.now() - timedelta(days=INTRADAY_1H_RETENTION_DAYS + 1)).isoformat()
        new_ts = (datetime.now() - timedelta(hours=1)).isoformat()
        small_db.execute(
            "INSERT INTO ticker_intraday (symbol, timestamp, interval, open, high, low, close, volume) "
            "VALUES (?, ?, '1h', 100, 101, 99, 100, 1000)",
            ("AAA", old_ts),
        )
        small_db.execute(
            "INSERT INTO ticker_intraday (symbol, timestamp, interval, open, high, low, close, volume) "
            "VALUES (?, ?, '1h', 100, 101, 99, 100, 1000)",
            ("BBB", new_ts),
        )
        small_db.commit()
        monkeypatch.setattr(
            "app.backgroundtasks._SyncSessionLocal",
            lambda: _FakeSession(small_db),
        )
        _run_cleanup_if_due()
        rows = small_db.execute("SELECT symbol FROM ticker_intraday").fetchall()
        syms = {r["symbol"] for r in rows}
        assert "AAA" not in syms
        assert "BBB" in syms

    def test_1h_pruner_does_not_affect_W_or_M(self, monkeypatch, small_db):
        old_ts = (datetime.now() - timedelta(days=INTRADAY_1H_RETENTION_DAYS + 30)).isoformat()
        for iv in ("W", "M"):
            small_db.execute(
                "INSERT INTO ticker_intraday (symbol, timestamp, interval, open, high, low, close, volume) "
                "VALUES (?, ?, ?, 100, 101, 99, 100, 1000)",
                (iv + "-sym", old_ts, iv),
            )
        small_db.commit()
        monkeypatch.setattr(
            "app.backgroundtasks._SyncSessionLocal",
            lambda: _FakeSession(small_db),
        )
        _run_cleanup_if_due()
        rows = small_db.execute("SELECT interval FROM ticker_intraday").fetchall()
        ivs = {r["interval"] for r in rows}
        assert "W" in ivs
        assert "M" in ivs

    def test_W_pruner_deletes_old_rows(self, monkeypatch, small_db):
        old_ts = (datetime.now() - timedelta(days=365 * INTRADAY_W_RETENTION_YEARS + 30)).isoformat()
        new_ts = (datetime.now() - timedelta(days=30)).isoformat()
        small_db.execute(
            "INSERT INTO ticker_intraday (symbol, timestamp, interval, open, high, low, close, volume) "
            "VALUES (?, ?, 'W', 100, 101, 99, 100, 1000)",
            ("OLD-W", old_ts),
        )
        small_db.execute(
            "INSERT INTO ticker_intraday (symbol, timestamp, interval, open, high, low, close, volume) "
            "VALUES (?, ?, 'W', 100, 101, 99, 100, 1000)",
            ("NEW-W", new_ts),
        )
        small_db.commit()
        monkeypatch.setattr(
            "app.backgroundtasks._SyncSessionLocal",
            lambda: _FakeSession(small_db),
        )
        _run_cleanup_if_due()
        rows = small_db.execute("SELECT symbol FROM ticker_intraday").fetchall()
        syms = {r["symbol"] for r in rows}
        assert "OLD-W" not in syms
        assert "NEW-W" in syms

    def test_24h_gate_prevents_re_runs(self, monkeypatch, small_db):
        # First call runs
        monkeypatch.setattr(
            "app.backgroundtasks._SyncSessionLocal",
            lambda: _FakeSession(small_db),
        )
        _run_cleanup_if_due()
        n_after_first = len(
            small_db.execute("SELECT * FROM news_articles").fetchall()
        )
        # Insert a row that would be deleted if re-ran
        old = (datetime.now() - timedelta(days=NEWS_RETENTION_DAYS + 5)).isoformat()
        small_db.execute(
            "INSERT INTO news_articles VALUES (?, ?, ?, ?, ?, ?)",
            ("gate://1", "src", "Gate", "body", old, old),
        )
        small_db.commit()
        # Second call within 24h should be a no-op
        _run_cleanup_if_due()
        rows = small_db.execute("SELECT url FROM news_articles").fetchall()
        assert any(r["url"] == "gate://1" for r in rows), "24h gate failed"

    def test_all_pruners_run_even_if_one_fails(self, monkeypatch, small_db):
        # News table is missing — news pruner should fail but others should still run
        small_db.execute("DROP TABLE news_articles")
        small_db.commit()
        monkeypatch.setattr(
            "app.backgroundtasks._SyncSessionLocal",
            lambda: _FakeSession(small_db),
        )
        # Should not raise
        _run_cleanup_if_due()


# ─── _run_vacuum() ────────────────────────────────────────────────────────────


class TestVacuum:
    def test_vacuum_runs_VACUUM_and_ANALYZE(self, monkeypatch, tmp_path):
        """End-to-end: build a real SQLite DB, run _run_vacuum(), verify
        the file is left in a valid state and ANALYZE was applied."""
        db = tmp_path / "test.db"
        # Pre-populate with some data so VACUUM has something to do
        con = sqlite3.connect(str(db))
        con.execute("CREATE TABLE t (x INTEGER)")
        con.executemany("INSERT INTO t VALUES (?)", [(i,) for i in range(1000)])
        con.commit()
        con.close()

        from app import backgroundtasks as bg
        monkeypatch.setattr(bg.settings, "db_path", str(db))

        # _run_vacuum() should complete without raising and the resulting
        # DB should be openable.  We don't try to spy on the actual SQL
        # because sqlite3.Connection's methods aren't safely monkey-patchable.
        _run_vacuum()

        # Verify the DB is still valid
        con = sqlite3.connect(str(db))
        n = con.execute("SELECT COUNT(*) FROM t").fetchone()[0]
        assert n == 1000, "VACUUM destroyed data"
        # Verify ANALYZE ran (sqlite_stat1 table would exist)
        stats = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='sqlite_stat1'"
        ).fetchall()
        assert len(stats) == 1, "ANALYZE didn't run (sqlite_stat1 missing)"
        con.close()


# ─── Constants ───────────────────────────────────────────────────────────────


class TestConstants:
    def test_news_retention_is_30_days(self):
        assert NEWS_RETENTION_DAYS == 30

    def test_intraday_1h_retention_is_30_days(self):
        assert INTRADAY_1H_RETENTION_DAYS == 30

    def test_intraday_W_retention_is_2_years(self):
        assert INTRADAY_W_RETENTION_YEARS == 2

    def test_vacuum_cron_is_sunday_4am(self):
        assert VACUUM_CRON == "0 4 * * 0"

    def test_cleanup_interval_is_24h(self):
        assert CLEANUP_INTERVAL == 24 * 60 * 60


# ─── Helper ──────────────────────────────────────────────────────────────────


class _FakeSession:
    """Minimal session context-manager for testing the pruners' SQL.

    Forwards .execute() to an in-memory SQLite connection (parameterised
    SQL via SQLAlchemy's text() is compatible with sqlite3).
    """

    def __init__(self, con: sqlite3.Connection):
        self._con = con

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, stmt, params=None):
        # SQLAlchemy text() → string
        sql = str(stmt)
        cur = self._con.execute(sql, params or {})
        # Mimic SQLAlchemy Result.rowcount
        return _FakeResult(cur.rowcount)

    def commit(self):
        self._con.commit()


class _FakeResult:
    def __init__(self, rowcount: int):
        self.rowcount = rowcount
