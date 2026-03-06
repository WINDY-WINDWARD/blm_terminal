"""BLM Analytics — FastAPI application entry point."""
import asyncio
import logging
import logging.config
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

from pathlib import Path

from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, inspect as sa_inspect

from app.config import settings
from app.routers import filings_router, market_router, stockuniverse_router
from app.routers.nonpersistence import start_cache_cleanup
from app.services.nse_client import nse_client
from app.backgroundtasks import stock_universe_scheduler

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Migrations
# ---------------------------------------------------------------------------

# Revision ID of the first migration that captured the original schema.
_INITIAL_REVISION = "aaf83c15d9f1"
# Absolute path to alembic.ini so the helper works regardless of CWD.
_ALEMBIC_INI = str(Path(__file__).resolve().parent / "alembic.ini")


def _run_migrations_sync() -> None:
    """Apply all pending Alembic migrations synchronously.

    If the database already has schema tables but no alembic_version row
    (i.e. it was created before migrations were introduced), the DB is
    stamped at the initial revision so only subsequent migrations run.
    """
    alembic_cfg = AlembicConfig(_ALEMBIC_INI)

    # Detect legacy databases (schema exists, no migration tracking yet).
    sync_url = f"sqlite:///{settings.db_path}"
    sync_engine = create_engine(sync_url)
    try:
        with sync_engine.connect() as conn:
            inspector = sa_inspect(conn)
            tables = set(inspector.get_table_names())
            legacy = "stock_universe" in tables and "alembic_version" not in tables
    finally:
        sync_engine.dispose()

    if legacy:
        logger.info("migrations: legacy DB detected — stamping to initial revision")
        alembic_command.stamp(alembic_cfg, _INITIAL_REVISION)

    alembic_command.upgrade(alembic_cfg, "head")

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("Starting up BLM Analytics backend...")
    await asyncio.to_thread(_run_migrations_sync)
    logger.info("Database schema up to date")
    cleanup_task = await start_cache_cleanup()
    universe_task = asyncio.create_task(stock_universe_scheduler())
    yield
    logger.info("Shutting down — closing NSE client...")
    cleanup_task.cancel()
    universe_task.cancel()
    await nse_client.close()


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="BLM Analytics",
    description=(
        "NSE India analytics service for BLM Terminal.\n\n"
        "Provides earnings, corporate filings, and market circulars "
        "fetched and cached from NSE India."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

# CORS — allow the Next.js dev server and any local variants
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

app.include_router(filings_router, prefix="/api")
app.include_router(market_router, prefix="/api")
app.include_router(stockuniverse_router, prefix="/api")


@app.get("/health", tags=["meta"])
async def health() -> dict[str, str]:
    """Service health check."""
    return {"status": "ok"}
