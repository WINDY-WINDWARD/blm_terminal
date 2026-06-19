"""iinvest.cogencis.com data source router.

Exposes 18 read-only data endpoints + a /health + a /path resolver +
an /all aggregator under /api/iinvest/*.

All endpoints share the same error model:
  - 422 on invalid symbol format
  - 404 when the symbol's ISIN/path can't be resolved
  - 503 when the iinvest client is unhealthy (no JWT, etc.)
  - 502 on upstream HTTP failure
  - 500 on unexpected errors (logged)
"""

from __future__ import annotations

import logging
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.iinvest_client import get_iinvest_client

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/iinvest", tags=["iinvest"])

# Valid NSE symbols: alpha + digits + . _ -  (no spaces, no &, max 30 chars)
_SYMBOL_RE = re.compile(r"^[A-Z0-9._-]{1,30}$")


def _validate_symbol(symbol: str) -> str:
    symbol = symbol.upper().strip()
    if not _SYMBOL_RE.fullmatch(symbol):
        raise HTTPException(status_code=422, detail="Invalid symbol format")
    return symbol


# ── Health ────────────────────────────────────────────────────────────────────


@router.get(
    "/health",
    summary="iinvest client health",
)
async def iinvest_health() -> dict[str, Any]:
    """Returns {configured, healthy, expires_at, last_error}."""
    client = get_iinvest_client()
    return client.health()


# ── Path resolution ──────────────────────────────────────────────────────────


@router.get(
    "/path/{symbol}",
    summary="Resolve the iinvest path slug for a symbol",
)
async def iinvest_path(
    symbol: str = Path(..., description="NSE ticker symbol"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Returns {symbol, isin, path}. 404 if unresolvable."""
    symbol = _validate_symbol(symbol)
    client = get_iinvest_client()
    isin, path = await client.resolve_path(symbol, db=db)
    if not isin or not path:
        raise HTTPException(
            status_code=404,
            detail=f"iinvest path not found for symbol {symbol}",
        )
    return {"symbol": symbol, "isin": isin, "path": path}


# ── Data endpoints (path-based: take a symbol, resolve to path, call fetcher) ─


async def _resolve_or_404(symbol: str, db: AsyncSession) -> tuple[str, str]:
    """Resolve symbol to (isin, path). 404 if unresolvable, 503 if client unhealthy."""
    client = get_iinvest_client()
    try:
        isin, path = await client.resolve_path(symbol, db=db)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=f"iinvest client unavailable: {exc}")
    if not isin or not path:
        raise HTTPException(
            status_code=404,
            detail=f"iinvest path not found for symbol {symbol}",
        )
    return isin, path


@router.get("/announcements/{symbol}")
async def get_announcements(
    symbol: str,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    symbol = _validate_symbol(symbol)
    _, path = await _resolve_or_404(symbol, db)
    return await get_iinvest_client().get_announcements(path, page=page, size=size)


@router.get("/auditors/{symbol}")
async def get_auditors(
    symbol: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    symbol = _validate_symbol(symbol)
    _, path = await _resolve_or_404(symbol, db)
    return await get_iinvest_client().get_auditors(path)


@router.get("/block-deals/{symbol}")
async def get_block_deals(
    symbol: str,
    type: int = Query(1, description="1 = historical, 2 = today (semantics per iinvest)"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    symbol = _validate_symbol(symbol)
    _, path = await _resolve_or_404(symbol, db)
    return await get_iinvest_client().get_block_deals(path, deal_type=type, page=page, size=size)


@router.get("/board-meetings/{symbol}")
async def get_board_meetings(
    symbol: str,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    symbol = _validate_symbol(symbol)
    _, path = await _resolve_or_404(symbol, db)
    return await get_iinvest_client().get_board_meetings(path, page=page, size=size)


@router.get("/capital-history/{symbol}")
async def get_capital_history(
    symbol: str,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    symbol = _validate_symbol(symbol)
    _, path = await _resolve_or_404(symbol, db)
    return await get_iinvest_client().get_capital_history(path, page=page, size=size)


@router.get("/corporate-actions/{symbol}")
async def get_corporate_actions(
    symbol: str,
    action_type: str = Query("Dividend", description="Dividend | Split | Bonus | Others"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    symbol = _validate_symbol(symbol)
    _, path = await _resolve_or_404(symbol, db)
    return await get_iinvest_client().get_corporate_actions(
        path, action_type=action_type, page=page, size=size,
    )


@router.get("/financial-peer-filters")
async def get_financial_peer_filters() -> dict[str, Any]:
    """Static enum — no symbol needed."""
    return await get_iinvest_client().get_financial_peer_filters()


@router.get("/financial-peers/{symbol}")
async def get_financial_peers(
    symbol: str,
    filter_basis: int = Query(9, description="9=Revenue, 10=Market Cap, 11=PAT"),
    compare: int = Query(2, description="2=Financial Overview, 4=Fundamentals, 14=Non-Fin, 15=Bank, 16=Insurance, 20=Shareholding"),
    year: int | None = Query(None),
    statement_type: str = Query("c", description="s=standalone, c=consolidated"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    symbol = _validate_symbol(symbol)
    isin, _ = await _resolve_or_404(symbol, db)
    return await get_iinvest_client().get_financial_peers(
        isin, filter_basis=filter_basis, compare=compare, year=year,
        statement_type=statement_type, page=page, size=size,
    )


@router.get("/index-of-charges/{symbol}")
async def get_index_of_charges(
    symbol: str,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    symbol = _validate_symbol(symbol)
    isin, _ = await _resolve_or_404(symbol, db)
    return await get_iinvest_client().get_index_of_charges(isin, page=page, size=size)


@router.get("/insider-trading/{symbol}")
async def get_insider_trading(
    symbol: str,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    symbol = _validate_symbol(symbol)
    _, path = await _resolve_or_404(symbol, db)
    return await get_iinvest_client().get_insider_trading(path, page=page, size=size)


@router.get("/key-shareholders/{symbol}")
async def get_key_shareholders(
    symbol: str,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    symbol = _validate_symbol(symbol)
    _, path = await _resolve_or_404(symbol, db)
    return await get_iinvest_client().get_key_shareholders(path, page=page, size=size)


@router.get("/legal-cases/{symbol}")
async def get_legal_cases(
    symbol: str,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    symbol = _validate_symbol(symbol)
    isin, _ = await _resolve_or_404(symbol, db)
    return await get_iinvest_client().get_legal_cases(isin, page=page, size=size)


@router.get("/marketdata-timeseries/{symbol}")
async def get_marketdata_timeseries(
    symbol: str,
    timescale: int = Query(1),
    from_: str = Query("1DAY", alias="from"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    symbol = _validate_symbol(symbol)
    _, path = await _resolve_or_404(symbol, db)
    return await get_iinvest_client().get_marketdata_timeseries(path, timescale=timescale, from_=from_)


@router.get("/pledged-shares/{symbol}")
async def get_pledged_shares(
    symbol: str,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    symbol = _validate_symbol(symbol)
    _, path = await _resolve_or_404(symbol, db)
    return await get_iinvest_client().get_pledged_shares(path, page=page, size=size)


@router.get("/sast/{symbol}")
async def get_sast(
    symbol: str,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    symbol = _validate_symbol(symbol)
    _, path = await _resolve_or_404(symbol, db)
    return await get_iinvest_client().get_sast(path, page=page, size=size)


@router.get("/tribunals/{symbol}")
async def get_tribunals(
    symbol: str,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    symbol = _validate_symbol(symbol)
    isin, _ = await _resolve_or_404(symbol, db)
    return await get_iinvest_client().get_tribunals(isin, page=page, size=size)


@router.get("/news/{symbol}")
async def get_news(
    symbol: str,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    symbol = _validate_symbol(symbol)
    isin, _ = await _resolve_or_404(symbol, db)
    return await get_iinvest_client().get_news([isin], page=page, size=size)


# ── Aggregator ────────────────────────────────────────────────────────────────


@router.get("/all/{symbol}")
async def get_all(
    symbol: str,
    news_limit: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    symbol = _validate_symbol(symbol)
    isin, path = await _resolve_or_404(symbol, db)
    return await get_iinvest_client().get_all(path, isin, news_limit=news_limit)


# ── Overview (HTML scrape) ───────────────────────────────────────────────────


@router.get("/overview/{symbol}")
async def get_overview(
    symbol: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Fetch the iinvest overview HTML page and extract identity fields.

    The overview page is reachable without a JWT (it's public HTML) so this
    works as a fallback when the data APIs are blocked.
    """
    from app.services.iinvest_client import IinvestClient, IINVEST_SITE_URL
    from app.services.iinvest_html_parser import parse_overview_html
    import httpx

    symbol = _validate_symbol(symbol)
    client = get_iinvest_client()
    # Use the cached path if we have one, otherwise look it up
    _, path = await client.resolve_path(symbol, db=db)
    if not path:
        raise HTTPException(
            status_code=404,
            detail=f"iinvest path not found for symbol {symbol}",
        )

    # Construct the overview URL
    isin = path.split("/")[0].upper()
    # The first path segment after ISIN is /symbol/ns/{SYM}/{NAME}
    rest = path[len(isin):].lstrip("/")  # "symbol/ns/RELIANCE/..."
    url = f"{IINVEST_SITE_URL}/{isin}/{rest}?tab=overview"

    # Use a fresh client (no JWT needed for HTML)
    try:
        async with httpx.AsyncClient(
            headers=dict(IinvestClient.__dict__.get("DEFAULT_HEADERS", {})),
            timeout=httpx.Timeout(30.0, connect=10.0),
        ) as http:
            resp = await http.get(url)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"iinvest overview fetch failed: {exc}") from exc

    if resp.status_code != 200:
        raise HTTPException(
            status_code=503,
            detail=f"iinvest overview returned HTTP {resp.status_code}",
        )

    return parse_overview_html(url, resp.text)
