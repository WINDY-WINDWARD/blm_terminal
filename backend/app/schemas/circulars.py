"""Pydantic response schema for circular records."""
from datetime import datetime

from pydantic import BaseModel


class CircularOut(BaseModel):
    id: int
    circular_id: str | None
    department: str | None
    subject: str | None
    circular_date: str | None
    url: str | None
    cached_at: datetime

    model_config = {"from_attributes": True}
