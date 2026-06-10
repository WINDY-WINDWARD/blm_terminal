"""Breakout snapshot capture + repeat-breakout alert generation.

Called every 30 minutes from the global scan cycle:

1. ``_capture_breakout_snapshot()`` — records which symbols appeared
   in the NSE 52W HIGH, 52W LOW, and VOLUME GAINER lists today.
   Uses ``ON CONFLICT DO NOTHING`` so re-runs within the same day
   are idempotent.

2. ``_generate_repeat_breakout_alerts()`` — queries the last N
   trading days of snapshots and fires ``GlobalNotification`` alerts
   for symbols that appeared >= ``min_days`` times within the window.

Migrated from the breakout snapshot plan (2026-06).
"""
import json
import logging
from datetime import date, datetime, timedelta

from sqlalchemy import func, text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.database import _SyncSessionLocal
from app.models.breakout_snapshot import BreakoutSnapshot


logger = logging.getLogger(__name__)


# NSE breakout_type → GlobalNotification trigger_type mapping
_TYPE_MAP = {
    "52W_HIGH": "repeated_52w_high",
    "52W_LOW": "repeated_52w_low",
    "VOLUME_GAINER": "repeated_volume_breakout",
}

# Human-readable labels for alert messages
_TYPE_LABEL = {
    "52W_HIGH": "52W HIGH",
    "52W_LOW": "52W LOW",
    "VOLUME_GAINER": "VOLUME GAINER",
}


def _capture_breakout_snapshot() -> None:
    """Fetch NSE breakout data and insert a snapshot row for each symbol.

    Reuses the existing safe-fetch helpers from nse_parsing.
    Called once per global_scan_cycle (every 30 min).
    """
    from app.services.data_sync.nse_parsing import (
        _safe_fetch_52week_high,
        _safe_fetch_52week_low,
        _safe_fetch_volume_gainers,
        _parse_52week_data,
        _parse_volume_gainers,
    )

    today = date.today()

    # 52-week high
    try:
        high_raw = _safe_fetch_52week_high()
        high_data = _parse_52week_data(high_raw)
        _insert_snapshot_rows(today, "52W_HIGH", high_data)
    except Exception:
        logger.exception("breakout_snapshot: failed to capture 52W HIGH")

    # 52-week low
    try:
        low_raw = _safe_fetch_52week_low()
        low_data = _parse_52week_data(low_raw)
        _insert_snapshot_rows(today, "52W_LOW", low_data)
    except Exception:
        logger.exception("breakout_snapshot: failed to capture 52W LOW")

    # Volume gainers
    try:
        vol_raw = _safe_fetch_volume_gainers()
        vol_data = _parse_volume_gainers(vol_raw)
        _insert_snapshot_rows(today, "VOLUME_GAINER", vol_data)
    except Exception:
        logger.exception("breakout_snapshot: failed to capture VOLUME GAINER")


def _insert_snapshot_rows(
    snapshot_date: date,
    breakout_type: str,
    data: dict[str, dict],
) -> None:
    """Bulk-insert snapshot rows with ON CONFLICT DO NOTHING."""
    if not data:
        return

    rows = []
    for symbol, info in data.items():
        rows.append({
            "snapshot_date": snapshot_date,
            "breakout_type": breakout_type,
            "symbol": symbol,
            "ltp": info.get("ltp"),
            "pchange": info.get("pChange"),
            "extra_json": json.dumps(info) if len(info) > 3 else None,
        })

    if not rows:
        return

    with _SyncSessionLocal() as session:
        stmt = (
            sqlite_insert(BreakoutSnapshot)
            .values(rows)
            .on_conflict_do_nothing(
                index_elements=["snapshot_date", "breakout_type", "symbol"]
            )
        )
        session.execute(stmt)
        session.commit()

    logger.info(
        "breakout_snapshot: captured %d %s symbols for %s",
        len(rows), breakout_type, snapshot_date,
    )


def _generate_repeat_breakout_alerts(
    window_days: int = 10,
    min_days: int = 2,
) -> list[dict]:
    """Scan the breakout_snapshots table for repeat appearances.

    Returns a list of GlobalNotification-ready dicts for symbols that
    appeared in the same breakout list >= min_days times within the
    last ``window_days`` calendar days.
    """
    from app.services.data_sync.notifications import (
        _get_global_seen_today,
    )

    cutoff = date.today() - timedelta(days=window_days)
    seen_today = _get_global_seen_today()
    pending: list[dict] = []

    try:
        with _SyncSessionLocal() as session:
            rows = session.execute(
                text(
                    "SELECT symbol, breakout_type, COUNT(DISTINCT snapshot_date) AS cnt, "
                    "MAX(snapshot_date) AS last_seen "
                    "FROM breakout_snapshots "
                    "WHERE snapshot_date >= :cutoff "
                    "GROUP BY symbol, breakout_type "
                    "HAVING cnt >= :min_days"
                ),
                {"cutoff": cutoff, "min_days": min_days},
            ).fetchall()

            now = datetime.now()
            today = now.date()

            for symbol, breakout_type, cnt, last_seen in rows:
                trigger_type = _TYPE_MAP.get(breakout_type)
                if not trigger_type:
                    continue

                # Skip if already fired today
                if (symbol, trigger_type) in seen_today:
                    continue
                seen_today.add((symbol, trigger_type))

                label = _TYPE_LABEL.get(breakout_type, breakout_type)
                pending.append({
                    "symbol": symbol,
                    "exchange": "NSE",
                    "trigger_type": trigger_type,
                    "message": (
                        f"{symbol} appeared in {label} list "
                        f"{cnt}/{window_days} calendar days"
                    ),
                    "triggered_at": now,
                    "triggered_date": today,
                    "is_read": False,
                })

        if pending:
            logger.info(
                "breakout_snapshot: generated %d repeat-breakout alerts",
                len(pending),
            )

    except Exception:
        logger.exception("breakout_snapshot: repeat alert generation failed")

    return pending
