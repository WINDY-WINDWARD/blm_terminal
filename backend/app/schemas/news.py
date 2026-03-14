"""Pydantic schemas for the news endpoints."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class NewsArticleOut(BaseModel):
    """Output schema for a cached news article."""

    model_config = ConfigDict(from_attributes=True)

    url: str
    source: str
    title: str | None
    text: str | None
    authors: list[str] | None
    top_image: str | None
    publish_date: datetime | None
    fetched_at: datetime
    created_at: datetime
    company_symbol: str | None
