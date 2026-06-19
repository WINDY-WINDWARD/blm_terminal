from fastapi import APIRouter
from app.services.tradingview_client import fetch_tradingview_fundamentals

router = APIRouter(prefix="/tradingview", tags=["TradingView"])

@router.get("/fundamentals/{symbol}")
async def get_tradingview_fundamentals(symbol: str):
    data = await fetch_tradingview_fundamentals(symbol)
    return {"status": True, "data": data}
