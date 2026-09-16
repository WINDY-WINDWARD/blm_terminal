"""Router for stock universe related endpoints.

This router only returns data from the database and makes no direct
calls to the NSE client/service.
"""

from typing import List, Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.auth import get_admin_user
from app.models.user import User
from app.models.stockuniverse import StockUniverse as StockUniverseModel
from app.models.ticker import TickerDaily
from app.schemas.stockuniverse import (
    ChangeSymbolRequest,
    ConfirmMatchRequest,
    ErrorCategory,
    MatchResultResponse,
    StockUniverse as StockUniverseSchema,
    StockUniverseErrorSymbol,
    StockUniverseErrorsResponse,
)
from app.services.mc_stock_linker import MCStockLinker
from app.services.nse_client import NSEClient


router = APIRouter()

ERROR_STATUSES = frozenset({"delisted", "illiquid", "suspended", "not_tradable", "unknown", "ticker_error"})
REVIEW_STATUS_REMOVED = "removed"


def _orm_to_schema(obj: StockUniverseModel) -> StockUniverseSchema:
    """Map ORM model to pydantic schema (field-name translation)."""
    return StockUniverseSchema(
        symbol=obj.symbol,
        companyName=obj.company_name,
        segment=obj.segment,
        industry=obj.industry,
        sectorPE=obj.sector_pe,
        symbolPE=obj.symbol_pe,
        industryInfo=obj.industry_info or {},
        series=obj.series,
        lastUpdateTime=obj.last_update_time,
        screenerTradesId=obj.screener_trades_id,
        mcUrl=obj.mc_url,
        reviewStatus=obj.review_status,
        matchConfidence=obj.match_confidence,
        mcMatchSource=obj.mc_match_source,
        mcCompanyName=obj.mc_company_name,
        morningstarId=obj.morningstar_id,
        fairValue=obj.fair_value,
        fairValueUpdatedAt=obj.fair_value_updated_at,
        high_52w=obj.high_52w,
        low_52w=obj.low_52w,
        high_52w_date=obj.high_52w_date,
        low_52w_date=obj.low_52w_date,
        isin=obj.isin,
        iinvestPath=obj.iinvest_path,
        iinvestPathResolvedAt=obj.iinvest_path_resolved_at,
        market_cap_cr=obj.market_cap_cr,
    )


@router.get(
    "/stockuniverse", response_model=List[StockUniverseSchema], tags=["stockuniverse"]
)
async def list_stock_universe(
    limit: int = 200,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
) -> List[StockUniverseSchema]:
    """Return stock universe records with pagination."""
    q = (
        select(StockUniverseModel)
        .order_by(StockUniverseModel.symbol)
        .limit(limit)
        .offset(offset)
    )
    res = await db.execute(q)
    rows = res.scalars().all()
    return [_orm_to_schema(r) for r in rows]


@router.get(
    "/stockuniverse/search/{prefix}",
    response_model=List[StockUniverseSchema],
    tags=["stockuniverse"],
)
async def search_stock_universe(
    prefix: str,
    limit: int = 200,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
) -> List[StockUniverseSchema]:
    """Return stock universe records matching prefix with pagination."""
    q = (
        select(StockUniverseModel)
        .where(
            StockUniverseModel.symbol.ilike(f"{prefix}%")
            | StockUniverseModel.company_name.ilike(f"{prefix}%")
        )
        .order_by(StockUniverseModel.symbol)
        .limit(limit)
        .offset(offset)
    )
    res = await db.execute(q)
    rows = res.scalars().all()
    return [_orm_to_schema(r) for r in rows]


@router.post(
    "/stockuniverse/run-mc-linker",
    response_model=MatchResultResponse,
    tags=["stockuniverse"],
)
async def run_mc_linker(db: AsyncSession = Depends(get_db), admin: User = Depends(get_admin_user)) -> MatchResultResponse:
    """Run the MoneyControl stock linker to match stocks with MC data."""
    linker = MCStockLinker(db)
    result = await linker.run_matching()
    return MatchResultResponse(**result)


@router.get(
    "/stockuniverse/pending-review",
    response_model=List[StockUniverseSchema],
    tags=["stockuniverse"],
)
async def get_pending_review(
    limit: int = 50, db: AsyncSession = Depends(get_db)
) -> List[StockUniverseSchema]:
    """Get stocks that need manual review (ambiguous matches)."""
    linker = MCStockLinker(db)
    records = await linker.get_pending_review(limit)
    return [_orm_to_schema(r) for r in records]


@router.put(
    "/stockuniverse/{symbol}/confirm-match",
    response_model=StockUniverseSchema,
    tags=["stockuniverse"],
)
async def confirm_match(
    symbol: str,
    body: ConfirmMatchRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_admin_user),
) -> StockUniverseSchema:
    """Confirm or reject an ambiguous match."""
    linker = MCStockLinker(db)
    success = await linker.confirm_match(symbol, body.confirmed, body.mc_url)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="symbol not found"
        )
    rec = await db.get(StockUniverseModel, symbol)
    return _orm_to_schema(rec)


# NOTE: {symbol} path-param routes must come AFTER all specific sub-paths
# (pending-review, search/{prefix}, {symbol}/confirm-match) to prevent
# FastAPI from matching "pending-review" as a symbol name.


class NSEMarketRatiosResponse(BaseModel):
    """Per-company market ratios from NSE's GetQuoteApi (live, no auth).

    This is a FALLBACK data source used by the FDM widget when screener.in
    is unavailable (HTTP 503). NSE provides a subset of what screener
    returns — P/E, sector P/E, 52W high/low, plus the company name/ISIN.
    iinvest also has the same ratios but only in the HTML overview page
    (which the iinvest server only populates for authenticated browser
    sessions, not the guest-JWT data APIs).
    """
    symbol: str
    company_name: str | None = None
    isin: str | None = None
    symbol_pe: float | None = None
    sector_pe: float | None = None
    industry: str | None = None
    high_52w: float | None = None
    low_52w: float | None = None
    high_52w_date: datetime | None = None
    low_52w_date: datetime | None = None
    source: str = "NSE"


@router.get(
    "/stockuniverse/{symbol}/ratios",
    response_model=NSEMarketRatiosResponse,
    tags=["stockuniverse"],
)
async def get_market_ratios(
    symbol: str,
) -> NSEMarketRatiosResponse:
    """Live per-company market ratios from NSE (no screener.in session needed).

    Returns 4 of screener's 10 core ratios: P/E, sector P/E, 52W high, 52W low.
    Used by the FDM widget as a fallback when screener.in returns 503.
    """
    from app.services.nse_client_async import nse_client_async, SymbolNotFoundError

    symbol_upper = symbol.upper()
    try:
        meta = await nse_client_async.get_stock_metadata(symbol_upper)
    except SymbolNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"symbol {symbol_upper} not found on NSE",
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"NSE request failed: {exc}",
        )
    return NSEMarketRatiosResponse(
        symbol=symbol_upper,
        company_name=meta.companyName,
        isin=meta.isin,
        symbol_pe=meta.symbolPE,
        sector_pe=meta.sectorPE,
        industry=meta.industry,
        high_52w=meta.high_52w,
        low_52w=meta.low_52w,
        high_52w_date=meta.high_52w_date,
        low_52w_date=meta.low_52w_date,
    )


@router.get(
    "/stockuniverse/{symbol}",
    response_model=StockUniverseSchema,
    tags=["stockuniverse"],
)
async def get_stock_universe(
    symbol: str, db: AsyncSession = Depends(get_db)
) -> StockUniverseSchema:
    """Return a single stock universe record by `symbol` from the database."""
    rec = await db.get(StockUniverseModel, symbol)
    if rec is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="symbol not found"
        )
    return _orm_to_schema(rec)


errors_router = APIRouter(prefix="/stockuniverse/errors", dependencies=[Depends(get_admin_user)])


@errors_router.get(
    "",
    response_model=StockUniverseErrorsResponse,
    tags=["stockuniverse"],
)
async def list_stock_universe_errors(
    db: AsyncSession = Depends(get_db),
) -> StockUniverseErrorsResponse:
    """Return all errored stock universe symbols grouped by review_status."""
    q = select(StockUniverseModel).where(
        StockUniverseModel.review_status.in_(ERROR_STATUSES)
    )
    res = await db.execute(q)
    rows = res.scalars().all()

    categories: dict[str, list[StockUniverseErrorSymbol]] = {
        "delisted": [], "illiquid": [], "suspended": [], "not_tradable": [], "unknown": [], "ticker_error": []
    }
    for row in rows:
        status_val = row.review_status
        if status_val in categories:
            categories[status_val].append(StockUniverseErrorSymbol(
                symbol=row.symbol,
                companyName=row.company_name,
                reviewStatus=status_val,
                series=row.series,
                lastUpdateTime=row.last_update_time,
            ))

    return StockUniverseErrorsResponse(
        delisted=ErrorCategory(count=len(categories["delisted"]), symbols=categories["delisted"]),
        illiquid=ErrorCategory(count=len(categories["illiquid"]), symbols=categories["illiquid"]),
        suspended=ErrorCategory(count=len(categories["suspended"]), symbols=categories["suspended"]),
        not_tradable=ErrorCategory(count=len(categories["not_tradable"]), symbols=categories["not_tradable"]),
        unknown=ErrorCategory(count=len(categories["unknown"]), symbols=categories["unknown"]),
        ticker_error=ErrorCategory(count=len(categories["ticker_error"]), symbols=categories["ticker_error"]),
    )


@errors_router.delete(
    "/{symbol}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["stockuniverse"],
)
async def remove_stock_universe_symbol(
    symbol: str,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Soft-delete a symbol: set review_status='removed' and delete its ticker_warehouse rows."""
    rec = await db.get(StockUniverseModel, symbol)
    if rec is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="symbol not found")

    rec.review_status = REVIEW_STATUS_REMOVED
    db.add(rec)

    await db.execute(
        delete(TickerDaily).where(TickerDaily.symbol == symbol)
    )

    await db.commit()


@errors_router.put(
    "/{symbol}/reset-ticker",
    status_code=status.HTTP_200_OK,
    tags=["stockuniverse"],
)
async def reset_ticker_error(
    symbol: str,
    db: AsyncSession = Depends(get_db),
) -> StockUniverseSchema:
    """Reset ticker_failure_count to 0 and clear ticker_error review_status.

    Use this to re-enable a symbol that was disabled after repeated backfill failures.
    """
    rec = await db.get(StockUniverseModel, symbol)
    if rec is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="symbol not found")

    rec.ticker_failure_count = 0
    if rec.review_status == "ticker_error":
        rec.review_status = None
    db.add(rec)
    await db.commit()
    await db.refresh(rec)
    return _orm_to_schema(rec)


@errors_router.put(
    "/{symbol}/change-symbol",
    response_model=StockUniverseSchema,
    tags=["stockuniverse"],
)
async def change_stock_universe_symbol(
    symbol: str,
    body: ChangeSymbolRequest,
    db: AsyncSession = Depends(get_db),
) -> StockUniverseSchema:
    """Rename a symbol and re-fetch its metadata from NSE.

    1. Validate newSymbol not already in DB.
    2. Re-fetch metadata for newSymbol from NSE.
    3. Update existing row with all fields from fetched data.
    4. Return updated record.
    """
    new_symbol = body.newSymbol.strip().upper()

    rec = await db.get(StockUniverseModel, symbol)
    if rec is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="old symbol not found")

    new_rec = await db.get(StockUniverseModel, new_symbol)
    if new_rec is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"new symbol '{new_symbol}' already exists in stock universe",
        )

    nse = NSEClient()
    try:
        new_meta = nse.get_stock_metadata(new_symbol)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"new symbol '{new_symbol}' is also invalid on NSE: {exc}",
        )

    rec.symbol = new_meta.symbol
    rec.company_name = new_meta.companyName
    rec.segment = new_meta.segment
    rec.industry = new_meta.industry
    rec.sector_pe = new_meta.sectorPE
    rec.symbol_pe = new_meta.symbolPE
    rec.industry_info = new_meta.industryInfo
    rec.series = new_meta.series
    rec.last_update_time = new_meta.lastUpdateTime
    rec.review_status = None
    rec.high_52w = new_meta.high_52w
    rec.low_52w = new_meta.low_52w
    rec.high_52w_date = new_meta.high_52w_date
    rec.low_52w_date = new_meta.low_52w_date

    db.add(rec)
    await db.commit()
    await db.refresh(rec)
    return _orm_to_schema(rec)
