"""Async SQLAlchemy engine and session factory."""
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import event
from sqlalchemy.pool import NullPool as _AsyncNullPool
from app.config import settings

DATABASE_URL = f"sqlite+aiosqlite:///{settings.db_path}"


def _apply_sqlite_pragmas(cursor) -> None:
    """Enable WAL mode and tune SQLite for concurrent multi-writer workloads.

    Shared by BOTH the async engine and the sync engine via the
    ``connect`` event listener.  Single source of truth for pragma
    tuning.

    Key choices:
    - busy_timeout=30000: 30 s retry window — set FIRST so the journal_mode=WAL
      exclusive-lock acquisition retries instead of immediately failing with
      "database is locked" when multiple connections open concurrently at startup.
    - synchronous=NORMAL: safe in WAL mode (WAL file is still synced before a
      checkpoint), ~3x faster than FULL because it avoids per-transaction fsyncs.
    - cache_size=-65536: 64 MB page cache reduces disk I/O and shortens the time
      write locks are held, reducing contention between concurrent workers.
    - temp_store=MEMORY: temp tables and indices live in RAM, not temp files.
    - mmap_size=268435456: 256 MB memory-mapped I/O for faster sequential reads.
    """
    # busy_timeout must be set first so that the journal_mode=WAL exclusive
    # lock acquisition retries rather than immediately raising "database is locked".
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA cache_size=-65536")
    cursor.execute("PRAGMA temp_store=MEMORY")
    cursor.execute("PRAGMA mmap_size=268435456")


def _set_sqlite_pragma(dbapi_conn, connection_record):
    """Async-engine connect listener.  Delegates to ``_apply_sqlite_pragmas``."""
    cursor = dbapi_conn.cursor()
    _apply_sqlite_pragmas(cursor)
    cursor.close()


engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False},
    poolclass=_AsyncNullPool,
)
event.listen(engine.sync_engine, "connect", _set_sqlite_pragma)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields a database session."""
    async with AsyncSessionLocal() as session:
        yield session


# ---------------------------------------------------------------------------
# Sync engine — used exclusively by background worker threads.
# Must never be imported by async request handlers or routers.
# Async code must never import _SyncSessionLocal.
# ---------------------------------------------------------------------------
from sqlalchemy import create_engine
from sqlalchemy import event as _sa_event
from sqlalchemy.orm import sessionmaker as _sync_sessionmaker
from sqlalchemy.pool import QueuePool as _SyncQueuePool

# Sync engine: QueuePool reuses connections across the 14 daemon worker
# threads. Each pooled connection keeps its PRAGMAs (WAL, cache_size, etc.)
# alive, avoiding per-call allocation churn.
# The async engine above deliberately stays on NullPool — aiosqlite
# serialises access internally and high-concurrency request handlers
# benefit from NullPool's simpler lifecycle.
_sync_engine = create_engine(
    f"sqlite:///{settings.db_path}",
    connect_args={"check_same_thread": False},
    poolclass=_SyncQueuePool,
    pool_size=5,
    max_overflow=10,
    pool_timeout=30.0,
)


@_sa_event.listens_for(_sync_engine, "connect")
def _set_sync_sqlite_pragmas(dbapi_conn, connection_record):
    """Sync-engine connect listener.  Delegates to ``_apply_sqlite_pragmas``."""
    cursor = dbapi_conn.cursor()
    _apply_sqlite_pragmas(cursor)
    cursor.close()


_SyncSessionLocal = _sync_sessionmaker(
    bind=_sync_engine,
    autocommit=False,
    autoflush=False,
)
