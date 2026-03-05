"""Pydantic response schema for filing records."""
from datetime import datetime

from pydantic import BaseModel


class FilingOut(BaseModel):
    id: int
    symbol: str
    exchange: str
    filing_type: str | None
    subject: str | None
    description: str | None
    filing_date: str | None
    url: str | None
    attachment_id: str | None
    cached_at: datetime

    model_config = {"from_attributes": True}
