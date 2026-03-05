"""FastAPI router for market circulars endpoints."""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.circulars import CircularOut
from app.services.circulars import get_circulars

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/circulars", tags=["circulars"])


@router.get("", response_model=list[CircularOut])
async def list_circulars(
    dept: str | None = Query(None, description="Department filter, e.g. TRADING"),
    from_date: str | None = Query(
        None,
        alias="from_date",
        description="Start date in DD-MM-YYYY format",
    ),
    to_date: str | None = Query(
        None,
        alias="to_date",
        description="End date in DD-MM-YYYY format",
    ),
    db: AsyncSession = Depends(get_db),
) -> list[CircularOut]:
    """
    Return NSE market circulars.

    All parameters are optional. Without filters, returns all cached circulars
    (refreshed from NSE when stale). Use ``dept`` to filter by issuing department
    and ``from_date``/``to_date`` (``DD-MM-YYYY``) to limit by date range.
    """
    try:
        records = await get_circulars(
            db,
            department=dept,
            from_date=from_date,
            to_date=to_date,
        )
    except Exception:
        logger.exception("Error fetching circulars")
        raise HTTPException(status_code=503, detail="NSE circulars data unavailable")

    return records  # type: ignore[return-value]
