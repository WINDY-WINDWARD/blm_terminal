"""
Corporate filings / announcements service.

NSE endpoint used:
  GET /api/corporate-announcements?index=equities&symbol=<SYMBOL>

Returns a list of corporate announcements for the given symbol.
Each announcement has attachments that link to PDF documents.
"""
import json
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.filings import FilingRecord
from app.services.nse_client import nse_client

logger = logging.getLogger(__name__)

_NSE_PATH = "/api/corporate-announcements"
_NSE_ATTACH_BASE = "https://nsearchives.nseindia.com"


def _is_stale(record: FilingRecord) -> bool:
    now = datetime.now(timezone.utc)
    cached = record.cached_at
    if cached.tzinfo is None:
        cached = cached.replace(tzinfo=timezone.utc)
    return (now - cached).total_seconds() > settings.nse_cache_ttl_seconds


async def get_filings(
    db: AsyncSession,
    symbol: str,
    exchange: str = "NSE",
    filing_type: str | None = None,
) -> list[FilingRecord]:
    """
    Return corporate filings for *symbol*, optionally filtered by *filing_type*.

    Fetches fresh data from NSE when the cache is stale or empty.
    Falls back to stale cached data if the NSE call fails.
    """
    symbol = symbol.upper()
    exchange = exchange.upper()

    query = (
        select(FilingRecord)
        .where(FilingRecord.symbol == symbol, FilingRecord.exchange == exchange)
        .order_by(FilingRecord.id.desc())
    )
    if filing_type:
        query = query.where(FilingRecord.filing_type == filing_type.upper())

    result = await db.execute(query)
    rows = list(result.scalars().all())

    if rows and not _is_stale(rows[0]):
        logger.debug("Filings cache hit for %s", symbol)
        return rows

    try:
        raw = await nse_client.fetch(_NSE_PATH, params={"index": "equities", "symbol": symbol})
        rows = await _upsert_filings(db, symbol, exchange, raw)
        logger.info("Filings refreshed for %s (%d records)", symbol, len(rows))
        # Re-apply type filter after upsert
        if filing_type:
            rows = [r for r in rows if r.filing_type == filing_type.upper()]
    except Exception:
        logger.exception("NSE filings fetch failed for %s; returning cached data", symbol)
        if rows:
            return rows
        raise

    return rows


async def _upsert_filings(
    db: AsyncSession,
    symbol: str,
    exchange: str,
    data: list | dict,
) -> list[FilingRecord]:
    """Parse NSE announcements response and upsert filing records."""
    items: list[dict] = []
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        items = data.get("data", []) or data.get("announcements", []) or []

    upserted: list[FilingRecord] = []

    for item in items:
        # NSE uses various casing; normalise keys lower
        normed: dict = {k.lower(): v for k, v in item.items()}

        attachment_id = str(normed.get("an_dt") or normed.get("attchmntid") or "")

        # Build PDF URL from attachment path if available
        attach_path = normed.get("attchmntfile") or normed.get("attchmnt") or ""
        url = f"{_NSE_ATTACH_BASE}/{attach_path}" if attach_path else None

        # Determine filing_type from subject / antype
        filing_type_raw = normed.get("antype") or normed.get("ann_type") or "ANNOUNCEMENT"

        record = FilingRecord(
            symbol=symbol,
            exchange=exchange,
            filing_type=str(filing_type_raw).upper() if filing_type_raw else None,
            subject=normed.get("subject") or normed.get("desc"),
            description=normed.get("description") or normed.get("an_desc"),
            filing_date=normed.get("an_dt") or normed.get("date"),
            url=url,
            attachment_id=attachment_id or None,
            raw_json=json.dumps(item),
            cached_at=datetime.now(timezone.utc),
        )

        # Upsert on attachment_id if present, else always insert
        if record.attachment_id:
            existing = await db.execute(
                select(FilingRecord).where(FilingRecord.attachment_id == record.attachment_id)
            )
            existing_row = existing.scalar_one_or_none()
            if existing_row:
                existing_row.subject = record.subject
                existing_row.description = record.description
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
