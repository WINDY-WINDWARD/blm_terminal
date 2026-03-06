"""SQLite-backed persistent cache for NSE historical CSV data.

A separate DB file (nse_history_cache.db) is used intentionally to avoid
mixing stdlib sqlite3 (sync) with the main aiosqlite async connection on
data.db, which would risk WAL-mode lock contention.

TTL rules
---------
* to_date < today  →  permanent (historical data never changes)
* to_date >= today →  expires after ``nse_history_cache_ttl_hours`` hours
"""
from __future__ import annotations

import logging
import sqlite3
import threading
import time
from datetime import date
from io import StringIO

import pandas as pd

from app.config import settings

logger = logging.getLogger(__name__)

_DATE_FMT = "%d-%m-%Y"


class NseHistoryCache:
    """Persistent, self-contained SQLite cache for `fetch_nse_historical_csv` results."""

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or settings.nse_history_cache_path
        self._ttl_seconds = settings.nse_history_cache_ttl_hours * 3600
        self._local = threading.local()
        # Create the table using a temporary bootstrap connection so the schema
        # exists before any thread calls _get_conn() for the first time.
        bootstrap = sqlite3.connect(self._db_path)
        try:
            bootstrap.execute("PRAGMA journal_mode=WAL;")
            bootstrap.execute(
                """
                CREATE TABLE IF NOT EXISTS nse_historical_cache (
                    symbol    TEXT NOT NULL,
                    from_date TEXT NOT NULL,
                    to_date   TEXT NOT NULL,
                    csv_data  TEXT NOT NULL,
                    cached_at REAL NOT NULL,
                    PRIMARY KEY (symbol, from_date, to_date)
                )
                """
            )
            bootstrap.commit()
        finally:
            bootstrap.close()
        logger.debug("NseHistoryCache initialised at %s", self._db_path)

    def _get_conn(self) -> sqlite3.Connection:
        """Return the connection for the current thread, creating one if needed."""
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self._db_path)
            conn.execute("PRAGMA journal_mode=WAL;")
            self._local.conn = conn
        return conn

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _is_stale(self, to_date_str: str, cached_at: float) -> bool:
        """Return True only when the entry should be considered expired.

        Historical ranges (to_date < today) are never stale.
        Ranges that include today expire after the configured TTL.
        """
        try:
            to_dt = date(
                int(to_date_str[6:10]),
                int(to_date_str[3:5]),
                int(to_date_str[0:2]),
            )
        except (ValueError, IndexError):
            # Unparseable date — treat as stale so it is refreshed
            return True
        if to_dt < date.today():
            return False  # permanent — historical data is immutable
        return (time.time() - cached_at) > self._ttl_seconds

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, symbol: str, from_date: str, to_date: str) -> pd.DataFrame | None:
        """Return cached DataFrame or None on a miss / stale entry."""
        cur = self._get_conn().execute(
            "SELECT csv_data, cached_at FROM nse_historical_cache "
            "WHERE symbol = ? AND from_date = ? AND to_date = ?",
            (symbol.upper(), from_date, to_date),
        )
        row = cur.fetchone()
        if row is None:
            return None
        csv_data, cached_at = row
        if self._is_stale(to_date, cached_at):
            logger.debug("Cache stale for %s %s→%s", symbol, from_date, to_date)
            return None
        logger.debug("Cache hit for %s %s→%s", symbol, from_date, to_date)
        return pd.read_csv(StringIO(csv_data))

    def set(self, symbol: str, from_date: str, to_date: str, df: pd.DataFrame) -> None:
        """Persist a DataFrame for the given key."""
        csv_data = df.to_csv(index=False)
        conn = self._get_conn()
        conn.execute(
            """
            INSERT OR REPLACE INTO nse_historical_cache
                (symbol, from_date, to_date, csv_data, cached_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (symbol.upper(), from_date, to_date, csv_data, time.time()),
        )
        conn.commit()
        logger.debug("Cache stored for %s %s→%s", symbol, from_date, to_date)

    def evict_expired(self) -> int:
        """Delete only non-permanent entries whose TTL has elapsed.

        Historical rows (to_date < today) are never deleted.
        Returns the number of rows removed.
        """
        today_str = date.today().strftime(_DATE_FMT)
        conn = self._get_conn()
        # Fetch volatile rows (to_date on or after today) and check TTL individually
        cur = conn.execute(
            "SELECT symbol, from_date, to_date, cached_at FROM nse_historical_cache "
            "WHERE to_date >= ?",
            (today_str,),
        )
        rows = cur.fetchall()
        removed = 0
        for symbol, from_date, to_date, cached_at in rows:
            if self._is_stale(to_date, cached_at):
                conn.execute(
                    "DELETE FROM nse_historical_cache "
                    "WHERE symbol = ? AND from_date = ? AND to_date = ?",
                    (symbol, from_date, to_date),
                )
                removed += 1
        if removed:
            conn.commit()
            logger.info("NseHistoryCache evicted %d stale row(s)", removed)
        return removed

    def close(self) -> None:
        """Close the current thread's SQLite connection, if open."""
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None


# Module-level singleton — imported by customrequests.py
nse_history_cache = NseHistoryCache()
