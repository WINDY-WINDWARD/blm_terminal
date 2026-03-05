"""
Market circulars service.

NSE endpoint used:
  GET /api/circulars?dept=<DEPT>&fromDate=<DD-MM-YYYY>&toDate=<DD-MM-YYYY>

Dept is optional — if omitted, NSE returns circulars from all departments.
"""
import json
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.circulars import CircularRecord
from app.services.nse_client import nse_client

logger = logging.getLogger(__name__)

_NSE_PATH = "/api/circulars"
_NSE_DOC_BASE = "https://nsearchives.nseindia.com"


def _is_stale(record: CircularRecord) -> bool:
    now = datetime.now(timezone.utc)
    cached = record.cached_at
    if cached.tzinfo is None:
        cached = cached.replace(tzinfo=timezone.utc)
    return (now - cached).total_seconds() > settings.nse_cache_ttl_seconds


async def get_circulars(
    db: AsyncSession,
    department: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
) -> list[CircularRecord]:
    """
    Return circulars, optionally filtered by department and date range.

    Date strings should be in ``DD-MM-YYYY`` format (NSE convention).
    Fetches fresh data from NSE when the cache is stale or empty.
    Falls back to stale cached data if the NSE call fails.
    """
    query = select(CircularRecord).order_by(CircularRecord.id.desc())
    if department:
        query = query.where(CircularRecord.department == department.upper())

    result = await db.execute(query)
    rows = list(result.scalars().all())

    if rows and not _is_stale(rows[0]):
        logger.debug("Circulars cache hit")
        return rows

    # Build NSE params
    params: dict[str, str] = {}
    if department:
        params["dept"] = department
    if from_date:
        params["fromDate"] = from_date
    if to_date:
        params["toDate"] = to_date

    try:
        raw = await nse_client.fetch(_NSE_PATH, params=params or None)
        rows = await _upsert_circulars(db, raw)
        logger.info("Circulars refreshed (%d records)", len(rows))
        # Re-apply department filter
        if department:
            rows = [r for r in rows if r.department == department.upper()]
    except Exception:
        logger.exception("NSE circulars fetch failed; returning cached data")
        if rows:
            return rows
        raise

    return rows


async def _upsert_circulars(db: AsyncSession, data: list | dict) -> list[CircularRecord]:
    """Parse NSE circulars response and upsert records."""
    items: list[dict] = []
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        items = data.get("data", []) or data.get("circulars", []) or []

    upserted: list[CircularRecord] = []

    for item in items:
        normed: dict = {k.lower(): v for k, v in item.items()}

        circular_id = (
            normed.get("circular_no")
            or normed.get("circularno")
            or normed.get("cn")
        )

        attach = normed.get("attchmntfile") or normed.get("file_name") or ""
        url = f"{_NSE_DOC_BASE}/{attach}" if attach else normed.get("url")

        department = normed.get("dept") or normed.get("department")

        circular_date = normed.get("date") or normed.get("circular_date") or normed.get("circulardate")

        record = CircularRecord(
            circular_id=str(circular_id) if circular_id else None,
            department=str(department).upper() if department else None,
            subject=normed.get("subject") or normed.get("circular_subject"),
            circular_date=str(circular_date) if circular_date else None,
            url=url,
            raw_json=json.dumps(item),
            cached_at=datetime.now(timezone.utc),
        )

        # Upsert on circular_id
        if record.circular_id:
            existing = await db.execute(
                select(CircularRecord).where(CircularRecord.circular_id == record.circular_id)
            )
            existing_row = existing.scalar_one_or_none()
            if existing_row:
                existing_row.subject = record.subject
                existing_row.url = record.url
                existing_row.raw_json = record.raw_json
                existing_row.cached_at = record.cached_at
                upserted.append(existing_row)
                continue

        db.add(record)
        upserted.append(record)

    await db.commit()
    for r in upserted:
        await db.refresh(r)

    return upserted
