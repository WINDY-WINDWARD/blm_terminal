"""SQLALCHEMY ORM MODEL for NSE India stock corporate filings"""

from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class CorporateFiling(Base):
    """ORM model for NSE corporate filing CSV cache per symbol."""

    __tablename__ = "corporate_filings"

    symbol: Mapped[str] = mapped_column(String(32), primary_key=True, index=True)
    csv_data: Mapped[str] = mapped_column(Text, nullable=False)
    last_fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

