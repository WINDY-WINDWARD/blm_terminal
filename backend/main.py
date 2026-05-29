"""BLM Analytics — FastAPI application entry point."""

import asyncio
import logging
import logging.config
import logging.handlers
import re
import time
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

from pathlib import Path

from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine, inspect as sa_inspect, text as sa_text, event as sa_event

from app.config import settings
from app.routers import (
    ai_chat_router,
    ai_summarizer_router,
    announcements_router,
    filings_router,
    markets_router,
    market_router,
    market_ws_router,
    morningstar_router,
    news_router,
    news_ws_router,
    notifications_router,
    screener_router,
    system_config_router,
    stockuniverse_router,
    stockuniverse_errors_router,
    watchlist_router,
    jobs_router,
)
from app.backgroundtasks import start_cache_cleanup
from app.services.ai_summarizer import ai_summarizer
from app.services.nse_client import nse_client
from app.services.screener_client import screener_client
from app.services.news_fetcher import news_fetcher
from app.services.nse_rate_limiter import NSEServiceUnavailableError
from app.orchestrator import orchestrator
from app import mcp_server

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Migrations
# ---------------------------------------------------------------------------

# Revision ID of the first migration that captured the original schema.
_INITIAL_REVISION = "aaf83c15d9f1"
# Absolute path to alembic.ini so the helper works regardless of CWD.
_ALEMBIC_INI = str(Path(__file__).resolve().parent / "alembic.ini")


def _get_current_revision() -> str | None:
    """Read the current alembic_version directly from the DB."""
    sync_url = f"sqlite:///{settings.db_path}"
    engine = create_engine(sync_url, connect_args={"check_same_thread": False})
    try:
        with engine.connect() as conn:
            result = conn.execute(sa_text("SELECT version_num FROM alembic_version"))
            row = result.fetchone()
            return row[0] if row else None
    except Exception:
        return None
    finally:
        engine.dispose()


def _extract_revision_from_error(exc: Exception) -> str | None:
    """Try to extract an Alembic revision ID from a migration error string.

    Looks for 12+ character hex strings (Alembic revision IDs).
    Falls back to reading alembic_version directly if no match found.
    """
    match = re.search(r"\b([0-9a-f]{12,})\b", str(exc))
    if match:
        return match.group(1)
    return _get_current_revision()


def _run_migrations_sync() -> None:
    """Apply all pending Alembic migrations synchronously.

    If the database already has schema tables but no alembic_version row
    (i.e. it was created before migrations were introduced), the DB is
    stamped at the initial revision so only subsequent migrations run.
    """
    alembic_cfg = AlembicConfig(_ALEMBIC_INI)

    # Detect legacy databases (schema exists, no migration tracking yet).
    sync_url = f"sqlite:///{settings.db_path}"
    sync_engine = create_engine(sync_url, connect_args={"check_same_thread": False})

    @sa_event.listens_for(sync_engine, "connect")
    def set_sqlite_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

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

    try:
        alembic_command.upgrade(alembic_cfg, "head")
    except Exception as exc:
        err = str(exc).lower()

        if "duplicate column" in err:
            # A migration partially ran before (column added manually or by a
            # previous run) but the revision wasn't recorded.  Stamp at the
            # current revision and retry so Alembic picks up where it left off.
            revision = _extract_revision_from_error(exc)
            if revision:
                logger.warning(
                    "migrations: duplicate column detected — stamping at %s and retrying",
                    revision,
                )
                alembic_command.stamp(alembic_cfg, revision)
                alembic_command.upgrade(alembic_cfg, "head")
            else:
                logger.error(
                    "migrations: duplicate column but could not identify current revision. "
                    "Run 'alembic upgrade head' manually to diagnose. Error: %s",
                    exc,
                )
                raise

        elif "overlap" in err or "multiple head" in err:
            # Multiple Alembic branches with overlapping migrations.
            # Upgrade each head independently to avoid the merge conflict.
            logger.warning("migrations: overlapping branches — upgrading each head individually")
            heads = alembic_command.heads(alembic_cfg) or []
            for head in heads:
                logger.info("migrations: upgrading to %s", head)
                alembic_command.upgrade(alembic_cfg, head)

        else:
            logger.error("migrations: unhandled migration error: %s", exc)
            raise


def _ensure_watchlist_data() -> None:
    """Ensure watchlist data consistency after migrations.

    Creates Default watchlist if missing and associates any orphaned
    watchlist_items with it. Handles partial migration runs.
    """
    sync_url = f"sqlite:///{settings.db_path}"
    sync_engine = create_engine(sync_url, connect_args={"check_same_thread": False})

    @sa_event.listens_for(sync_engine, "connect")
    def set_sqlite_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    try:
        with sync_engine.connect() as conn:
            inspector = sa_inspect(conn)
            tables = set(inspector.get_table_names())

            if "watchlists" not in tables:
                return

            result = conn.execute(sa_text("SELECT COUNT(*) FROM watchlists WHERE id = 1"))
            if result.scalar() == 0:
                logger.info("Creating Default watchlist")
                conn.execute(sa_text("INSERT INTO watchlists (id, name) VALUES (1, 'Default')"))
                conn.commit()

            result = conn.execute(sa_text("SELECT COUNT(*) FROM watchlist_items WHERE watchlist_id IS NULL"))
            if result.scalar() > 0:
                logger.info("Associating orphaned watchlist items with Default watchlist")
                conn.execute(sa_text("UPDATE watchlist_items SET watchlist_id = 1 WHERE watchlist_id IS NULL"))
                conn.commit()
    finally:
        sync_engine.dispose()


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

    # Application namespaces inherit the configured root level.
    for ns in ("app", "app.services", "app.routers"):
        logging.getLogger(ns).setLevel(root_level)

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


def _backfill_entities_double_encoding() -> None:
    """Fix legacy news_articles rows where entities was double-JSON-encoded.

    Before the news_aggregator.py fix, entities was stored as a JSON string
    whose value is another JSON string (double-encoded).  SQLAlchemy's JSON
    column decodes one layer on read, leaving a Python str instead of dict,
    which causes Pydantic ValidationErrors in every news endpoint.

    This function repairs all such rows in a single atomic transaction.
    It is idempotent: on subsequent startups, the WHERE clause matches 0 rows
    and the function returns instantly without touching the DB.

    Safety: SQLite WAL mode allows concurrent reads during the write.  This
    runs before start_all_workers() so the RSS background writer is not yet
    active when the transaction commits.
    """
    import json
    import sqlite3

    db_path = Path(settings.db_path)
    if not db_path.exists():
        logger.warning("_backfill_entities: DB not found at %s — skipping", db_path)
        return

    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.cursor()
        cur.execute("SELECT rowid, entities FROM news_articles WHERE typeof(entities) = 'text'")
        rows = cur.fetchall()
        if not rows:
            logger.debug("_backfill_entities: no corrupted rows found — nothing to do")
            return

        fixed: list[tuple[str, int]] = []
        skipped = 0
        for rowid, raw in rows:
            try:
                # SQLAlchemy JSON column does one json.loads() on read, so
                # the stored value is: '"<escaped inner json string>"'
                # raw here is the literal text from SQLite (the outer layer).
                inner = json.loads(raw)          # str → str (still encoded)
                if isinstance(inner, str):
                    result = json.loads(inner)   # str → dict
                elif isinstance(inner, dict):
                    result = inner               # already a dict somehow
                else:
                    skipped += 1
                    continue
                if not isinstance(result, dict):
                    skipped += 1
                    continue
                fixed.append((json.dumps(result), rowid))
            except (json.JSONDecodeError, TypeError, ValueError):
                skipped += 1

        if fixed:
            cur.executemany(
                "UPDATE news_articles SET entities = ? WHERE rowid = ?",
                fixed,
            )
            conn.commit()
            logger.info(
                "_backfill_entities: fixed %d corrupted rows (%d skipped/unparseable)",
                len(fixed),
                skipped,
            )
        else:
            logger.warning(
                "_backfill_entities: %d candidate rows found but none were fixable (%d skipped)",
                len(rows),
                skipped,
            )
    finally:
        conn.close()



@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Re-configure logging: restores our handlers after uvicorn's own startup
    # logging setup (which runs after module import in reload mode).
    _configure_logging()

    logger.info("Starting up BLM Analytics backend...")
    await asyncio.to_thread(_run_migrations_sync)
    await asyncio.to_thread(_ensure_watchlist_data)
    await asyncio.to_thread(_backfill_entities_double_encoding)

    # alembic/env.py calls fileConfig(alembic.ini) during migrations which
    # resets the root logger to WARNING/stderr-only.  Restore our handlers now.
    _configure_logging()

    logger.info("Database schema up to date")
    cleanup_task = await start_cache_cleanup()

    await screener_client.init()
    await news_fetcher.init()

    # Start all workers, schedulers, and the startup pipeline via the orchestrator.
    # This replaces the previous scattered calls to start_all_workers(),
    # init_client(), _run_watchlist_scheduler(), _run_nightly_scheduler(), and
    # the Morningstar first-run sync block.
    await orchestrator.start()

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

        logger.info("Shutting down — cancelling background tasks...")
        cleanup_task.cancel()

        logger.info("Shutting down — stopping workers and closing clients...")
        await orchestrator.stop()


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

@app.exception_handler(NSEServiceUnavailableError)
async def nse_unavailable_handler(request: Request, exc: NSEServiceUnavailableError) -> JSONResponse:
    """Return 503 when the NSE circuit breaker is open instead of crashing the ASGI app."""
    return JSONResponse(status_code=503, content={"error": str(exc)})


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

app.include_router(ai_chat_router, prefix="/api")
app.include_router(ai_summarizer_router, prefix="/api")
app.include_router(announcements_router, prefix="/api")
app.include_router(filings_router, prefix="/api")
app.include_router(markets_router, prefix="/api")
app.include_router(morningstar_router, prefix="/api")
app.include_router(market_router, prefix="/api")
app.include_router(news_router, prefix="/api")
# WebSocket routers mounted at /ws (no api prefix)
app.include_router(news_ws_router, prefix="/ws")
app.include_router(market_ws_router, prefix="/ws")
app.include_router(screener_router, prefix="/api")
app.include_router(system_config_router, prefix="/api")
app.include_router(stockuniverse_router, prefix="/api")
app.include_router(stockuniverse_errors_router, prefix="/api")
app.include_router(watchlist_router, prefix="/api")
app.include_router(notifications_router, prefix="/api")
app.include_router(jobs_router, prefix="/api")
from app.routers.ticker import router as ticker_router
app.include_router(ticker_router, prefix="/api")

import os as _os
if _os.environ.get("ENV") != "production":
    from app.routers.notifications import _dev_router
    app.include_router(_dev_router, prefix="/api")

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
        reload=False,
        log_config=None,
        forwarded_allow_ips='*',
    )
