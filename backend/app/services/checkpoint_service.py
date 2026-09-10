"""Checkpoint and resume service for background data sync tasks.

Provides sync helpers (used by background worker threads) to get and set
checkpoint cursors in `sync_state`.
"""
from __future__ import annotations

import logging
from typing import Optional
from datetime import datetime, timezone

from sqlalchemy import select
from app.database import _SyncSessionLocal
from app.models.sync_state import SyncState

logger = logging.getLogger(__name__)


def get_checkpoint(task_name: str) -> tuple[Optional[str], Optional[str]]:
    """Get (last_symbol, cursor_info) for the specified task."""
    try:
        with _SyncSessionLocal() as session:
            row = session.execute(
                select(SyncState).where(SyncState.task_name == task_name)
            ).scalar_one_or_none()
            if row:
                return row.last_symbol, row.cursor_info
    except Exception as e:
        logger.warning("Failed to read checkpoint for task %s: %s", task_name, e)
    return None, None


def set_checkpoint(task_name: str, last_symbol: Optional[str] = None, cursor_info: Optional[str] = None) -> None:
    """Save or update checkpoint for task_name."""
    try:
        with _SyncSessionLocal() as session:
            row = session.execute(
                select(SyncState).where(SyncState.task_name == task_name)
            ).scalar_one_or_none()
            if not row:
                row = SyncState(task_name=task_name, last_symbol=last_symbol, cursor_info=cursor_info)
                session.add(row)
            else:
                row.last_symbol = last_symbol
                row.cursor_info = cursor_info
                row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
            session.commit()
    except Exception as e:
        logger.warning("Failed to set checkpoint for task %s: %s", task_name, e)


def clear_checkpoint(task_name: str) -> None:
    """Clear checkpoint when a task cycle completes successfully."""
    try:
        with _SyncSessionLocal() as session:
            row = session.execute(
                select(SyncState).where(SyncState.task_name == task_name)
            ).scalar_one_or_none()
            if row:
                session.delete(row)
                session.commit()
    except Exception as e:
        logger.warning("Failed to clear checkpoint for task %s: %s", task_name, e)
