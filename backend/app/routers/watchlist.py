"""FastAPI router for watchlist CRUD endpoints."""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.watchlist import WatchlistItem as WatchlistItemModel
from app.schemas.watchlist import WatchlistItemCreate, WatchlistItemOut

router = APIRouter()


@router.get("/watchlist", response_model=List[WatchlistItemOut], tags=["watchlist"])
async def list_watchlist(
    db: AsyncSession = Depends(get_db),
) -> List[WatchlistItemOut]:
    """Return all watchlist items ordered by creation time."""
    q = select(WatchlistItemModel).order_by(WatchlistItemModel.created_at)
    res = await db.execute(q)
    return list(res.scalars().all())


@router.post(
    "/watchlist",
    response_model=WatchlistItemOut,
    status_code=status.HTTP_201_CREATED,
    tags=["watchlist"],
)
async def add_watchlist_item(
    body: WatchlistItemCreate,
    db: AsyncSession = Depends(get_db),
) -> WatchlistItemOut:
    """Add a symbol/exchange pair to the watchlist (idempotent upsert).

    If the pair already exists the existing row is returned with HTTP 201.
    """
    # Check for existing row first (upsert semantics without dialect-specific ON CONFLICT).
    existing = await db.execute(
        select(WatchlistItemModel).where(
            WatchlistItemModel.symbol == body.symbol,
            WatchlistItemModel.exchange == body.exchange,
        )
    )
    row = existing.scalar_one_or_none()
    if row is not None:
        return row  # type: ignore[return-value]

    item = WatchlistItemModel(symbol=body.symbol, exchange=body.exchange)
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item  # type: ignore[return-value]


@router.delete("/watchlist/{item_id}", tags=["watchlist"])
async def remove_watchlist_item(
    item_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Remove a watchlist item by its numeric id."""
    item = await db.get(WatchlistItemModel, item_id)
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"watchlist item {item_id} not found",
        )
    await db.delete(item)
    await db.commit()
    return {"ok": True}
