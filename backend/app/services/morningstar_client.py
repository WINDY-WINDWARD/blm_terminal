"""Morningstar client service for fetching fair values from Morningstar India API."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any

import httpx
import rookiepy
from bs4 import BeautifulSoup
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.stockuniverse import StockUniverse

logger = logging.getLogger(__name__)

MORNINGSTAR_BASE_URL = "https://api-global.morningstar.com"
MORNINGSTAR_PAGE_URL = "https://www.morningstar.in"

TOKEN_CACHE_TTL = 60 * 60
HTML_CACHE_TTL = 15 * 60
ID_CACHE_TTL = 24 * 60 * 60
FAIR_VALUE_CACHE_TTL = 3 * 60 * 60

MAX_CONCURRENT_REQUESTS = 2
REQUEST_DELAY = 1.0
DB_BATCH_SIZE = 50

_token_cache: dict[str, tuple[float, dict[str, str]]] = {}
_token_refresh_lock: asyncio.Lock | None = None
_html_cache: dict[str, tuple[float, str]] = {}
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
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

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
        """Fetch fresh tokens from Morningstar page."""
        cookies = await self._load_browser_cookies()
        if not cookies:
            logger.warning("No browser cookies available for Morningstar")
            return {}

        client = await _get_client()
        url = "https://www.morningstar.in/stocks/0p0000bec4/nse-tata-consultancy-services-ltd/overview.aspx"

        for name, value in cookies.items():
            client.cookies.set(name, value, domain="morningstar.in")

        response = await client.get(url)
        response.raise_for_status()

        return await self._extract_tokens_from_html(response.text)

    async def _extract_tokens_from_html(self, html: str) -> dict[str, str]:
        """Extract accessToken and realTimeToken from meta tags."""
        soup = BeautifulSoup(html, "html.parser")

        access_token = soup.find("meta", {"name": "accessToken"})
        realtime_token = soup.find("meta", {"name": "realTimeToken"})

        tokens = {}
        if access_token:
            tokens["access_token"] = access_token.get("content", "")
        if realtime_token:
            tokens["X-Api-Realtime-E"] = realtime_token.get("content", "")

        _token_cache_set("default", tokens)
        return tokens

    async def _load_browser_cookies(self) -> dict[str, str]:
        """Use rookiepy to get morningstar.in cookies."""
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

        ms_id = await self._search_algolia(symbol)

        if ms_id:
            _id_cache_set(symbol_upper, ms_id)

        return ms_id

    async def _search_algolia(self, symbol: str) -> str | None:
        """Search Morningstar via Algolia to get security ID."""
        client = await _get_client()
        headers = {
            "X-Algolia-Application-Id": "17IQHZWXZW",
            "X-Algolia-API-Key": "be7c37718f927d0137a88a11b69ae419",
            "Content-Type": "application/json",
        }
        body = json.dumps(
            {"query": symbol, "restrictHighlightAndSnippetArrays": True}
        )

        try:
            response = await client.post(
                "https://17iqhzwxzw-dsn.algolia.net/1/indexes/companies/query",
                headers=headers,
                content=body,
            )
            response.raise_for_status()
            data = response.json()

            for hit in data.get("hits", []):
                if hit.get("ticker", "").upper() == symbol.upper():
                    return hit.get("objectID") or hit.get("secId")

            return None
        except Exception as e:
            logger.error(f"Algolia search failed for {symbol}: {e}")
            return None

    async def get_fair_value(self, security_id: str) -> float | None:
        """Fetch fair value for a given Morningstar security ID."""
        try:
            async with self._semaphore:
                tokens = await self._ensure_tokens()
                client = await _get_client()

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

    async def get_fair_value_by_symbol(
        self, symbol: str, db: AsyncSession | None = None
    ) -> dict[str, Any]:
        """Full pipeline: symbol → ID → fair value."""
        symbol_upper = symbol.upper().strip()

        ms_id = await self.resolve_symbol_to_id(symbol_upper, db)
        if not ms_id:
            return {
                "symbol": symbol_upper,
                "morningstarId": None,
                "fairValue": None,
                "updatedAt": None,
            }

        fair_value = await self.get_fair_value(ms_id)

        return {
            "symbol": symbol_upper,
            "morningstarId": ms_id,
            "fairValue": fair_value,
            "updatedAt": datetime.now(timezone.utc).isoformat()
            if fair_value
            else None,
        }


morningstar_client = MorningstarClient()
