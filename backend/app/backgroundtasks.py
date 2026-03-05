import asyncio

from app.services.nse_client import NSEClient
from app.models import stockuniverse
from app.database import AsyncSessionLocal
from app.config import settings

async def populate_stock_universe():
    """Background task to populate the stock universe table on startup."""

    nse_client = NSEClient()
    stock_list = await nse_client.get_stock_list()
    async with AsyncSessionLocal() as session:
        for symbol in stock_list:
            record = stockuniverse.StockUniverse(symbol=symbol)
            session.add(record)
            await asyncio.sleep(1)
        await session.commit()