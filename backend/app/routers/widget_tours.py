"""FastAPI router for widget tour persistence."""

import time

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import _SyncSessionLocal, get_db
from app.models.user import User
from app.models.widget_tour import WidgetTour
from app.schemas.widget_tour import (
    PANEL_COMMAND_SET,
    WidgetTourMarkSeen,
    WidgetTourResponse,
    WidgetToursResponse,
)
from app.services.write_queue import PRIO_UI_ACTION, enqueue_write_async

router = APIRouter(tags=["widget-tours"])


@router.get("/widget-tours", response_model=WidgetToursResponse)
async def get_widget_tours(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WidgetToursResponse:
    """Return seen map for all tours completed by the authenticated user."""
    stmt = select(WidgetTour).where(WidgetTour.user_id == current_user.id)
    res = await db.execute(stmt)
    tours = res.scalars().all()
    seen_map = {t.widget_command: t.seen_at for t in tours}
    return WidgetToursResponse(seen=seen_map)


@router.post("/widget-tours", response_model=WidgetTourResponse)
async def mark_widget_tour_seen(
    body: WidgetTourMarkSeen,
    current_user: User = Depends(get_current_user),
) -> WidgetTourResponse:
    """Mark a widget tour as seen for the authenticated user (upsert)."""
    command = body.command.strip().upper()
    if command not in PANEL_COMMAND_SET:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown widget command: {body.command}",
        )

    now_ms = int(time.time() * 1000)

    def _save_tour_sync() -> dict:
        with _SyncSessionLocal() as session:
            stmt = select(WidgetTour).where(
                WidgetTour.user_id == current_user.id,
                WidgetTour.widget_command == command,
            )
            ex = session.execute(stmt).scalar_one_or_none()
            if ex:
                ex.seen_at = now_ms
                target = ex
            else:
                target = WidgetTour(
                    user_id=current_user.id,
                    widget_command=command,
                    seen_at=now_ms,
                )
                session.add(target)
            session.commit()
            session.refresh(target)
            return {
                "command": target.widget_command,
                "seen_at": target.seen_at,
            }

    out_dict = await enqueue_write_async(PRIO_UI_ACTION, _save_tour_sync)
    return WidgetTourResponse.model_validate(out_dict)
