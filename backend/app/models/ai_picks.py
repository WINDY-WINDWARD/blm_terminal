import enum
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Enum, Float, JSON, DateTime
from app.database import Base

class PickStatus(str, enum.Enum):
    NEW = "NEW"
    ACTED_ON = "ACTED_ON"
    CLOSED = "CLOSED"
    ABANDONED = "ABANDONED"

class PickDirection(str, enum.Enum):
    LONG = "LONG"
    SHORT = "SHORT"

class AIPick(Base):
    __tablename__ = "ai_picks"

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String, index=True, nullable=False)
    exchange = Column(String, default="NSE", nullable=False)
    status = Column(Enum(PickStatus), default=PickStatus.NEW, nullable=False)
    direction = Column(Enum(PickDirection), nullable=False)
    
    entry_price = Column(Float, nullable=False)
    take_profit = Column(Float, nullable=False)
    stop_loss = Column(Float, nullable=False)
    
    # Array of dicts: [{"timestamp": "2026-06-12T...", "note": "...", "model": "..."}]
    notes = Column(JSON, default=list, nullable=False)
    
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)
    status_updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
