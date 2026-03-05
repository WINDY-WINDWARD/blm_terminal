"""Router for corporate filings endpoints.

GET /corporatefilings/{symbol}
  - Returns cached CSV if it exists and is < 30 days old.
  - Otherwise fetches fresh data from NSE, stores it in the DB, and returns
    the new CSV.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.corporatefilings import CorporateFiling
from app.services.nse_client import nse_client

logger = logging.getLogger(__name__)

router = APIRouter()

_STALE_AFTER = timedelta(days=30)


async def _fetch_and_upsert(symbol: str, db: AsyncSession) -> str:
    """Fetch fresh corporate filing CSV from NSE and persist it.

    Runs the blocking NSE call in a thread-pool executor so the event loop
    is not blocked.
    """
    try:
        csv_text: str = await asyncio.to_thread(
            nse_client.get_corporate_filing_comparison, symbol
        )
    except Exception as exc:
        logger.exception("NSE fetch failed for %s", symbol)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to fetch corporate filings for {symbol} from NSE: {exc}",
        ) from exc

    now = datetime.now(tz=timezone.utc).replace(tzinfo=None)

    record = await db.get(CorporateFiling, symbol)
    if record is None:
        record = CorporateFiling(
            symbol=symbol,
            csv_data=csv_text,
            last_fetched_at=now,
        )
        db.add(record)
    else:
        record.csv_data = csv_text
        record.last_fetched_at = now

    await db.commit()
    logger.info("Corporate filings refreshed for %s", symbol)
    return csv_text


@router.get(
    "/corporatefilings/{symbol}",
    tags=["corporatefilings"],
    response_class=Response,
    responses={
        200: {"content": {"text/csv": {}}, "description": "Pipe-delimited CSV of quarterly results"},
        404: {"description": "Symbol not found"},
        502: {"description": "NSE upstream error"},
    },
)
async def get_corporate_filings(
    symbol: str,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Return quarterly financial results for *symbol* as a pipe-delimited CSV.

    The response is served from the local cache when the data is less than
    30 days old.  A stale or missing record triggers a live fetch from NSE,
    which updates the cache before responding.
    """
    symbol = symbol.upper().strip()

    record = await db.get(CorporateFiling, symbol)

    now = datetime.now(tz=timezone.utc).replace(tzinfo=None)
    needs_refresh = record is None or (now - record.last_fetched_at) > _STALE_AFTER

    if needs_refresh:
        csv_text = await _fetch_and_upsert(symbol, db)
    else:
        csv_text = record.csv_data  # type: ignore[union-attr]

    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{symbol}_filings.csv"',
        },
    )
