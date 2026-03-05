"""Router for stock universe related endpoints.

This router only returns data from the database and makes no direct
calls to the NSE client/service.
"""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.stockuniverse import StockUniverse as StockUniverseModel
from app.schemas.stockuniverse import StockUniverse as StockUniverseSchema


router = APIRouter()


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
		lastUpdateTime=obj.last_update_time,
	)


@router.get("/stockuniverse", response_model=List[StockUniverseSchema], tags=["stockuniverse"])
async def list_stock_universe(db: AsyncSession = Depends(get_db)) -> List[StockUniverseSchema]:
	"""Return all stock universe records from the database."""
	q = select(StockUniverseModel).order_by(StockUniverseModel.symbol)
	res = await db.execute(q)
	rows = res.scalars().all()
	return [_orm_to_schema(r) for r in rows]


@router.get("/stockuniverse/{symbol}", response_model=StockUniverseSchema, tags=["stockuniverse"])
async def get_stock_universe(symbol: str, db: AsyncSession = Depends(get_db)) -> StockUniverseSchema:
	"""Return a single stock universe record by `symbol` from the database."""
	rec = await db.get(StockUniverseModel, symbol)
	if rec is None:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="symbol not found")
	return _orm_to_schema(rec)

@router.get("/stockuniverse/search/{prefix}", response_model=List[StockUniverseSchema], tags=["stockuniverse"])
async def search_stock_universe(prefix: str, db: AsyncSession = Depends(get_db)) -> List[StockUniverseSchema]:
    """Return stock universe records that match the prefix in symbol or company name."""
    q = select(StockUniverseModel).where(
        StockUniverseModel.symbol.ilike(f"{prefix}%") |
        StockUniverseModel.company_name.ilike(f"{prefix}%")
    ).order_by(StockUniverseModel.symbol)
    res = await db.execute(q)
    rows = res.scalars().all()
    return [_orm_to_schema(r) for r in rows]

# add corporate filings endpoints here in the future, e.g. /stockuniverse/{symbol}/filings



