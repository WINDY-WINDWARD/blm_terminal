"""FastAPI router for watchlist CRUD endpoints."""

from typing import List, Sequence

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.watchlist import Watchlist as WatchlistModel
from app.models.watchlist import WatchlistItem as WatchlistItemModel
from app.schemas.watchlist import (
    WatchlistCreate,
    WatchlistItemCreate,
    WatchlistItemOut,
    WatchlistOut,
    WatchlistWithCountOut,
)

router = APIRouter()


@router.get("/watchlists", response_model=List[WatchlistWithCountOut], tags=["watchlist"])
async def list_watchlists(
    db: AsyncSession = Depends(get_db),
) -> List[WatchlistWithCountOut]:
    """Return all watchlists with item counts ordered by creation time."""
    q = (
        select(
            WatchlistModel.id,
            WatchlistModel.name,
            WatchlistModel.created_at,
            func.count(WatchlistItemModel.id).label("item_count"),
        )
        .outerjoin(WatchlistItemModel, WatchlistModel.id == WatchlistItemModel.watchlist_id)
        .group_by(WatchlistModel.id)
        .order_by(WatchlistModel.id)
    )
    res = await db.execute(q)
    rows = res.all()
    return [
        WatchlistWithCountOut(
            id=row.id,
            name=row.name,
            created_at=row.created_at,
            item_count=row.item_count or 0,
        )
        for row in rows
    ]


@router.post("/watchlists", response_model=WatchlistOut, status_code=status.HTTP_201_CREATED, tags=["watchlist"])
async def create_watchlist(
    body: WatchlistCreate,
    db: AsyncSession = Depends(get_db),
) -> WatchlistOut:
    """Create a new watchlist with the given name."""
    watchlist = WatchlistModel(name=body.name)
    db.add(watchlist)
    await db.commit()
    await db.refresh(watchlist)
    return WatchlistOut.model_validate(watchlist)


@router.delete("/watchlists/{watchlist_id}", tags=["watchlist"])
async def delete_watchlist(
    watchlist_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Delete a watchlist and all its items (cascade). Cannot delete Default (id=1)."""
    if watchlist_id == 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete the Default watchlist",
        )
    watchlist = await db.get(WatchlistModel, watchlist_id)
    if watchlist is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Watchlist {watchlist_id} not found",
        )
    await db.delete(watchlist)
    await db.commit()
    return {"ok": True}


@router.get("/watchlists/{watchlist_id}/items", response_model=List[WatchlistItemOut], tags=["watchlist"])
async def list_watchlist_items(
    watchlist_id: int,
    db: AsyncSession = Depends(get_db),
) -> List[WatchlistItemOut]:
    """Return all items in a specific watchlist."""
    watchlist = await db.get(WatchlistModel, watchlist_id)
    if watchlist is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Watchlist {watchlist_id} not found",
        )
    q = (
        select(WatchlistItemModel)
        .where(WatchlistItemModel.watchlist_id == watchlist_id)
        .order_by(WatchlistItemModel.created_at)
    )
    res = await db.execute(q)
    return [WatchlistItemOut.model_validate(item) for item in res.scalars().all()]  # type: ignore[return-value]


@router.post(
    "/watchlists/{watchlist_id}/items",
    response_model=WatchlistItemOut,
    status_code=status.HTTP_201_CREATED,
    tags=["watchlist"],
)
async def add_watchlist_item(
    watchlist_id: int,
    body: WatchlistItemCreate,
    db: AsyncSession = Depends(get_db),
) -> WatchlistItemOut:
    """Add a symbol/exchange pair to a specific watchlist (idempotent upsert).

    If the pair already exists in that watchlist, return the existing row.
    """
    watchlist = await db.get(WatchlistModel, watchlist_id)
    if watchlist is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Watchlist {watchlist_id} not found",
        )

    existing = await db.execute(
        select(WatchlistItemModel).where(
            WatchlistItemModel.watchlist_id == watchlist_id,
            WatchlistItemModel.symbol == body.symbol,
            WatchlistItemModel.exchange == body.exchange,
        )
    )
    row = existing.scalar_one_or_none()
    if row is not None:
        return row  # type: ignore[return-value]

    item = WatchlistItemModel(
        watchlist_id=watchlist_id,
        symbol=body.symbol,
        exchange=body.exchange,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item  # type: ignore[return-value]


@router.delete("/watchlists/{watchlist_id}/items/{item_id}", tags=["watchlist"])
async def remove_watchlist_item(
    watchlist_id: int,
    item_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Remove a watchlist item by its numeric id."""
    item = await db.get(WatchlistItemModel, item_id)
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Watchlist item {item_id} not found",
        )
    if item.watchlist_id != watchlist_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Item {item_id} does not belong to watchlist {watchlist_id}",
        )
    await db.delete(item)
    await db.commit()
    return {"ok": True}


# Legacy endpoints for backward compatibility (GET/POST/DELETE on /watchlist)
# These now operate on the Default watchlist (id=1)


@router.get("/watchlist", response_model=List[WatchlistItemOut], tags=["watchlist-legacy"])
async def list_default_watchlist(
    db: AsyncSession = Depends(get_db),
) -> List[WatchlistItemOut]:
    """Return all watchlist items in the Default watchlist (legacy endpoint)."""
    q = (
        select(WatchlistItemModel)
        .where(WatchlistItemModel.watchlist_id == 1)
        .order_by(WatchlistItemModel.created_at)
    )
    res = await db.execute(q)
    return [WatchlistItemOut.model_validate(item) for item in res.scalars().all()]  # type: ignore[return-value]


@router.post(
    "/watchlist",
    response_model=WatchlistItemOut,
    status_code=status.HTTP_201_CREATED,
    tags=["watchlist-legacy"],
)
async def add_default_watchlist_item(
    body: WatchlistItemCreate,
    db: AsyncSession = Depends(get_db),
) -> WatchlistItemOut:
    """Add a symbol/exchange pair to the Default watchlist (legacy endpoint).

    If the pair already exists in the Default watchlist, return the existing row.
    """
    existing = await db.execute(
        select(WatchlistItemModel).where(
            WatchlistItemModel.watchlist_id == 1,
            WatchlistItemModel.symbol == body.symbol,
            WatchlistItemModel.exchange == body.exchange,
        )
    )
    row = existing.scalar_one_or_none()
    if row is not None:
        return row  # type: ignore[return-value]

    item = WatchlistItemModel(
        watchlist_id=1,
        symbol=body.symbol,
        exchange=body.exchange,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item  # type: ignore[return-value]


@router.delete("/watchlist/{item_id}", tags=["watchlist-legacy"])
async def remove_default_watchlist_item(
    item_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Remove a watchlist item from the Default watchlist (legacy endpoint)."""
    item = await db.get(WatchlistItemModel, item_id)
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"watchlist item {item_id} not found",
        )
    if item.watchlist_id != 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Item {item_id} does not belong to the Default watchlist",
        )
    await db.delete(item)
    await db.commit()
    return {"ok": True}
