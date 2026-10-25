"""Morningstar client service for fetching fair values from Morningstar India API."""

from __future__ import annotations

import asyncio
import logging
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.services.browser_harvester import harvest_public_html
from app.services.persistent_cache import get_cached_json, set_cached_json
import httpx
from bs4 import BeautifulSoup
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.stockuniverse import StockUniverse


@dataclass
class FairValueResult:
    """Result of a fair value lookup."""
    symbol: str
    morningstar_id: str | None
    fair_value: float | None
    updated_at: datetime | None

logger = logging.getLogger(__name__)

MORNINGSTAR_BASE_URL = "https://api-global.morningstar.com"
MORNINGSTAR_PAGE_URL = "https://www.morningstar.in"
AUTOCOMPLETE_URL = "https://morningstar.in/handlers/autocompletehandler.ashx"

TOKEN_CACHE_TTL = 60 * 60
ID_CACHE_TTL = 24 * 60 * 60

# Concurrency, courtesy delay, and circuit breaker for morningstar.in
# requests are now delegated to ``nse_rate_limiter.throttled_nse_call``
# (audit B.7) so all three external services (NSE, screener.in,
# morningstar.in) share one global concurrency budget.
from app.services.nse_rate_limiter import throttled_nse_call  # noqa: E402
REQUEST_DELAY = 1.0
DB_BATCH_SIZE = 50

SAL_CONTENT_TYPE = "nNsGdN3REOnPMlKDShOYjlk6VYiEVLSdpfpXAm7o2Tk="
DEFAULT_TOKEN_PAGE = "https://www.morningstar.in/stocks/0p0000bec4/nse-tata-consultancy-services-ltd/overview.aspx"

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

API_PARAMS = {
    "languageId": "en",
    "locale": "en",
    "clientId": "RSIN_SAL",
    "component": "sal-price-fairvalue",
    "version": "4.13.0",
    "secExchangeList": "NSE",
}

_token_cache: dict[str, tuple[float, dict[str, str]]] = {}
_token_refresh_lock: asyncio.Lock | None = None
_id_cache: dict[str, tuple[float, str]] = {}

_client: httpx.AsyncClient | None = None


def _get_token_lock() -> asyncio.Lock:
    """Get or create the token refresh lock."""
    global _token_refresh_lock
    if _token_refresh_lock is None:
        _token_refresh_lock = asyncio.Lock()
    return _token_refresh_lock


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
    """Return pre-initialized HTTP client."""
    if _client is None:
        raise RuntimeError("Morningstar client not initialized. Call init_client() first.")
    return _client


def _token_cache_get(key: str) -> dict[str, str] | None:
    entry = _token_cache.get(key)
    if entry and time.monotonic() < entry[0]:
        return entry[1]
    return None


def _token_cache_set(key: str, tokens: dict[str, str]) -> None:
    _token_cache[key] = (time.monotonic() + TOKEN_CACHE_TTL, tokens)


def _id_cache_get(symbol: str) -> str | None:
    entry = _id_cache.get(symbol.upper())
    if entry and time.monotonic() < entry[0]:
        return entry[1]
    return None


def _id_cache_set(symbol: str, ms_id: str) -> None:
    _id_cache[symbol.upper()] = (time.monotonic() + ID_CACHE_TTL, ms_id)


class MorningstarClient:
    """Client for Morningstar India API."""

    def __init__(self):
        # Concurrency is now governed by ``throttled_nse_call`` (audit B.7)
        # so all three external services (NSE, screener.in, morningstar.in)
        # share one global concurrency budget.
        pass

    async def _ensure_tokens(self) -> dict[str, str]:
        """Ensure valid auth tokens, refreshing if needed."""
        cached = _token_cache_get("default")
        if cached:
            return cached

        async with _get_token_lock():
            cached = _token_cache_get("default")
            if cached:
                return cached
            return await self._refresh_tokens()

    async def _refresh_tokens(self) -> dict[str, str]:
        """Fetch fresh tokens from Morningstar page using anonymous browser harvester."""
        url = DEFAULT_TOKEN_PAGE
        html = await harvest_public_html(url)
        if not html:
            logger.info("Morningstar token harvesting via browser returned empty; trying anonymous HTTP GET")
            try:
                client = await _get_client()
                headers = {
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                }
                response = await client.get(url, headers=headers)
                if response.status_code == 200:
                    html = response.text
            except Exception as e:
                logger.warning("Failed to fetch token page via HTTP: %s", type(e).__name__)

        if not html:
            logger.warning("Failed to fetch Morningstar token page")
            return {}

        return await self._extract_tokens_from_html(html)

    async def _extract_tokens_from_html(self, html: str) -> dict[str, str]:
        """Extract accessToken and realTimeToken from meta tags."""
        soup = BeautifulSoup(html, "html.parser")

        access_token = soup.find("meta", {"name": "accessToken"})
        realtime_token = soup.find("meta", {"name": "realTimeToken"})

        tokens = {}
        if access_token:
            token_value = access_token.get("content", "")
            if token_value:
                tokens["access_token"] = token_value
                logger.info("Found accessToken")
            else:
                logger.warning("accessToken meta tag found but empty content")
        else:
            logger.warning("No accessToken meta tag found in page")
        if realtime_token:
            token_value = realtime_token.get("content", "")
            if token_value:
                tokens["X-Api-Realtime-E"] = token_value
                logger.info("Found realtimeToken")
            else:
                logger.warning("realtimeToken meta tag found but empty content")
        else:
            logger.warning("No realtimeToken meta tag found in page")

        if not tokens:
            logger.warning("No tokens extracted from Morningstar page")

        _token_cache_set("default", tokens)
        return tokens

    async def resolve_symbol_to_id(
        self, symbol: str, db: AsyncSession | None = None
    ) -> str | None:
        """Convert NSE symbol to Morningstar security ID."""
        symbol_upper = symbol.upper()

        cached = _id_cache_get(symbol_upper)
        if cached:
            return cached

        if db:
            from sqlalchemy import select

            stmt = select(StockUniverse.morningstar_id).where(
                StockUniverse.symbol == symbol_upper
            )
            result = await db.execute(stmt)
            ms_id = result.scalar_one_or_none()

            if ms_id:
                _id_cache_set(symbol_upper, ms_id)
                return ms_id

        ms_id = await self._search_autocomplete(symbol)

        if ms_id:
            _id_cache_set(symbol_upper, ms_id)
            logger.info(f"Resolved {symbol_upper} to Morningstar ID: {ms_id}")
        else:
            logger.warning(f"Could not resolve {symbol_upper} to Morningstar ID via Algolia")

        return ms_id

    async def _search_autocomplete(self, symbol: str) -> str | None:
        """Search Morningstar India autocomplete to get security ID."""
        client = await _get_client()
        
        try:
            url = f"{AUTOCOMPLETE_URL}?criteria={symbol}"
            headers = {
                "User-Agent": DEFAULT_HEADERS["User-Agent"],
                "Accept": "application/xml, text/xml, */*",
            }
            
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            
            root = ET.fromstring(response.text)
            
            for table in root.findall(".//Table"):
                exchange_elem = table.find("Exchange")
                if exchange_elem is not None and exchange_elem.text == "NSE":
                    ms_id_elem = table.find("ID")
                    if ms_id_elem is not None and ms_id_elem.text:
                        ms_id = ms_id_elem.text
                        logger.info(f"Autocomplete found NSE ID for {symbol}: {ms_id}")
                        return ms_id
            
            logger.warning(f"No NSE ID found for {symbol} in autocomplete results")
            return None
        except Exception as e:
            logger.error("Autocomplete search failed for %s: %s", symbol, type(e).__name__)
            return None

    async def _get_fair_value_impl(self, security_id: str) -> float | None:
        """Internal: actual fair-value fetch logic, wrapped by ``get_fair_value``
        via ``throttled_nse_call`` (audit B.7)."""
        tokens = await self._ensure_tokens()

        if not tokens:
            logger.warning(f"No tokens available for fair value fetch, skipping {security_id}")
            return None

        client = await _get_client()

        access_token = tokens.get("access_token", "")
        realtime_token = tokens.get("X-Api-Realtime-E", "")

        url = f"{MORNINGSTAR_BASE_URL}/sal-service/v1/stock/priceFairValue/v3/{security_id}/data"
        params = {**API_PARAMS, "access_token": access_token}
        headers = {
            "X-Api-Realtime-E": realtime_token,
            "X-Sal-Contenttype": SAL_CONTENT_TYPE,
            "Accept": "application/json",
        }

        logger.debug(f"Fetching fair value for {security_id}")

        response = await client.get(url, params=params, headers=headers)

        logger.debug("Fair value response status: %s", response.status_code)

        if response.status_code == 401:
            logger.warning("Fair value response status 401: Unauthorized")
            logger.info("Token expired, refreshing...")
            await self._refresh_tokens()
            tokens = await self._ensure_tokens()
            access_token = tokens.get("access_token", "")
            realtime_token = tokens.get("X-Api-Realtime-E", "")
            params["access_token"] = access_token
            headers["X-Api-Realtime-E"] = realtime_token
            response = await client.get(url, params=params, headers=headers)
            logger.debug(f"Retry fair value response status: {response.status_code}")

        if response.status_code == 206:
            logger.debug(f"Got 206 Partial Content for {security_id}, attempting to parse")
        elif response.status_code >= 400:
            response.raise_for_status()

        try:
            data = response.json()
        except Exception as e:
            logger.warning("Failed to parse fair value response for %s: %s", security_id, type(e).__name__)
            return None

        try:
            return data["chart"]["chartDatums"]["recent"]["latestFairValue"]
        except (KeyError, TypeError) as e:
            logger.warning("Unexpected fair value response structure for %s: %s", security_id, type(e).__name__)
            return None

    async def get_fair_value(self, security_id: str) -> float | None:
        """Fetch fair value for a given Morningstar security ID.

        Routed through ``throttled_nse_call`` so morningstar.in requests
        share the global NSE-rate-limit semaphore and circuit breaker
        (audit B.7).
        """
        try:
            return await throttled_nse_call(
                "morningstar.fair_value",
                self._get_fair_value_impl,
                security_id,
                is_async_fn=True,
                coalesce_key=f"morningstar.fair_value:{security_id}",
            )
        except httpx.TimeoutException:
            logger.warning(f"Timeout fetching fair value for {security_id}")
            return None
        except httpx.HTTPStatusError as e:
            logger.error("HTTP error fetching fair value for %s: %s", security_id, type(e).__name__)
            return None
        except Exception as e:
            logger.error("Error fetching fair value for %s: %s", security_id, type(e).__name__)
            return None

    async def get_fair_value_by_symbol(
        self, symbol: str, db: AsyncSession | None = None
    ) -> dict[str, Any]:
        """Full pipeline: symbol → ID → fair value. Returns dict for backward compatibility."""
        symbol_upper = symbol.upper().strip()
        cache_key = f"morningstar:fv:{symbol_upper}"

        cached = await get_cached_json(cache_key)
        if cached:
            logger.debug(f"Morningstar FV persistent cache hit for {symbol_upper}")
            return cached

        ms_id = await self.resolve_symbol_to_id(symbol_upper, db)
        if not ms_id:
            result = {
                "symbol": symbol_upper,
                "morningstarId": None,
                "fairValue": None,
                "updatedAt": None,
            }
            await set_cached_json(cache_key, result, ttl_hours=24)
            return result

        fair_value = await self.get_fair_value(ms_id)

        result = {
            "symbol": symbol_upper,
            "morningstarId": ms_id,
            "fairValue": fair_value,
            "updatedAt": datetime.now(timezone.utc).isoformat() if fair_value else None,
        }
        await set_cached_json(cache_key, result, ttl_hours=24)
        return result

    async def get_fair_value_batch(
        self, symbols: list[str], db: AsyncSession | None = None
    ) -> dict[str, dict[str, Any]]:
        """Fetch fair value for multiple symbols concurrently (chunked)."""
        results: list[dict[str, Any]] = []
        for i in range(0, len(symbols), 5):
            chunk = symbols[i : i + 5]
            tasks = [self.get_fair_value_by_symbol(sym, db) for sym in chunk]
            chunk_results = await asyncio.gather(*tasks)
            results.extend(chunk_results)
        return {res["symbol"]: res for res in results}

    def get_fair_value_result(self, symbol: str, ms_id: str | None, fair_value: float | None) -> FairValueResult:
        """Create a FairValueResult from raw values."""
        return FairValueResult(
            symbol=symbol.upper().strip(),
            morningstar_id=ms_id,
            fair_value=fair_value,
            updated_at=datetime.now(timezone.utc) if fair_value else None,
        )


morningstar_client = MorningstarClient()
