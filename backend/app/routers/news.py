"""Router for news endpoints.

GET  /news/global               - Cached global MoneyControl articles filtered by date
POST /news/company              - Fetch & store articles for a specific company symbol
GET  /news/company/{symbol}   - Return stored articles for a given company symbol
GET  /news/sources             - List all configured RSS news sources
GET  /news/all                 - Aggregated multi-source news with filters
POST /news/analyze             - Analyze raw text for NLP
GET  /news/fetch               - Trigger fetch of all RSS sources
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.news import NewsArticle
from app.schemas.news import (
    AnalyzeTextOut,
    AnalyzeTextRequest,
    CompanyNewsFetchRequest,
    FetchAllOut,
    FetchResultOut,
    NewsArticleOut,
    NewsPaginatedOut,
    NewsSourceOut,
    NewsSourcesOut,
)
from app.services.nlp_service import analyze_article_dict
from app.services.news_aggregator import (
    article_to_dict,
    fetch_all_feeds,
    fetch_source_by_id,
    get_stored_articles,
)
from app.services.pagination import paginate
from app.services.news_fetcher import SOURCE_NAME, news_fetcher
from app.services.news_sources import (
    ALL_SOURCES,
    SourceCategory,
    get_all_source_ids,
    get_sources_by_category,
    get_sources_by_tier,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/news", tags=["news"])


# ---------------------------------------------------------------------------
# Global news (MoneyControl - existing)
# ---------------------------------------------------------------------------


@router.get(
    "/global",
    summary="Get paginated global news articles",
    response_model=NewsPaginatedOut,
)
async def get_global_news(
    start_date: datetime = Query(
        default=None,
        description="Start date for filtering (default: 7 days ago)",
    ),
    end_date: datetime = Query(
        default=None,
        description="End date for filtering (default: current date)",
    ),
    limit: int = Query(default=50, ge=1, le=100, description="Number of articles per page"),
    offset: int = Query(default=0, ge=0, description="Number of articles to skip"),
    db: AsyncSession = Depends(get_db),
) -> NewsPaginatedOut:
    """Return paginated cached news articles from MoneyControl filtered by date range.

    If no start_date is provided, defaults to 7 days ago.
    If no end_date is provided, defaults to current datetime.
    Default page size is 50 articles.
    """
    if end_date is None:
        end_date = datetime.now()
    if start_date is None:
        start_date = end_date - timedelta(days=7)

    conditions = [NewsArticle.source == SOURCE_NAME]
    if start_date:
        conditions.append(NewsArticle.publish_date >= start_date)
    if end_date:
        conditions.append(NewsArticle.publish_date <= end_date)

    count_stmt = (
        select(func.count())
        .select_from(NewsArticle)
        .where(and_(*conditions))
    )
    stmt = (
        select(NewsArticle)
        .where(and_(*conditions))
        .order_by(NewsArticle.publish_date.desc().nullslast())
        .limit(limit)
        .offset(offset)
    )

    total, articles, has_more = await paginate(
        db, count_stmt, stmt, offset=offset, limit=limit,
    )

    logger.debug("Returning %d articles (offset %d, limit %d, total %d)", len(articles), offset, limit, total)
    return NewsPaginatedOut(
        articles=[NewsArticleOut.model_validate(a) for a in articles],
        total=total,
        limit=limit,
        offset=offset,
        has_more=has_more,
    )


# ---------------------------------------------------------------------------
# Company-specific news (MoneyControl - existing)
# ---------------------------------------------------------------------------



@router.post(
    "/company",
    summary="Fetch and store news articles for a specific company",
    response_model=NewsPaginatedOut,
)
async def fetch_company_news(
    body: CompanyNewsFetchRequest,
    db: AsyncSession = Depends(get_db),
) -> NewsPaginatedOut:
    """Fetch company-specific news from the MoneyControl stock quote page."""
    symbol_upper = body.symbol.upper()
    limit = 50
    offset = 0

    count = await news_fetcher.fetch_company_news(
        symbol=symbol_upper,
        db=db,
        mc_url=body.mc_url,
    )
    logger.info(
        "fetch_company_news endpoint: stored/tagged %d articles for %s",
        count,
        symbol_upper,
    )

    count_stmt = (
        select(func.count())
        .select_from(NewsArticle)
        .where(NewsArticle.company_symbol == symbol_upper)
    )
    stmt = (
        select(NewsArticle)
        .where(NewsArticle.company_symbol == symbol_upper)
        .order_by(NewsArticle.publish_date.desc().nullslast())
        .limit(limit)
        .offset(offset)
    )
    total, articles, has_more = await paginate(
        db, count_stmt, stmt, offset=offset, limit=limit,
    )

    return NewsPaginatedOut(
        articles=[NewsArticleOut.model_validate(a) for a in articles],
        total=total,
        limit=limit,
        offset=offset,
        has_more=has_more,
    )


@router.get(
    "/company/{symbol}",
    summary="Get paginated stored news articles for a company symbol",
    response_model=NewsPaginatedOut,
)
async def get_company_news(
    symbol: str,
    start_date: datetime = Query(
        default=None,
        description="Start date for filtering (default: 30 days ago)",
    ),
    end_date: datetime = Query(
        default=None,
        description="End date for filtering (default: current date)",
    ),
    limit: int = Query(default=50, ge=1, le=100, description="Number of articles per page"),
    offset: int = Query(default=0, ge=0, description="Number of articles to skip"),
    db: AsyncSession = Depends(get_db),
) -> NewsPaginatedOut:
    """Return paginated cached news articles tagged with *symbol*."""
    symbol_upper = symbol.upper()

    if end_date is None:
        end_date = datetime.now()
    if start_date is None:
        start_date = end_date - timedelta(days=30)

    conditions = [NewsArticle.company_symbol == symbol_upper]
    if start_date:
        conditions.append(NewsArticle.publish_date >= start_date)
    if end_date:
        conditions.append(NewsArticle.publish_date <= end_date)

    count_stmt = (
        select(func.count())
        .select_from(NewsArticle)
        .where(and_(*conditions))
    )
    precomputed_total = (await db.scalar(count_stmt) or 0)
    if precomputed_total == 0:
        raise HTTPException(
            status_code=404,
            detail=f"No articles found for symbol '{symbol_upper}'. "
            "Use POST /news/company to fetch them first.",
        )

    stmt = (
        select(NewsArticle)
        .where(and_(*conditions))
        .order_by(NewsArticle.publish_date.desc().nullslast())
        .limit(limit)
        .offset(offset)
    )
    total, articles, has_more = await paginate(
        db, count_stmt, stmt, offset=offset, limit=limit,
        precomputed_total=precomputed_total,
    )

    logger.debug(
        "get_company_news: returning %d articles (offset %d, limit %d, total %d) for %s",
        len(articles), offset, limit, total, symbol_upper
    )
    return NewsPaginatedOut(
        articles=[NewsArticleOut.model_validate(a) for a in articles],
        total=total,
        limit=limit,
        offset=offset,
        has_more=has_more,
    )


# ---------------------------------------------------------------------------
# Multi-source news (NEW)
# ---------------------------------------------------------------------------


@router.get(
    "/sources",
    summary="List all configured RSS news sources",
    response_model=NewsSourcesOut,
)
async def get_news_sources(
    category: str | None = Query(default=None, description="Filter by category (MARKETS, GEOPOLITICS, etc.)"),
    tier: int | None = Query(default=None, description="Filter by tier (1, 2, 3)"),
) -> NewsSourcesOut:
    """Return all configured RSS news sources with optional filtering."""
    sources = ALL_SOURCES

    if category:
        sources = [s for s in sources if s.category.value == category.upper()]

    if tier:
        sources = [s for s in sources if s.tier.value == tier]

    source_outs = [
        NewsSourceOut(
            id=s.id,
            name=s.name,
            category=s.category.value,
            tier=s.tier.value,
            description=s.description,
        )
        for s in sources
    ]

    return NewsSourcesOut(sources=source_outs, total=len(source_outs))


@router.get(
    "/all",
    summary="Get aggregated multi-source news with filters",
    response_model=NewsPaginatedOut,
)
async def get_all_news(
    sources: str | None = Query(default=None, description="Comma-separated source IDs"),
    categories: str | None = Query(default=None, description="Comma-separated categories"),
    sentiment: str | None = Query(default=None, description="Filter by sentiment (BULLISH, BEARISH, NEUTRAL)"),
    threat_level: str | None = Query(default=None, description="Filter by threat level (CRITICAL, HIGH, MEDIUM, LOW)"),
    language: str | None = Query(default=None, description="Filter by language code"),
    start_date: datetime | None = Query(default=None, description="Start date for filtering"),
    end_date: datetime | None = Query(default=None, description="End date for filtering"),
    limit: int = Query(default=50, ge=1, le=100, description="Number of articles per page"),
    offset: int = Query(default=0, ge=0, description="Number of articles to skip"),
    db: AsyncSession = Depends(get_db),
) -> NewsPaginatedOut:
    """Return paginated aggregated news from all RSS sources with optional filtering.

    This endpoint provides access to news from 35+ sources including Bloomberg,
    WSJ, CNBC, MoneyControl, Economic Times, and more.
    """
    # Parse comma-separated values
    source_list = [s.strip() for s in sources.split(",")] if sources else None
    category_list = [c.strip().upper() for c in categories.split(",")] if categories else None

    # Build filter conditions
    conditions = []
    if source_list:
        conditions.append(NewsArticle.source.in_(source_list))
    if sentiment:
        conditions.append(NewsArticle.sentiment == sentiment.upper())
    if threat_level:
        conditions.append(NewsArticle.threat_level == threat_level.upper())
    if language:
        conditions.append(NewsArticle.language == language.lower())

    # Date filtering
    if end_date is None:
        end_date = datetime.now()
    if start_date is None:
        start_date = end_date - timedelta(days=30)

    conditions.append(NewsArticle.publish_date >= start_date)
    conditions.append(NewsArticle.publish_date <= end_date)

    # Get total count
    count_query = select(func.count()).select_from(NewsArticle)
    if conditions:
        count_query = count_query.where(and_(*conditions))

    # Fetch paginated articles
    query = (
        select(NewsArticle)
        .where(and_(*conditions))
        .order_by(NewsArticle.publish_date.desc().nullslast())
        .limit(limit)
        .offset(offset)
    )
    total, articles, has_more = await paginate(
        db, count_query, query, offset=offset, limit=limit,
    )

    logger.debug(
        "get_all_news: returning %d articles (offset %d, limit %d, total %d)",
        len(articles), offset, limit, total
    )

    return NewsPaginatedOut(
        articles=[NewsArticleOut.model_validate(a) for a in articles],
        total=total,
        limit=limit,
        offset=offset,
        has_more=has_more,
    )


@router.post(
    "/analyze",
    summary="Analyze text for NLP (sentiment, entities, threat)",
    response_model=AnalyzeTextOut,
)
async def analyze_text(body: AnalyzeTextRequest) -> AnalyzeTextOut:
    """Perform NLP analysis on raw headline and summary text.

    Returns sentiment, entities, threat classification, and source credibility.
    """
    result = analyze_article_dict(
        headline=body.headline,
        summary=body.summary,
        source_name="",  # No source context for raw analysis
    )

    return AnalyzeTextOut(**result)
