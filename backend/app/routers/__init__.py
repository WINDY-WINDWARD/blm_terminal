"""FastAPI router registry."""

from app.routers.corporatefilings import router as filings_router
from app.routers.nonpersistence import router as market_router
from app.routers.stockuniverse import router as stockuniverse_router

__all__ = ["filings_router", "market_router", "stockuniverse_router"]
