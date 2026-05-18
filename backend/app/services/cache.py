"""
Shared caching layer for the BLM backend.

Provides two backends:

1. In-process cache: cachetools.TTLCache
   - Thread-safe (RLock internally)
   - Per-process — NOT shared across workers
   - Best for: single-worker deployments

2. SQLite shared cache: SQLiteCache (v1.2 fixes applied)
   - Shared across all workers on the same machine
   - Uses WAL mode for concurrent reads during writes
   - RLock used instead of Lock to prevent deadlock in pop()
   - time.time() used instead of time.monotonic() for cross-process TTL
   - Zero additional dependencies
   - Best for: multi-worker deployments
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import tempfile
import threading
import time
from typing import Any

from cachetools import TTLCache as _TTLCache

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 1. In-process cache — cachetools (single-worker)
# ---------------------------------------------------------------------------

nse_cache = _TTLCache(maxsize=200, ttl=600.0)
screener_html_cache = _TTLCache(maxsize=500, ttl=900.0)
screener_search_cache = _TTLCache(maxsize=200, ttl=60.0)
mcp_cache = _TTLCache(maxsize=200, ttl=600.0)


# ---------------------------------------------------------------------------
# 2. SQLite shared cache — v1.2 fixes applied
# ---------------------------------------------------------------------------

class SQLiteCache:
    """
    A SQLite-backed key-value cache shared across uvicorn workers.
    
    Uses WAL mode so reads don't block writes.
    TTL uses wall-clock time (time.time()) so it is consistent across processes.
    RLock is used instead of Lock to prevent deadlock in pop().
    """

    _DDL = """
    CREATE TABLE IF NOT EXISTS shared_cache (
        key       TEXT PRIMARY KEY,
        value     TEXT NOT NULL,
        expires_at REAL NOT NULL,
        created_at REAL NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_expires ON shared_cache(expires_at);
    """

    def __init__(
        self,
        db_path: str | None = None,
        max_size: int = 1000,
        default_ttl: float = 600.0,
    ) -> None:
        self._db_path = db_path or os.path.join(tempfile.gettempdir(), "blm_shared_cache.db")
        self._max_size = max_size
        self._default_ttl = default_ttl

        self._lock = threading.RLock()

        self._local = threading.local()

        with self._get_conn() as conn:
            conn.executescript(self._DDL)
            conn.commit()

    def _get_conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            conn = sqlite3.connect(
                self._db_path,
                timeout=10.0,
                check_same_thread=False,
            )
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            self._local.conn = conn
        return self._local.conn

    def get(self, key: str) -> Any | None:
        """Get a value. Returns None if missing, expired, or on error."""
        with self._lock:
            try:
                conn = self._get_conn()
                now = time.time()
                row = conn.execute(
                    "SELECT value, expires_at FROM shared_cache WHERE key = ?",
                    (key,),
                ).fetchone()

                if row is None:
                    return None

                value_json, expires_at = row
                if now >= expires_at:
                    conn.execute("DELETE FROM shared_cache WHERE key = ?", (key,))
                    conn.commit()
                    return None

                return json.loads(value_json)

            except Exception:
                logger.debug("SQLiteCache.get('%s') failed", key)
                return None

    def set(self, key: str, value: Any, ttl: float | None = None) -> None:
        """Set a value with TTL. Overwrites existing."""
        with self._lock:
            try:
                conn = self._get_conn()
                now = time.time()
                effective_ttl = ttl if ttl is not None else self._default_ttl
                expires_at = now + effective_ttl
                value_json = json.dumps(value)

                conn.execute(
                    "INSERT OR REPLACE INTO shared_cache (key, value, expires_at, created_at) "
                    "VALUES (?, ?, ?, ?)",
                    (key, value_json, expires_at, now),
                )
                conn.commit()

                count_row = conn.execute("SELECT COUNT(*) FROM shared_cache").fetchone()
                if count_row and count_row[0] > self._max_size:
                    conn.execute(
                        "DELETE FROM shared_cache WHERE expires_at < ?",
                        (now,),
                    )
                    remaining = conn.execute("SELECT COUNT(*) FROM shared_cache").fetchone()[0]
                    if remaining > self._max_size:
                        to_delete = remaining - self._max_size
                        conn.execute(
                            f"DELETE FROM shared_cache WHERE key IN "
                            f"(SELECT key FROM shared_cache ORDER BY created_at ASC LIMIT {to_delete})"
                        )
                    conn.commit()

            except Exception:
                logger.debug("SQLiteCache.set('%s') failed", key)

    def pop(self, key: str, default: Any = None) -> Any | None:
        """
        Delete a key and return the value (or default if missing).
        
        Uses threading.RLock to prevent deadlock — pop() holds the lock
        while calling _get_conn(), and _get_conn() also uses the lock.
        """
        with self._lock:
            try:
                conn = self._get_conn()
                now = time.time()
                row = conn.execute(
                    "SELECT value, expires_at FROM shared_cache WHERE key = ?",
                    (key,),
                ).fetchone()
                conn.execute("DELETE FROM shared_cache WHERE key = ?", (key,))
                conn.commit()

                if row is None:
                    return default

                value_json, expires_at = row
                if now >= expires_at:
                    return default

                return json.loads(value_json)

            except Exception:
                logger.debug("SQLiteCache.pop('%s') failed", key)
                return default

    def __len__(self) -> int:
        with self._lock:
            conn = self._get_conn()
            now = time.time()
            row = conn.execute(
                "SELECT COUNT(*) FROM shared_cache WHERE expires_at >= ?",
                (now,),
            ).fetchone()
            return row[0] if row else 0

    def clear(self) -> None:
        with self._lock:
            conn = self._get_conn()
            conn.execute("DELETE FROM shared_cache")
            conn.commit()


_shared_cache: SQLiteCache | None = None
_shared_cache_lock = threading.Lock()


def get_shared_cache() -> SQLiteCache:
    """Get the singleton shared SQLite cache."""
    global _shared_cache
    if _shared_cache is None:
        with _shared_cache_lock:
            if _shared_cache is None:
                cache_db_path = os.getenv("SHARED_CACHE_DB", os.path.join(tempfile.gettempdir(), "blm_shared_cache.db"))
                _shared_cache = SQLiteCache(cache_db_path)
                logger.info("SQLite shared cache initialized at %s", cache_db_path)
    return _shared_cache
