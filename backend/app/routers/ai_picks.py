from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from typing import List, Optional
from datetime import datetime, timezone

from app.database import get_db
from app.auth import get_admin_user
from app.models.user import User
from app.models.ai_picks import AIPick, PickStatus, AIPickTrace
from app.schemas.ai_picks import AIPickResponse, PickStatusUpdate, AIPickTraceResponse

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
