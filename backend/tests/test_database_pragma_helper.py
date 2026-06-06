"""Tests for audit B.4 — ``database.py`` pragma + engine consolidation.

B.4a — extract ``_apply_sqlite_pragmas(cursor)`` helper so the 2 pragma
       blocks (async engine + sync engine) in ``database.py`` share one
       source of truth.

B.4b — drop ``_thread_async_engine`` / ``_ThreadAsyncSessionLocal`` and
       route the worker-thread code paths through the main
       ``AsyncSessionLocal`` (NullPool is already thread-safe — each
       ``engine.connect()`` opens a fresh DBAPI connection bound to the
       loop that opened it).
"""

from __future__ import annotations

import asyncio
import sqlite3
import threading
from typing import Any

import pytest

from app import database
from app.config import settings


# ---------------------------------------------------------------------------
# B.4a — _apply_sqlite_pragmas helper
# ---------------------------------------------------------------------------

class TestApplySqlitePragmasHelper:
    """The 2 pragma blocks must call a shared helper."""

    def test_helper_applies_all_six_pragmas(self, tmp_path) -> None:
        """The helper must set busy_timeout, journal_mode, synchronous,
        cache_size, temp_store, mmap_size — in that order so that
        busy_timeout runs BEFORE the journal_mode=WAL exclusive lock
        acquisition (otherwise the first connect races and fails).

        Uses a real on-disk SQLite (not ``:memory:``) so mmap_size
        applies (mmap is a no-op on in-memory databases and the
        PRAGMA mmap_size query returns NULL in that case).
        """
        db_file = tmp_path / "test.db"
        con = sqlite3.connect(str(db_file))
        try:
            cur = con.cursor()
            database._apply_sqlite_pragmas(cur)
            # Spot-check the values via PRAGMA ... query syntax
            busy_timeout = cur.execute("PRAGMA busy_timeout").fetchone()[0]
            journal_mode = cur.execute("PRAGMA journal_mode").fetchone()[0].lower()
            synchronous = cur.execute("PRAGMA synchronous").fetchone()[0]
            cache_size = cur.execute("PRAGMA cache_size").fetchone()[0]
            temp_store = cur.execute("PRAGMA temp_store").fetchone()[0]
            mmap_size = cur.execute("PRAGMA mmap_size").fetchone()[0]
            assert busy_timeout == 30000
            assert journal_mode == "wal"
            assert synchronous == 1  # NORMAL
            assert cache_size == -65536
            assert temp_store == 2  # MEMORY
            assert mmap_size == 268435456
        finally:
            con.close()

    def test_event_listeners_delegate_to_helper(self, monkeypatch) -> None:
        """The two event-listener functions (``_set_sqlite_pragma`` and
        ``_set_sync_sqlite_pragmas``) must call ``_apply_sqlite_pragmas``
        so that pragma changes happen in exactly one place."""
        from app import database as db

        calls: list[Any] = []
        real_helper = db._apply_sqlite_pragmas

        def spy(cursor):
            calls.append(cursor)
            return real_helper(cursor)

        monkeypatch.setattr(db, "_apply_sqlite_pragmas", spy)

        # 1. async engine — open + close a session to trigger the connect
        # event listener (which calls the helper).
        from app.database import AsyncSessionLocal
        from sqlalchemy import text

        loop = asyncio.new_event_loop()
        try:
            async def exercise_async():
                async with AsyncSessionLocal() as session:
                    await session.execute(text("SELECT 1"))

            loop.run_until_complete(exercise_async())
        finally:
            loop.close()

        # 2. sync engine
        from app.database import _SyncSessionLocal
        with _SyncSessionLocal() as session:
            session.execute(text("SELECT 1"))

        # Both event listeners must have invoked the helper at least once
        assert len(calls) >= 2, (
            f"expected helper called >=2 times (one per listener), got {len(calls)}"
        )


# ---------------------------------------------------------------------------
# B.4b — drop _thread_async_engine
# ---------------------------------------------------------------------------

class TestThreadAsyncEngineRemoved:
    """The duplicate ``_thread_async_engine`` and
    ``_ThreadAsyncSessionLocal`` must be removed; the worker-thread code
    paths must use the main ``engine`` / ``AsyncSessionLocal``."""

    def test_thread_async_engine_removed(self) -> None:
        """The module must not export ``_thread_async_engine`` or
        ``_ThreadAsyncSessionLocal`` after the refactor."""
        assert not hasattr(database, "_thread_async_engine"), (
            "_thread_async_engine still present — B.4b refactor incomplete"
        )
        assert not hasattr(database, "_ThreadAsyncSessionLocal"), (
            "_ThreadAsyncSessionLocal still present — B.4b refactor incomplete"
        )

    def test_backgroundtasks_uses_main_session_local(self) -> None:
        """The 4 ``_ThreadAsyncSessionLocal`` callers in backgroundtasks
        must now use ``AsyncSessionLocal`` instead.

        After Phase C.1 A.1 split, the implementation lives in
        ``app/backgroundtasks/_impl.py`` — read the source of that
        file (the re-export shim doesn't import the session factories
        itself).
        """
        from pathlib import Path
        impl_path = (
            Path(__file__).resolve().parents[1]
            / "app" / "backgroundtasks" / "_impl.py"
        )
        source = impl_path.read_text()
        assert "_ThreadAsyncSessionLocal" not in source, (
            "backgroundtasks/_impl.py still references _ThreadAsyncSessionLocal"
        )
        # And it should reference the main AsyncSessionLocal
        assert "AsyncSessionLocal" in source

    def test_worker_thread_session_works_with_main_engine(self) -> None:
        """A session created via ``AsyncSessionLocal`` in a worker thread
        with its own event loop must be able to read+write.

        This is the key invariant: ``NullPool`` is already thread-safe —
        each ``engine.connect()`` opens a fresh DBAPI connection bound
        to whichever loop is running at the time.
        """
        from app.database import AsyncSessionLocal
        from sqlalchemy import text

        errors: list[BaseException] = []

        def worker() -> None:
            loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(loop)
                async def go() -> None:
                    async with AsyncSessionLocal() as session:
                        result = await session.execute(text("SELECT 1"))
                        assert result.scalar() == 1
                loop.run_until_complete(go())
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)
            finally:
                loop.close()
                asyncio.set_event_loop(None)

        t = threading.Thread(target=worker, name="test-worker")
        t.start()
        t.join(timeout=10)
        assert not t.is_alive(), "worker thread hung"
        assert not errors, f"worker thread errored: {errors!r}"
