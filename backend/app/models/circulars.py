"""SQLAlchemy model for NSE market circulars."""
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class CircularRecord(Base):
    __tablename__ = "circulars"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # NSE's own circular ID (e.g. "NSE/COMP/67890") — used as natural dedup key
    circular_id: Mapped[str | None] = mapped_column(String, nullable=True, unique=True, index=True)

    department: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    subject: Mapped[str | None] = mapped_column(String, nullable=True)
    circular_date: Mapped[str | None] = mapped_column(String, nullable=True, index=True)

    # Direct PDF link on NSE
    url: Mapped[str | None] = mapped_column(String, nullable=True)

    raw_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    cached_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
