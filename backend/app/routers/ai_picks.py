from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from typing import List, Optional
from datetime import datetime, timezone

from app.database import get_db
from app.auth import get_admin_user
from app.models.user import User
from app.models.ai_picks import AIPick, PickStatus, AIPickTrace
from app.schemas.ai_picks import (
    AIPickResponse,
    PickStatusUpdate,
    AIPickTraceResponse,
    AIPickTriggerResponse,
)
from app.jobs.runner import get_job_status, trigger_job, sync_job_to_db

router = APIRouter(prefix="/ai", tags=["ai-picks"])

@router.get("/picks/traces", response_model=List[AIPickTraceResponse])
async def get_pick_traces(
    limit: int = Query(50, description="Max traces to return"),
    db: AsyncSession = Depends(get_db)
):
    query = select(AIPickTrace).order_by(desc(AIPickTrace.created_at)).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()

@router.get("/picks", response_model=List[AIPickResponse])
async def get_all_picks(
    status: Optional[PickStatus] = Query(None, description="Filter by pick status"),
    db: AsyncSession = Depends(get_db)
):
    query = select(AIPick).order_by(AIPick.updated_at.desc())
    if status:
        query = query.where(AIPick.status == status)
    
    result = await db.execute(query)
    picks = result.scalars().all()
    return picks

@router.put("/picks/{pick_id}/status", response_model=AIPickResponse)
async def update_pick_status(
    pick_id: int, 
    update_data: PickStatusUpdate, 
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_admin_user)
):
    result = await db.execute(select(AIPick).where(AIPick.id == pick_id))
    pick = result.scalar_one_or_none()
    
    if not pick:
        raise HTTPException(status_code=404, detail="AI Pick not found")
    
    # Only update timestamp if status actually changes
    if pick.status != update_data.status:
        pick.status = update_data.status
        pick.status_updated_at = datetime.now(timezone.utc)
    
    # Update exit_price if provided
    if update_data.exit_price is not None:
        pick.exit_price = update_data.exit_price
    
    await db.commit()
    await db.refresh(pick)
        
    return pick


@router.post("/picks/trigger", response_model=AIPickTriggerResponse)
async def trigger_picks_run(
    mode: str = Query("morning", description="Run mode: 'morning'/'hunter' or 'evening'/'verifier'/'evaluator'"),
    force: bool = Query(False, description="Bypass the 15-minute cooldown gate if True"),
    admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Trigger an AI Picks run (Hunter+Verifier morning loop or Evaluator evening loop).

    Enforces a 15-minute gating window to prevent duplicate or excessive runs.
    When manually triggered, the orchestrator updates job timestamps and config,
    ensuring that background cron daemons recognize the run and skip duplicate execution.
    """
    normalized_mode = mode.lower().strip()
    mode_to_job = {
        "morning": "job.ai_picks_morning",
        "hunter": "job.ai_picks_morning",
        "evening": "job.ai_picks_evening",
        "verifier": "job.ai_picks_evening",
        "evaluator": "job.ai_picks_evening",
    }

    if normalized_mode not in mode_to_job:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid mode '{mode}'. Valid modes: {list(mode_to_job.keys())}"
        )

    job_key = mode_to_job[normalized_mode]
    job = await get_job_status(job_key)
    if not job:
        await sync_job_to_db(job_key)
        job = await get_job_status(job_key)

    if not job:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_key}")

    # Check if job is currently executing
    if job.status == "running":
        return AIPickTriggerResponse(
            ok=False,
            gated=True,
            message="A run is currently in progress. Please wait for it to complete."
        )

    # 15-minute gate (900 seconds)
    if not force and job.last_triggered_at:
        now = datetime.now(timezone.utc)
        last_trig = job.last_triggered_at
        if last_trig.tzinfo is None:
            last_trig = last_trig.replace(tzinfo=timezone.utc)
        elapsed = (now - last_trig).total_seconds()
        gate_window = 900  # 15 minutes
        if elapsed < gate_window:
            remaining_secs = int(gate_window - elapsed)
            remaining_mins = max(1, (remaining_secs + 59) // 60)
            return AIPickTriggerResponse(
                ok=False,
                gated=True,
                message=f"Run triggered recently. Please wait {remaining_mins} min{'s' if remaining_mins > 1 else ''} before triggering another run (15-min cooldown)."
            )

    # Trigger job asynchronously via the background job runner
    result = await trigger_job(job_key, force=True)
    if not result.get("ok"):
        return AIPickTriggerResponse(
            ok=False,
            gated=False,
            message=result.get("error", "Failed to trigger run")
        )

    run_name = "Hunter (Morning)" if "morning" in job_key else "Evaluator / Verifier (Evening)"
    return AIPickTriggerResponse(
        ok=True,
        gated=False,
        message=f"Successfully triggered {run_name} run."
    )

