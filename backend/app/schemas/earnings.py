"""Pydantic response schema for earnings records."""
from datetime import datetime

from pydantic import BaseModel


class EarningsOut(BaseModel):
    id: int
    symbol: str
    exchange: str
    period: str | None
    result_date: str | None
    net_profit: float | None
    revenue: float | None
    eps: float | None
    cached_at: datetime

    model_config = {"from_attributes": True}
