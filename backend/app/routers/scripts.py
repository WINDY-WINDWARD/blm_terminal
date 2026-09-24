"""FastAPI router for BLM Script Lab (user chart scripts, spec v1).

UI endpoints manage metadata, chart state, and transport (export/import).
AI-only endpoints (called by AI tools, never by the UI by design):
POST /scripts (create, rev 1) and POST /scripts/{id}/revise (rev N+1).
There is deliberately NO UI code-update endpoint — code reaches the backend
only through AI validate -> save/revise flows.
"""

import time

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.script import SavedScript, ScriptChartState, ScriptRevision
from app.models.user import User
from app.schemas.script import (
    ChartStateOut,
    ChartStateSetIn,
    ScriptCreateIn,
    ScriptDetailOut,
    ScriptImportIn,
    ScriptRenameIn,
    ScriptRevisionOut,
    ScriptReviseIn,
    ScriptRollbackIn,
    ScriptSummaryOut,
    ValidateIn,
    ValidateOut,
    validate_script,
)
from app.services import script_seeds

router = APIRouter()


def _now_ms() -> int:
    return int(time.time() * 1000)


def _rev_out(rev: ScriptRevision) -> ScriptRevisionOut:
    return ScriptRevisionOut(
        rev_no=rev.rev_no,
        manifest=dict(rev.manifest),
        code=rev.code,
        note=rev.note or "",
        chat_session_id=rev.chat_session_id,
        created_at=rev.created_at,
    )


async def _get_script(db: AsyncSession, user_id: int, script_id: int) -> SavedScript:
    q = select(SavedScript).where(
        SavedScript.id == script_id,
        SavedScript.user_id == user_id,
        SavedScript.deleted_at.is_(None),
    )
    script = (await db.execute(q)).scalar_one_or_none()
    if script is None:
        raise HTTPException(status_code=404, detail="script not found")
    return script


async def _head_rev(db: AsyncSession, script: SavedScript) -> ScriptRevision | None:
    if script.head_rev_id is None:
        return None
    return await db.get(ScriptRevision, script.head_rev_id)


def _migrate_params(old_manifest: dict, new_manifest: dict, values: dict) -> dict:
    """Param auto-migration: surviving keys keep values, new keys dropped
    (host fills manifest defaults), removed keys dropped. Prototype-polluting
    keys are never carried over (frontend params.ts parity)."""
    old_keys = {p.get("key") for p in old_manifest.get("params", []) if isinstance(p, dict)}
    new_keys = {p.get("key") for p in new_manifest.get("params", []) if isinstance(p, dict)}
    return {
        k: v
        for k, v in values.items()
        if k in old_keys and k in new_keys and k not in ("__proto__", "constructor", "prototype")
    }


@router.get("/scripts", response_model=list[ScriptSummaryOut], tags=["scripts"])
async def list_scripts(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ScriptSummaryOut]:
    """List live scripts (builtins seeded lazily on first call)."""
    await script_seeds.ensure_builtin_seeds(db, current_user.id)
    q = (
        select(SavedScript, ScriptRevision.rev_no)
        .outerjoin(ScriptRevision, ScriptRevision.id == SavedScript.head_rev_id)
        .where(SavedScript.user_id == current_user.id, SavedScript.deleted_at.is_(None))
        .order_by(SavedScript.is_builtin.desc(), SavedScript.name)
    )
    rows = (await db.execute(q)).all()
    return [
        ScriptSummaryOut(
            id=s.id, name=s.name, description=s.description or "",
            is_builtin=bool(s.is_builtin), head_rev_no=rev_no,
            updated_at=s.updated_at,
        )
        for s, rev_no in rows
    ]


@router.get("/scripts/{script_id}", response_model=ScriptDetailOut, tags=["scripts"])
async def get_script(
    script_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ScriptDetailOut:
    script = await _get_script(db, current_user.id, script_id)
    q = (
        select(ScriptRevision)
        .where(ScriptRevision.script_id == script.id)
        .order_by(ScriptRevision.rev_no)
    )
    revs = (await db.execute(q)).scalars().all()
    history = [_rev_out(r) for r in revs]
    head_rev = await _head_rev(db, script)
    head = _rev_out(head_rev) if head_rev else None
    return ScriptDetailOut(
        id=script.id, name=script.name, description=script.description or "",
        is_builtin=bool(script.is_builtin),
        head_rev_no=head.rev_no if head else None, head=head, history=history,
    )


@router.post("/scripts/validate", response_model=ValidateOut, tags=["scripts"])
async def validate_endpoint(body: ValidateIn) -> ValidateOut:
    """Schema + static validation. The backend never executes JS."""
    manifest, errors = validate_script(body.code)
    if manifest is None:
        return ValidateOut(valid=False, errors=errors)
    return ValidateOut(
        valid=not errors, errors=errors, name=manifest.name,
        outputs=[o.id for o in manifest.outputs],
        params=[p.key for p in manifest.params],
    )


@router.post("/scripts", response_model=ScriptDetailOut, status_code=201, tags=["scripts"])
async def create_script(
    body: ScriptCreateIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ScriptDetailOut:
    """AI-only by design: create a script at rev 1. Validates first."""
    manifest, errors = validate_script(body.code)
    if manifest is None or errors:
        raise HTTPException(status_code=422, detail=errors or ["invalid script"])
    script = SavedScript(
        user_id=current_user.id, name=body.name,
        description=body.description or manifest.description,
    )
    db.add(script)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="a script with this name already exists")
    rev = ScriptRevision(
        script_id=script.id, rev_no=1, manifest=manifest.model_dump(),
        code=body.code, note=body.note, chat_session_id=body.chat_session_id,
    )
    db.add(rev)
    await db.flush()
    script.head_rev_id = rev.id
    await db.commit()
    return await get_script(script.id, current_user, db)


@router.post("/scripts/{script_id}/revise", response_model=ScriptDetailOut, tags=["scripts"])
async def revise_script(
    script_id: int,
    body: ScriptReviseIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ScriptDetailOut:
    """AI-only by design: append rev N+1 + migrate chart-state params."""
    script = await _get_script(db, current_user.id, script_id)
    if script.is_builtin:
        raise HTTPException(status_code=403, detail="builtin scripts cannot be revised (import a copy first)")
    manifest, errors = validate_script(body.code)
    if manifest is None or errors:
        raise HTTPException(status_code=422, detail=errors or ["invalid script"])
    head = await _head_rev(db, script)
    next_rev_no = (head.rev_no + 1) if head else 1
    old_manifest = dict(head.manifest) if head else {}
    rev = ScriptRevision(
        script_id=script.id, rev_no=next_rev_no, manifest=manifest.model_dump(),
        code=body.code, note=body.note, chat_session_id=body.chat_session_id,
    )
    db.add(rev)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="revision conflict — retry")
    script.head_rev_id = rev.id
    # Param auto-migration on every chart slot using this script.
    q = select(ScriptChartState).where(
        ScriptChartState.user_id == current_user.id,
        ScriptChartState.script_id == script.id,
    )
    for st in (await db.execute(q)).scalars().all():
        st.param_values = _migrate_params(old_manifest, manifest.model_dump(), dict(st.param_values or {}))
    await db.commit()
    return await get_script(script.id, current_user, db)


@router.post("/scripts/{script_id}/rename", response_model=ScriptSummaryOut, tags=["scripts"])
async def rename_script(
    script_id: int,
    body: ScriptRenameIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ScriptSummaryOut:
    script = await _get_script(db, current_user.id, script_id)
    if script.is_builtin:
        raise HTTPException(status_code=403, detail="builtin scripts cannot be renamed")
    script.name = body.name
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="a script with this name already exists")
    # onupdate columns (updated_at) expire on UPDATE — refresh before reading.
    await db.refresh(script)
    head = await _head_rev(db, script)
    return ScriptSummaryOut(
        id=script.id, name=script.name, description=script.description or "",
        is_builtin=False, head_rev_no=head.rev_no if head else None,
        updated_at=script.updated_at,
    )


@router.post("/scripts/{script_id}/delete", tags=["scripts"])
async def delete_script(
    script_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    script = await _get_script(db, current_user.id, script_id)
    if script.is_builtin:
        raise HTTPException(status_code=403, detail="builtin scripts cannot be deleted")
    script.deleted_at = _now_ms()
    await db.commit()
    return {"ok": True}


@router.post("/scripts/{script_id}/rollback", response_model=ScriptDetailOut, tags=["scripts"])
async def rollback_script(
    script_id: int,
    body: ScriptRollbackIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ScriptDetailOut:
    """Re-point the head at an older revision (history is never deleted)."""
    script = await _get_script(db, current_user.id, script_id)
    q = select(ScriptRevision).where(
        ScriptRevision.script_id == script.id, ScriptRevision.rev_no == body.rev_no
    )
    rev = (await db.execute(q)).scalar_one_or_none()
    if rev is None:
        raise HTTPException(status_code=404, detail="revision not found")
    # Rollback re-points the head, so stored chart params must migrate the
    # same way revise does — otherwise a later disable 422s on unknown keys.
    old_head = await _head_rev(db, script)
    old_manifest = old_head.manifest if old_head is not None else {"params": []}
    new_manifest = rev.manifest or {}
    script.head_rev_id = rev.id
    rows = (
        await db.execute(
            select(ScriptChartState).where(
                ScriptChartState.user_id == current_user.id,
                ScriptChartState.script_id == script.id,
            )
        )
    ).scalars().all()
    for st in rows:
        st.param_values = _migrate_params(
            old_manifest, new_manifest, dict(st.param_values or {})
        )
    await db.commit()
    return await get_script(script.id, current_user, db)


@router.get("/chart-state", response_model=list[ChartStateOut], tags=["scripts"])
async def get_chart_state(
    panel_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ChartStateOut]:
    q = (
        select(ScriptChartState, SavedScript.name, ScriptRevision.rev_no)
        .join(SavedScript, SavedScript.id == ScriptChartState.script_id)
        .outerjoin(ScriptRevision, ScriptRevision.id == SavedScript.head_rev_id)
        .where(
            ScriptChartState.user_id == current_user.id,
            ScriptChartState.panel_id == panel_id,
            SavedScript.deleted_at.is_(None),
        )
    )
    return [
        ChartStateOut(
            script_id=st.script_id, enabled=bool(st.enabled),
            param_values=dict(st.param_values or {}), name=name,
            head_rev_no=rev_no,
        )
        for st, name, rev_no in (await db.execute(q)).all()
    ]


@router.post("/chart-state", response_model=ChartStateOut, tags=["scripts"])
async def set_chart_state(
    panel_id: str,
    body: ChartStateSetIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChartStateOut:
    script = await _get_script(db, current_user.id, body.script_id)
    head = await _head_rev(db, script)
    if head is None:
        raise HTTPException(status_code=422, detail="script has no revisions")
    valid_keys = {p.get("key") for p in head.manifest.get("params", []) if isinstance(p, dict)}
    incoming = body.param_values if body.param_values is not None else None
    unknown = set(incoming or {}) - valid_keys
    if unknown:
        raise HTTPException(status_code=422, detail=f"unknown params: {sorted(unknown)}")
    q = select(ScriptChartState).where(
        ScriptChartState.user_id == current_user.id,
        ScriptChartState.panel_id == panel_id,
        ScriptChartState.script_id == script.id,
    )
    st = (await db.execute(q)).scalar_one_or_none()
    if st is None:
        st = ScriptChartState(
            user_id=current_user.id, panel_id=panel_id, script_id=script.id,
            enabled=body.enabled, param_values=dict(incoming or {}),
            added_at=_now_ms(),
        )
        db.add(st)
    else:
        st.enabled = body.enabled
        if incoming is not None:
            st.param_values = dict(incoming)
    await db.commit()
    return ChartStateOut(
        script_id=script.id, enabled=bool(st.enabled),
        param_values=dict(st.param_values or {}), name=script.name,
        head_rev_no=head.rev_no,
    )


@router.get("/scripts/{script_id}/export", tags=["scripts"])
async def export_script(
    script_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Export envelope (transport only — importing creates a new user script)."""
    script = await _get_script(db, current_user.id, script_id)
    head = await _head_rev(db, script)
    if head is None:
        raise HTTPException(status_code=422, detail="script has no revisions")
    return {
        "kind": "blm-script-export",
        "version": 1,
        "name": script.name,
        "description": script.description or "",
        "manifest": dict(head.manifest),
        "code": head.code,
    }


@router.post("/scripts/import", response_model=ScriptDetailOut, status_code=201, tags=["scripts"])
async def import_script(
    body: ScriptImportIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ScriptDetailOut:
    payload = body.payload
    if payload.get("kind") != "blm-script-export" or payload.get("version") != 1:
        raise HTTPException(status_code=422, detail="not a v1 blm-script-export envelope")
    code = payload.get("code", "")
    manifest, errors = validate_script(code)
    if manifest is None or errors:
        raise HTTPException(status_code=422, detail=errors or ["invalid script"])
    script = SavedScript(
        user_id=current_user.id,
        name=str(payload.get("name") or manifest.name)[:64],
        description=str(payload.get("description") or "")[:280],
    )
    db.add(script)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="a script with this name already exists")
    rev = ScriptRevision(
        script_id=script.id, rev_no=1, manifest=manifest.model_dump(), code=code,
        note="imported",
    )
    db.add(rev)
    await db.flush()
    script.head_rev_id = rev.id
    await db.commit()
    return await get_script(script.id, current_user, db)


@router.get("/scripts/stats/count", tags=["scripts"])
async def scripts_count(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    q = select(func.count()).select_from(SavedScript).where(
        SavedScript.user_id == current_user.id, SavedScript.deleted_at.is_(None)
    )
    return {"count": (await db.execute(q)).scalar() or 0}
