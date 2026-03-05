"""FastAPI router for earnings endpoints."""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.earnings import EarningsOut
from app.services.earnings import get_earnings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/earnings", tags=["earnings"])


@router.get("", response_model=list[EarningsOut])
async def list_earnings(
    symbol: str = Query(..., description="NSE symbol, e.g. RELIANCE"),
    exchange: str = Query("NSE", description="Exchange, e.g. NSE or BSE"),
    db: AsyncSession = Depends(get_db),
) -> list[EarningsOut]:
    """
    Return financial results for a given symbol.

    Data is fetched from NSE India and cached locally. The cache is refreshed
    automatically when it becomes stale (controlled by ``NSE_CACHE_TTL_SECONDS``).
    """
    try:
        records = await get_earnings(db, symbol=symbol, exchange=exchange)
    except Exception:
        logger.exception("Error fetching earnings for %s", symbol)
        raise HTTPException(status_code=503, detail="NSE earnings data unavailable")

    return records  # type: ignore[return-value]
