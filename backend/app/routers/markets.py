"""Router for market category (industry/sector) endpoints.

GET  /markets/industries               - List all industries with metadata
GET  /markets/sectors                   - List all sectors with metadata
GET  /markets/industries/{slug}/stocks - Get stocks in a specific industry
GET  /markets/sectors/{slug}/stocks     - Get stocks in a specific sector
"""

import logging
from typing import Sequence

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.marketcategory import MarketCategory, MarketCategoryStock
from app.schemas.marketcategory import MarketCategoryOut, MarketCategoryStockOut

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/markets", tags=["markets"])


class RefreshMarketDataRequest(BaseModel):
    """Request body to trigger a manual refresh of market data."""

    pass


@router.get(
    "/industries",
    summary="Get all industries with metadata",
    response_model=list[MarketCategoryOut],
)
async def get_industries(
    db: AsyncSession = Depends(get_db),
) -> Sequence[MarketCategory]:
    """Return all industries with their metadata (market cap, PE, sentiment, etc.)."""
    stmt = (
        select(MarketCategory)
        .where(MarketCategory.category_type == "industry")
        .order_by(MarketCategory.name)
    )
    result = await db.execute(stmt)
    categories = result.scalars().all()
    return categories


@router.get(
    "/sectors",
    summary="Get all sectors with metadata",
    response_model=list[MarketCategoryOut],
)
async def get_sectors(
    db: AsyncSession = Depends(get_db),
) -> Sequence[MarketCategory]:
    """Return all sectors with their metadata (market cap, PE, sentiment, etc.)."""
    stmt = (
        select(MarketCategory)
        .where(MarketCategory.category_type == "sector")
        .order_by(MarketCategory.name)
    )
    result = await db.execute(stmt)
    categories = result.scalars().all()
    return categories


@router.get(
    "/industries/{slug}/stocks",
    summary="Get stocks in a specific industry",
    response_model=list[MarketCategoryStockOut],
)
async def get_industry_stocks(
    slug: str,
    db: AsyncSession = Depends(get_db),
) -> Sequence[MarketCategoryStock]:
    """Return all stocks in a specific industry.

    Returns 404 if the industry doesn't exist.
    """
    # First check if the industry exists
    stmt = select(MarketCategory).where(
        MarketCategory.category_type == "industry", MarketCategory.slug == slug
    )
    result = await db.execute(stmt)
    category = result.scalar_one_or_none()

    if not category:
        raise HTTPException(
            status_code=404,
            detail=f"Industry '{slug}' not found. "
            "Use GET /markets/industries to list all available industries.",
        )

    # Get all stocks and filter in Python (SQLite JSON query limitations)
    stmt = select(MarketCategoryStock)
    result = await db.execute(stmt)
    all_stocks = result.scalars().all()

    # Filter stocks that have this industry in their categories
    stocks = [
        s
        for s in all_stocks
        if s.categories
        and any(
            c.get("type") == "industry" and c.get("slug") == slug for c in s.categories
        )
    ]

    # Sort by market cap descending
    stocks.sort(key=lambda x: x.market_cap or 0, reverse=True)
    return stocks


@router.get(
    "/sectors/{slug}/stocks",
    summary="Get stocks in a specific sector",
    response_model=list[MarketCategoryStockOut],
)
async def get_sector_stocks(
    slug: str,
    db: AsyncSession = Depends(get_db),
) -> Sequence[MarketCategoryStock]:
    """Return all stocks in a specific sector.

    Returns 404 if the sector doesn't exist.
    """
    # First check if the sector exists
    stmt = select(MarketCategory).where(
        MarketCategory.category_type == "sector", MarketCategory.slug == slug
    )
    result = await db.execute(stmt)
    category = result.scalar_one_or_none()

    if not category:
        raise HTTPException(
            status_code=404,
            detail=f"Sector '{slug}' not found. "
            "Use GET /markets/sectors to list all available sectors.",
        )

    # Get all stocks and filter in Python (SQLite JSON query limitations)
    stmt = select(MarketCategoryStock)
    result = await db.execute(stmt)
    all_stocks = result.scalars().all()

    # Filter stocks that have this sector in their categories
    stocks = [
        s
        for s in all_stocks
        if s.categories
        and any(
            c.get("type") == "sector" and c.get("slug") == slug for c in s.categories
        )
    ]

    # Sort by market cap descending
    stocks.sort(key=lambda x: x.market_cap or 0, reverse=True)
    return stocks
