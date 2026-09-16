"""SQLAlchemy ORM model for persistent JSON API caching."""

from datetime import datetime
from sqlalchemy import DateTime, String, func, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ApiCache(Base):
    """Persistent JSON cache for external data endpoints (Screener, iinvest, Morningstar).
    
    Used to implement a 24-hour fetch-once caching strategy to avoid 
    spamming upstream providers and provide instant UI responses.
    """

    __tablename__ = "api_cache"

    key: Mapped[str] = mapped_column(String(255), primary_key=True, index=True)
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        default=func.now()
    )
    
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        index=True
    )
