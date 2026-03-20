"""FastAPI router for the notifications API."""

import os
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.notification import Notification
from app.schemas.notification import NotificationOut

router = APIRouter()


@router.get("/notifications", response_model=list[NotificationOut], tags=["notifications"])
async def list_notifications(
    watchlist_id: Annotated[int, Query()],
    db: AsyncSession = Depends(get_db),
) -> list[NotificationOut]:
    """Return unread notifications for a watchlist, newest first."""
    stmt = (
        select(Notification)
        .where(Notification.watchlist_id == watchlist_id, Notification.is_read == False)
        .order_by(Notification.triggered_at.desc())
    )
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
