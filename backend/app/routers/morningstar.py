"""Morningstar proxy endpoints for fair value data."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Query

from app.services.morningstar_client import morningstar_client

logger = logging.getLogger(__name__)
router = APIRouter(tags=["morningstar"])


@router.get("/morningstar/fairvalue/{symbol}")
async def get_fair_value(symbol: str) -> dict[str, Any]:
    """Get fair value for a stock symbol."""
    symbol = symbol.upper().strip()
    result = await morningstar_client.get_fair_value_by_symbol(symbol)
    return result


@router.get("/morningstar/search")
async def search_stock(q: str = Query(..., min_length=1, max_length=80)) -> list[dict[str, Any]]:
    """Search for a stock to get Morningstar ID."""
    ms_id = await morningstar_client.resolve_symbol_to_id(q)
    if ms_id:
        return [{"symbol": q.upper(), "morningstarId": ms_id}]
    return []
