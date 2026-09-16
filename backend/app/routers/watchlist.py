"""FastAPI router for watchlist CRUD endpoints."""

from typing import List, Sequence

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.models.watchlist import Watchlist as WatchlistModel
from app.models.watchlist import WatchlistItem as WatchlistItemModel
from app.schemas.watchlist import (
    WatchlistBulkReplace,
    WatchlistCreate,
    WatchlistItemCreate,
    WatchlistItemOut,
    WatchlistOut,
    WatchlistWithCountOut,
)
from app.services.write_queue import enqueue_write_async, PRIO_UI_ACTION
from app.database import _SyncSessionLocal

router = APIRouter()


async def get_default_watchlist_id(db: AsyncSession, current_user: User) -> int:
    q = select(WatchlistModel).where(WatchlistModel.user_id == current_user.id, WatchlistModel.name == "Default")
    wl = (await db.execute(q)).scalar_one_or_none()
    if wl:
        return wl.id
    def _create_default_sync() -> int:
        with _SyncSessionLocal() as session:
            existing = session.execute(
                select(WatchlistModel).where(
                    WatchlistModel.user_id == current_user.id,
                    WatchlistModel.name == "Default"
                )
            ).scalar_one_or_none()
            if existing:
                return existing.id
            new_wl = WatchlistModel(name="Default", user_id=current_user.id)
            session.add(new_wl)
            session.commit()
            session.refresh(new_wl)
            return new_wl.id

    return await enqueue_write_async(PRIO_UI_ACTION, _create_default_sync)


@router.get("/watchlists", response_model=List[WatchlistWithCountOut], tags=["watchlist"])
async def list_watchlists(
    current_user: User = Depends(get_current_user),
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
        .where(WatchlistModel.user_id == current_user.id)
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
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WatchlistOut:
    """Create a new watchlist with the given name."""
    def _create_wl_sync() -> dict:
        with _SyncSessionLocal() as session:
            wl = WatchlistModel(name=body.name, user_id=current_user.id)
            session.add(wl)
            session.commit()
            session.refresh(wl)
            return {
                "id": wl.id,
                "name": wl.name,
                "user_id": wl.user_id,
                "created_at": wl.created_at,
            }

    wl_dict = await enqueue_write_async(PRIO_UI_ACTION, _create_wl_sync)
    return WatchlistOut.model_validate(wl_dict)


@router.delete("/watchlists/{watchlist_id}", tags=["watchlist"])
async def delete_watchlist(
    watchlist_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Delete a watchlist and all its items (cascade). Cannot delete Default."""
    watchlist = await db.get(WatchlistModel, watchlist_id)
    if watchlist is None or watchlist.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Watchlist {watchlist_id} not found",
        )
    if watchlist.name == "Default":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete the Default watchlist",
        )
    def _del_wl_sync() -> None:
        with _SyncSessionLocal() as session:
            wl = session.get(WatchlistModel, watchlist_id)
            if wl:
                session.delete(wl)
                session.commit()

    await enqueue_write_async(PRIO_UI_ACTION, _del_wl_sync)
    return {"ok": True}


@router.get("/watchlists/{watchlist_id}/items", response_model=List[WatchlistItemOut], tags=["watchlist"])
async def list_watchlist_items(
    watchlist_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> List[WatchlistItemOut]:
    """Return all items in a specific watchlist."""
    watchlist = await db.get(WatchlistModel, watchlist_id)
    if watchlist is None or watchlist.user_id != current_user.id:
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
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WatchlistItemOut:
    """Add a symbol/exchange pair to a specific watchlist (idempotent upsert).

    If the pair already exists in that watchlist, return the existing row.
    """
    watchlist = await db.get(WatchlistModel, watchlist_id)
    if watchlist is None or watchlist.user_id != current_user.id:
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

    def _add_item_sync() -> dict:
        with _SyncSessionLocal() as session:
            new_item = WatchlistItemModel(
                watchlist_id=watchlist_id,
                symbol=body.symbol,
                exchange=body.exchange,
            )
            session.add(new_item)
            session.commit()
            session.refresh(new_item)
            return {
                "id": new_item.id,
                "watchlist_id": new_item.watchlist_id,
                "symbol": new_item.symbol,
                "exchange": new_item.exchange,
            }

    item_dict = await enqueue_write_async(PRIO_UI_ACTION, _add_item_sync)

    # Warm deals cache asynchronously for the newly added symbol
    try:
        from app.services.data_sync.deals import warm_symbol_deals
        warm_symbol_deals(body.symbol)
    except Exception:
        pass

    return item_dict  # type: ignore[return-value]


@router.delete("/watchlists/{watchlist_id}/items/{item_id}", tags=["watchlist"])
async def remove_watchlist_item(
    watchlist_id: int,
    item_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Remove a watchlist item by its numeric id."""
    item = await db.get(WatchlistItemModel, item_id)
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Watchlist item {item_id} not found",
        )
    watchlist = await db.get(WatchlistModel, item.watchlist_id)
    if watchlist is None or watchlist.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Watchlist item {item_id} not found",
        )
    if item.watchlist_id != watchlist_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Item {item_id} does not belong to watchlist {watchlist_id}",
        )
    def _delete_item_sync() -> None:
        with _SyncSessionLocal() as session:
            db_item = session.get(WatchlistItemModel, item_id)
            if db_item:
                session.delete(db_item)
                session.commit()

    await enqueue_write_async(PRIO_UI_ACTION, _delete_item_sync)
    return {"ok": True}


@router.post(
    "/watchlists/{watchlist_id}/items/bulk-replace",
    tags=["watchlist"],
)
async def bulk_replace_watchlist_items(
    watchlist_id: int,
    body: WatchlistBulkReplace,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Atomically replace all items in a watchlist with a new set of symbols.

    Deletes all existing items for the watchlist, then inserts new rows for
    each symbol in the payload.  Operates in a single transaction.
    """
    watchlist = await db.get(WatchlistModel, watchlist_id)
    if watchlist is None or watchlist.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Watchlist {watchlist_id} not found",
        )

    # Delete existing items and insert new items via single serialized write
    def _bulk_replace_sync(target_wlid: int, symbols: list[str], exch: str) -> None:
        with _SyncSessionLocal() as session:
            session.execute(
                delete(WatchlistItemModel).where(
                    WatchlistItemModel.watchlist_id == target_wlid
                )
            )
            for sym in symbols:
                item = WatchlistItemModel(
                    watchlist_id=target_wlid,
                    symbol=sym,
                    exchange=exch,
                )
                session.add(item)
            session.commit()

    await enqueue_write_async(PRIO_UI_ACTION, _bulk_replace_sync, watchlist_id, list(body.symbols), body.exchange)

    # Warm deals cache asynchronously for newly added symbols
    try:
        from app.services.data_sync.deals import warm_symbol_deals
        for s in body.symbols:
            warm_symbol_deals(s)
    except Exception:
        pass

    return {
        "ok": True,
        "watchlist_id": watchlist_id,
        "items_added": len(body.symbols),
    }


# Legacy endpoints for backward compatibility (GET/POST/DELETE on /watchlist)
# These now operate on the Default watchlist (id=1)


@router.get("/watchlist", response_model=List[WatchlistItemOut], tags=["watchlist-legacy"])
async def list_default_watchlist(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> List[WatchlistItemOut]:
    """Return all watchlist items in the Default watchlist (legacy endpoint)."""
    default_id = await get_default_watchlist_id(db, current_user)
    q = (
        select(WatchlistItemModel)
        .where(WatchlistItemModel.watchlist_id == default_id)
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
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WatchlistItemOut:
    """Add a symbol/exchange pair to the Default watchlist (legacy endpoint).

    If the pair already exists in the Default watchlist, return the existing row.
    """
    default_id = await get_default_watchlist_id(db, current_user)
    existing = await db.execute(
        select(WatchlistItemModel).where(
            WatchlistItemModel.watchlist_id == default_id,
            WatchlistItemModel.symbol == body.symbol,
            WatchlistItemModel.exchange == body.exchange,
        )
    )
    row = existing.scalar_one_or_none()
    if row is not None:
        return row  # type: ignore[return-value]

    def _add_legacy_sync() -> dict:
        with _SyncSessionLocal() as session:
            new_item = WatchlistItemModel(
                watchlist_id=default_id,
                symbol=body.symbol,
                exchange=body.exchange,
            )
            session.add(new_item)
            session.commit()
            session.refresh(new_item)
            return {
                "id": new_item.id,
                "watchlist_id": new_item.watchlist_id,
                "symbol": new_item.symbol,
                "exchange": new_item.exchange,
            }

    item_dict = await enqueue_write_async(PRIO_UI_ACTION, _add_legacy_sync)
    return item_dict  # type: ignore[return-value]


@router.delete("/watchlist/{item_id}", tags=["watchlist-legacy"])
async def remove_default_watchlist_item(
    item_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Remove a watchlist item from the Default watchlist (legacy endpoint)."""
    default_id = await get_default_watchlist_id(db, current_user)
    item = await db.get(WatchlistItemModel, item_id)
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"watchlist item {item_id} not found",
        )
    if item.watchlist_id != default_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Item {item_id} does not belong to the Default watchlist",
        )
    def _delete_legacy_sync() -> None:
        with _SyncSessionLocal() as session:
            db_item = session.get(WatchlistItemModel, item_id)
            if db_item:
                session.delete(db_item)
                session.commit()

    await enqueue_write_async(PRIO_UI_ACTION, _delete_legacy_sync)
    return {"ok": True}
