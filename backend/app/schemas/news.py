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

    # NLP fields (optional for backward compatibility)
    sentiment: str | None = None
    sentiment_score: float | None = None
    confidence: float | None = None
    language: str | None = None
    entities: dict | None = None
    threat_level: str | None = None
    threat_category: str | None = None
    source_credibility: str | None = None


class NewsPaginatedOut(BaseModel):
    """Paginated response for news articles."""

    articles: list[NewsArticleOut]
    total: int
    limit: int
    offset: int
    has_more: bool


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
