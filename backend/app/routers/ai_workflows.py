"""Router for AI workflows, runs, and custom prompts."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, TypeVar

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import current_user_id
from app.database import get_db
from app.models.ai_workflow import AiCustomPrompt, AiWorkflow, AiWorkflowRun
from app.schemas.ai_workflow import (
    PromptCreate,
    PromptOut,
    PromptUpdate,
    RunOut,
    WorkflowCreate,
    WorkflowOut,
    WorkflowPreviewOut,
    WorkflowPreviewRequest,
    WorkflowSummaryOut,
    WorkflowUpdate,
)
from app.services.workflow_schedule import (
    ScheduleError,
    build_cron,
    default_catch_up_hours,
    describe,
    next_run,
    next_runs,
    validate_cron,
)
from app.workers.workflow_scheduler import catch_up_missed, enqueue_due_runs

router = APIRouter(prefix="/ai", tags=["ai-workflows"])

T = TypeVar("T")


def current_user_dep() -> int:
    return current_user_id.get() or 1


async def _get_owned(db: AsyncSession, model: type[T], item_id: int, user_id: int) -> T:
    stmt = select(model).where(
        model.id == item_id,
        model.user_id == user_id,
        model.deleted_at.is_(None),
    )
    res = await db.execute(stmt)
    item = res.scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{model.__name__} not found")
    return item


def _workflow_to_out(wf: AiWorkflow) -> WorkflowOut:
    label = describe(wf.schedule_type, wf.cron_expression, wf.timezone)
    raw_symbols = []
    if wf.symbols_json:
        try:
            raw_symbols = json.loads(wf.symbols_json)
        except Exception:
            raw_symbols = []

    return WorkflowOut(
        id=wf.id,
        name=wf.name,
        description=wf.description,
        prompt=wf.prompt,
        schedule_type=wf.schedule_type,
        cron_expression=wf.cron_expression,
        timezone=wf.timezone,
        time_of_day=wf.time_of_day,
        days_of_week=wf.days_of_week,
        symbols=raw_symbols if isinstance(raw_symbols, list) else [],
        watchlist_id=wf.watchlist_id,
        model=wf.model,
        persona=wf.persona,
        mode=wf.mode,
        allow_write_tools=wf.allow_write_tools,
        is_enabled=wf.is_enabled,
        catch_up_enabled=wf.catch_up_enabled,
        catch_up_window_hours=wf.catch_up_window_hours,
        next_run_at=wf.next_run_at,
        last_run_at=wf.last_run_at,
        last_success_at=wf.last_success_at,
        schedule_label=label,
        created_at=wf.created_at,
    )


# ---------------------------------------------------------------------------
# Workflow Endpoints
# ---------------------------------------------------------------------------


@router.get("/workflows")
async def list_workflows(
    enabled: bool | None = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user_id: int = Depends(current_user_dep),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    base_cond = [AiWorkflow.user_id == user_id, AiWorkflow.deleted_at.is_(None)]
    if enabled is not None:
        base_cond.append(AiWorkflow.is_enabled == enabled)

    count_stmt = select(func.count(AiWorkflow.id)).where(*base_cond)
    total = (await db.execute(count_stmt)).scalar() or 0

    stmt = (
        select(AiWorkflow)
        .where(*base_cond)
        .order_by(AiWorkflow.next_run_at.asc().nulls_last(), AiWorkflow.id.asc())
        .offset(offset)
        .limit(limit)
    )
    items = (await db.execute(stmt)).scalars().all()

    return {
        "items": [_workflow_to_out(wf) for wf in items],
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": (offset + len(items)) < total,
    }


@router.post("/workflows", status_code=status.HTTP_201_CREATED, response_model=WorkflowOut)
async def create_workflow(
    payload: WorkflowCreate,
    user_id: int = Depends(current_user_dep),
    db: AsyncSession = Depends(get_db),
) -> WorkflowOut:
    tz = "Asia/Kolkata"
    if payload.schedule_type == "custom":
        if not payload.cron:
            raise HTTPException(status_code=400, detail="cron expression is required for custom schedule")
        cron_expr = payload.cron
    else:
        try:
            cron_expr = build_cron(
                payload.schedule_type,
                time_of_day=payload.time_of_day,
                days_of_week=payload.days_of_week,
                once_at=payload.once_at,
                tz=tz,
            )
        except ScheduleError as e:
            raise HTTPException(status_code=400, detail=str(e))

    try:
        validate_cron(cron_expr, tz)
    except ScheduleError as e:
        raise HTTPException(status_code=400, detail=str(e))

    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    try:
        computed_next_run = next_run(cron_expr, tz, now_utc)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to calculate next run: {e}")

    catch_up_window = (
        payload.catch_up_window_hours
        if payload.catch_up_window_hours is not None
        else default_catch_up_hours(payload.schedule_type)
    )

    days_of_week_str = None
    if payload.days_of_week is not None:
        days_of_week_str = ",".join(str(d) for d in sorted(payload.days_of_week))

    symbols_str = json.dumps(payload.symbols or [])

    wf = AiWorkflow(
        user_id=user_id,
        name=payload.name,
        prompt=payload.prompt,
        schedule_type=payload.schedule_type,
        cron_expression=cron_expr,
        timezone=tz,
        time_of_day=payload.time_of_day,
        days_of_week=days_of_week_str,
        once_at=payload.once_at,
        symbols_json=symbols_str,
        watchlist_id=payload.watchlist_id,
        model=payload.model,
        persona=payload.persona,
        allow_write_tools=payload.allow_write_tools,
        catch_up_enabled=payload.catch_up_enabled,
        catch_up_window_hours=catch_up_window,
        is_enabled=True,
        next_run_at=computed_next_run,
    )
    db.add(wf)
    await db.commit()
    await db.refresh(wf)
    return _workflow_to_out(wf)


@router.post("/workflows/preview", response_model=WorkflowPreviewOut)
async def preview_workflow(payload: WorkflowPreviewRequest) -> WorkflowPreviewOut:
    tz = payload.timezone or "Asia/Kolkata"
    if payload.schedule_type == "custom":
        if not payload.cron:
            raise HTTPException(status_code=400, detail="cron expression is required for custom schedule")
        cron_expr = payload.cron
    else:
        try:
            cron_expr = build_cron(
                payload.schedule_type,
                time_of_day=payload.time_of_day,
                days_of_week=payload.days_of_week,
                once_at=payload.once_at,
                tz=tz,
            )
        except ScheduleError as e:
            raise HTTPException(status_code=400, detail=str(e))

    try:
        validate_cron(cron_expr, tz)
    except ScheduleError as e:
        raise HTTPException(status_code=400, detail=str(e))

    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    try:
        runs = next_runs(cron_expr, tz, now_utc, count=3)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to calculate next runs: {e}")

    label = describe(payload.schedule_type, cron_expr, tz)
    return WorkflowPreviewOut(
        cron_expression=cron_expr,
        schedule_label=label,
        next_runs=runs,
    )


@router.post("/workflows/catch-up")
async def trigger_catch_up() -> dict[str, int]:
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    processed = await catch_up_missed(now_utc)
    enqueued = await enqueue_due_runs(now_utc)
    return {"processed": processed, "enqueued": enqueued}


@router.get("/workflows/summary", response_model=WorkflowSummaryOut)
async def get_workflows_summary(
    user_id: int = Depends(current_user_dep),
    db: AsyncSession = Depends(get_db),
) -> WorkflowSummaryOut:
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)

    armed_stmt = select(func.count(AiWorkflow.id)).where(
        AiWorkflow.user_id == user_id,
        AiWorkflow.deleted_at.is_(None),
        AiWorkflow.is_enabled == True,
    )
    armed = (await db.execute(armed_stmt)).scalar() or 0

    unread_stmt = select(func.count(AiWorkflowRun.id)).where(
        AiWorkflowRun.user_id == user_id,
        AiWorkflowRun.is_read == False,
        AiWorkflowRun.is_silent == False,
    )
    unread = (await db.execute(unread_stmt)).scalar() or 0

    running_stmt = select(func.count(AiWorkflowRun.id)).where(
        AiWorkflowRun.user_id == user_id,
        AiWorkflowRun.status == "running",
    )
    running = (await db.execute(running_stmt)).scalar() or 0

    next_stmt = select(func.min(AiWorkflow.next_run_at)).where(
        AiWorkflow.user_id == user_id,
        AiWorkflow.deleted_at.is_(None),
        AiWorkflow.is_enabled == True,
        AiWorkflow.next_run_at > now_utc,
    )
    next_run_at = (await db.execute(next_stmt)).scalar()

    return WorkflowSummaryOut(
        armed=armed,
        unread=unread,
        running=running,
        next_run_at=next_run_at,
        server_now=now_utc,
    )


@router.patch("/workflows/{workflow_id}", response_model=WorkflowOut)
async def update_workflow(
    workflow_id: int,
    payload: WorkflowUpdate,
    user_id: int = Depends(current_user_dep),
    db: AsyncSession = Depends(get_db),
) -> WorkflowOut:
    wf = await _get_owned(db, AiWorkflow, workflow_id, user_id)
    update_data = payload.model_dump(exclude_unset=True)

    schedule_fields = {"schedule_type", "time_of_day", "days_of_week", "cron", "once_at"}
    schedule_changed = bool(schedule_fields.intersection(update_data.keys()))

    enabled_flipped_on = False
    if "is_enabled" in update_data:
        if not wf.is_enabled and update_data["is_enabled"]:
            enabled_flipped_on = True

    if "name" in update_data:
        wf.name = update_data["name"]
    if "prompt" in update_data:
        wf.prompt = update_data["prompt"]
    if "symbols" in update_data:
        wf.symbols_json = json.dumps(update_data["symbols"] or [])
    if "watchlist_id" in update_data:
        wf.watchlist_id = update_data["watchlist_id"]
    if "model" in update_data:
        wf.model = update_data["model"]
    if "persona" in update_data:
        wf.persona = update_data["persona"]
    if "allow_write_tools" in update_data:
        wf.allow_write_tools = update_data["allow_write_tools"]
    if "catch_up_enabled" in update_data:
        wf.catch_up_enabled = update_data["catch_up_enabled"]
    if "catch_up_window_hours" in update_data:
        wf.catch_up_window_hours = update_data["catch_up_window_hours"]
    if "is_enabled" in update_data:
        wf.is_enabled = update_data["is_enabled"]

    new_schedule_type = update_data.get("schedule_type", wf.schedule_type)
    new_time_of_day = update_data.get("time_of_day", wf.time_of_day)
    new_once_at = update_data.get("once_at", wf.once_at)

    if "days_of_week" in update_data:
        dow = update_data["days_of_week"]
        new_days_of_week = ",".join(str(d) for d in sorted(dow)) if dow is not None else None
        dow_arg = dow
    else:
        new_days_of_week = wf.days_of_week
        dow_arg = [int(x) for x in wf.days_of_week.split(",")] if wf.days_of_week else None

    if schedule_changed or enabled_flipped_on:
        if new_schedule_type == "custom":
            new_cron = update_data.get("cron", wf.cron_expression)
            if not new_cron:
                raise HTTPException(status_code=400, detail="cron expression is required for custom schedule")
        else:
            try:
                new_cron = build_cron(
                    new_schedule_type,
                    time_of_day=new_time_of_day,
                    days_of_week=dow_arg,
                    once_at=new_once_at,
                    tz=wf.timezone,
                )
            except ScheduleError as e:
                raise HTTPException(status_code=400, detail=str(e))

        try:
            validate_cron(new_cron, wf.timezone)
        except ScheduleError as e:
            raise HTTPException(status_code=400, detail=str(e))

        wf.schedule_type = new_schedule_type
        wf.time_of_day = new_time_of_day
        wf.days_of_week = new_days_of_week
        wf.once_at = new_once_at
        wf.cron_expression = new_cron

        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        if wf.is_enabled:
            try:
                wf.next_run_at = next_run(wf.cron_expression, wf.timezone, now_utc)
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Failed to calculate next run: {e}")
        else:
            wf.next_run_at = None
    elif "is_enabled" in update_data and not wf.is_enabled:
        wf.next_run_at = None

    await db.commit()
    await db.refresh(wf)
    return _workflow_to_out(wf)


@router.delete("/workflows/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workflow(
    workflow_id: int,
    user_id: int = Depends(current_user_dep),
    db: AsyncSession = Depends(get_db),
) -> None:
    wf = await _get_owned(db, AiWorkflow, workflow_id, user_id)
    wf.deleted_at = datetime.now(timezone.utc).replace(tzinfo=None)
    wf.is_enabled = False
    wf.next_run_at = None
    await db.commit()


@router.post("/workflows/{workflow_id}/run", response_model=RunOut)
async def run_workflow_manual(
    workflow_id: int,
    user_id: int = Depends(current_user_dep),
    db: AsyncSession = Depends(get_db),
) -> RunOut:
    wf = await _get_owned(db, AiWorkflow, workflow_id, user_id)

    # 409 when a queued or running run exists
    active_check = await db.execute(
        select(AiWorkflowRun).where(
            AiWorkflowRun.workflow_id == wf.id,
            AiWorkflowRun.status.in_(["queued", "running"]),
        )
    )
    if active_check.scalars().first() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A run is already queued or running for this workflow",
        )

    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    slot_k = f"{wf.id}:manual:{int(now_utc.timestamp())}"

    run = AiWorkflowRun(
        workflow_id=wf.id,
        user_id=user_id,
        trigger="manual",
        status="queued",
        scheduled_for=now_utc,
        slot_key=slot_k,
        name_snapshot=wf.name,
        prompt_snapshot=wf.prompt,
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    return RunOut.model_validate(run)


# ---------------------------------------------------------------------------
# Workflow Run Endpoints
# ---------------------------------------------------------------------------


@router.get("/workflow-runs")
async def list_workflow_runs(
    workflow_id: int | None = Query(None),
    unread: bool | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user_id: int = Depends(current_user_dep),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    base_cond = [AiWorkflowRun.user_id == user_id]
    if workflow_id is not None:
        base_cond.append(AiWorkflowRun.workflow_id == workflow_id)
    if unread is not None:
        base_cond.append(AiWorkflowRun.is_read == (not unread))

    count_stmt = select(func.count(AiWorkflowRun.id)).where(*base_cond)
    total = (await db.execute(count_stmt)).scalar() or 0

    stmt = (
        select(AiWorkflowRun)
        .where(*base_cond)
        .order_by(AiWorkflowRun.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    items = (await db.execute(stmt)).scalars().all()

    return {
        "items": [RunOut.model_validate(r) for r in items],
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": (offset + len(items)) < total,
    }


@router.post("/workflow-runs/{run_id}/read")
async def mark_workflow_run_read(
    run_id: int,
    user_id: int = Depends(current_user_dep),
    db: AsyncSession = Depends(get_db),
) -> dict[str, bool]:
    stmt = select(AiWorkflowRun).where(
        AiWorkflowRun.id == run_id,
        AiWorkflowRun.user_id == user_id,
    )
    run = (await db.execute(stmt)).scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")

    run.is_read = True
    await db.commit()
    return {"ok": True}


@router.post("/workflow-runs/read-all")
async def mark_all_workflow_runs_read(
    user_id: int = Depends(current_user_dep),
    db: AsyncSession = Depends(get_db),
) -> dict[str, int]:
    stmt = select(AiWorkflowRun).where(
        AiWorkflowRun.user_id == user_id,
        AiWorkflowRun.is_read == False,
    )
    runs = (await db.execute(stmt)).scalars().all()
    count = len(runs)
    for r in runs:
        r.is_read = True
    if count > 0:
        await db.commit()
    return {"updated": count}


# ---------------------------------------------------------------------------
# Custom Prompts Endpoints
# ---------------------------------------------------------------------------


@router.get("/prompts")
async def list_prompts(
    mode: str | None = Query(None),
    limit: int = Query(4, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user_id: int = Depends(current_user_dep),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    base_cond = [AiCustomPrompt.user_id == user_id, AiCustomPrompt.deleted_at.is_(None)]
    if mode is not None:
        base_cond.append(AiCustomPrompt.mode == mode)

    count_stmt = select(func.count(AiCustomPrompt.id)).where(*base_cond)
    total = (await db.execute(count_stmt)).scalar() or 0

    stmt = (
        select(AiCustomPrompt)
        .where(*base_cond)
        .order_by(AiCustomPrompt.sort_order.asc(), AiCustomPrompt.id.asc())
        .offset(offset)
        .limit(limit)
    )
    items = (await db.execute(stmt)).scalars().all()

    return {
        "items": [PromptOut.model_validate(p) for p in items],
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": (offset + len(items)) < total,
    }


@router.post("/prompts", status_code=status.HTTP_201_CREATED, response_model=PromptOut)
async def create_prompt(
    payload: PromptCreate,
    user_id: int = Depends(current_user_dep),
    db: AsyncSession = Depends(get_db),
) -> PromptOut:
    max_order_stmt = select(func.max(AiCustomPrompt.sort_order)).where(
        AiCustomPrompt.user_id == user_id,
        AiCustomPrompt.deleted_at.is_(None),
    )
    max_order = (await db.execute(max_order_stmt)).scalar()
    sort_order = 0 if max_order is None else max_order + 1

    prompt_item = AiCustomPrompt(
        user_id=user_id,
        title=payload.title,
        tag=payload.tag,
        description=payload.description,
        prompt=payload.prompt,
        icon=payload.icon,
        mode=payload.mode,
        sort_order=sort_order,
    )
    db.add(prompt_item)
    await db.commit()
    await db.refresh(prompt_item)
    return PromptOut.model_validate(prompt_item)


@router.patch("/prompts/{prompt_id}", response_model=PromptOut)
async def update_prompt(
    prompt_id: int,
    payload: PromptUpdate,
    user_id: int = Depends(current_user_dep),
    db: AsyncSession = Depends(get_db),
) -> PromptOut:
    prompt_item = await _get_owned(db, AiCustomPrompt, prompt_id, user_id)
    update_data = payload.model_dump(exclude_unset=True)

    for field, val in update_data.items():
        setattr(prompt_item, field, val)

    await db.commit()
    await db.refresh(prompt_item)
    return PromptOut.model_validate(prompt_item)


@router.delete("/prompts/{prompt_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_prompt(
    prompt_id: int,
    user_id: int = Depends(current_user_dep),
    db: AsyncSession = Depends(get_db),
) -> None:
    prompt_item = await _get_owned(db, AiCustomPrompt, prompt_id, user_id)
    prompt_item.deleted_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await db.commit()


@router.post("/prompts/{prompt_id}/used")
async def mark_prompt_used(
    prompt_id: int,
    user_id: int = Depends(current_user_dep),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    prompt_item = await _get_owned(db, AiCustomPrompt, prompt_id, user_id)
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    prompt_item.use_count += 1
    prompt_item.last_used_at = now_utc
    await db.commit()
    return {"use_count": prompt_item.use_count, "last_used_at": now_utc}
