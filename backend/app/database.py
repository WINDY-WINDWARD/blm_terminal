"""Async SQLAlchemy engine and session factory."""
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import event
from sqlalchemy.pool import StaticPool

from app.config import settings

DATABASE_URL = f"sqlite+aiosqlite:///{settings.db_path}"


def _set_sqlite_pragma(dbapi_conn, connection_record):
    """Enable WAL mode and set busy timeout for SQLite."""
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
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
