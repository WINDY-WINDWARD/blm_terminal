"""FastAPI router for corporate filings endpoints."""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.filings import FilingOut
from app.services.filings import get_filings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/filings", tags=["filings"])


@router.get("", response_model=list[FilingOut])
async def list_filings(
    symbol: str = Query(..., description="NSE symbol, e.g. RELIANCE"),
    exchange: str = Query("NSE", description="Exchange, e.g. NSE or BSE"),
    type: str | None = Query(None, description="Filter by filing type, e.g. BOARD MEETING"),
    db: AsyncSession = Depends(get_db),
) -> list[FilingOut]:
    """
    Return corporate announcements and filings for a given symbol.

    Data is fetched from NSE India's corporate-announcements API and cached
    locally. Pass ``type`` to filter by announcement type.
    """
    try:
        records = await get_filings(db, symbol=symbol, exchange=exchange, filing_type=type)
    except Exception:
        logger.exception("Error fetching filings for %s", symbol)
        raise HTTPException(status_code=503, detail="NSE filings data unavailable")

    return records  # type: ignore[return-value]
