"""Router for news endpoints.

GET  /news/global               - Cached global MoneyControl articles filtered by date
POST /news/company              - Fetch & store articles for a specific company symbol
GET  /news/company/{symbol}     - Return stored articles for a given company symbol
"""

import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.news import NewsArticle
from app.schemas.news import NewsArticleOut
from app.services.news_fetcher import SOURCE_NAME, news_fetcher

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/news", tags=["news"])


@router.get(
    "/global",
    summary="Get global news articles",
    response_model=list[NewsArticleOut],
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
    db: AsyncSession = Depends(get_db),
) -> list[NewsArticleOut]:
    """Return cached news articles from MoneyControl filtered by date range.

    If no start_date is provided, defaults to 7 days ago.
    If no end_date is provided, defaults to current datetime.
    """
    if end_date is None:
        end_date = datetime.now()
    if start_date is None:
        start_date = end_date - timedelta(days=7)

    stmt = (
        select(NewsArticle)
        .where(
            and_(
                NewsArticle.source == SOURCE_NAME,
            )
        )
        .order_by(NewsArticle.publish_date.desc().nullslast())
    )

    result = await db.execute(stmt)
    articles: list[NewsArticle] = list(result.scalars().all())

    if start_date or end_date:
        filtered: list[NewsArticle] = []
        for a in articles:
            if a.publish_date is None:
                filtered.append(a)
            elif start_date <= a.publish_date <= end_date:
                filtered.append(a)
        articles = filtered

    logger.debug("Returning %d articles", len(articles))
    return [NewsArticleOut.model_validate(a) for a in articles]


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
    response_model=list[NewsArticleOut],
)
async def fetch_company_news(
    body: CompanyNewsFetchRequest,
    db: AsyncSession = Depends(get_db),
) -> list[NewsArticleOut]:
    """Fetch company-specific news from the MoneyControl stock quote page.

    Parses the ``#news`` section of *mc_url*, fetches each new article, stores
    it tagged with *symbol*, and returns the full list of articles now associated
    with that symbol.  Articles already in the DB from the global crawl are
    tagged (not duplicated).
    """
    symbol_upper = body.symbol.upper()

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

    # Return the full set of articles now tagged for this symbol
    stmt = (
        select(NewsArticle)
        .where(NewsArticle.company_symbol == symbol_upper)
        .order_by(NewsArticle.publish_date.desc().nullslast())
    )
    result = await db.execute(stmt)
    articles: list[NewsArticle] = list(result.scalars().all())
    return [NewsArticleOut.model_validate(a) for a in articles]


@router.get(
    "/company/{symbol}",
    summary="Get stored news articles for a company symbol",
    response_model=list[NewsArticleOut],
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
    db: AsyncSession = Depends(get_db),
) -> list[NewsArticleOut]:
    """Return cached news articles tagged with *symbol*.

    Applies an optional date range filter (defaults to the last 30 days).
    Returns 404 if no articles are stored for the symbol yet.
    """
    symbol_upper = symbol.upper()

    if end_date is None:
        end_date = datetime.now()
    if start_date is None:
        start_date = end_date - timedelta(days=30)

    stmt = (
        select(NewsArticle)
        .where(NewsArticle.company_symbol == symbol_upper)
        .order_by(NewsArticle.publish_date.desc().nullslast())
    )
    result = await db.execute(stmt)
    articles: list[NewsArticle] = list(result.scalars().all())

    if not articles:
        raise HTTPException(
            status_code=404,
            detail=f"No articles found for symbol '{symbol_upper}'. "
            "Use POST /news/company to fetch them first.",
        )

    filtered: list[NewsArticle] = []
    for a in articles:
        if a.publish_date is None:
            filtered.append(a)
        elif start_date <= a.publish_date <= end_date:
            filtered.append(a)
    articles = filtered

    logger.debug(
        "get_company_news: returning %d articles for %s", len(articles), symbol_upper
    )
    return [NewsArticleOut.model_validate(a) for a in articles]
