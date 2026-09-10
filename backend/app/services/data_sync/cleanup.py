"""Daily DB cleanup suite (Phase C.1, A.12 part 1).

Implements the once-per-24h ``_run_cleanup_if_due`` background task
that hard-deletes:

  - read notifications older than ``CLEANUP_READ_AFTER_DAYS``
  - news articles older than ``NEWS_RETENTION_DAYS``
  - 1h intraday candles older than ``INTRADAY_1H_RETENTION_DAYS``
  - weekly (W) intraday candles older than ``INTRADAY_W_RETENTION_YEARS``

Monthly (M) candles are never pruned (small footprint, useful for
long-term charts).  Errors in any single pruner are logged and do
not prevent the others from running.

The ``_cleanup_last_run`` module-level timestamp guards against
running more often than ``CLEANUP_INTERVAL``.

Migrated from ``app.backgroundtasks._impl`` (audit C.1, A.12 part 1).
"""
import logging
from datetime import datetime, timedelta

from sqlalchemy import delete, text

from app.models.notification import Notification


logger = logging.getLogger(__name__)

# Imported lazily inside the function body to break the circular
# dependency: ``app.backgroundtasks.__init__`` (the shim) imports
# ``_run_cleanup_if_due`` from this module, so we cannot import
# ``app.backgroundtasks._impl`` at module level here.  See
# ``tests/test_backgroundtasks_split.py`` for the shim contract.


CLEANUP_READ_AFTER_DAYS = 30
CLEANUP_INTERVAL = 24 * 60 * 60

# Phase C: data-retention policies for high-volume tables
NEWS_RETENTION_DAYS = 30
INTRADAY_1H_RETENTION_DAYS = 30
INTRADAY_W_RETENTION_YEARS = 2
# Monthly (M) candles: kept forever (small footprint, useful for long-term charts)


_cleanup_last_run: datetime | None = None


def _run_cleanup_if_due() -> None:
    """Run the daily cleanup suite.

    - Hard-delete read notifications older than CLEANUP_READ_AFTER_DAYS
    - Phase C: hard-delete news_articles older than NEWS_RETENTION_DAYS
    - Phase C: prune ticker_intraday 1h bars older than INTRADAY_1H_RETENTION_DAYS
    - Phase C: prune ticker_intraday W bars older than INTRADAY_W_RETENTION_YEARS
    - Monthly bars are never pruned.

    Runs at most once per CLEANUP_INTERVAL to avoid unnecessary DB writes.
    Errors in any single pruner are logged and do not prevent the others.
    """
    global _cleanup_last_run
    now = datetime.now()
    if _cleanup_last_run is not None and (now - _cleanup_last_run).total_seconds() < CLEANUP_INTERVAL:
        return

    # Lazy import to break the circular dep with the shim.
    from app.database import _SyncSessionLocal, _sync_engine

    # 1) notifications
    try:
        cutoff = datetime.combine(now.date() - timedelta(days=CLEANUP_READ_AFTER_DAYS), datetime.min.time())
        with _SyncSessionLocal() as session:
            deleted = session.execute(
                delete(Notification).where(
                    Notification.is_read == True,
                    Notification.triggered_at < cutoff,
                )
            )
            session.commit()
            if deleted.rowcount > 0:
                logger.info(
                    "notification_cleanup: deleted %d read notifications older than %s",
                    deleted.rowcount,
                    cutoff.date(),
                )
    except Exception:
        logger.exception("notification_cleanup: failed (non-fatal)")

    # 2) news articles (full row hard-delete) — use raw SQL for speed
    #    (SQLAlchemy ORM delete() does a SELECT-then-DELETE-per-row)
    try:
        news_cutoff = now - timedelta(days=NEWS_RETENTION_DAYS)
        with _SyncSessionLocal() as session:
            deleted = session.execute(
                text("DELETE FROM news_articles WHERE publish_date < :cutoff"),
                {"cutoff": news_cutoff},
            )
            session.commit()
            if deleted.rowcount > 0:
                logger.info(
                    "news_cleanup: deleted %d articles older than %s",
                    deleted.rowcount, news_cutoff.date(),
                )
    except Exception:
        logger.exception("news_cleanup: failed (non-fatal)")

    # 3) intraday 1h — chunked DELETE so the WAL lock is held briefly per batch
    try:
        cutoff_1h = now - timedelta(days=INTRADAY_1H_RETENTION_DAYS)
        total_1h = 0
        for _ in range(50):  # up to 50 batches per cleanup cycle
            with _SyncSessionLocal() as session:
                deleted = session.execute(
                    text(
                        "DELETE FROM ticker_intraday WHERE rowid IN ("
                        "  SELECT rowid FROM ticker_intraday "
                        "  WHERE interval = '1h' AND timestamp < :cutoff "
                        "  LIMIT 50000"
                        ")"
                    ),
                    {"cutoff": cutoff_1h},
                )
                session.commit()
                count = deleted.rowcount
            total_1h += count
            if count < 50000:
                break
        if total_1h > 0:
            logger.info(
                "intraday_cleanup: deleted %d 1h candles older than %s",
                total_1h, cutoff_1h,
            )
    except Exception:
        logger.exception("intraday_1h_cleanup: failed (non-fatal)")

    # 4) intraday W
    try:
        cutoff_w = now - timedelta(days=365 * INTRADAY_W_RETENTION_YEARS)
        total_W = 0
        for _ in range(50):
            with _SyncSessionLocal() as session:
                deleted = session.execute(
                    text(
                        "DELETE FROM ticker_intraday WHERE rowid IN ("
                        "  SELECT rowid FROM ticker_intraday "
                        "  WHERE interval = 'W' AND timestamp < :cutoff "
                        "  LIMIT 50000"
                        ")"
                    ),
                    {"cutoff": cutoff_w},
                )
                session.commit()
                count = deleted.rowcount
            total_W += count
            if count < 50000:
                break
        if total_W > 0:
            logger.info(
                "intraday_cleanup: deleted %d W candles older than %s",
                total_W, cutoff_w.date(),
            )
    except Exception:
        logger.exception("intraday_W_cleanup: failed (non-fatal)")

    # 4b) intraday 1m, 5m, 15m older than 30 days (Desktop Storage Hygiene)
    try:
        cutoff_sub1h = now - timedelta(days=30)
        total_sub1h = 0
        for _ in range(50):
            with _SyncSessionLocal() as session:
                deleted = session.execute(
                    text(
                        "DELETE FROM ticker_intraday WHERE rowid IN ("
                        "  SELECT rowid FROM ticker_intraday "
                        "  WHERE interval IN ('1m', '5m', '15m', '30m') AND timestamp < :cutoff "
                        "  LIMIT 50000"
                        ")"
                    ),
                    {"cutoff": cutoff_sub1h},
                )
                session.commit()
                count = deleted.rowcount
            total_sub1h += count
            if count < 50000:
                break
        if total_sub1h > 0:
            logger.info(
                "intraday_cleanup: deleted %d intraday sub-hour candles older than %s",
                total_sub1h, cutoff_sub1h,
            )
    except Exception:
        logger.exception("intraday_sub1h_cleanup: failed (non-fatal)")

    # 5) breakout_snapshots — retain ~14 calendar days (~10 trading days)
    try:
        cutoff_bs = now - timedelta(days=14)
        with _SyncSessionLocal() as session:
            deleted = session.execute(
                text(
                    "DELETE FROM breakout_snapshots WHERE rowid IN ("
                    "  SELECT rowid FROM breakout_snapshots "
                    "  WHERE snapshot_date < :cutoff "
                    "  LIMIT 50000"
                    ")"
                ),
                {"cutoff": cutoff_bs.date()},
            )
            session.commit()
            if deleted.rowcount > 0:
                logger.info(
                    "breakout_snapshot_cleanup: deleted %d snapshots older than %s",
                    deleted.rowcount, cutoff_bs.date(),
                )
    except Exception:
        logger.exception("breakout_snapshot_cleanup: failed (non-fatal)")

    # 6) Vacuum database to reclaim physical disk space (SQLite only)
    try:
        with _sync_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.execute(text("VACUUM"))
            logger.info("database_vacuum: completed successfully")
    except Exception:
        logger.exception("database_vacuum: failed (non-fatal)")

    _cleanup_last_run = now
