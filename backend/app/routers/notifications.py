"""FastAPI router for the notifications API."""

import os
from datetime import date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.notification import Notification, GlobalNotification
from app.schemas.notification import NotificationOut, GlobalNotificationOut

router = APIRouter()


@router.get("/notifications", response_model=list[NotificationOut], tags=["notifications"])
async def list_notifications(
    watchlist_id: Annotated[int, Query()],
    days: Annotated[int, Query()] = 2,
    read_filter: Annotated[str, Query()] = "unread",
    db: AsyncSession = Depends(get_db),
) -> list[NotificationOut]:
    """Return notifications for a watchlist, newest first.

    - days: number of past days to include (default 2)
    - read_filter: 'unread' (default), 'read', or 'all'
    """
    cutoff_date = date.today() - timedelta(days=days - 1)
    stmt = select(Notification).where(
        Notification.watchlist_id == watchlist_id,
        Notification.triggered_date >= cutoff_date,
    )
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
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Soft-delete a single notification (set is_read=True).

    Returns 403 if the notification does not belong to the specified watchlist_id.
    """
    notif = await db.get(Notification, notif_id)
    if notif is None:
        raise HTTPException(status_code=404, detail=f"Notification {notif_id} not found")
    if notif.watchlist_id != watchlist_id:
        raise HTTPException(
            status_code=403,
            detail=f"Notification {notif_id} does not belong to watchlist {watchlist_id}",
        )
    notif.is_read = True
    await db.commit()
    return {"ok": True}


@router.delete("/notifications", tags=["notifications"])
async def dismiss_all_notifications(
    all: Annotated[bool, Query(alias="all")],
    watchlist_id: Annotated[int, Query()],
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Soft-delete all unread notifications for a watchlist.

    Requires ?all=true query param. Without it, returns 400.
    """
    if not all:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing ?all=true query param",
        )
    stmt = (
        update(Notification)
        .where(Notification.watchlist_id == watchlist_id, Notification.is_read == False)
        .values(is_read=True)
    )
    await db.execute(stmt)
    await db.commit()
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
) -> dict:
    """Soft-delete a single global notification (set is_read=True)."""
    notif = await db.get(GlobalNotification, notif_id)
    if notif is None:
        raise HTTPException(status_code=404, detail=f"Global notification {notif_id} not found")
    notif.is_read = True
    await db.commit()
    return {"ok": True}


@router.delete("/notifications/global", tags=["notifications"])
async def dismiss_all_global_notifications(
    all: Annotated[bool, Query(alias="all")],
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Soft-delete all unread global notifications.

    Requires ?all=true query param.
    """
    if not all:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing ?all=true query param",
        )
    stmt = (
        update(GlobalNotification)
        .where(GlobalNotification.is_read == False)
        .values(is_read=True)
    )
    await db.execute(stmt)
    await db.commit()
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
    if os.environ.get("ENV") == "production":
        raise HTTPException(
            status_code=403,
            detail="Notification trigger endpoint is disabled in production",
        )
    from app.backgroundtasks import _notification_cycle_full

    loop = __import__("asyncio").get_running_loop()
    await loop.run_in_executor(None, _notification_cycle_full)
    return {"ok": True, "triggered_at": datetime.now().isoformat()}
