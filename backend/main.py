"""BLM Analytics — FastAPI application entry point."""

import asyncio
import logging
import logging.config
import logging.handlers
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

from pathlib import Path

from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, inspect as sa_inspect

from app.config import settings
from app.routers import (
    ai_summarizer_router,
    filings_router,
    market_router,
    screener_router,
    stockuniverse_router,
)
from app.routers.nonpersistence import start_cache_cleanup
from app.services.ai_summarizer import ai_summarizer
from app.services.nse_client import nse_client
from app.services.screener_client import screener_client
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

def _configure_logging() -> None:
    """Configure logging handlers. Call this at module load AND in lifespan."""
    import logging.handlers
    
    log_dir = Path(__file__).parent / "logs"
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / "backend.log"

    # Create handlers
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(
        logging.Formatter("%(asctime)s  %(levelname)-8s  %(name)s  %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    )

    file_handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
    )
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s  %(levelname)-8s  %(name)s  %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    )

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    root_logger.handlers = []  # Clear existing handlers
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)

    # Also configure uvicorn loggers
    for uv_name in ["uvicorn", "uvicorn.access", "uvicorn.error"]:
        uv_logger = logging.getLogger(uv_name)
        uv_logger.setLevel(logging.INFO)
        uv_logger.handlers = []
        uv_logger.addHandler(console_handler)
        uv_logger.addHandler(file_handler)

    # Set levels for specific loggers
    logging.getLogger("app").setLevel(logging.DEBUG)
    logging.getLogger("app.services").setLevel(logging.DEBUG)
    logging.getLogger("app.routers").setLevel(logging.DEBUG)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)

# Configure logging at module load (for initial startup)
_configure_logging()


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Re-configure logging for uvicorn reload child process
    _configure_logging()
    
    print("=== LIFESPAN START ===")
    logger.info("Starting up BLM Analytics backend...")
    await asyncio.to_thread(_run_migrations_sync)
    logger.info("Database schema up to date")
    cleanup_task = await start_cache_cleanup()
    universe_task = asyncio.create_task(stock_universe_scheduler())
    await screener_client.init()

    logger.info("Starting AI summarizer model loading in background...")
    print(">>> Starting AI model load...")
    
    async def load_model():
        try:
            await asyncio.to_thread(ai_summarizer.initialize)
            return True
        except Exception as e:
            print(f">>> Model load failed: {e}")
            return False
    
    load_task = asyncio.create_task(load_model())
    
    try:
        await asyncio.wait_for(load_task, timeout=300.0)
    except asyncio.TimeoutError:
        logger.warning("AI model loading timed out after 5 minutes")
        print(">>> AI model loading timed out")
    except Exception as e:
        logger.error(f"AI model loading failed: {e}")
        print(f">>> AI model loading failed: {e}")

    if ai_summarizer.is_ready:
        logger.info("AI summarizer loaded successfully")
        print(">>> AI summarizer loaded!")
    else:
        logger.warning("AI summarizer not ready - will load on first request")
        print(">>> AI summarizer NOT ready")

    print("=== LIFESPAN YIELD ===")
    yield

    print("=== LIFESPAN SHUTDOWN ===")
    logger.info("Shutting down — closing clients...")
    cleanup_task.cancel()
    universe_task.cancel()

    if not load_task.done():
        load_task.cancel()
        try:
            await load_task
        except asyncio.CancelledError:
            pass

    ai_summarizer.close()
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

app.include_router(ai_summarizer_router, prefix="/api")
app.include_router(filings_router, prefix="/api")
app.include_router(market_router, prefix="/api")
app.include_router(screener_router, prefix="/api")
app.include_router(stockuniverse_router, prefix="/api")


@app.get("/health", tags=["meta"])
async def health() -> dict[str, str]:
    """Service health check."""
    test_logger = logging.getLogger("app.routers.test")
    test_logger.info("Test log from /health endpoint")
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=4455,
        reload=True,
        log_config=None,  # Use Python logging (configured above)
    )
