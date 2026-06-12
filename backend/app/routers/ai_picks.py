from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional
from datetime import datetime, timezone

from app.database import get_db
from app.models.ai_picks import AIPick, PickStatus
from app.schemas.ai_picks import AIPickResponse, PickStatusUpdate

router = APIRouter(prefix="/ai", tags=["ai-picks"])

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
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(AIPick).where(AIPick.id == pick_id))
    pick = result.scalar_one_or_none()
    
    if not pick:
        raise HTTPException(status_code=404, detail="AI Pick not found")
    
    # Only update timestamp if status actually changes
    if pick.status != update_data.status:
        pick.status = update_data.status
        pick.status_updated_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(pick)
        
    return pick
