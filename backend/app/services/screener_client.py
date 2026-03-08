"""
ScreenerClient — authenticated HTTP client for screener.in.

Uses rookiepy to extract the sessionid cookie from the local browser profile.
Tries Chrome first, then Firefox as fallback.
All requests are made with httpx, sharing a single async client.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx
import rookiepy
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

BASE_URL = "https://www.screener.in"
SEARCH_URL = f"{BASE_URL}/api/company/search/"
COMPANY_URL = f"{BASE_URL}/company/{{symbol}}/{{mode}}/"
QUICK_RATIOS_URL = f"{BASE_URL}/api/company/{{warehouse_id}}/quick_ratios/"

_COURTESY_DELAY = 1.0
_screener_lock = asyncio.Lock()


def _extract_cookies(cookies: list[dict[str, Any]]) -> dict[str, str]:
    """Extract sessionid and csrftoken from rookiepy cookie list."""
    result: dict[str, str] = {}
    for cookie in cookies:
        name = cookie.get("name", "")
        if name in ("sessionid", "csrftoken"):
            result[name] = cookie.get("value", "")
    return result


def _get_browser_cookies() -> dict[str, str]:
    """
    Try to extract sessionid and csrftoken for screener.in from browser profiles.
    Attempts Chrome first, then Firefox as fallback.
    Returns empty dict if no cookies found.
    """
    browsers = ["chrome", "firefox"]

    for browser_name in browsers:
        try:
            func = getattr(rookiepy, browser_name, None)
            if func is None:
                continue
            raw: list[dict[str, Any]] = func(["screener.in"])
            if raw:
                cookies = _extract_cookies(raw)
                if cookies.get("sessionid"):
                    logger.info("Found screener.in cookies in %s", browser_name)
                    return cookies
                logger.debug(
                    "No sessionid in %s cookies, trying next browser", browser_name
                )
        except Exception as exc:
            logger.debug("Failed to read cookies from %s: %s", browser_name, exc)
            continue

    logger.warning(
        "No screener.in session found in Chrome or Firefox. "
        "Company fundamentals endpoints will return 503 until you log in."
    )
    return {}


def _clean_value(value: str | None) -> str | None:
    """Clean up parsed values: remove ₹ symbol, normalize spacing."""
    if value is None:
        return None
    return value.replace("₹", "").replace("\u20b9", "").strip()


def _parse_warehouse_id(soup: BeautifulSoup) -> str | None:
    """Extract data-warehouse-id from the page."""
    tag = soup.select_one("[data-warehouse-id]")
    if tag:
        wid = tag.get("data-warehouse-id")
        return str(wid) if wid else None
    return None


def _parse_quick_ratios(html: str) -> dict[str, str | None]:
    """
    Parse the quick_ratios API response.
    Returns a dict mapping ratio names to values.
    """
    soup = BeautifulSoup(html, "lxml")
    result: dict[str, str | None] = {}

    for li in soup.select("li"):
        name_tag = li.select_one(".name")
        value_tag = li.select_one(".number, .value")
        if not name_tag or not value_tag:
            continue
        name = name_tag.get_text(strip=True).lower().replace(" ", "_")
        value = _clean_value(value_tag.get_text(strip=True))
        if name:
            result[name] = value

    return result


def _parse_name(soup: BeautifulSoup) -> str:
    tag = soup.select_one("h1.show-from-tablet-landscape")
    if tag:
        return tag.get_text(strip=True)
    tag = soup.select_one("h1")
    return tag.get_text(strip=True) if tag else ""


def _parse_ratios(soup: BeautifulSoup) -> dict[str, str | None]:
    """
    Screener renders ratios inside <li> elements under #top.
    Each <li> has a <span class="name"> label and a <span class="number"> value.
    """
    mapping = {
        "Market Cap": "market_cap",
        "Current Price": "price",
        "High / Low": "high_low_52w",
        "Stock P/E": "pe",
        "Book Value": "book_value",
        "Dividend Yield": "dividend_yield",
        "ROCE": "roce",
        "ROE": "roe",
        "Face Value": "face_value",
    }

    result: dict[str, str | None] = {v: None for v in mapping.values()}

    for li in soup.select("#top li"):
        name_tag = li.select_one(".name")
        value_tag = li.select_one(".number, .value")
        if not name_tag or not value_tag:
            continue
        label = name_tag.get_text(strip=True)
        value = _clean_value(value_tag.get_text(" ", strip=True))
        key = mapping.get(label)
        if key:
            result[key] = value

    high_low = result.get("high_low_52w")
    if high_low:
        parts = high_low.split("/")
        result["high_52w"] = _clean_value(parts[0]) if len(parts) > 0 else None
        result["low_52w"] = _clean_value(parts[1]) if len(parts) > 1 else None
    else:
        result["high_52w"] = None
        result["low_52w"] = None

    del result["high_low_52w"]
    return result


def _parse_quarters(soup: BeautifulSoup) -> list[dict[str, str | None]]:
    """Parse the quarterly results table."""
    section = soup.select_one("#quarters")
    if not section:
        return []

    table = section.select_one("table")
    if not table:
        return []

    headers = [th.get_text(strip=True) for th in table.select("thead th")]

    row_map: dict[str, list[str]] = {}
    target_rows = {"Sales": "sales", "Net Profit": "net_profit", "EPS in Rs": "eps"}

    for tr in table.select("tbody tr"):
        cells = [td.get_text(strip=True) for td in tr.select("td")]
        if not cells:
            continue
        label = cells[0].rstrip(" +")
        for key, field in target_rows.items():
            if label.startswith(key):
                row_map[field] = cells[1:]
                break

    if not row_map:
        return []

    periods = headers[1:]
    n = len(periods)
    start = max(0, n - 4)
    periods = periods[start:]

    quarters = []
    for i, period in enumerate(periods):
        idx = start + i
        quarters.append(
            {
                "period": period,
                "sales": row_map.get("sales", [])[idx]
                if idx < len(row_map.get("sales", []))
                else None,
                "net_profit": row_map.get("net_profit", [])[idx]
                if idx < len(row_map.get("net_profit", []))
                else None,
                "eps": row_map.get("eps", [])[idx]
                if idx < len(row_map.get("eps", []))
                else None,
            }
        )

    return list(reversed(quarters))


class ScreenerClient:
    """
    Async client for screener.in. Instantiate once at app startup.

    Usage:
        client = ScreenerClient()
        await client.init()          # loads cookies; call in FastAPI lifespan
        results = await client.search("reliance")
        data = await client.get_company("RELIANCE")
        await client.close()         # call in lifespan shutdown
    """

    def __init__(self) -> None:
        self._cookies: dict[str, str] = {}
        self._http: httpx.AsyncClient | None = None

    async def init(self) -> None:
        """Load browser cookies (Chrome → Firefox) and create the shared httpx client."""
        self._cookies = _get_browser_cookies()

        self._http = httpx.AsyncClient(
            base_url=BASE_URL,
            cookies=self._cookies,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                "Referer": BASE_URL + "/",
            },
            timeout=15.0,
            follow_redirects=True,
        )
        logger.info(
            "ScreenerClient initialised (authenticated=%s)",
            bool(self._cookies.get("sessionid")),
        )

    async def close(self) -> None:
        if self._http:
            await self._http.aclose()

    @property
    def is_authenticated(self) -> bool:
        return bool(self._cookies.get("sessionid"))

    async def search(self, query: str) -> list[dict[str, Any]]:
        """
        Search for companies by name or symbol.
        This endpoint is public — no login required.

        Returns a list of dicts: [{ id, name, url }, ...]
        """
        if self._http is None:
            raise RuntimeError(
                "ScreenerClient not initialised. Call await client.init() first."
            )

        async with _screener_lock:
            resp = await self._http.get(
                SEARCH_URL,
                params={"q": query, "v": "3", "fts": "1"},
            )
            await asyncio.sleep(_COURTESY_DELAY)

        resp.raise_for_status()
        return resp.json()

    async def _fetch_quick_ratios(self, warehouse_id: str) -> dict[str, str | None]:
        """
        Fetch supplemental ratios from the quick_ratios API.
        Returns a dict of ratio_name -> value mappings.
        """
        if not self._http:
            return {}

        url = QUICK_RATIOS_URL.format(warehouse_id=warehouse_id)

        try:
            async with _screener_lock:
                resp = await self._http.get(url)
                await asyncio.sleep(_COURTESY_DELAY)

            if resp.status_code != 200:
                logger.warning(
                    "quick_ratios API returned %s for warehouse_id=%s",
                    resp.status_code,
                    warehouse_id,
                )
                return {}

            return _parse_quick_ratios(resp.text)
        except Exception as exc:
            logger.warning(
                "Failed to fetch quick_ratios for warehouse_id=%s: %s",
                warehouse_id,
                exc,
            )
            return {}

    async def get_company(
        self,
        symbol: str,
        consolidated: bool = True,
    ) -> dict[str, Any]:
        """
        Fetch and parse the company page for `symbol`.
        Requires a valid sessionid cookie.

        Returns a dict with:
          - symbol, name
          - screener_warehouse_id
          - ratios: { market_cap, price, high_52w, low_52w, pe, book_value,
                      dividend_yield, roce, roe, face_value, ... } (includes quick_ratios)
          - quarters: list of { period, sales, net_profit, eps } (last 4 quarters)

        Raises:
          - RuntimeError  if not authenticated
          - httpx.HTTPStatusError  on non-2xx from screener.in
          - ValueError  if symbol is not found (404 from screener.in)
        """
        if not self.is_authenticated:
            raise RuntimeError(
                "screener.in session not available. "
                "Please log in at https://www.screener.in in Chrome and restart the backend."
            )
        if self._http is None:
            raise RuntimeError(
                "Screener. Call await clientClient not initialised.init() first."
            )

        mode = "consolidated" if consolidated else "standalone"
        url = COMPANY_URL.format(symbol=symbol.upper(), mode=mode)

        async with _screener_lock:
            resp = await self._http.get(url)
            await asyncio.sleep(_COURTESY_DELAY)

        if resp.status_code == 404:
            raise ValueError(f"Symbol '{symbol}' not found on screener.in")

        if resp.status_code == 200 and _is_login_page(resp.text):
            raise RuntimeError(
                "screener.in session appears invalid (got login page). "
                "Please log in at https://www.screener.in in Chrome and restart the backend."
            )

        resp.raise_for_status()

        symbol_upper = symbol.upper()
        parsed = _parse_company_page(symbol_upper, resp.text)

        warehouse_id = parsed.get("screener_warehouse_id")
        if warehouse_id:
            quick_ratios = await self._fetch_quick_ratios(warehouse_id)
            if quick_ratios:
                existing_ratios = parsed.get("ratios", {})
                merged_ratios = {**existing_ratios, **quick_ratios}
                parsed["ratios"] = merged_ratios

        return parsed


def _is_login_page(html: str) -> bool:
    """Detect if the response is a login page instead of the company page."""
    return "/login/" in html or 'action="/login/"' in html.lower()


def _parse_company_page(symbol: str, html: str) -> dict[str, Any]:
    """
    Parse the screener.in company HTML page.

    Key sections targeted:
    - <h1> inside #top: company name
    - <ul class="company-ratios"> or #top .company-ratios: key ratio <li> items
    - Table#quarters (or section#quarters): quarterly P&L rows
    """
    soup = BeautifulSoup(html, "lxml")

    name = _parse_name(soup)
    ratios = _parse_ratios(soup)
    quarters = _parse_quarters(soup)
    warehouse_id = _parse_warehouse_id(soup)

    return {
        "symbol": symbol,
        "name": name,
        "screener_warehouse_id": warehouse_id,
        "ratios": ratios,
        "quarters": quarters,
    }


screener_client = ScreenerClient()
