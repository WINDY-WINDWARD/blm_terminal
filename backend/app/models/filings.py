"""SQLAlchemy model for NSE corporate announcements / filings."""
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class FilingRecord(Base):
    __tablename__ = "filings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String, nullable=False, index=True)
    exchange: Mapped[str] = mapped_column(String, nullable=False, default="NSE")

    filing_type: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    subject: Mapped[str | None] = mapped_column(String, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    filing_date: Mapped[str | None] = mapped_column(String, nullable=True, index=True)

    # Direct link to the filing PDF/document on NSE
    url: Mapped[str | None] = mapped_column(String, nullable=True)

    # NSE's own attachment ID — used as a natural dedup key
    attachment_id: Mapped[str | None] = mapped_column(String, nullable=True, unique=True)

    raw_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    cached_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
