"""Pydantic schemas for the news endpoints."""

import json
from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator


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

    # NLP fields (optional for backward compatibility)
    sentiment: str | None = None
    sentiment_score: float | None = None
    confidence: float | None = None
    language: str | None = None
    entities: dict | None = None
    threat_level: str | None = None
    threat_category: str | None = None
    source_credibility: str | None = None

    # iinvest fields (optional, populated for iinvest-sourced articles)
    iinvest_story_id: str | None = None
    iinvest_published_at: datetime | None = None

    @field_validator("entities", mode="before")
    @classmethod
    def _coerce_entities(cls, v: object) -> dict | None:
        """Defensively decode entities field.

        Handles three cases:
        - None / dict  → pass through unchanged (clean rows)
        - str          → legacy double-encoded rows written before the
                         json.dumps() bug was fixed.  SQLAlchemy's JSON
                         column already does one json.loads(), turning
                         the stored '\"<escaped>\"' into a Python str.
                         We need one (or two) more json.loads() to reach
                         the actual dict.
        """
        if v is None or isinstance(v, dict):
            return v
        if isinstance(v, str):
            try:
                result = json.loads(v)
                # Handle double-encoding: str → str → dict
                if isinstance(result, str):
                    result = json.loads(result)
                return result if isinstance(result, dict) else None
            except (json.JSONDecodeError, TypeError, ValueError):
                return None
        return None


class NewsPaginatedOut(BaseModel):
    """Paginated response for news articles."""

    articles: list[NewsArticleOut]
    total: int
    limit: int
    offset: int
    has_more: bool
    source_used: str | None = None  # "iinvest" | "moneycontrol" | "merged" — populated by news router


class NewsSourceOut(BaseModel):
    """Output schema for a news source."""

    id: str
    name: str
    category: str
    tier: int
    description: str


class NewsSourcesOut(BaseModel):
    """Response for /news/sources endpoint."""

    sources: list[NewsSourceOut]
    total: int


class AnalyzeTextRequest(BaseModel):
    """Request body for POST /news/analyze."""

    headline: str
    summary: str = ""


class AnalyzeTextOut(BaseModel):
    """Output schema for text analysis."""

    sentiment: str
    sentiment_score: float
    confidence: float
    language: str
    entities: dict
    threat_level: str
    threat_category: str
    source_credibility: str


class FetchResultOut(BaseModel):
    """Output schema for a single feed fetch result."""

    source_id: str
    source_name: str
    articles_count: int
    error: str | None = None


class FetchAllOut(BaseModel):
    """Response for /news/fetch endpoint."""

    articles_fetched: int
    sources_updated: int
    errors: list[FetchResultOut]


class CompanyNewsFetchRequest(BaseModel):
    """Request body for POST /news/company."""

    symbol: str
    mc_url: str | None = None
