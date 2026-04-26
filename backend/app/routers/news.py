"""Router for news endpoints.

GET  /news/global               - Cached global MoneyControl articles filtered by date
POST /news/company              - Fetch & store articles for a specific company symbol
GET  /news/company/{symbol}     - Return stored articles for a given company symbol
"""

import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.news import NewsArticle
from app.schemas.news import NewsArticleOut, NewsPaginatedOut
from app.services.news_fetcher import SOURCE_NAME, news_fetcher

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/news", tags=["news"])


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

    # Build filter conditions
    conditions = [NewsArticle.source == SOURCE_NAME]
    if start_date:
        conditions.append(NewsArticle.publish_date >= start_date)
    if end_date:
        conditions.append(NewsArticle.publish_date <= end_date)

    # Get total count
    count_stmt = (
        select(func.count())
        .select_from(NewsArticle)
        .where(and_(*conditions))
    )
    total = await db.scalar(count_stmt) or 0

    # Fetch paginated articles
    stmt = (
        select(NewsArticle)
        .where(and_(*conditions))
        .order_by(NewsArticle.publish_date.desc().nullslast())
        .limit(limit)
        .offset(offset)
    )

    result = await db.execute(stmt)
    articles: list[NewsArticle] = list(result.scalars().all())

    logger.debug("Returning %d articles (offset %d, limit %d, total %d)", len(articles), offset, limit, total)
    return NewsPaginatedOut(
        articles=[NewsArticleOut.model_validate(a) for a in articles],
        total=total,
        limit=limit,
        offset=offset,
        has_more=(offset + limit) < total,
    )


# ---------------------------------------------------------------------------
# Company-specific news
# ---------------------------------------------------------------------------


class CompanyNewsFetchRequest(BaseModel):
    """Request body for POST /news/company."""

    symbol: str
    """NSE ticker symbol, e.g. ``RELIANCE``."""

    mc_url: str | None = None
    """Optional full MoneyControl stock quote page URL.
    If not provided, it will be auto-resolved from the symbol.
    """


@router.post(
    "/company",
    summary="Fetch and store news articles for a specific company",
    response_model=NewsPaginatedOut,
)
async def fetch_company_news(
    body: CompanyNewsFetchRequest,
    db: AsyncSession = Depends(get_db),
) -> NewsPaginatedOut:
    """Fetch company-specific news from the MoneyControl stock quote page.

    Parses the ``#news`` section of *mc_url*, fetches each new article, stores
    it tagged with *symbol*, and returns the first page of articles now associated
    with that symbol.  Articles already in the DB from the global crawl are
    tagged (not duplicated).
    """
    symbol_upper = body.symbol.upper()
    limit = 50  # Default page size for initial fetch
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

    # Get total count
    count_stmt = (
        select(func.count())
        .select_from(NewsArticle)
        .where(NewsArticle.company_symbol == symbol_upper)
    )
    total = await db.scalar(count_stmt) or 0

    # Fetch first page of articles
    stmt = (
        select(NewsArticle)
        .where(NewsArticle.company_symbol == symbol_upper)
        .order_by(NewsArticle.publish_date.desc().nullslast())
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(stmt)
    articles: list[NewsArticle] = list(result.scalars().all())

    return NewsPaginatedOut(
        articles=[NewsArticleOut.model_validate(a) for a in articles],
        total=total,
        limit=limit,
        offset=offset,
        has_more=(offset + limit) < total,
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
    """Return paginated cached news articles tagged with *symbol*.

    Applies an optional date range filter (defaults to the last 30 days).
    Returns 404 if no articles are stored for the symbol yet.
    Default page size is 50 articles.
    """
    symbol_upper = symbol.upper()

    if end_date is None:
        end_date = datetime.now()
    if start_date is None:
        start_date = end_date - timedelta(days=30)

    # Build filter conditions
    conditions = [NewsArticle.company_symbol == symbol_upper]
    if start_date:
        conditions.append(NewsArticle.publish_date >= start_date)
    if end_date:
        conditions.append(NewsArticle.publish_date <= end_date)

    # Check if any articles exist
    count_stmt = (
        select(func.count())
        .select_from(NewsArticle)
        .where(and_(*conditions))
    )
    total = await db.scalar(count_stmt) or 0

    if total == 0:
        raise HTTPException(
            status_code=404,
            detail=f"No articles found for symbol '{symbol_upper}'. "
            "Use POST /news/company to fetch them first.",
        )

    # Fetch paginated articles
    stmt = (
        select(NewsArticle)
        .where(and_(*conditions))
        .order_by(NewsArticle.publish_date.desc().nullslast())
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(stmt)
    articles: list[NewsArticle] = list(result.scalars().all())

    logger.debug(
        "get_company_news: returning %d articles (offset %d, limit %d, total %d) for %s",
        len(articles), offset, limit, total, symbol_upper
    )
    return NewsPaginatedOut(
        articles=[NewsArticleOut.model_validate(a) for a in articles],
        total=total,
        limit=limit,
        offset=offset,
        has_more=(offset + limit) < total,
    )
