"""FastAPI router for the notifications API."""

import os
from datetime import date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user, get_admin_user
from app.config import settings
from app.database import get_db
from app.models.notification import Notification, GlobalNotification
from app.models.user import User
from app.models.watchlist import Watchlist as WatchlistModel
from app.schemas.notification import NotificationOut, GlobalNotificationOut
from app.services.write_queue import enqueue_write_async, PRIO_UI_ACTION
from app.database import _SyncSessionLocal

router = APIRouter(dependencies=[Depends(get_current_user)])


@router.get("/notifications", response_model=list[NotificationOut], tags=["notifications"])
async def list_notifications(
    watchlist_id: Annotated[int | None, Query()] = None,
    all_watchlists: Annotated[bool, Query(alias="all")] = False,
    days: Annotated[int, Query()] = 2,
    read_filter: Annotated[str, Query()] = "unread",
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[NotificationOut]:
    """Return notifications for a watchlist or all user watchlists, newest first.

    - watchlist_id: specific watchlist to query. If omitted (or all=true), queries all watchlists owned by user.
    - days: number of past days to include (default 2)
    - read_filter: 'unread' (default), 'read', or 'all'
    """
    if watchlist_id is not None and not all_watchlists:
        watchlist = await db.get(WatchlistModel, watchlist_id)
        if watchlist is None or watchlist.user_id != current_user.id:
            raise HTTPException(status_code=404, detail=f"Watchlist {watchlist_id} not found")

    cutoff_date = date.today() - timedelta(days=days - 1)

    stmt = select(Notification).where(
        Notification.triggered_date >= cutoff_date,
    )

    if watchlist_id is not None and not all_watchlists:
        stmt = stmt.where(Notification.watchlist_id == watchlist_id)
    else:
        # If no watchlist_id provided, or all=True, restrict to watchlists owned by the current user
        user_watchlists = select(WatchlistModel.id).where(WatchlistModel.user_id == current_user.id)
        stmt = stmt.where(Notification.watchlist_id.in_(user_watchlists))

    if read_filter == "unread":
        stmt = stmt.where(Notification.is_read == False)
    elif read_filter == "read":
        stmt = stmt.where(Notification.is_read == True)
    stmt = stmt.order_by(Notification.triggered_at.desc())
    res = await db.execute(stmt)
    return [NotificationOut.model_validate(n) for n in res.scalars().all()]


@router.delete("/notifications/{notif_id}", tags=["notifications"])
async def dismiss_notification(
    notif_id: int,
    watchlist_id: Annotated[int, Query()],
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Soft-delete a single notification (set is_read=True).

    Returns 403 if the notification does not belong to the specified watchlist_id.
    """
    watchlist = await db.get(WatchlistModel, watchlist_id)
    if watchlist is None or watchlist.user_id != current_user.id:
        raise HTTPException(status_code=404, detail=f"Watchlist {watchlist_id} not found")
    notif = await db.get(Notification, notif_id)
    if notif is None:
        raise HTTPException(status_code=404, detail=f"Notification {notif_id} not found")
    if notif.watchlist_id != watchlist_id:
        raise HTTPException(
            status_code=403,
            detail=f"Notification {notif_id} does not belong to watchlist {watchlist_id}",
        )
    def _read_sync():
        with _SyncSessionLocal() as session:
            n = session.get(Notification, notif_id)
            if n:
                n.is_read = True
                session.commit()

    await enqueue_write_async(PRIO_UI_ACTION, _read_sync)
    return {"ok": True}


@router.delete("/notifications", tags=["notifications"])
async def dismiss_all_notifications(
    all: Annotated[bool, Query(alias="all")],
    watchlist_id: Annotated[int | None, Query()] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Soft-delete all unread notifications.

    Requires ?all=true query param. Without it, returns 400.
    If watchlist_id is provided, deletes only for that watchlist.
    If omitted, deletes for all watchlists owned by user.
    """
    if not all:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing ?all=true query param",
        )

    stmt = update(Notification).where(Notification.is_read == False)

    if watchlist_id is not None:
        watchlist = await db.get(WatchlistModel, watchlist_id)
        if watchlist is None or watchlist.user_id != current_user.id:
            raise HTTPException(status_code=404, detail=f"Watchlist {watchlist_id} not found")
        stmt = stmt.where(Notification.watchlist_id == watchlist_id)
    else:
        user_watchlists = select(WatchlistModel.id).where(WatchlistModel.user_id == current_user.id)
        stmt = stmt.where(Notification.watchlist_id.in_(user_watchlists))

    def _dismiss_all_sync():
        with _SyncSessionLocal() as session:
            s = update(Notification).where(Notification.is_read == False)
            if watchlist_id is not None:
                s = s.where(Notification.watchlist_id == watchlist_id)
            else:
                user_wl = select(WatchlistModel.id).where(WatchlistModel.user_id == current_user.id)
                s = s.where(Notification.watchlist_id.in_(user_wl))
            s = s.values(is_read=True)
            session.execute(s)
            session.commit()

    await enqueue_write_async(PRIO_UI_ACTION, _dismiss_all_sync)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Global notifications (SCAN widget) — no watchlist_id
# ---------------------------------------------------------------------------


@router.get("/notifications/global", response_model=list[GlobalNotificationOut], tags=["notifications"])
async def list_global_notifications(
    days: Annotated[int, Query()] = 2,
    read_filter: Annotated[str, Query()] = "unread",
    limit: Annotated[int | None, Query()] = None,
    trigger_type: Annotated[str | None, Query()] = None,
    db: AsyncSession = Depends(get_db),
) -> list[GlobalNotificationOut]:
    """Return global notifications (all NSE stocks), newest first.

    - days: number of past days to include (default 2)
    - read_filter: 'unread' (default), 'read', or 'all'
    - limit: optional max rows to return
    - trigger_type: optional filter by trigger type
    """
    cutoff_date = date.today() - timedelta(days=days - 1)
    stmt = select(GlobalNotification).where(
        GlobalNotification.triggered_date >= cutoff_date,
    )
    if read_filter == "unread":
        stmt = stmt.where(GlobalNotification.is_read == False)
    elif read_filter == "read":
        stmt = stmt.where(GlobalNotification.is_read == True)
    if trigger_type is not None:
        stmt = stmt.where(GlobalNotification.trigger_type == trigger_type)
    stmt = stmt.order_by(GlobalNotification.triggered_at.desc())
    if limit is not None:
        stmt = stmt.limit(limit)
    res = await db.execute(stmt)
    return [GlobalNotificationOut.model_validate(n) for n in res.scalars().all()]


@router.delete("/notifications/global/{notif_id}", tags=["notifications"])
async def dismiss_global_notification(
    notif_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_admin_user),
) -> dict:
    """Soft-delete a single global notification (set is_read=True)."""
    notif = await db.get(GlobalNotification, notif_id)
    if notif is None:
        raise HTTPException(status_code=404, detail=f"Global notification {notif_id} not found")
    def _read_global_sync():
        with _SyncSessionLocal() as session:
            gn = session.get(GlobalNotification, notif_id)
            if gn:
                gn.is_read = True
                session.commit()

    await enqueue_write_async(PRIO_UI_ACTION, _read_global_sync)
    return {"ok": True}


@router.delete("/notifications/global", tags=["notifications"])
async def dismiss_all_global_notifications(
    all: Annotated[bool, Query(alias="all")],
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_admin_user),
) -> dict:
    """Soft-delete all unread global notifications.

    Requires ?all=true query param.
    """
    if not all:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing ?all=true query param",
        )
    def _dismiss_all_global_sync():
        with _SyncSessionLocal() as session:
            s = (
                update(GlobalNotification)
                .where(GlobalNotification.is_read == False)
                .values(is_read=True)
            )
            session.execute(s)
            session.commit()

    await enqueue_write_async(PRIO_UI_ACTION, _dismiss_all_global_sync)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Dev-only endpoint — disabled when ENV=production
# ---------------------------------------------------------------------------

_dev_router = APIRouter(tags=["notifications-dev"])


@_dev_router.post("/notifications/trigger")
async def trigger_notification_cycle() -> dict:
    """Manually trigger one full notification worker cycle.

    **For development and testing only.** Disabled when ENV=production.
    Raises 403 in production environments.
    """
    if settings.is_production:
        raise HTTPException(
            status_code=403,
            detail="Notification trigger endpoint is disabled in production",
        )
    from app.workers.notification_cycles import _notification_cycle_full

    loop = __import__("asyncio").get_running_loop()
    await loop.run_in_executor(None, _notification_cycle_full)
    return {"ok": True, "triggered_at": datetime.now().isoformat()}
