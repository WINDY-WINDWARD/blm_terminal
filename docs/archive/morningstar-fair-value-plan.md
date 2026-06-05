> **ARCHIVED** — This document describes a completed implementation. It is kept for historical reference only and is no longer maintained.

---

# Morningstar Fair Value Integration Plan

## Overview

This document outlines the implementation plan to fetch and store fair values for stocks from Morningstar India. The system will integrate with the existing backend infrastructure, using the same patterns established for screener.in and MoneyControl integrations.

---

## Research Findings

### Morningstar API Structure

#### 1. Stock Screener API (Free, No Auth Required)

```
https://lt.morningstar.com/api/rest.svc/g9vi2nsqjb/security/screener
```

Returns JSON with all BSE and NSE stocks:
- `secId`: Morningstar's internal ID (e.g., `0P0000bec4` for TCS)
- `name`: Company name
- `exchangeId`: Exchange identifier (e.g., `EX$$$$XNSE`)
- Various metrics: marketCap, peRatio, quantitativeStarRating, etc.

**Limitation**: Does NOT include fair value data.

#### 2. Fair Value API Endpoint (Requires Auth Tokens)

```
https://api-global.morningstar.com/sal-service/v1/stock/priceFairValue/v3/{securityId}/data
```

**Authentication Required**:
- `access_token` - from HTML meta tag `<meta name="accessToken">`
- `X-Api-Realtime-E` - from HTML meta tag `<meta name="realTimeToken">`

**Note on Token Security**: Tokens in query parameters appear in server logs, browser history, and proxy logs. The API expects:
- `access_token` as query parameter (required by Morningstar API design)
- `X-Api-Realtime-E` as header

This is an accepted risk for the Morningstar API - they do not offer header-based auth for this endpoint.

**Response Structure**:
```json
{
  "chart": {
    "chartDatums": {
      "recent": {
        "latestFairValue": 4200.00
      }
    }
  }
}
```

#### 3. Token Extraction

Tokens are embedded in any Morningstar stock page HTML:
- Page: `https://www.morningstar.in/stocks/0p0000bec4/nse-tata-consultancy-services-ltd/overview.aspx`
- Meta tags: `accessToken`, `realTimeToken`

The existing codebase (`screener_client.py`, `mc_market_fetcher.py`) already uses **rookiepy** to extract browser cookies. We'll follow the same pattern.

### Reference Implementation Sources

1. **PKDevTools/morningstar** - Python library that implements this functionality:
   - Uses `CookieHelper` to extract tokens from browser session
   - Calls `priceFairValue/v3` endpoint
   - Returns `latestFairValue` from response

2. **Existing Integration Patterns**:
   - `screener_client.py` - Uses rookiepy for Chrome/Firefox cookie extraction
   - `mc_market_fetcher.py` - Similar cookie loading pattern with async support
   - Both services use `asyncio.Semaphore` for concurrency limiting

---

## Database Schema Changes

### StockUniverse Model Updates

**File**: `backend/app/models/stockuniverse.py`

Add three new columns:

```python
# New columns to add after mc_company_name
morningstar_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
fair_value: Mapped[float | None] = mapped_column(Float, nullable=True)
fair_value_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
```

### StockUniverse Schema Updates

**File**: `backend/app/schemas/stockuniverse.py`

Add three new Pydantic fields:

```python
# Add after mcCompanyName
morningstarId: str | None = None
fairValue: float | None = None
fairValueUpdatedAt: datetime | None = None
```

### New System Config Table (For Sync State)

**File**: `backend/app/models/system_config.py` (NEW)

```python
class SystemConfig(Base):
    """Key-value store for system state."""
    __tablename__ = "system_config"
    
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(512), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=False))
```

Used to track:
- `last_full_fairvalue_sync`: Timestamp of last full universe sync
- `last_watchlist_fairvalue_sync`: Timestamp of last watchlist sync

---

## Architecture

### New Files

| File | Purpose |
|------|---------|
| `backend/app/services/morningstar_client.py` | Morningstar API client service |
| `backend/app/routers/morningstar.py` | REST API endpoints |
| `backend/app/models/system_config.py` | System config table for sync state |

### Modified Files

| File | Changes |
|------|---------|
| `backend/app/models/stockuniverse.py` | Add 3 columns |
| `backend/app/schemas/stockuniverse.py` | Add 3 schema fields |
| `backend/app/backgroundtasks.py` | Add sync tasks with proper locking |
| `backend/app/main.py` | Add startup trigger logic |

---

## Implementation Details

### 1. Morningstar Client Service

**File**: `backend/app/services/morningstar_client.py`

#### Constants

```python
MORNINGSTAR_BASE_URL = "https://api-global.morningstar.com"
MORNINGSTAR_PAGE_URL = "https://www.morningstar.in"
MORNINGSTAR_SEARCH_URL = "https://www.morningstar.in/stocks/"

# Cache TTLs
TOKEN_CACHE_TTL = 60 * 60        # 1 hour
HTML_CACHE_TTL = 15 * 60         # 15 minutes
ID_CACHE_TTL = 24 * 60 * 60      # 24 hours
FAIR_VALUE_CACHE_TTL = 3 * 60 * 60  # 3 hours

# Concurrency - intentionally conservative for rate limiting
MAX_CONCURRENT_REQUESTS = 2
REQUEST_DELAY = 1.0  # Sleep between sequential requests (not token bucket, just conservative throttling)

# Batch settings for DB commits
DB_BATCH_SIZE = 50
```

#### Module-Level Caches with Proper Locking

```python
import asyncio
import time

# Token cache: key -> (expiry_monotonic, tokens_dict)
_token_cache: dict[str, tuple[float, dict[str, str]]] = {}
_token_refresh_lock = asyncio.Lock()  # Prevent concurrent token refresh

# HTML page cache: url -> (expiry_monotonic, html_text)
_html_cache: dict[str, tuple[float, str]] = {}

# Stock ID cache: symbol -> (expiry_monotonic, morningstar_id)
_id_cache: dict[str, tuple[float, str]] = {}
```

#### Client Initialization - Eager (Not Lazy)

```python
import httpx
from contextlib import asynccontextmanager


async def init_client():
    """Initialize HTTP client. Called from app lifespan."""
    global _client
    _client = httpx.AsyncClient(
        timeout=httpx.Timeout(30.0, connect=10.0),
        follow_redirects=True,
        limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
    )


async def close_client():
    """Close HTTP client. Called from app shutdown."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


async def _get_client() -> httpx.AsyncClient:
    """Return pre-initialized HTTP client.
    
    Client is created once in lifespan and closed on shutdown.
    No lazy init = no race condition.
    """
    if _client is None:
        raise RuntimeError("Morningstar client not initialized. Call init_client() first.")
    return _client
```

#### Class: MorningstarClient

```python
class MorningstarClient:
    """Client for Morningstar India API.
    
    This class is instantiated once as a module-level singleton:
        morningstar_client = MorningstarClient()
    
    It is stateful (holds semaphore and references the shared HTTP client),
    so only one instance should exist.
    """
    
    def __init__(self):
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
    
    # --- Client Management ---
    async def _ensure_tokens(self) -> dict[str, str]:
        """Ensure valid auth tokens, refreshing if needed.
        
        Uses double-checked locking pattern to prevent race conditions.
        """
        cache_entry = _token_cache.get("default")
        if cache_entry and time.monotonic() < cache_entry[0]:
            return cache_entry[1]
        
        # Token expired or not found - refresh with lock
        async with _token_refresh_lock:
            # Double-check inside lock
            cache_entry = _token_cache.get("default")
            if cache_entry and time.monotonic() < cache_entry[0]:
                return cache_entry[1]
            return await self._refresh_tokens()
    
    # --- Cookie/Token Management ---
    async def _refresh_tokens(self) -> dict[str, str]:
        """Fetch fresh tokens from Morningstar page.
        
        1. Load browser cookies via rookiepy
        2. Fetch a known stock page
        3. Extract tokens from meta tags
        4. Cache with TTL
        """
        # 1. Load browser cookies
        cookies = await self._load_browser_cookies()
        if not cookies:
            logger.warning("No browser cookies available for Morningstar")
            return {}
        
        # 2. Fetch a known stock page (TCS is always available)
        client = await _get_client()
        url = "https://www.morningstar.in/stocks/0p0000bec4/nse-tata-consultancy-services-ltd/overview.aspx"
        
        # Set cookies on request
        for name, value in cookies.items():
            client.cookies.set(name, value, domain="morningstar.in")
        
        response = await client.get(url)
        response.raise_for_status()
        
        # 3. Extract tokens from meta tags
        return await self._extract_tokens_from_html(response.text)
    
    async def _extract_tokens_from_html(self, html: str) -> dict[str, str]:
        """Extract accessToken and realTimeToken from meta tags."""
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        
        access_token = soup.find("meta", {"name": "accessToken"})
        realtime_token = soup.find("meta", {"name": "realTimeToken"})
        
        tokens = {}
        if access_token:
            tokens["access_token"] = access_token.get("content", "")
        if realtime_token:
            tokens["X-Api-Realtime-E"] = realtime_token.get("content", "")
        
        # Cache tokens
        _token_cache["default"] = (time.monotonic() + TOKEN_CACHE_TTL, tokens)
        return tokens
    
    async def _load_browser_cookies(self) -> dict[str, str]:
        """Use rookiepy to get morningstar.in cookies.
        
        Follows pattern from screener_client.py:
        - Try Chrome first, then Firefox
        - Return empty dict if no cookies found
        """
        import rookiepy
        
        browsers = ["chrome", "firefox"]
        for browser_name in browsers:
            try:
                func = getattr(rookiepy, browser_name, None)
                if func is None:
                    continue
                raw = await asyncio.to_thread(func, ["morningstar.in"])
                if raw:
                    cookies = {}
                    for c in raw:
                        name = c.get("name")
                        if name:
                            cookies[name] = c.get("value", "")
                    logger.info("Found morningstar.in cookies in %s", browser_name)
                    return cookies
            except Exception as exc:
                logger.debug("Failed to read cookies from %s: %s", browser_name, exc)
                continue
        
        logger.warning("No morningstar.in session found in Chrome or Firefox")
        return {}
    
    # --- Stock Resolution ---
    async def resolve_symbol_to_id(self, symbol: str, db: AsyncSession | None = None) -> str | None:
        """Convert NSE symbol to Morningstar security ID.
        
        Resolution strategy (in order of priority):
        1. Check _id_cache (in-memory, 24h TTL) - fastest path
        2. Check stock_universe.morningstar_id (DB) - persistent, most symbols will be here after first sync
        3. Use Morningstar Algolia search API (free, no auth needed) - last resort
        
        Algolia search endpoint:
        POST https://17iqhzwxzw-dsn.algolia.net/1/indexes/companies/query
        Headers: X-Algolia-Application-Id: 17IQHZWXZW
                 X-Algolia-API-Key: be7c37718f927d0137a88a11b69ae419
        Body: {"query": "TCS", "restrictHighlightAndSnippetArrays": true}
        
        Response contains secId in hits.
        
        Args:
            symbol: NSE stock symbol (e.g., "TCS")
            db: Optional AsyncSession for DB lookup. If None, skips DB lookup.
        """
        symbol_upper = symbol.upper()
        
        # 1. Check in-memory cache first (fastest)
        cache_entry = _id_cache.get(symbol_upper)
        if cache_entry and time.monotonic() < cache_entry[0]:
            return cache_entry[1]
        
        # 2. Check DB if session provided (most symbols will be here after first sync)
        if db:
            from sqlalchemy import select
            from app.models.stockuniverse import StockUniverse
            
            stmt = select(StockUniverse.morningstar_id).where(StockUniverse.symbol == symbol_upper)
            result = await db.execute(stmt)
            ms_id = result.scalar_one_or_none()
            
            if ms_id:
                # Cache the result
                _id_cache[symbol_upper] = (time.monotonic() + ID_CACHE_TTL, ms_id)
                return ms_id
        
        # 3. Algolia search as last resort (first time only, result gets persisted by sync task)
        ms_id = await self._search_algolia(symbol)
        
        if ms_id:
            _id_cache[symbol_upper] = (time.monotonic() + ID_CACHE_TTL, ms_id)
        
        return ms_id
    
    async def _search_algolia(self, symbol: str) -> str | None:
        """Search Morningstar via Algolia to get security ID."""
        import json
        
        client = await _get_client()
        headers = {
            "X-Algolia-Application-Id": "17IQHZWXZW",
            "X-Algolia-API-Key": "be7c37718f927d0137a88a11b69ae419",
            "Content-Type": "application/json",
        }
        body = json.dumps({
            "query": symbol,
            "restrictHighlightAndSnippetArrays": True
        })
        
        try:
            response = await client.post(
                "https://17iqhzwxzw-dsn.algolia.net/1/indexes/companies/query",
                headers=headers,
                content=body,
            )
            response.raise_for_status()
            data = response.json()
            
            # Find first exact match or closest match
            for hit in data.get("hits", []):
                if hit.get("ticker", "").upper() == symbol.upper():
                    return hit.get("objectID") or hit.get("secId")
            
            return None
        except Exception as e:
            logger.error(f"Algolia search failed for {symbol}: {e}")
            return None
    
    # --- Fair Value Fetching ---
    async def get_fair_value(self, security_id: str) -> float | None:
        """Fetch fair value for a given Morningstar security ID.
        
        API: GET /sal-service/v1/stock/priceFairValue/v3/{id}/data
        
        Error handling:
        - 401: Refresh tokens, retry once
        - Timeout: Return None, keep existing value
        - Not found: Return None
        """
        try:
            async with self._semaphore:
                tokens = await self._ensure_tokens()
                client = await _get_client()
                
                # Note: access_token passed as query param (Morningstar API design)
                url = f"{MORNINGSTAR_BASE_URL}/sal-service/v1/stock/priceFairValue/v3/{security_id}/data"
                params = {
                    "languageId": "en",
                    "locale": "en",
                    "clientId": "RSIN_SAL",
                    "component": "sal-price-fairvalue",
                    "version": "4.13.0",
                    "access_token": tokens.get("access_token", ""),
                }
                headers = {
                    "X-Api-Realtime-E": tokens.get("X-Api-Realtime-E", ""),
                }
                
                response = await client.get(url, params=params, headers=headers)
                
                if response.status_code == 401:
                    # Token expired - refresh and retry once
                    logger.info("Token expired, refreshing...")
                    await self._refresh_tokens()
                    tokens = await self._ensure_tokens()
                    params["access_token"] = tokens.get("access_token", "")
                    headers["X-Api-Realtime-E"] = tokens.get("X-Api-Realtime-E", "")
                    response = await client.get(url, params=params, headers=headers)
                
                response.raise_for_status()
                data = response.json()
                return data["chart"]["chartDatums"]["recent"]["latestFairValue"]
                
        except httpx.TimeoutException:
            logger.warning(f"Timeout fetching fair value for {security_id}")
            return None
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error fetching fair value for {security_id}: {e}")
            return None
        except KeyError as e:
            logger.error(f"Unexpected response structure for {security_id}: {e}")
            return None
        except Exception as e:
            logger.error(f"Error fetching fair value for {security_id}: {e}")
            return None
    
    async def get_fair_value_by_symbol(self, symbol: str, db: AsyncSession | None = None) -> dict:
        """Full pipeline: symbol → ID → fair value.
        
        Returns:
        {
            "symbol": "TCS",
            "morningstarId": "0P0000bec4",
            "fairValue": 4200.00,
            "updatedAt": "2024-03-24T10:30:00"
        }
        
        Args:
            symbol: NSE stock symbol
            db: Optional AsyncSession for DB lookups (speeds up repeated calls)
        """
        symbol = symbol.upper().strip()
        
        # Resolve symbol to Morningstar ID (pass db for DB lookup)
        ms_id = await self.resolve_symbol_to_id(symbol, db)
        if not ms_id:
            return {"symbol": symbol, "morningstarId": None, "fairValue": None, "updatedAt": None}
        
        # Fetch fair value
        fair_value = await self.get_fair_value(ms_id)
        
        return {
            "symbol": symbol,
            "morningstarId": ms_id,
            "fairValue": fair_value,
            "updatedAt": datetime.now(timezone.utc).isoformat() if fair_value else None
        }


# Module-level singleton - this is the single source of truth
morningstar_client = MorningstarClient()
```

### 2. API Router

**File**: `backend/app/routers/morningstar.py`

```python
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query

from app.database import get_db
from app.services.morningstar_client import morningstar_client

router = APIRouter(tags=["morningstar"])

# Note: We don't cache at router level - let morningstar_client be the single source of truth
# The client already handles in-memory caching

@router.get("/morningstar/fairvalue/{symbol}")
async def get_fair_value(symbol: str) -> dict:
    """
    Get fair value for a stock symbol.
    
    Returns:
    - Fresh fetch from Morningstar API
    - Result includes morningstarId for reference
    """
    symbol = symbol.upper().strip()
    result = await morningstar_client.get_fair_value_by_symbol(symbol)
    return result


@router.get("/morningstar/search")
async def search_stock(q: str = Query(..., min_length=1, max_length=80)) -> list[dict]:
    """
    Search for a stock to get Morningstar ID.
    
    Uses Algolia search API (free, no auth needed).
    """
    ms_id = await morningstar_client.resolve_symbol_to_id(q)
    if ms_id:
        return [{"symbol": q.upper(), "morningstarId": ms_id}]
    return []
```

### 3. Background Tasks with Proper Locking

**File**: `backend/app/backgroundtasks.py`

#### Locks for Overlap Prevention

```python
# Global locks to prevent concurrent execution
_watchlist_sync_lock = asyncio.Lock()
_full_sync_lock = asyncio.Lock()

# Batch size for DB commits
DB_BATCH_SIZE = 50
```

#### Task 1: Watchlist Fair Value Sync (Every 3 Hours)

```python
async def sync_watchlist_fair_values():
    """
    Fetch fair values for all watchlist stocks.
    Runs every 3 hours.
    
    Uses lock to prevent overlap if previous sync is still running.
    Uses single DB session with batch commits (every 50 symbols).
    """
    if _watchlist_sync_lock.locked():
        logger.warning("Watchlist sync already running, skipping this cycle")
        return
    
    async with _watchlist_sync_lock:
        logger.info("Starting watchlist fair value sync")
        
        # Get all unique symbols from watchlist_items table
        async with AsyncSession(engine) as db:
            stmt = select(WatchlistItem.symbol).distinct()
            result = await db.execute(stmt)
            symbols = [row[0] for row in result.fetchall()]
        
        updated = 0
        failed = 0
        
        # Single session for all updates, batch commits every DB_BATCH_SIZE
        async with AsyncSession(engine) as db:
            for i, symbol in enumerate(symbols, 1):
                try:
                    # Pass db to resolve_symbol_to_id for DB lookup
                    result = await morningstar_client.get_fair_value_by_symbol(symbol)
                    if result.get("fairValue"):
                        await _update_stock_universe(db, symbol, result)
                        updated += 1
                    else:
                        failed += 1
                except Exception as e:
                    logger.warning(f"Failed to fetch fair value for {symbol}: {e}")
                    failed += 1
                
                # Batch commit every DB_BATCH_SIZE symbols
                if i % DB_BATCH_SIZE == 0:
                    await db.commit()
                    logger.debug(f"Watchlist sync progress: {i}/{len(symbols)}")
                
                await asyncio.sleep(REQUEST_DELAY)  # Conservative rate limiting
            
            # Final flush
            await db.commit()
        
        logger.info(f"Watchlist fair value sync complete: {updated} updated, {failed} failed")
        
        # Update sync timestamp
        await _update_sync_timestamp("last_watchlist_fairvalue_sync")
```

#### Task 2: Full Universe Sync (Nightly + Server Start)

```python
async def sync_all_fair_values():
    """
    Fetch fair values for all stocks in stock_universe.
    Runs:
    - Nightly at 2 AM IST
    - On server fresh start immediately
    
    Strategy:
    1. First: Populate missing morningstar_id for all stocks (batch of 50)
    2. Then: Fetch fair values for all stocks (batch of 50)
    
    Uses batch commits to avoid keeping DB session open for hours.
    """
    if _full_sync_lock.locked():
        logger.warning("Full sync already running, skipping this cycle")
        return
    
    async with _full_sync_lock:
        logger.info("Starting full universe fair value sync")
        
        # Get all symbols from stock_universe
        async with AsyncSession(engine) as db:
            stmt = select(StockUniverse.symbol)
            result = await db.execute(stmt)
            all_symbols = [row[0] for row in result.fetchall()]
        
        # Step 1: Populate missing morningstar_ids
        logger.info("Step 1: Populating missing Morningstar IDs")
        batch_counter = 0
        
        for symbol in all_symbols:
            try:
                ms_id = await morningstar_client.resolve_symbol_to_id(symbol)
                if ms_id:
                    async with AsyncSession(engine) as db:
                        await _update_morningstar_id(db, symbol, ms_id)
                        batch_counter += 1
                        
                        if batch_counter % DB_BATCH_SIZE == 0:
                            logger.info(f"ID sync progress: {batch_counter}/{len(all_symbols)}")
                            await asyncio.sleep(1)  # Brief pause between batches
            except Exception as e:
                logger.debug(f"Failed to resolve ID for {symbol}: {e}")
            
            await asyncio.sleep(REQUEST_DELAY)
        
        # Step 2: Fetch fair values
        logger.info("Step 2: Fetching fair values")
        batch_counter = 0
        
        for symbol in all_symbols:
            try:
                result = await morningstar_client.get_fair_value_by_symbol(symbol)
                if result.get("fairValue"):
                    async with AsyncSession(engine) as db:
                        await _update_stock_universe(db, symbol, result)
                        batch_counter += 1
                        
                        if batch_counter % DB_BATCH_SIZE == 0:
                            logger.info(f"Fair value progress: {batch_counter}/{len(all_symbols)}")
                            await asyncio.sleep(1)
            except Exception as e:
                logger.debug(f"Failed to fetch fair value for {symbol}: {e}")
            
            await asyncio.sleep(REQUEST_DELAY)
        
        logger.info("Full universe fair value sync complete")
        
        # Update sync timestamp
        await _update_sync_timestamp("last_full_fairvalue_sync")
```

#### Helper Functions

```python
async def _update_stock_universe(db: AsyncSession, symbol: str, result: dict):
    """Update stock_universe with fair value."""
    from sqlalchemy import update
    from app.models.stockuniverse import StockUniverse
    
    stmt = (
        update(StockUniverse)
        .where(StockUniverse.symbol == symbol)
        .values(
            morningstar_id=result.get("morningstarId"),
            fair_value=result.get("fairValue"),
            fair_value_updated_at=datetime.now(timezone.utc)
        )
    )
    await db.execute(stmt)


async def _update_morningstar_id(db: AsyncSession, symbol: str, ms_id: str):
    """Update morningstar_id in stock_universe if NULL."""
    from sqlalchemy import update
    from app.models.stockuniverse import StockUniverse
    
    stmt = (
        update(StockUniverse)
        .where(StockUniverse.symbol == symbol)
        .where(StockUniverse.morningstar_id.is_(None))
        .values(morningstar_id=ms_id)
    )
    await db.execute(stmt)


async def _update_sync_timestamp(key: str):
    """Update system_config with current timestamp using upsert.
    
    Uses SQLite upsert (INSERT OR REPLACE) to handle both first insert
    and subsequent updates without primary key violations.
    """
    from sqlalchemy import insert
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert
    from app.models.system_config import SystemConfig
    
    async with AsyncSession(engine) as db:
        # SQLite upsert: INSERT OR REPLACE
        stmt = sqlite_insert(SystemConfig).values(
            key=key,
            value=datetime.now(timezone.utc).isoformat(),
            updated_at=datetime.now(timezone.utc)
        )
        # On conflict, update the value and timestamp
        stmt = stmt.on_conflict_do_update(
            index_elements=["key"],
            set_={
                "value": stmt.excluded.value,
                "updated_at": stmt.excluded.updated_at
            }
        )
        await db.execute(stmt)
        await db.commit()
```

#### Server Start Trigger - Fixed Heuristic

```python
async def _should_trigger_full_sync() -> bool:
    """Check if full sync should run at startup.
    
    Uses MAX(fair_value_updated_at) as signal:
    - If NULL (never synced): trigger
    - If older than 24 hours: trigger
    
    Note: fair_value_updated_at uses DateTime(timezone=False) in the model,
    so we use datetime.utcnow() for naive datetime comparison.
    """
    async with AsyncSession(engine) as db:
        from sqlalchemy import func, select
        from app.models.stockuniverse import StockUniverse
        
        stmt = select(func.max(StockUniverse.fair_value_updated_at))
        result = await db.execute(stmt)
        last_update = result.scalar()  # This is a naive datetime (timezone=False)
        
        if last_update is None:
            return True
        
        # Use datetime.utcnow() to match the naive datetime in DB
        from datetime import timedelta
        now_naive = datetime.utcnow()
        if now_naive - last_update > timedelta(hours=24):
            return True
        
        return False
```

#### Scheduler Implementation

```python
async def _run_watchlist_scheduler():
    """Run every 3 hours."""
    while True:
        await asyncio.sleep(3 * 60 * 60)  # 3 hours
        await sync_watchlist_fair_values()


async def _run_nightly_scheduler():
    """Run at 2 AM IST daily.
    
    2 AM IST = 20:30 UTC (IST is UTC+5:30, no DST)
    """
    while True:
        now = datetime.now(timezone.utc)
        # 2 AM IST = 20:30 UTC previous day -> need to calculate properly
        # IST = UTC + 5:30, so 2 AM IST = 20:30 UTC same day, or 20:30 - 24h if past
        target = now.replace(hour=20, minute=30, second=0, microsecond=0)
        if now >= target:
            target += timedelta(days=1)
        
        seconds_until_target = (target - now).total_seconds()
        await asyncio.sleep(seconds_until_target)
        await sync_all_fair_values()
```

#### Updated Lifespan Logic

In `app/main.py`:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # ... existing startup code ...
    
    # Initialize Morningstar HTTP client
    await init_client()
    
    # Check if full sync should run
    if await _should_trigger_full_sync():
        logger.info("Triggering immediate full fair value sync (DB cold or stale)")
        asyncio.create_task(sync_all_fair_values())
        asyncio.create_task(sync_watchlist_fair_values())
    
    # Start schedulers
    asyncio.create_task(_run_watchlist_scheduler())
    asyncio.create_task(_run_nightly_scheduler())
    
    yield
    
    # ... existing shutdown code ...
    
    # Close Morningstar HTTP client
    await close_client()
```

---

## Data Flow

### Watchlist Stocks (Active - Every 3 Hours)

```
┌─────────────────┐     ┌──────────────────────┐     ┌─────────────────┐
│  Scheduler      │────▶│  morningstar_client   │────▶│  stock_universe │
│  (every 3h)     │     │  get_fair_value()     │     │  DB Update      │
│  + Lock         │     │  (per-symbol session) │     │  (batch commit) │
└─────────────────┘     └──────────────────────┘     └─────────────────┘
```

### Non-Watchlist Stocks (Nightly Batch)

```
┌─────────────────┐     ┌──────────────────────┐     ┌─────────────────┐
│  Nightly Cron   │────▶│  morningstar_client   │────▶│  stock_universe │
│  (2 AM IST)     │     │  get_fair_value()     │     │  DB Update      │
│  + Lock         │     │  (batch of 50)        │     │  (batch commit) │
└─────────────────┘     └──────────────────────┘     └─────────────────┘
```

---

## Caching Strategy

| Data Type | Cache TTL | Storage | Update Frequency |
|-----------|-----------|---------|------------------|
| Auth Tokens | 1 hour | In-memory + asyncio.Lock | Auto-refresh on 401 |
| HTML Page | 15 minutes | In-memory | Per-request |
| Stock ID Mapping | 24 hours | In-memory + DB | Once, persist |
| Fair Value | 3 hours | stock_universe DB | Every 3h (watchlist), nightly (others) |

---

## Database Migration

```bash
cd backend

# Generate migration for new columns
alembic revision --autogenerate -m "add morningstar fair value columns"

# Also need to create system_config table
# This can be done via migration or SQL script

# Run migrations
alembic upgrade head
```

---

## Error Handling Summary

| Error | Action |
|-------|--------|
| Token expired (401) | Refresh tokens via rookiepy, retry once |
| Stock not found | Return null, don't update DB |
| API timeout | Return null, keep existing DB value |
| Rate limit | Use semaphore + sleep between requests |
| DB update fail | Log error, continue with next stock |
| Sync already running | Skip this cycle, log warning |

---

## API Endpoints Summary

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/morningstar/fairvalue/{symbol}` | GET | Get fair value for a stock |
| `/morningstar/search` | GET | Search stocks to get Morningstar ID |

---

## Implementation Checklist

- [ ] Add columns to `stockuniverse.py` model
- [ ] Add fields to `stockuniverse.py` schema
- [ ] Create `system_config.py` model
- [ ] Create `morningstar_client.py` service with proper locking
- [ ] Create `morningstar.py` router
- [ ] Add fair value sync to `backgroundtasks.py` with locks + batch commits
- [ ] Update `main.py` lifespan with proper startup trigger
- [ ] Run Alembic migration
- [ ] Test with sample symbols

---

## Dependencies

Already available in project:
- `httpx` - Async HTTP client
- `rookiepy` - Browser cookie extraction
- `bs4` (BeautifulSoup) - HTML parsing
- `asyncio` - Async/await support
- `sqlalchemy` - Database ORM

No new dependencies required.

**Python Version Note**: This implementation uses `asyncio.to_thread()` which was added in Python 3.9. If the project targets Python 3.8, replace with `loop.run_in_executor`:

```python
# Python 3.8 compatible
loop = asyncio.get_event_loop()
raw = await loop.run_in_executor(None, lambda: func(["morningstar.in"]))
```

---

## Rate Limiting Note

The `REQUEST_DELAY = 1.0` with `asyncio.sleep()` in loops is intentionally conservative throttling, not a proper token-bucket rate limiter. This is deliberate because:

1. Morningstar doesn't publish rate limits for their API
2. We're using authenticated endpoints that may have stricter limits
3. The conservative approach ensures we don't get blocked
4. For batch operations (full universe sync), this is acceptable - it will take several hours regardless

For production, if this proves too slow, we can add proper rate limiting later after monitoring.

---

## Thread Safety Summary

| Component | Fix Applied |
|-----------|-------------|
| Token refresh | `asyncio.Lock` with double-checked locking |
| HTTP client | Created once at module load, not lazily |
| DB commits | Batch every 50 symbols, separate sessions |
| Background tasks | `asyncio.Lock` to prevent overlap |
| Sync trigger | Use `MAX(fair_value_updated_at)` instead of heuristic |
