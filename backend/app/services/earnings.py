"""
Earnings / financial results service.

NSE endpoint used:
  GET /api/top-corp-info?symbol=<SYMBOL>&market=equities

This returns board-meeting announcements, quarterly results, and dividend info.
We extract the financial results and upsert into the ``earnings`` table.
"""
import json
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.earnings import EarningsRecord
from app.services.nse_client import nse_client

logger = logging.getLogger(__name__)

_NSE_PATH = "/api/top-corp-info"


def _is_stale(record: EarningsRecord) -> bool:
    now = datetime.now(timezone.utc)
    cached = record.cached_at
    if cached.tzinfo is None:
        cached = cached.replace(tzinfo=timezone.utc)
    return (now - cached).total_seconds() > settings.nse_cache_ttl_seconds


async def get_earnings(
    db: AsyncSession,
    symbol: str,
    exchange: str = "NSE",
) -> list[EarningsRecord]:
    """
    Return earnings records for *symbol*.

    Fetches fresh data from NSE when the cache is stale or empty.
    Falls back to stale cached data if the NSE call fails.
    """
    symbol = symbol.upper()
    exchange = exchange.upper()

    # Check existing records
    result = await db.execute(
        select(EarningsRecord)
        .where(EarningsRecord.symbol == symbol, EarningsRecord.exchange == exchange)
        .order_by(EarningsRecord.id.desc())
    )
    rows = list(result.scalars().all())

    # Use cache if fresh
    if rows and not _is_stale(rows[0]):
        logger.debug("Earnings cache hit for %s", symbol)
        return rows

    # Fetch from NSE
    try:
        data = await nse_client.fetch(_NSE_PATH, params={"symbol": symbol, "market": "equities"})
        rows = await _upsert_earnings(db, symbol, exchange, data)
        logger.info("Earnings refreshed for %s (%d records)", symbol, len(rows))
    except Exception:
        logger.exception("NSE earnings fetch failed for %s; returning cached data", symbol)
        # Return whatever we have cached even if stale
        if rows:
            return rows
        raise

    return rows


async def _upsert_earnings(
    db: AsyncSession,
    symbol: str,
    exchange: str,
    data: dict,
) -> list[EarningsRecord]:
    """Parse NSE response and upsert earnings records."""
    # NSE returns various keys; we look for 'corporate' array with result entries
    corporate = data.get("corporate", []) if isinstance(data, dict) else []

    # Filter to financial result announcements
    result_items = [
        item
        for item in corporate
        if isinstance(item, dict)
        and "financial" in item.get("purpose", "").lower()
    ]

    # If the specific key is absent, fall back to storing the raw top-level payload
    if not result_items and isinstance(data, dict):
        result_items = [data]

    upserted: list[EarningsRecord] = []

    for item in result_items:
        period = item.get("period") or item.get("quarter") or item.get("meetingtype")
        result_date = item.get("bm_date") or item.get("date") or item.get("meetingDate")

        # Attempt to parse numeric financials — NSE returns them as strings
        def _float(key: str) -> float | None:
            val = item.get(key)
            if val is None:
                return None
            try:
                return float(str(val).replace(",", ""))
            except (ValueError, TypeError):
                return None

        record = EarningsRecord(
            symbol=symbol,
            exchange=exchange,
            period=str(period) if period else None,
            result_date=str(result_date) if result_date else None,
            net_profit=_float("profit"),
            revenue=_float("income") or _float("revenue"),
            eps=_float("eps"),
            raw_json=json.dumps(item),
            cached_at=datetime.now(timezone.utc),
        )
        db.add(record)
        upserted.append(record)

    await db.commit()
    for r in upserted:
        await db.refresh(r)

    return upserted or await _fetch_all(db, symbol, exchange)


async def _fetch_all(db: AsyncSession, symbol: str, exchange: str) -> list[EarningsRecord]:
    result = await db.execute(
        select(EarningsRecord)
        .where(EarningsRecord.symbol == symbol, EarningsRecord.exchange == exchange)
        .order_by(EarningsRecord.id.desc())
    )
    return list(result.scalars().all())
