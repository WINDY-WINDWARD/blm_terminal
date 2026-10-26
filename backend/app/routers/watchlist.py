"""FastAPI router for watchlist CRUD endpoints."""

from typing import List, Sequence

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.models.watchlist import Watchlist as WatchlistModel
from app.models.watchlist import WatchlistItem as WatchlistItemModel
from app.schemas.watchlist import (
    WatchlistBulkReplace,
    WatchlistCreate,
    WatchlistItemCreate,
    WatchlistItemOut,
    WatchlistOut,
    WatchlistWithCountOut,
    WatchlistImportItem,
    WatchlistImportSection,
    WatchlistImportRequest,
    WatchlistImportResponse,
    WatchlistImportSkippedItem,
    WatchlistImportUrlRequest,
    WatchlistImportUrlResponse,
)
from app.models.stockuniverse import StockUniverse
import urllib.parse
import json
import re
import httpx
from bs4 import BeautifulSoup
from app.services.write_queue import enqueue_write_async, PRIO_UI_ACTION
from app.database import _SyncSessionLocal

router = APIRouter()


async def get_default_watchlist_id(db: AsyncSession, current_user: User) -> int:
    q = select(WatchlistModel).where(WatchlistModel.user_id == current_user.id, WatchlistModel.name == "Default")
    wl = (await db.execute(q)).scalar_one_or_none()
    if wl:
        return wl.id
    def _create_default_sync() -> int:
        with _SyncSessionLocal() as session:
            existing = session.execute(
                select(WatchlistModel).where(
                    WatchlistModel.user_id == current_user.id,
                    WatchlistModel.name == "Default"
                )
            ).scalar_one_or_none()
            if existing:
                return existing.id
            new_wl = WatchlistModel(name="Default", user_id=current_user.id)
            session.add(new_wl)
            session.commit()
            session.refresh(new_wl)
            return new_wl.id

    return await enqueue_write_async(PRIO_UI_ACTION, _create_default_sync)


@router.get("/watchlists", response_model=List[WatchlistWithCountOut], tags=["watchlist"])
async def list_watchlists(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> List[WatchlistWithCountOut]:
    """Return all watchlists with item counts ordered by creation time."""
    q = (
        select(
            WatchlistModel.id,
            WatchlistModel.name,
            WatchlistModel.created_at,
            func.count(WatchlistItemModel.id).label("item_count"),
        )
        .outerjoin(WatchlistItemModel, WatchlistModel.id == WatchlistItemModel.watchlist_id)
        .where(WatchlistModel.user_id == current_user.id)
        .group_by(WatchlistModel.id)
        .order_by(WatchlistModel.id)
    )
    res = await db.execute(q)
    rows = res.all()
    return [
        WatchlistWithCountOut(
            id=row.id,
            name=row.name,
            created_at=row.created_at,
            item_count=row.item_count or 0,
        )
        for row in rows
    ]


@router.post("/watchlists", response_model=WatchlistOut, status_code=status.HTTP_201_CREATED, tags=["watchlist"])
async def create_watchlist(
    body: WatchlistCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WatchlistOut:
    """Create a new watchlist with the given name."""
    def _create_wl_sync() -> dict:
        with _SyncSessionLocal() as session:
            wl = WatchlistModel(name=body.name, user_id=current_user.id)
            session.add(wl)
            session.commit()
            session.refresh(wl)
            return {
                "id": wl.id,
                "name": wl.name,
                "user_id": wl.user_id,
                "created_at": wl.created_at,
            }

    wl_dict = await enqueue_write_async(PRIO_UI_ACTION, _create_wl_sync)
    return WatchlistOut.model_validate(wl_dict)


@router.delete("/watchlists/{watchlist_id}", tags=["watchlist"])
async def delete_watchlist(
    watchlist_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Delete a watchlist and all its items (cascade). Cannot delete Default."""
    watchlist = await db.get(WatchlistModel, watchlist_id)
    if watchlist is None or watchlist.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Watchlist {watchlist_id} not found",
        )
    if watchlist.name == "Default":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete the Default watchlist",
        )
    def _del_wl_sync() -> None:
        with _SyncSessionLocal() as session:
            wl = session.get(WatchlistModel, watchlist_id)
            if wl:
                session.delete(wl)
                session.commit()

    await enqueue_write_async(PRIO_UI_ACTION, _del_wl_sync)
    return {"ok": True}


@router.get("/watchlists/{watchlist_id}/items", response_model=List[WatchlistItemOut], tags=["watchlist"])
async def list_watchlist_items(
    watchlist_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> List[WatchlistItemOut]:
    """Return all items in a specific watchlist."""
    watchlist = await db.get(WatchlistModel, watchlist_id)
    if watchlist is None or watchlist.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Watchlist {watchlist_id} not found",
        )
    q = (
        select(WatchlistItemModel)
        .where(WatchlistItemModel.watchlist_id == watchlist_id)
        .order_by(WatchlistItemModel.created_at)
    )
    res = await db.execute(q)
    return [WatchlistItemOut.model_validate(item) for item in res.scalars().all()]  # type: ignore[return-value]


@router.post(
    "/watchlists/{watchlist_id}/items",
    response_model=WatchlistItemOut,
    status_code=status.HTTP_201_CREATED,
    tags=["watchlist"],
)
async def add_watchlist_item(
    watchlist_id: int,
    body: WatchlistItemCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WatchlistItemOut:
    """Add a symbol/exchange pair to a specific watchlist (idempotent upsert).

    If the pair already exists in that watchlist, return the existing row.
    """
    watchlist = await db.get(WatchlistModel, watchlist_id)
    if watchlist is None or watchlist.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Watchlist {watchlist_id} not found",
        )

    existing = await db.execute(
        select(WatchlistItemModel).where(
            WatchlistItemModel.watchlist_id == watchlist_id,
            WatchlistItemModel.symbol == body.symbol,
            WatchlistItemModel.exchange == body.exchange,
        )
    )
    row = existing.scalar_one_or_none()
    if row is not None:
        return row  # type: ignore[return-value]

    def _add_item_sync() -> dict:
        with _SyncSessionLocal() as session:
            new_item = WatchlistItemModel(
                watchlist_id=watchlist_id,
                symbol=body.symbol,
                exchange=body.exchange,
            )
            session.add(new_item)
            session.commit()
            session.refresh(new_item)
            return {
                "id": new_item.id,
                "watchlist_id": new_item.watchlist_id,
                "symbol": new_item.symbol,
                "exchange": new_item.exchange,
                "created_at": new_item.created_at,
            }

    item_dict = await enqueue_write_async(PRIO_UI_ACTION, _add_item_sync)

    # Warm deals cache asynchronously for the newly added symbol
    try:
        from app.services.data_sync.deals import warm_symbol_deals
        warm_symbol_deals(body.symbol)
    except Exception:
        pass

    return item_dict  # type: ignore[return-value]


@router.delete("/watchlists/{watchlist_id}/items/{item_id}", tags=["watchlist"])
async def remove_watchlist_item(
    watchlist_id: int,
    item_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Remove a watchlist item by its numeric id."""
    item = await db.get(WatchlistItemModel, item_id)
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Watchlist item {item_id} not found",
        )
    watchlist = await db.get(WatchlistModel, item.watchlist_id)
    if watchlist is None or watchlist.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Watchlist item {item_id} not found",
        )
    if item.watchlist_id != watchlist_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Item {item_id} does not belong to watchlist {watchlist_id}",
        )
    def _delete_item_sync() -> None:
        with _SyncSessionLocal() as session:
            db_item = session.get(WatchlistItemModel, item_id)
            if db_item:
                session.delete(db_item)
                session.commit()

    await enqueue_write_async(PRIO_UI_ACTION, _delete_item_sync)
    return {"ok": True}


@router.post(
    "/watchlists/{watchlist_id}/items/bulk-replace",
    tags=["watchlist"],
)
async def bulk_replace_watchlist_items(
    watchlist_id: int,
    body: WatchlistBulkReplace,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Atomically replace all items in a watchlist with a new set of symbols.

    Deletes all existing items for the watchlist, then inserts new rows for
    each symbol in the payload.  Operates in a single transaction.
    """
    watchlist = await db.get(WatchlistModel, watchlist_id)
    if watchlist is None or watchlist.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Watchlist {watchlist_id} not found",
        )

    # Delete existing items and insert new items via single serialized write
    def _bulk_replace_sync(target_wlid: int, symbols: list[str], exch: str) -> None:
        with _SyncSessionLocal() as session:
            session.execute(
                delete(WatchlistItemModel).where(
                    WatchlistItemModel.watchlist_id == target_wlid
                )
            )
            for sym in symbols:
                item = WatchlistItemModel(
                    watchlist_id=target_wlid,
                    symbol=sym,
                    exchange=exch,
                )
                session.add(item)
            session.commit()

    await enqueue_write_async(PRIO_UI_ACTION, _bulk_replace_sync, watchlist_id, list(body.symbols), body.exchange)

    # Warm deals cache asynchronously for newly added symbols
    try:
        from app.services.data_sync.deals import warm_symbol_deals
        for s in body.symbols:
            warm_symbol_deals(s)
    except Exception:
        pass

    return {
        "ok": True,
        "watchlist_id": watchlist_id,
        "items_added": len(body.symbols),
    }


# Legacy endpoints for backward compatibility (GET/POST/DELETE on /watchlist)
# These now operate on the Default watchlist (id=1)


@router.get("/watchlist", response_model=List[WatchlistItemOut], tags=["watchlist-legacy"])
async def list_default_watchlist(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> List[WatchlistItemOut]:
    """Return all watchlist items in the Default watchlist (legacy endpoint)."""
    default_id = await get_default_watchlist_id(db, current_user)
    q = (
        select(WatchlistItemModel)
        .where(WatchlistItemModel.watchlist_id == default_id)
        .order_by(WatchlistItemModel.created_at)
    )
    res = await db.execute(q)
    return [WatchlistItemOut.model_validate(item) for item in res.scalars().all()]  # type: ignore[return-value]


@router.post(
    "/watchlist",
    response_model=WatchlistItemOut,
    status_code=status.HTTP_201_CREATED,
    tags=["watchlist-legacy"],
)
async def add_default_watchlist_item(
    body: WatchlistItemCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WatchlistItemOut:
    """Add a symbol/exchange pair to the Default watchlist (legacy endpoint).

    If the pair already exists in the Default watchlist, return the existing row.
    """
    default_id = await get_default_watchlist_id(db, current_user)
    existing = await db.execute(
        select(WatchlistItemModel).where(
            WatchlistItemModel.watchlist_id == default_id,
            WatchlistItemModel.symbol == body.symbol,
            WatchlistItemModel.exchange == body.exchange,
        )
    )
    row = existing.scalar_one_or_none()
    if row is not None:
        return row  # type: ignore[return-value]

    def _add_legacy_sync() -> dict:
        with _SyncSessionLocal() as session:
            new_item = WatchlistItemModel(
                watchlist_id=default_id,
                symbol=body.symbol,
                exchange=body.exchange,
            )
            session.add(new_item)
            session.commit()
            session.refresh(new_item)
            return {
                "id": new_item.id,
                "watchlist_id": new_item.watchlist_id,
                "symbol": new_item.symbol,
                "exchange": new_item.exchange,
                "created_at": new_item.created_at,
            }

    item_dict = await enqueue_write_async(PRIO_UI_ACTION, _add_legacy_sync)
    return item_dict  # type: ignore[return-value]


@router.delete("/watchlist/{item_id}", tags=["watchlist-legacy"])
async def remove_default_watchlist_item(
    item_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Remove a watchlist item from the Default watchlist (legacy endpoint)."""
    default_id = await get_default_watchlist_id(db, current_user)
    item = await db.get(WatchlistItemModel, item_id)
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"watchlist item {item_id} not found",
        )
    if item.watchlist_id != default_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Item {item_id} does not belong to the Default watchlist",
        )
    def _delete_legacy_sync() -> None:
        with _SyncSessionLocal() as session:
            db_item = session.get(WatchlistItemModel, item_id)
            if db_item:
                session.delete(db_item)
                session.commit()

    await enqueue_write_async(PRIO_UI_ACTION, _delete_legacy_sync)
    return {"ok": True}


# ---------------------------------------------------------------------------
# TradingView Watchlist Import Endpoints
# ---------------------------------------------------------------------------

ALLOWED_TV_HOSTNAMES = {
    "tradingview.com",
    "www.tradingview.com",
    "in.tradingview.com",
}


def _validate_tradingview_url(url: str) -> urllib.parse.ParseResult:
    """Validate TradingView URL against exact scheme, host allowlist, port, credentials, and watchlist path."""
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid URL format",
        )

    # 1. Scheme must be exactly https
    if parsed.scheme.lower() != "https":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid URL: Scheme must be https",
        )

    # 2. Reject credentials / userinfo
    if parsed.username or parsed.password or "@" in (parsed.netloc or ""):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid URL: User credentials in URL are not permitted",
        )

    # 3. Reject non-default ports
    if parsed.port is not None and parsed.port != 443:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid URL: Non-default ports are not permitted",
        )

    # 4. Exact host allowlist
    hostname = (parsed.hostname or "").lower()
    if hostname not in ALLOWED_TV_HOSTNAMES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid URL: Only TradingView URLs (tradingview.com, www.tradingview.com, in.tradingview.com) are allowed",
        )

    # 5. Non-watchlist path check
    path = (parsed.path or "").strip()
    if not path or "watchlist" not in path.lower():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid TradingView URL: Must be a shared watchlist link",
        )

    return parsed


def _extract_tv_json_symbols_and_name(data: object) -> tuple[str | None, list[str]]:
    name: str | None = None
    symbols: list[str] = []

    def _crawl_name(obj: object) -> None:
        nonlocal name
        if name is not None:
            return
        if isinstance(obj, dict):
            for k in ("name", "title", "listName", "watchlistName"):
                val = obj.get(k)
                if isinstance(val, str) and val.strip():
                    name = val.strip()
                    return
            for v in obj.values():
                if isinstance(v, (dict, list)):
                    _crawl_name(v)

    def _crawl_symbols(obj: object) -> None:
        nonlocal symbols
        if symbols:
            return
        if isinstance(obj, dict):
            for k in ("symbols", "items", "tickers", "symbolsList"):
                val = obj.get(k)
                if isinstance(val, list) and len(val) > 0:
                    extracted = []
                    for item in val:
                        if isinstance(item, str) and item.strip():
                            extracted.append(item.strip())
                        elif isinstance(item, dict):
                            sym = item.get("symbol") or item.get("name") or item.get("ticker") or item.get("id")
                            if isinstance(sym, str) and sym.strip():
                                extracted.append(sym.strip())
                    if extracted and any(":" in s or s.isupper() for s in extracted):
                        symbols = extracted
                        return
            for v in obj.values():
                if isinstance(v, (dict, list)):
                    _crawl_symbols(v)
        elif isinstance(obj, list):
            if len(obj) > 0 and all(isinstance(x, str) and (":" in x or x.isupper()) for x in obj):
                symbols = [x.strip() for x in obj if isinstance(x, str) and x.strip()]
                return
            for item in obj:
                if isinstance(item, (dict, list)):
                    _crawl_symbols(item)

    _crawl_name(data)
    _crawl_symbols(data)
    return name, symbols


def _parse_tradingview_html(html_text: str) -> tuple[str, list[str]]:
    soup = BeautifulSoup(html_text, "html.parser")

    source_name = "TradingView Watchlist"
    if soup.title and soup.title.string:
        t = soup.title.string.strip()
        for suffix in ("— TradingView", "- TradingView", "| TradingView"):
            if suffix in t:
                t = t.split(suffix)[0].strip()
        if t:
            source_name = t

    raw_symbols: list[str] = []

    # 1. Find script type="application/prs.init-data+json"
    script_tag = soup.find("script", type="application/prs.init-data+json")
    if script_tag and script_tag.string:
        try:
            parsed_json = json.loads(script_tag.string)
            extracted_name, extracted_symbols = _extract_tv_json_symbols_and_name(parsed_json)
            if extracted_name:
                source_name = extracted_name
            if extracted_symbols:
                raw_symbols = extracted_symbols
        except Exception:
            pass

    # 2. Fallback to any script containing prs.init-data
    if not raw_symbols:
        for s in soup.find_all("script"):
            if s.string and "prs.init-data" in (s.get("type", "") or ""):
                try:
                    parsed_json = json.loads(s.string)
                    extracted_name, extracted_symbols = _extract_tv_json_symbols_and_name(parsed_json)
                    if extracted_symbols:
                        raw_symbols = extracted_symbols
                        if extracted_name:
                            source_name = extracted_name
                        break
                except Exception:
                    continue

    # 3. Fallback: regex search for symbol tickers
    if not raw_symbols:
        matches = re.findall(r"['\"]((?:NSE|BSE|NASDAQ|NYSE|BINANCE):[A-Za-z0-9_.-]+)['\"]", html_text)
        if matches:
            seen = set()
            for m in matches:
                if m not in seen and not m.startswith("HTTP"):
                    seen.add(m)
                    raw_symbols.append(m)

    return source_name, raw_symbols


@router.post("/watchlists/import-url", response_model=WatchlistImportUrlResponse, tags=["watchlist"])
async def import_watchlist_from_url(
    body: WatchlistImportUrlRequest,
    current_user: User = Depends(get_current_user),
) -> WatchlistImportUrlResponse:
    """Fetch public TradingView shared watchlist URL and extract raw symbols with strict security and redirect limits."""
    _validate_tradingview_url(body.url)

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    current_url = body.url
    redirect_count = 0
    max_redirects = 3
    final_resp = None

    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=False, headers=headers) as client:
            while True:
                try:
                    resp = await client.get(current_url)
                except httpx.TimeoutException:
                    raise HTTPException(
                        status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                        detail="TradingView request timed out after 15 seconds",
                    )
                except Exception as e:
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail=f"Failed to fetch TradingView page: {str(e)}",
                    )

                if resp.status_code in (301, 302, 303, 307, 308):
                    redirect_count += 1
                    if redirect_count > max_redirects:
                        raise HTTPException(
                            status_code=status.HTTP_502_BAD_GATEWAY,
                            detail="TradingView request exceeded maximum allowed redirects (3)",
                        )
                    loc = resp.headers.get("Location")
                    if not loc:
                        raise HTTPException(
                            status_code=status.HTTP_502_BAD_GATEWAY,
                            detail="Redirect response missing Location header",
                        )
                    next_url = urllib.parse.urljoin(current_url, loc)
                    try:
                        _validate_tradingview_url(next_url)
                    except HTTPException as he:
                        raise HTTPException(
                            status_code=status.HTTP_502_BAD_GATEWAY,
                            detail=f"Disallowed redirect location: {he.detail}",
                        )
                    current_url = next_url
                    continue

                final_resp = resp
                break
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to fetch TradingView page: {str(e)}",
        )

    if final_resp is None:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to receive a response from TradingView",
        )

    if final_resp.status_code == 404:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="TradingView watchlist not found or is private (HTTP 404 from TradingView)",
        )
    elif final_resp.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"TradingView returned status HTTP {final_resp.status_code}",
        )

    source_name, raw_symbols = _parse_tradingview_html(final_resp.text)

    if not raw_symbols:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No symbols found in the TradingView watchlist. The list may be empty, private, or using an unrecognized format.",
        )

    return WatchlistImportUrlResponse(source_name=source_name, raw_symbols=raw_symbols)


@router.post("/watchlists/import", response_model=WatchlistImportResponse, tags=["watchlist"])
async def import_watchlist(
    body: WatchlistImportRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WatchlistImportResponse:
    """Import symbols from TradingView sections into watchlists with destination-aware planning and limits."""
    # 1. Validation of mode and options
    if body.split_sections and body.mode != "create":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="split_sections is only supported when mode='create'",
        )

    if body.mode in ("append", "replace"):
        if not body.target_watchlist_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"target_watchlist_id is required when mode='{body.mode}'",
            )
        target_wl = await db.get(WatchlistModel, body.target_watchlist_id)
        if target_wl is None or target_wl.user_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Watchlist {body.target_watchlist_id} not found",
            )

    # 2. Collect candidate NSE symbols
    all_nse_symbols: set[str] = set()
    for sec in body.sections:
        for item in sec.items:
            if item.exchange.upper() == "NSE":
                all_nse_symbols.add(item.symbol.upper())

    # 3. Query stock_universe in safe chunks of 500
    valid_db_symbols: set[str] = set()
    if all_nse_symbols:
        nse_symbol_list = list(all_nse_symbols)
        CHUNK_SIZE = 500
        for i in range(0, len(nse_symbol_list), CHUNK_SIZE):
            batch = nse_symbol_list[i : i + CHUNK_SIZE]
            q = select(StockUniverse.symbol).where(StockUniverse.symbol.in_(batch))
            res = await db.execute(q)
            valid_db_symbols.update(s.upper() for s in res.scalars().all())

    # 4. If append mode, load target watchlist existing symbols
    existing_target_symbols: set[str] = set()
    if body.mode == "append":
        existing_rows = (
            await db.execute(
                select(WatchlistItemModel.symbol).where(
                    WatchlistItemModel.watchlist_id == body.target_watchlist_id
                )
            )
        ).scalars().all()
        existing_target_symbols = set(s.upper() for s in existing_rows)

    # 5. Destination planner: deduplicate and apply 1,000 capacity per destination
    skipped_symbols: list[WatchlistImportSkippedItem] = []
    planned_destinations: list[dict] = []

    if body.mode == "create" and body.split_sections:
        for sec in body.sections:
            sec_clean = re.sub(r"[^A-Za-z0-9 _-]", "", sec.name.strip())
            if not sec_clean or sec_clean.upper() == "DEFAULT":
                dest_name = body.base_name[:32]
            else:
                dest_name = f"{body.base_name} - {sec_clean}"[:32]

            dest_seen: set[str] = set()
            dest_symbols: list[str] = []

            for item in sec.items:
                sym = item.symbol.upper()
                exch = item.exchange.upper()
                if exch != "NSE":
                    skipped_symbols.append(
                        WatchlistImportSkippedItem(
                            symbol=sym,
                            exchange=exch,
                            reason=f"Unsupported exchange '{exch}'. V1 only supports NSE equities.",
                        )
                    )
                elif sym not in valid_db_symbols:
                    skipped_symbols.append(
                        WatchlistImportSkippedItem(
                            symbol=sym,
                            exchange=exch,
                            reason="Symbol not found in NSE universe",
                        )
                    )
                elif sym in dest_seen:
                    skipped_symbols.append(
                        WatchlistImportSkippedItem(
                            symbol=sym,
                            exchange=exch,
                            reason="Duplicate symbol in destination",
                        )
                    )
                else:
                    if len(dest_symbols) >= 1000:
                        skipped_symbols.append(
                            WatchlistImportSkippedItem(
                                symbol=sym,
                                exchange=exch,
                                reason="Destination capacity reached (1000)",
                            )
                        )
                    else:
                        dest_seen.add(sym)
                        dest_symbols.append(sym)

            if dest_symbols:
                planned_destinations.append({
                    "name": dest_name,
                    "symbols": dest_symbols,
                    "target_id": None,
                })

    else:
        # Single destination (create flat, replace, or append)
        dest_seen: set[str] = set()
        dest_symbols: list[str] = []
        current_target_count = len(existing_target_symbols) if body.mode == "append" else 0
        space_left = max(0, 1000 - current_target_count) if body.mode == "append" else 1000

        for sec in body.sections:
            for item in sec.items:
                sym = item.symbol.upper()
                exch = item.exchange.upper()
                if exch != "NSE":
                    skipped_symbols.append(
                        WatchlistImportSkippedItem(
                            symbol=sym,
                            exchange=exch,
                            reason=f"Unsupported exchange '{exch}'. V1 only supports NSE equities.",
                        )
                    )
                elif sym not in valid_db_symbols:
                    skipped_symbols.append(
                        WatchlistImportSkippedItem(
                            symbol=sym,
                            exchange=exch,
                            reason="Symbol not found in NSE universe",
                        )
                    )
                elif body.mode == "append" and sym in existing_target_symbols:
                    skipped_symbols.append(
                        WatchlistImportSkippedItem(
                            symbol=sym,
                            exchange=exch,
                            reason="Already in target watchlist",
                        )
                    )
                elif sym in dest_seen:
                    skipped_symbols.append(
                        WatchlistImportSkippedItem(
                            symbol=sym,
                            exchange=exch,
                            reason="Duplicate symbol in destination",
                        )
                    )
                else:
                    if len(dest_symbols) >= space_left:
                        reason = "Watchlist capacity reached (1000)" if body.mode == "append" else "Destination capacity reached (1000)"
                        skipped_symbols.append(
                            WatchlistImportSkippedItem(
                                symbol=sym,
                                exchange=exch,
                                reason=reason,
                            )
                        )
                    else:
                        dest_seen.add(sym)
                        dest_symbols.append(sym)

        if dest_symbols:
            planned_destinations.append({
                "name": body.base_name[:32],
                "symbols": dest_symbols,
                "target_id": body.target_watchlist_id,
            })

    # 6. Reject if zero valid symbols to import
    total_planned = sum(len(d["symbols"]) for d in planned_destinations)
    if total_planned == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No valid symbols to import. All symbols were skipped or invalid.",
        )

    # 7. Synchronous write transaction in background worker
    def _import_sync() -> dict:
        with _SyncSessionLocal() as session:
            created_watchlists = []
            added_symbols: list[str] = []
            final_target_id = body.target_watchlist_id

            if body.mode == "create":
                for dest in planned_destinations:
                    new_wl = WatchlistModel(name=dest["name"], user_id=current_user.id)
                    session.add(new_wl)
                    session.flush()

                    for s in dest["symbols"]:
                        item_model = WatchlistItemModel(
                            watchlist_id=new_wl.id,
                            symbol=s,
                            exchange="NSE",
                        )
                        session.add(item_model)
                        added_symbols.append(s)

                    session.flush()
                    session.refresh(new_wl)
                    created_watchlists.append({
                        "id": new_wl.id,
                        "name": new_wl.name,
                        "user_id": new_wl.user_id,
                        "created_at": new_wl.created_at,
                    })

                if created_watchlists:
                    final_target_id = created_watchlists[0]["id"]

            elif body.mode == "replace":
                session.execute(
                    delete(WatchlistItemModel).where(
                        WatchlistItemModel.watchlist_id == body.target_watchlist_id
                    )
                )
                dest = planned_destinations[0]
                for s in dest["symbols"]:
                    item_model = WatchlistItemModel(
                        watchlist_id=body.target_watchlist_id,
                        symbol=s,
                        exchange="NSE",
                    )
                    session.add(item_model)
                    added_symbols.append(s)
                final_target_id = body.target_watchlist_id

            elif body.mode == "append":
                dest = planned_destinations[0]
                for s in dest["symbols"]:
                    item_model = WatchlistItemModel(
                        watchlist_id=body.target_watchlist_id,
                        symbol=s,
                        exchange="NSE",
                    )
                    session.add(item_model)
                    added_symbols.append(s)
                final_target_id = body.target_watchlist_id

            session.commit()
            return {
                "created_watchlists": created_watchlists,
                "target_watchlist_id": final_target_id,
                "total_imported": len(added_symbols),
                "added_symbols": added_symbols,
            }

    write_result = await enqueue_write_async(PRIO_UI_ACTION, _import_sync)

    # Warm deals cache asynchronously for newly added symbols
    try:
        from app.services.data_sync.deals import warm_symbol_deals
        for s in write_result.get("added_symbols", []):
            warm_symbol_deals(s)
    except Exception:
        pass

    return WatchlistImportResponse(
        ok=True,
        created_watchlists=[WatchlistOut.model_validate(w) for w in write_result["created_watchlists"]],
        target_watchlist_id=write_result["target_watchlist_id"],
        total_imported=write_result["total_imported"],
        skipped_symbols=skipped_symbols,
    )
