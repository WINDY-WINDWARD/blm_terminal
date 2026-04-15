"""Pydantic v2 schemas for the notifications API."""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    watchlist_id: int
    symbol: str
    exchange: str
    trigger_type: str
    message: str
    triggered_at: datetime
    triggered_date: date
    is_read: bool


class GlobalNotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    symbol: str
    exchange: str
    trigger_type: str
    message: str
    triggered_at: datetime
    triggered_date: date
    is_read: bool
