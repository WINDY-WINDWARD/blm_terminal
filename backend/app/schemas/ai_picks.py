from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field
from app.models.ai_picks import PickStatus, PickDirection

class PickNote(BaseModel):
    timestamp: datetime
    note: str
    model: str
    verdict: Optional[str] = None
    technical: Optional[str] = None
    fundamental: Optional[str] = None
    catalyst: Optional[str] = None
    risk: Optional[str] = None
    action: Optional[str] = None

class AIPickTraceResponse(BaseModel):
    id: int
    pick_id: Optional[int]
    symbol: str
    agent_role: str
    prompt: str
    response: str
    duration_ms: int
    status: str
    error_message: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True

class AIPickBase(BaseModel):
    symbol: str = Field(..., description="NSE ticker symbol")
    exchange: str = Field("NSE", description="Exchange name")
    direction: PickDirection
    entry_price: float
    take_profit: float
    stop_loss: float

class AIPickCreate(AIPickBase):
    thesis: str = Field(..., description="Initial thesis from AI")

class AIPickResponse(AIPickBase):
    id: int
    status: PickStatus
    notes: List[PickNote]
    exit_price: Optional[float] = None
    created_at: datetime
    updated_at: datetime
    status_updated_at: datetime

    class Config:
        from_attributes = True

class PickStatusUpdate(BaseModel):
    status: PickStatus
    exit_price: Optional[float] = None

class AIPickTriggerResponse(BaseModel):
    ok: bool
    gated: bool = False
    message: str
