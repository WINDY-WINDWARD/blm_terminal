"""FastAPI router for user layout management endpoints."""

import time
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.layout import UserLayout
from app.models.user import User
from app.schemas.layout import (
    LayoutCreateOrUpdate,
    LayoutOut,
    LayoutRename,
    LayoutSyncResponse,
    LayoutTombstoneOut,
)
from app.services.write_queue import enqueue_write_async, PRIO_UI_ACTION
from app.database import _SyncSessionLocal

router = APIRouter()


@router.get("/layouts", response_model=List[LayoutOut], tags=["layouts"])
async def list_user_layouts(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> List[LayoutOut]:
    """Return all active saved layouts for the authenticated user."""
    stmt = (
        select(UserLayout)
        .where(
            UserLayout.user_id == current_user.id,
            UserLayout.deleted_at.is_(None),
        )
        .order_by(UserLayout.name)
    )
    res = await db.execute(stmt)
    layouts = res.scalars().all()
    return [LayoutOut.model_validate(l) for l in layouts]


@router.put("/layouts/{name}", response_model=LayoutOut, tags=["layouts"])
async def save_or_update_user_layout(
    name: str,
    body: LayoutCreateOrUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LayoutOut:
    """Save or overwrite a user layout by name (explicit user action).

    Revives tombstoned layouts if previously soft-deleted.
    """
    clean_name = name.strip().lower()
    
    # Validate layout name length (max 64 characters)
    if len(clean_name) > 64:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Layout name must be ≤ 64 characters",
        )
    
    if body.name != clean_name:
        body.name = clean_name

    def _save_layout_sync() -> dict:
        with _SyncSessionLocal() as session:
            stmt = select(UserLayout).where(
                UserLayout.user_id == current_user.id,
                UserLayout.name == clean_name,
            )
            ex = session.execute(stmt).scalar_one_or_none()
            if ex:
                ex.active_panels = body.active_panels
                ex.panel_count = body.panel_count
                ex.merged_groups = body.merged_groups
                ex.saved_at = body.saved_at
                ex.deleted_at = None
                target = ex
            else:
                target = UserLayout(
                    user_id=current_user.id,
                    name=clean_name,
                    active_panels=body.active_panels,
                    panel_count=body.panel_count,
                    merged_groups=body.merged_groups,
                    saved_at=body.saved_at,
                    deleted_at=None,
                )
                session.add(target)
            session.commit()
            session.refresh(target)
            return {
                "id": target.id,
                "user_id": target.user_id,
                "name": target.name,
                "active_panels": target.active_panels,
                "panel_count": target.panel_count,
                "merged_groups": target.merged_groups,
                "saved_at": target.saved_at,
                "created_at": target.created_at,
                "deleted_at": target.deleted_at,
            }

    out_dict = await enqueue_write_async(PRIO_UI_ACTION, _save_layout_sync)
    return LayoutOut.model_validate(out_dict)


@router.post("/layouts/bulk-sync", response_model=LayoutSyncResponse, tags=["layouts"])
async def bulk_sync_user_layouts(
    body: List[LayoutCreateOrUpdate],
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LayoutSyncResponse:
    """Bulk sync local layouts with server database.

    Rules for passive background sync:
    - Server ALWAYS wins for existing layouts or tombstones.
    - If local layout does not exist on server (no active layout and no tombstone), create it.
    - Returns active server layouts and tombstones.
    """
    stmt = select(UserLayout).where(UserLayout.user_id == current_user.id)
    existing_list = (await db.execute(stmt)).scalars().all()
    existing_map = {l.name: l for l in existing_list}

    def _bulk_sync() -> None:
        with _SyncSessionLocal() as session:
            stmt = select(UserLayout).where(UserLayout.user_id == current_user.id)
            existing_list = session.execute(stmt).scalars().all()
            existing_map = {l.name: l for l in existing_list}
            for item in body:
                c_name = item.name.strip().lower()
                if existing_map.get(c_name) is None:
                    new_l = UserLayout(
                        user_id=current_user.id,
                        name=c_name,
                        active_panels=item.active_panels,
                        panel_count=item.panel_count,
                        merged_groups=item.merged_groups,
                        saved_at=item.saved_at,
                        deleted_at=None,
                    )
                    session.add(new_l)
            session.commit()

    await enqueue_write_async(PRIO_UI_ACTION, _bulk_sync)

    # Re-fetch active layouts
    stmt_active = (
        select(UserLayout)
        .where(
            UserLayout.user_id == current_user.id,
            UserLayout.deleted_at.is_(None),
        )
        .order_by(UserLayout.name)
    )
    res_active = await db.execute(stmt_active)
    active_layouts = res_active.scalars().all()

    # Re-fetch tombstones
    stmt_tombstones = (
        select(UserLayout)
        .where(
            UserLayout.user_id == current_user.id,
            UserLayout.deleted_at.is_not(None),
        )
        .order_by(UserLayout.name)
    )
    res_tombstones = await db.execute(stmt_tombstones)
    tombstone_layouts = res_tombstones.scalars().all()

    return LayoutSyncResponse(
        layouts=[LayoutOut.model_validate(l) for l in active_layouts],
        tombstones=[LayoutTombstoneOut.model_validate(t) for t in tombstone_layouts],
    )


@router.patch("/layouts/{name}/rename", response_model=LayoutOut, tags=["layouts"])
async def rename_user_layout(
    name: str,
    body: LayoutRename,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LayoutOut:
    """Rename an existing active layout for the authenticated user."""
    old_name = name.strip().lower()
    new_name = body.new_name.strip().lower()
    
    # Validate layout name length (max 64 characters)
    if len(new_name) > 64:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Layout name must be ≤ 64 characters",
        )

    if old_name == new_name:
        stmt = select(UserLayout).where(
            UserLayout.user_id == current_user.id,
            UserLayout.name == old_name,
            UserLayout.deleted_at.is_(None),
        )
        layout = (await db.execute(stmt)).scalar_one_or_none()
        if not layout:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Active layout '{old_name}' not found",
            )
        return LayoutOut.model_validate(layout)

    # Check if active target layout exists
    target_stmt = select(UserLayout).where(
        UserLayout.user_id == current_user.id,
        UserLayout.name == new_name,
    )
    target_existing = (await db.execute(target_stmt)).scalar_one_or_none()
    if target_existing and target_existing.deleted_at is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Layout '{new_name}' already exists",
        )

    stmt = select(UserLayout).where(
        UserLayout.user_id == current_user.id,
        UserLayout.name == old_name,
        UserLayout.deleted_at.is_(None),
    )
    layout = (await db.execute(stmt)).scalar_one_or_none()
    if not layout:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Active layout '{old_name}' not found",
        )

    def _rename_sync() -> dict:
        with _SyncSessionLocal() as session:
            if target_existing and target_existing.deleted_at is not None:
                t_ex = session.execute(
                    select(UserLayout).where(
                        UserLayout.user_id == current_user.id,
                        UserLayout.name == new_name,
                    )
                ).scalar_one_or_none()
                if t_ex:
                    session.delete(t_ex)
                    session.flush()

            stmt_find = select(UserLayout).where(
                UserLayout.user_id == current_user.id,
                UserLayout.name == old_name,
                UserLayout.deleted_at.is_(None),
            )
            lay = session.execute(stmt_find).scalar_one_or_none()
            if not lay:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Active layout '{old_name}' not found")
            lay.name = new_name
            session.commit()
            session.refresh(lay)
            return {
                "id": lay.id,
                "user_id": lay.user_id,
                "name": lay.name,
                "active_panels": lay.active_panels,
                "panel_count": lay.panel_count,
                "merged_groups": lay.merged_groups,
                "saved_at": lay.saved_at,
                "created_at": lay.created_at,
                "deleted_at": lay.deleted_at,
            }

    res_dict = await enqueue_write_async(PRIO_UI_ACTION, _rename_sync)
    return LayoutOut.model_validate(res_dict)


@router.delete("/layouts/{name}", tags=["layouts"])
async def delete_user_layout(
    name: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Soft-delete a user layout by name (creates a persistent tombstone)."""
    clean_name = name.strip().lower()
    stmt = select(UserLayout).where(
        UserLayout.user_id == current_user.id,
        UserLayout.name == clean_name,
    )
    layout = (await db.execute(stmt)).scalar_one_or_none()
    if layout and layout.deleted_at is None:
        def _soft_del_sync():
            with _SyncSessionLocal() as session:
                target_lay = session.execute(
                    select(UserLayout).where(
                        UserLayout.user_id == current_user.id,
                        UserLayout.name == clean_name,
                    )
                ).scalar_one_or_none()
                if target_lay and target_lay.deleted_at is None:
                    target_lay.deleted_at = int(time.time() * 1000)
                    session.commit()

        await enqueue_write_async(PRIO_UI_ACTION, _soft_del_sync)

    return {"ok": True}
