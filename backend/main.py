"""BLM Analytics — FastAPI application entry point."""

import asyncio
import logging
import logging.config
import logging.handlers
import re
import time
from contextlib import asynccontextmanager
from typing import Annotated
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
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
    ai_routes_router,
    ai_chat_router,
    ai_picks_router,
    ai_summarizer_router,
    announcements_router,
    breakouts_router,
    filings_router,
    markets_router,
    market_router,
    market_ws_router,
    morningstar_router,
    news_router,
    news_ws_router,
    notifications_router,
    paper_trades_router,
    screener_router,
    iinvest_router,
    tradingview as tradingview_router,
    system_config_router,
    first_boot_router,
    stockuniverse_router,
    stockuniverse_errors_router,
    valuation_router,
    portfolio_router,
    watchlist_router,
    layout_router,
    scripts_router,
    jobs_router,
    auth_router,
    users_router,
)
from app.workers.lifecycle import start_cache_cleanup
from app.services.ai_summarizer import ai_summarizer
from app.services.nse_client import nse_client
from app.services.screener_client import screener_client
from app.services.news_fetcher import news_fetcher
from app.services.nse_rate_limiter import NSEServiceUnavailableError
from app.orchestrator import orchestrator

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Migrations
# ---------------------------------------------------------------------------

# Revision ID of the first migration that captured the original schema.
_INITIAL_REVISION = "aaf83c15d9f1"

def _resolve_alembic_ini() -> str:
    import sys
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        base_dir = Path(sys._MEIPASS)
    else:
        base_dir = Path(__file__).resolve().parent
    return str(base_dir / "alembic.ini")

# Absolute path to alembic.ini so the helper works regardless of CWD or PyInstaller bundling.
_ALEMBIC_INI = _resolve_alembic_ini()


def _get_current_revision() -> str | None:
    """Read the current alembic_version directly from the DB."""
    sync_url = f"sqlite:///{settings.db_path}"
    engine = create_engine(sync_url, connect_args={"check_same_thread": False, "timeout": 15})
    @sa_event.listens_for(engine, "connect")
    def _set_pragma(dbapi_conn, connection_record):
        from app.database import _apply_sqlite_pragmas
        cur = dbapi_conn.cursor()
        _apply_sqlite_pragmas(cur)
        cur.close()
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
        from app.database import _apply_sqlite_pragmas
        cursor = dbapi_conn.cursor()
        _apply_sqlite_pragmas(cursor)
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

        elif "can't locate revision" in err or "no such revision" in err:
            # The DB is stamped at a revision that was archived (moved out of
            # the active versions/ directory).  We can't use alembic's own
            # stamp/upgrade commands because they also read the stale version.
            # Strategy: clear stale version, use Base.metadata.create_all()
            # to ensure all ORM-defined tables exist (idempotent — creates
            # missing tables, skips existing), then stamp at HEAD.
            logger.warning(
                "migrations: stale/archived revision detected — "
                "recreating missing tables and stamping at HEAD"
            )
            from app.models import __init__ as _models_init  # noqa: F401 — ensure models loaded
            from app.database import Base, _apply_sqlite_pragmas
            sync_url2 = f"sqlite:///{settings.db_path}"
            sync_engine2 = create_engine(sync_url2, connect_args={"check_same_thread": False, "timeout": 15})
            @sa_event.listens_for(sync_engine2, "connect")
            def _set_pragma2(dbapi_conn, connection_record):
                cur = dbapi_conn.cursor()
                _apply_sqlite_pragmas(cur)
                cur.close()
            try:
                # 1. Create any missing tables (idempotent).
                Base.metadata.create_all(sync_engine2)
                logger.info("migrations: Base.metadata.create_all() completed")
                # 2. Clear stale version and stamp at HEAD.
                with sync_engine2.begin() as conn:
                    conn.execute(sa_text("DELETE FROM alembic_version"))
                logger.info("migrations: cleared stale alembic_version")
                alembic_command.stamp(alembic_cfg, "head")
                logger.info("migrations: stamped at HEAD")
            finally:
                sync_engine2.dispose()

        elif "syntax error" in err or "operationalerror" in err:
            # The squash migration's string-default rendering is incompatible
            # with the local SQLite build (e.g. `DEFAULT (New Chat)` instead of
            # `DEFAULT 'New Chat'`). Fall back to Base.metadata.create_all() to
            # ensure all ORM tables exist, then stamp at HEAD so subsequent
            # migrations run normally. This is safe because create_all is
            # idempotent and only adds missing tables.
            logger.warning(
                "migrations: alembic SQL error (%s) — falling back to Base.metadata.create_all",
                exc,
            )
            from app.models import __init__ as _models_init  # noqa: F401
            from app.database import Base, _apply_sqlite_pragmas
            sync_url2 = f"sqlite:///{settings.db_path}"
            sync_engine2 = create_engine(sync_url2, connect_args={"check_same_thread": False, "timeout": 15})
            @sa_event.listens_for(sync_engine2, "connect")
            def _set_pragma3(dbapi_conn, connection_record):
                cur = dbapi_conn.cursor()
                _apply_sqlite_pragmas(cur)
                cur.close()
            try:
                Base.metadata.create_all(sync_engine2)
                logger.info("migrations: Base.metadata.create_all() completed")
                # Run the seed functions inline so the watchlist data
                # gets created (these normally run later in the lifespan, but
                # only if migrations succeed). Admin creation is owned by
                # POST /api/auth/setup — _ensure_admin_user only logs.
                _ensure_admin_user()
                _ensure_watchlist_data()
                logger.info("migrations: seed functions (watchlist) applied")
                # Stamp at HEAD so the database is marked as up-to-date
                # with the latest migration, permanently breaking any infinite loop.
                alembic_command.stamp(alembic_cfg, "head")
            finally:
                sync_engine2.dispose()

        elif "already exists" in err:
            # Double-boot race: two backends on one DB_PATH ran check-then-
            # create migrations concurrently and the loser hit an existing
            # index/table. The winner already applied it — stamp at HEAD and
            # continue instead of failing this instance's startup.
            logger.warning(
                "migrations: concurrent-boot collision (%s) — stamping at HEAD and continuing",
                exc,
            )
            alembic_command.stamp(alembic_cfg, "head")

        else:
            logger.error("migrations: unhandled migration error: %s", exc)
            raise

    # Safety net: ensure all ORM-defined tables exist.  If a previous
    # handler run stamped at the squash base without actually running the
    # squash migration, tables like 'users' may be missing even though
    # alembic reports no errors.  create_all() is idempotent.
    from app.models import __init__ as _models_init  # noqa: F401
    from app.database import Base as _Base, _apply_sqlite_pragmas as _apply_safety_pragmas
    _safety_url = f"sqlite:///{settings.db_path}"
    _safety_engine = create_engine(_safety_url, connect_args={"check_same_thread": False, "timeout": 15})
    @sa_event.listens_for(_safety_engine, "connect")
    def _set_safety_pragma(dbapi_conn, connection_record):
        cur = dbapi_conn.cursor()
        _apply_safety_pragmas(cur)
        cur.close()
    try:
        before = set(sa_inspect(_safety_engine).get_table_names())
        _Base.metadata.create_all(_safety_engine)
        after = set(sa_inspect(_safety_engine).get_table_names())
        created = after - before
        if created:
            logger.warning("migrations: safety net created missing tables: %s", ', '.join(sorted(created)))
    finally:
        _safety_engine.dispose()


def _ensure_watchlist_data() -> None:
    """Ensure watchlist data consistency after migrations.

    Creates Default watchlist if missing and associates any orphaned
    watchlist_items with it. Handles partial migration runs.
    """
    sync_url = f"sqlite:///{settings.db_path}"
    sync_engine = create_engine(sync_url, connect_args={"check_same_thread": False})

    @sa_event.listens_for(sync_engine, "connect")
    def set_sqlite_pragma(dbapi_conn, connection_record):
        from app.database import _apply_sqlite_pragmas
        cursor = dbapi_conn.cursor()
        _apply_sqlite_pragmas(cursor)
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
                conn.execute(sa_text("INSERT INTO watchlists (id, name, user_id, created_at) VALUES (1, 'Default', 1, CURRENT_TIMESTAMP)"))
                conn.commit()

            result = conn.execute(sa_text("SELECT COUNT(*) FROM watchlist_items WHERE watchlist_id IS NULL"))
            if result.scalar() > 0:
                logger.info("Associating orphaned watchlist items with Default watchlist")
                conn.execute(sa_text("UPDATE watchlist_items SET watchlist_id = 1 WHERE watchlist_id IS NULL"))
                conn.commit()
    finally:
        sync_engine.dispose()


def _ensure_stock_universe() -> None:
    """Pre-seed stock universe on fresh install from bundled assets if table is empty."""
    import json
    import sys
    from datetime import datetime

    sync_url = f"sqlite:///{settings.db_path}"
    sync_engine = create_engine(sync_url, connect_args={"check_same_thread": False})

    @sa_event.listens_for(sync_engine, "connect")
    def set_sqlite_pragma(dbapi_conn, connection_record):
        from app.database import _apply_sqlite_pragmas
        cursor = dbapi_conn.cursor()
        _apply_sqlite_pragmas(cursor)
        cursor.close()

    try:
        with sync_engine.connect() as conn:
            inspector = sa_inspect(conn)
            tables = set(inspector.get_table_names())

            if "stock_universe" not in tables:
                return

            count = conn.execute(sa_text("SELECT COUNT(*) FROM stock_universe")).scalar()
            if count > 0:
                return

            # Determine path to stockuniverse.json
            if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
                asset_path = Path(sys._MEIPASS) / "app" / "assets" / "stockuniverse.json"
            else:
                asset_path = Path(__file__).resolve().parent / "app" / "assets" / "stockuniverse.json"

            if not asset_path.exists():
                logger.warning("_ensure_stock_universe: bundled seed file not found at %s", asset_path)
                return

            logger.info("_ensure_stock_universe: pre-seeding stock universe from %s", asset_path)
            with open(asset_path, "r", encoding="utf-8") as f:
                stocks = json.load(f)

            if not stocks:
                return

            now_str = datetime.now().isoformat()
            # Insert records in batches
            insert_sql = sa_text(
                """
                INSERT OR IGNORE INTO stock_universe (
                    symbol, series, company_name, segment, industry,
                    sector_pe, symbol_pe, industry_info, last_update_time,
                    screener_trades_id, mc_url, review_status, match_confidence,
                    mc_match_source, mc_company_name, morningstar_id, fair_value,
                    fair_value_updated_at, high_52w, low_52w, high_52w_date,
                    low_52w_date, high_52w_updated_at, ticker_failure_count,
                    created_at, updated_at, isin, iinvest_path, iinvest_path_resolved_at
                ) VALUES (
                    :symbol, :series, :company_name, :segment, :industry,
                    :sector_pe, :symbol_pe, :industry_info, :last_update_time,
                    :screener_trades_id, :mc_url, :review_status, :match_confidence,
                    :mc_match_source, :mc_company_name, :morningstar_id, :fair_value,
                    :fair_value_updated_at, :high_52w, :low_52w, :high_52w_date,
                    :low_52w_date, :high_52w_updated_at, :ticker_failure_count,
                    :created_at, :updated_at, :isin, :iinvest_path, :iinvest_path_resolved_at
                )
                """
            )

            # Ensure all keys exist and types are sanitized
            prepared = []
            for s in stocks:
                row = {
                    "symbol": s.get("symbol"),
                    "series": s.get("series"),
                    "company_name": s.get("company_name") or "",
                    "segment": s.get("segment") or "EQUITIES",
                    "industry": s.get("industry") or "",
                    "sector_pe": s.get("sector_pe"),
                    "symbol_pe": s.get("symbol_pe"),
                    "industry_info": s.get("industry_info") if isinstance(s.get("industry_info"), str) else json.dumps(s.get("industry_info") or {}),
                    "last_update_time": s.get("last_update_time") or now_str,
                    "screener_trades_id": s.get("screener_trades_id"),
                    "mc_url": s.get("mc_url"),
                    "review_status": s.get("review_status"),
                    "match_confidence": s.get("match_confidence"),
                    "mc_match_source": s.get("mc_match_source"),
                    "mc_company_name": s.get("mc_company_name"),
                    "morningstar_id": s.get("morningstar_id"),
                    "fair_value": s.get("fair_value"),
                    "fair_value_updated_at": s.get("fair_value_updated_at"),
                    "high_52w": s.get("high_52w"),
                    "low_52w": s.get("low_52w"),
                    "high_52w_date": s.get("high_52w_date"),
                    "low_52w_date": s.get("low_52w_date"),
                    "high_52w_updated_at": s.get("high_52w_updated_at"),
                    "ticker_failure_count": s.get("ticker_failure_count") or 0,
                    "created_at": s.get("created_at") or now_str,
                    "updated_at": s.get("updated_at") or now_str,
                    "isin": s.get("isin"),
                    "iinvest_path": s.get("iinvest_path"),
                    "iinvest_path_resolved_at": s.get("iinvest_path_resolved_at"),
                }
                prepared.append(row)

            # Batch execution
            batch_size = 500
            for i in range(0, len(prepared), batch_size):
                conn.execute(insert_sql, prepared[i:i + batch_size])
            conn.commit()
            logger.info("_ensure_stock_universe: successfully seeded %d stocks", len(prepared))
    except Exception:
        logger.exception("_ensure_stock_universe: failed to pre-seed stock universe")
    finally:
        sync_engine.dispose()


def _ensure_ai_provider_routes() -> None:
    """Ensure all eight OAuth routes are seeded idempotently with stable prefixes."""
    from app.services.route_registry import seed_oauth_routes_sync
    sync_url = f"sqlite:///{settings.db_path}"
    sync_engine = create_engine(sync_url, connect_args={"check_same_thread": False})

    @sa_event.listens_for(sync_engine, "connect")
    def set_sqlite_pragma(dbapi_conn, connection_record):
        from app.database import _apply_sqlite_pragmas
        cursor = dbapi_conn.cursor()
        _apply_sqlite_pragmas(cursor)
        cursor.close()

    try:
        with sync_engine.connect() as conn:
            inspector = sa_inspect(conn)
            tables = set(inspector.get_table_names())
            if "ai_provider_routes" in tables:
                seed_oauth_routes_sync(conn)
                conn.commit()
    except Exception:
        logger.exception("_ensure_ai_provider_routes: failed to ensure OAuth provider routes")
    finally:
        sync_engine.dispose()


def _ensure_user_columns() -> None:
    """Add missing user_id columns to watchlists and chat_sessions.

    Older DBs may have been created before the user-scoping migration.
    SQLite's ALTER TABLE ADD COLUMN is idempotent (errors if column exists).
    All existing rows are backfilled to user_id=1 (the admin user).
    """
    import sqlite3
    from app.database import _apply_sqlite_pragmas

    db_path = Path(settings.db_path)
    if not db_path.exists():
        return

    conn = sqlite3.connect(str(db_path), timeout=15, check_same_thread=False, isolation_level=None)
    cur = conn.cursor()
    _apply_sqlite_pragmas(cur)
    cur.close()
    try:
        for table in ("watchlists", "chat_sessions"):
            try:
                conn.execute(
                    f"ALTER TABLE {table} ADD COLUMN user_id INTEGER NOT NULL DEFAULT 1"
                )
                # Backfill any existing rows that got NULL (shouldn't with DEFAULT but be safe)
                conn.execute(
                    f"UPDATE {table} SET user_id = 1 WHERE user_id IS NULL"
                )
                conn.commit()
                logger.info("_ensure_user_columns: added user_id to %s", table)
            except sqlite3.OperationalError:
                pass  # column already exists — fine
    finally:
        conn.close()


def _ensure_user_layouts_columns() -> None:
    """Add missing deleted_at column to user_layouts if table exists.

    Handles existing DBs where user_layouts table was created before tombstones.
    SQLite's ALTER TABLE ADD COLUMN is idempotent (errors if column exists).
    """
    import sqlite3
    from app.database import _apply_sqlite_pragmas

    db_path = Path(settings.db_path)
    if not db_path.exists():
        return

    conn = sqlite3.connect(str(db_path), timeout=15, check_same_thread=False, isolation_level=None)
    cur = conn.cursor()
    _apply_sqlite_pragmas(cur)
    cur.close()
    try:
        try:
            conn.execute("ALTER TABLE user_layouts ADD COLUMN deleted_at BIGINT NULL")
            conn.commit()
            logger.info("_ensure_user_layouts_columns: added deleted_at to user_layouts")
        except sqlite3.OperationalError:
            pass  # column already exists or table doesn't exist yet — fine
    finally:
        conn.close()


def _migrate_deprecated_gemini_models() -> None:
    """Migrate legacy Gemini models in system_config and chat_sessions to Gemini 3.8 Flash tiers.

    Google now exclusively supports Gemini 3.8 Flash (High, Medium, and Low tiers).
    This function migrates historical database rows to avoid 404/400 errors from
    Google Cloud Code / Antigravity endpoints.
    """
    import sqlite3
    from app.database import _apply_sqlite_pragmas

    db_path = Path(settings.db_path)
    if not db_path.exists():
        return

    conn = sqlite3.connect(str(db_path), timeout=15, check_same_thread=False, isolation_level=None)
    cur = conn.cursor()
    _apply_sqlite_pragmas(cur)
    cur.close()
    try:
        # 1. Update system_config
        hunter_row = conn.execute("SELECT value FROM system_config WHERE key = 'ai.hunter_model'").fetchone()
        if hunter_row and hunter_row[0] and hunter_row[0].startswith("gemini"):
            val = hunter_row[0]
            if val not in ("gemini-3.8-flash-high", "gemini-3.8-flash-medium", "gemini-3.8-flash-low"):
                new_val = "gemini-3.8-flash-high"
                if val.endswith("-medium"):
                    new_val = "gemini-3.8-flash-medium"
                elif val.endswith("-low"):
                    new_val = "gemini-3.8-flash-low"
                conn.execute("UPDATE system_config SET value = ? WHERE key = 'ai.hunter_model'", (new_val,))
                logger.info("_migrate_deprecated_gemini_models: updated ai.hunter_model from %s to %s", val, new_val)

        verifier_row = conn.execute("SELECT value FROM system_config WHERE key = 'ai.verifier_model'").fetchone()
        if verifier_row and verifier_row[0] and verifier_row[0].startswith("gemini"):
            val = verifier_row[0]
            if val not in ("gemini-3.8-flash-high", "gemini-3.8-flash-medium", "gemini-3.8-flash-low"):
                new_val = "gemini-3.8-flash-low"
                if val.endswith("-high"):
                    new_val = "gemini-3.8-flash-high"
                elif val.endswith("-medium"):
                    new_val = "gemini-3.8-flash-medium"
                conn.execute("UPDATE system_config SET value = ? WHERE key = 'ai.verifier_model'", (new_val,))
                logger.info("_migrate_deprecated_gemini_models: updated ai.verifier_model from %s to %s", val, new_val)

        # 2. Update chat_sessions
        sessions = conn.execute("SELECT id, model FROM chat_sessions WHERE model LIKE 'gemini%'").fetchall()
        for sess_id, model in sessions:
            if model not in ("gemini-3.8-flash-high", "gemini-3.8-flash-medium", "gemini-3.8-flash-low"):
                if model.endswith("-high"):
                    new_m = "gemini-3.8-flash-high"
                elif model.endswith("-medium"):
                    new_m = "gemini-3.8-flash-medium"
                else:
                    new_m = "gemini-3.8-flash-low"
                conn.execute("UPDATE chat_sessions SET model = ? WHERE id = ?", (new_m, sess_id))
                logger.info("_migrate_deprecated_gemini_models: updated chat_session %s model from %s to %s", sess_id, model, new_m)
        conn.commit()

    except Exception:
        logger.exception("_migrate_deprecated_gemini_models: migration failed")
    finally:
        conn.close()


def _ensure_admin_user() -> None:
    """No-op placeholder kept for lifespan ordering.

    First-boot admin creation is owned by the frontend setup wizard via
    ``POST /api/auth/setup`` (single-use, empty-users-table only). No default
    credential is ever written here — an empty users table means "first boot,
    setup required", which ``GET /api/auth/setup-status`` reports to clients.
    """
    import sqlite3
    from app.database import _apply_sqlite_pragmas

    db_path = Path(settings.db_path)
    if not db_path.exists():
        return

    conn = sqlite3.connect(str(db_path), timeout=15, check_same_thread=False, isolation_level=None)
    cur = conn.cursor()
    _apply_sqlite_pragmas(cur)
    cur.close()
    try:
        count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        if count == 0:
            logger.info("_ensure_admin_user: no users found — first-boot setup required (see POST /api/auth/setup)")
    except Exception:
        logger.exception("_ensure_admin_user: failed")
    finally:
        conn.close()


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
    Respects LOG_DIR environment variable or settings.log_dir for OS-safe desktop logs.
    """
    if settings.log_dir:
        log_dir = Path(settings.log_dir)
    else:
        log_dir = Path(__file__).resolve().parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
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

    from app.database import _apply_sqlite_pragmas
    conn = sqlite3.connect(str(db_path), timeout=15, check_same_thread=False, isolation_level=None)
    cur = conn.cursor()
    _apply_sqlite_pragmas(cur)
    cur.close()
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
    await asyncio.to_thread(_ensure_user_columns)
    await asyncio.to_thread(_ensure_user_layouts_columns)
    await asyncio.to_thread(_ensure_admin_user)
    await asyncio.to_thread(_ensure_watchlist_data)
    await asyncio.to_thread(_ensure_stock_universe)
    await asyncio.to_thread(_ensure_ai_provider_routes)
    await asyncio.to_thread(_backfill_entities_double_encoding)
    await asyncio.to_thread(_migrate_deprecated_gemini_models)

    # Run legacy provider, model, and token migrations (must run after DB migration and route seeding)
    try:
        from app.database import AsyncSessionLocal
        from app.services.legacy_migration import run_all_legacy_migrations
        from app.services.provider_vault import get_provider_vault
        async with AsyncSessionLocal() as session:
            vault = get_provider_vault()
            await vault.initialize()
            await run_all_legacy_migrations(vault, session)
    except Exception as mig_exc:
        logger.warning("Startup legacy migration warning: %s", mig_exc)

    # Start the priority write queue writer thread (serialises non-critical writes)
    from app.services.write_queue import start_writer
    start_writer()

    # alembic/env.py calls fileConfig(alembic.ini) during migrations which
    # resets the root logger to WARNING/stderr-only.  Restore our handlers now.
    _configure_logging()

    logger.info("Database schema up to date")
    cleanup_task = await start_cache_cleanup()

    await screener_client.init()
    await news_fetcher.init()

    # iinvest: lazy init in background — do NOT block FastAPI lifespan!
    async def _init_iinvest_bg():
        try:
            from app.services.iinvest_client import get_iinvest_client
            await get_iinvest_client().init()
            logger.info("iinvest: client initialized in background")
        except Exception as exc:
            logger.warning("iinvest: background init failed: %s", exc)

    asyncio.create_task(_init_iinvest_bg())

    # Warm browser: background task — do NOT block FastAPI lifespan!
    async def _start_warm_browser_bg():
        try:
            from app.services.browser_harvester import (
                ensure_warm_browser,
                get_consent_status,
            )

            if await get_consent_status():
                ensure_warm_browser()
                logger.info("WarmBrowser: startup requested (consented)")
            else:
                logger.info("WarmBrowser: skipped (no advanced consent)")
        except Exception as exc:
            logger.warning("WarmBrowser: startup failed (cold path still works): %s", exc)

    asyncio.create_task(_start_warm_browser_bg())

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
            "AI Summarizer is not configured. News and Announcement summaries will not work. "
            "Set AI_API_KEY (and optionally AI_API_BASE_URL, AI_MODEL) in .env."
        )

    # Clean up stale proxy runtime dirs at startup
    try:
        from app.services.proxy_supervisor import get_proxy_supervisor
        get_proxy_supervisor().cleanup_stale_runtimes()
    except Exception as exc:
        logger.warning("ProxySupervisor: startup stale cleanup error: %s", exc)

    yield

    try:
        from app.services.proxy_supervisor import get_proxy_supervisor, SupervisorState
        supervisor = get_proxy_supervisor()
        if supervisor.state != SupervisorState.STOPPED or (supervisor.runtime_dir and supervisor.runtime_dir.exists()):
            await supervisor.stop(permanent=True)
            logger.info("ProxySupervisor: stopped on shutdown")
    except Exception as exc:
        logger.debug("ProxySupervisor: shutdown error: %s", exc)

    logger.info("Shutting down — cancelling background tasks...")
    cleanup_task.cancel()

    logger.info("Shutting down — stopping workers and closing clients...")
    await orchestrator.stop()

    # Drain and stop the write queue writer
    from app.services.write_queue import stop_writer
    stop_writer(timeout=10.0)

    try:
        from app.services.browser_harvester import shutdown_warm_browser
        await asyncio.to_thread(shutdown_warm_browser)
        logger.info("WarmBrowser: stopped on shutdown")
    except Exception as exc:
        logger.debug("WarmBrowser: shutdown error (non-fatal): %s", exc)

    try:
        from app.services.oauth_session_manager import get_oauth_session_manager
        await get_oauth_session_manager().shutdown()
        logger.info("OAuthSessionManager: stopped on shutdown")
    except Exception as exc:
        logger.debug("OAuthSessionManager: shutdown error: %s", exc)

    from app.services.llm_provider import cleanup_shared_clients
    await cleanup_shared_clients()




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

# CORS — locked down (Step 5): the renderer always talks to the backend through
# the same-origin Next.js proxy (/api/py/*), never cross-origin from a browser,
# so no browser origin is allowed. Direct browser access is removed; loopback
# HTTP clients (proxies, CLIs, tests) are unaffected by CORS.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[],
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
# Per-launch token (Step 5): the Electron parent writes one line on stdin,
# then EOF. Dev direct-run may set BLM_LAUNCH_TOKEN. Without either, the API
# runs OPEN with a loud warning (packaged runs always receive the token).
# Registered AFTER log_requests so it runs FIRST (outermost).
# /health stays open for diagnostics; everything else needs x-blm-token.
# WebSocket streams (public market/news data) are Host-checked by the Next.js
# upgrade layer + loopback bind here; they carry no token by browser design.
# ---------------------------------------------------------------------------
import os as _os
import secrets as _secrets


def _read_stdin_token(timeout_s: float = 3.0) -> str:
    import sys as _sys
    import threading as _threading

    box: list[str] = []

    def _rd() -> None:
        try:
            box.append(_sys.stdin.readline())
        except Exception:
            pass

    t = _threading.Thread(target=_rd, daemon=True)
    t.start()
    t.join(timeout_s)
    return (box[0] if box else "").strip()


LAUNCH_TOKEN = _read_stdin_token() or _os.environ.get("BLM_LAUNCH_TOKEN") or None
INTERNAL_TOKEN = _os.environ.get("BLM_INTERNAL_TOKEN") or None

logger = logging.getLogger("blm")
if LAUNCH_TOKEN:
    logger.info("Launch token armed (%d chars)", len(LAUNCH_TOKEN))
else:
    logger.warning(
        "BLM launch token absent (no stdin token, no BLM_LAUNCH_TOKEN): "
        "local API running OPEN — dev only, packaged runs always receive a token"
    )
if INTERNAL_TOKEN:
    logger.info("Internal server token armed (%d chars)", len(INTERNAL_TOKEN))


@app.middleware("http")
async def launch_token_guard(request: Request, call_next) -> Response:  # type: ignore[type-arg]
    """Reject token-less local API calls (401). /health stays open."""
    if request.url.path != "/health":
        has_launch_token = bool(
            LAUNCH_TOKEN
            and _secrets.compare_digest(
                request.headers.get("x-blm-token", ""), LAUNCH_TOKEN
            )
        )
        internal_header = request.headers.get("x-blm-server-token") or request.headers.get("x-blm-internal-token")
        has_internal_token = bool(
            INTERNAL_TOKEN
            and internal_header
            and _secrets.compare_digest(internal_header, INTERNAL_TOKEN)
        )
        if not (has_launch_token or has_internal_token):
            return JSONResponse(status_code=401, content={"error": "missing or invalid launch token"})
    return await call_next(request)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

app.include_router(ai_chat_router, prefix="/api")
app.include_router(ai_routes_router, prefix="/api")
app.include_router(ai_routes_router)
app.include_router(ai_picks_router, prefix="/api")
app.include_router(ai_summarizer_router, prefix="/api")
app.include_router(announcements_router, prefix="/api")
app.include_router(breakouts_router, prefix="/api")
app.include_router(filings_router, prefix="/api")
app.include_router(markets_router, prefix="/api")
app.include_router(morningstar_router, prefix="/api")
app.include_router(market_router, prefix="/api")
app.include_router(news_router, prefix="/api")
# WebSocket routers mounted at /ws (no api prefix)
app.include_router(news_ws_router, prefix="/ws")
app.include_router(market_ws_router, prefix="/ws")
app.include_router(screener_router, prefix="/api")
app.include_router(iinvest_router, prefix="/api")
app.include_router(tradingview_router.router, prefix="/api")
app.include_router(system_config_router, prefix="/api")
# First-boot flag: token-gated only (must work pre-login on fresh machines).
app.include_router(first_boot_router, prefix="/api")
app.include_router(stockuniverse_router, prefix="/api")
app.include_router(stockuniverse_errors_router, prefix="/api")
app.include_router(watchlist_router, prefix="/api")
app.include_router(layout_router, prefix="/api")
app.include_router(scripts_router, prefix="/api")
app.include_router(valuation_router, prefix="/api")
app.include_router(portfolio_router, prefix="/api")
app.include_router(paper_trades_router, prefix="/api")
app.include_router(notifications_router, prefix="/api")
app.include_router(jobs_router, prefix="/api")
from app.routers.ticker import router as ticker_router
app.include_router(ticker_router, prefix="/api")
app.include_router(auth_router, prefix="/api")
app.include_router(users_router, prefix="/api")

if settings.is_development:
    from app.routers.notifications import _dev_router
    app.include_router(_dev_router, prefix="/api")


@app.get("/health", tags=["meta"])
async def health() -> dict[str, str]:
    """Service health check."""
    return {"status": "ok"}


from app.routers.system_config import admin_shutdown_router, internal_router
app.include_router(admin_shutdown_router, prefix="/api")
app.include_router(admin_shutdown_router)
app.include_router(internal_router, prefix="/api")
app.include_router(internal_router)


if __name__ == "__main__":
    import socket as _socket
    import sys as _sys
    import uvicorn

    # Ephemeral by default (Step 5/A6): PORT unset or 0 binds a free loopback
    # port and reports BLM_BACKEND_PORT=<n> on stdout for the Electron parent.
    # Explicit PORT (launch scripts, uvicorn CLI) keeps working unchanged.
    requested = int(_os.environ.get("PORT", "0") or 0)
    if not requested:
        _sock = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
        _sock.bind(("127.0.0.1", 0))
        requested = _sock.getsockname()[1]
        _sock.close()

    print(f"BLM_BACKEND_PORT={requested}", flush=True)
    _sys.stdout.flush()

    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=requested,
        reload=False,
        log_config=None,
        forwarded_allow_ips="*",
    )
    server = uvicorn.Server(config)
    app.state.server = server
    server.run()
