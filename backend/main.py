"""BLM Analytics — FastAPI application entry point."""

import asyncio
import logging
import logging.config
import logging.handlers
import time
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

from pathlib import Path

from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, inspect as sa_inspect

from app.config import settings
from app.routers import (
    ai_summarizer_router,
    filings_router,
    market_router,
    screener_router,
    stockuniverse_router,
    watchlist_router,
)
from app.routers.nonpersistence import start_cache_cleanup
from app.services.ai_summarizer import ai_summarizer
from app.services.nse_client import nse_client
from app.services.screener_client import screener_client
from app.backgroundtasks import stock_universe_scheduler
from app import mcp_server

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


_LOG_FORMAT = "%(asctime)s  %(levelname)-8s  %(name)s  %(message)s"
_LOG_DATEFMT = "%Y-%m-%d %H:%M:%S"


def _configure_logging() -> None:
    """Configure root logger with console + rotating file handlers.

    Safe to call multiple times — replaces any handlers set by Alembic's
    fileConfig() (called during migrations, which wipes our file handler).
    Uses settings.log_level so the LOG_LEVEL env-var is respected.
    """
    log_dir = Path(__file__).parent / "logs"
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / "backend.log"

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_LOG_DATEFMT)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    file_handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    # Resolve level from settings so LOG_LEVEL env-var is respected.
    root_level = getattr(logging, settings.log_level.upper(), logging.INFO)

    # Configure root logger — replace any handlers set by Alembic's fileConfig().
    root_logger = logging.getLogger()
    root_logger.setLevel(root_level)
    root_logger.handlers = []
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)

    # Uvicorn loggers default to propagate=False; wire them directly into our
    # handlers so their output also reaches the rotating file.
    for uv_name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        uv_logger = logging.getLogger(uv_name)
        uv_logger.setLevel(logging.INFO)
        uv_logger.handlers = []
        uv_logger.propagate = False
        uv_logger.addHandler(console_handler)
        uv_logger.addHandler(file_handler)

    # Application namespaces — always DEBUG so detailed app logs are never
    # silenced by a higher root level set via LOG_LEVEL.
    for ns in ("app", "app.services", "app.routers"):
        logging.getLogger(ns).setLevel(logging.DEBUG)

    # Suppress chatty third-party loggers.
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


# Configure logging at module load so the very first import-time messages are
# captured.  The lifespan re-calls this after Alembic migrations run because
# alembic/env.py calls fileConfig() which wipes our handlers.
_configure_logging()


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Re-configure logging: restores our handlers after uvicorn's own startup
    # logging setup (which runs after module import in reload mode).
    _configure_logging()

    logger.info("Starting up BLM Analytics backend...")
    await asyncio.to_thread(_run_migrations_sync)

    # alembic/env.py calls fileConfig(alembic.ini) during migrations which
    # resets the root logger to WARNING/stderr-only.  Restore our handlers now.
    _configure_logging()

    logger.info("Database schema up to date")
    cleanup_task = await start_cache_cleanup()
    universe_task = asyncio.create_task(stock_universe_scheduler())
    await screener_client.init()

    if ai_summarizer.is_configured:
        logger.info(
            "AI summarizer configured — provider=%s model=%s",
            settings.ai_api_base_url,
            settings.ai_model,
        )
    else:
        logger.warning(
            "AI_API_KEY not set — AI summarizer endpoints will return 503. "
            "Set AI_API_KEY (and optionally AI_API_BASE_URL, AI_MODEL) in .env."
        )

    # The MCP streamable-HTTP session manager requires its task group to be
    # running for the duration of the application.  streamable_http_app() is
    # called at mount time (module scope), so _session_manager is already
    # created; we just need to start it here inside the lifespan.
    assert mcp_server.mcp._session_manager is not None, (
        "MCP session manager not initialised — ensure app.mount() runs before lifespan"
    )
    async with mcp_server.mcp._session_manager.run():
        yield

        logger.info("Shutting down — closing clients...")
        cleanup_task.cancel()
        universe_task.cancel()

        await ai_summarizer.close()
        await nse_client.close()
        await screener_client.close()


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

# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

# CORS — allow the Next.js dev server and any local variants.
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

# Request / response logging — logs every HTTP call with method, path, status,
# and latency so that all network activity appears in backend.log.
# Registered after CORS so the CORS middleware is outermost in the stack.
_access_logger = logging.getLogger("app.access")


@app.middleware("http")
async def log_requests(request: Request, call_next) -> Response:  # type: ignore[type-arg]
    """Log every HTTP request with method, path, status, and elapsed time."""
    start = time.perf_counter()
    response: Response = await call_next(request)
    elapsed_ms = (time.perf_counter() - start) * 1000
    _access_logger.info(
        "%s %s %d  %.1fms",
        request.method,
        request.url.path,
        response.status_code,
        elapsed_ms,
    )
    return response


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

app.include_router(ai_summarizer_router, prefix="/api")
app.include_router(filings_router, prefix="/api")
app.include_router(market_router, prefix="/api")
app.include_router(screener_router, prefix="/api")
app.include_router(stockuniverse_router, prefix="/api")
app.include_router(watchlist_router, prefix="/api")

# Mount MCP server under /api/mcp
app.mount("/api/mcp", mcp_server.mcp.streamable_http_app())


@app.get("/health", tags=["meta"])
async def health() -> dict[str, str]:
    """Service health check."""
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=settings.port,
        reload=True,
        # Disable uvicorn's own logging dictConfig so our _configure_logging()
        # remains the sole logging authority (file handler stays in place).
        log_config=None,
    )
