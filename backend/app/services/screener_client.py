"""
ScreenerClient — authenticated HTTP client for screener.in.

Uses rookiepy to extract the sessionid cookie from the local browser profile.
Tries Chrome first, then Firefox as fallback.
All requests are made with httpx, sharing a single async client.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Union

import httpx
import rookiepy
from bs4 import BeautifulSoup, Tag

logger = logging.getLogger(__name__)

BASE_URL = "https://www.screener.in"
SEARCH_URL = f"{BASE_URL}/api/company/search/"
COMPANY_URL = f"{BASE_URL}/company/{{symbol}}/{{mode}}/"
QUICK_RATIOS_URL = f"{BASE_URL}/api/company/{{warehouse_id}}/quick_ratios/"
TRADES_URL = f"{BASE_URL}/trades/company-{{warehouse_id}}/"

_COURTESY_DELAY = 1.0
_screener_lock = asyncio.Lock()

# Stable mapping of symbol → trades company ID.
# These IDs don't change, so no TTL is needed — the dict lives for the
# lifetime of the process and is populated on first access per symbol.
_trades_id_cache: dict[str, str] = {}

# ---------------------------------------------------------------------------
# Raw HTML cache — shared between company and quarterly endpoints so the
# same page is never fetched twice within the TTL window.
# key → (expiry_monotonic, html_text)
# ---------------------------------------------------------------------------
_HTML_CACHE: dict[str, tuple[float, str]] = {}
HTML_CACHE_TTL: float = 15 * 60  # 900 seconds


def _html_cache_get(key: str) -> str | None:
    entry = _HTML_CACHE.get(key)
    if entry and time.monotonic() < entry[0]:
        return entry[1]
    return None


def _html_cache_set(key: str, html: str) -> None:
    _HTML_CACHE[key] = (time.monotonic() + HTML_CACHE_TTL, html)


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


def _parse_number(raw: str | None) -> int | float | None:
    """
    Parse a number string that may contain commas and a leading minus sign.
    Examples: "-3,400" → -3400, "1,04,725" → 104725, "746" → 746, "1,182" → 1182.
    Returns int if the value has no decimal point, float otherwise. None on failure.
    """
    if raw is None:
        return None
    cleaned = raw.replace(",", "").strip()
    if not cleaned:
        return None
    try:
        return int(cleaned) if "." not in cleaned else float(cleaned)
    except ValueError:
        return None


def _parse_warehouse_id(soup: BeautifulSoup) -> str | None:
    """Extract data-warehouse-id from the page (used for quick_ratios API)."""
    tag = soup.select_one("[data-warehouse-id]")
    if tag:
        wid = tag.get("data-warehouse-id")
        return str(wid) if wid else None
    return None


def _parse_trades_company_id(soup: BeautifulSoup) -> str | None:
    """
    Extract the trades company ID from the Trades button on the company page.

    Screener renders a button like:
        <button data-url="/trades/company-2726/" ...>Trades</button>

    This ID is distinct from data-warehouse-id and is required to build the
    trades URL: https://www.screener.in/trades/company-{id}/

    Falls back to a regex search over the full page HTML if the button
    selector does not match (e.g. future markup changes).
    """
    import re as _re

    _TRADES_RE = _re.compile(r"/trades/company-(\d+)/")

    # Primary: look for the button with a matching data-url attribute
    tag = soup.find(attrs={"data-url": _TRADES_RE})
    if tag:
        m = _TRADES_RE.search(str(tag.get("data-url", "")))
        if m:
            return m.group(1)

    # Fallback: search the raw HTML for the pattern
    m = _TRADES_RE.search(str(soup))
    if m:
        return m.group(1)

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


def _parse_all_quarters(
    soup: BeautifulSoup,
) -> dict[str, dict[str, dict[str, str | None]]]:
    """
    Parse the full quarterly results table from the screener.in company page.

    Returns a nested dict keyed by year → month → {metric: value}.

    Period strings on screener follow the format "Sep 2024" or "Mar 2025 TTM".
    The TTM suffix is preserved so callers can distinguish trailing-twelve-month
    figures from discrete quarter-end figures.

    Example output::

        {
            "2023": {
                "Sep": {"Sales": "12345", "Expenses": "9876", ...},
                "Dec": {"Sales": "13000", ...},
            },
            "2024": {
                "Mar": {"Sales": "14000", ...},
                ...
            },
        }
    """
    section = soup.select_one("#quarters")
    if not section:
        return {}

    table = section.select_one("table")
    if not table:
        return {}

    # Collect all period headers (skip the first blank/label column)
    headers = [th.get_text(strip=True) for th in table.select("thead th")]
    periods = headers[1:]  # e.g. ["Sep 2022", "Dec 2022", ..., "Mar 2025 TTM"]

    # Build a mapping: row_label → [value_for_period_0, value_for_period_1, ...]
    row_data: dict[str, list[str | None]] = {}
    for tr in table.select("tbody tr"):
        cells = tr.select("td")
        if not cells:
            continue
        # First cell is the row label; strip trailing " +" used on expandable rows
        label = cells[0].get_text(strip=True).rstrip(" +").strip()
        if not label:
            continue
        values: list[str | None] = []
        for td in cells[1:]:
            raw = td.get_text(strip=True)
            values.append(raw if raw else None)
        row_data[label] = values

    if not row_data or not periods:
        return {}

    # Assemble year → month → {metric: value}
    result: dict[str, dict[str, dict[str, str | None]]] = {}
    for col_idx, period in enumerate(periods):
        # Parse "Sep 2024" or "Mar 2025 TTM" → year, month_label
        parts = period.split()
        if len(parts) < 2:
            # Unexpected format — use the raw period string as both year and month
            year_key = period
            month_key = period
        elif len(parts) == 2:
            month_key, year_key = parts[0], parts[1]
        else:
            # e.g. ["Mar", "2025", "TTM"] → year "2025", month "Mar TTM"
            year_key = parts[1]
            month_key = " ".join([parts[0]] + parts[2:])  # "Mar TTM"

        metrics: dict[str, str | None] = {}
        for label, values in row_data.items():
            metrics[label] = values[col_idx] if col_idx < len(values) else None

        if year_key not in result:
            result[year_key] = {}
        result[year_key][month_key] = metrics

    return result


def _parse_trades_table(
    section: Union[BeautifulSoup, Tag],
    value_column_header: str,
) -> list[dict[str, object]]:
    """
    Parse a single trades table (insider / bulk / block deals).

    Rows are grouped by period header rows (<tr class="stripe sticky-2">).
    For each data row the function extracts:
      - period        : most-recent period label (e.g. "Mar 2025")
      - person        : name of the person / entity
      - category      : role label below the name (e.g. "Designated Person")
      - quantity_raw  : raw text from the quantity cell (e.g. "-3,400")
      - quantity      : parsed integer (negative = sell, positive = buy)
      - direction     : "up" (buy) or "down" (sell) from the td CSS class
      - avg_price_raw : raw text of the average price cell
      - avg_price     : parsed number
      - value_raw     : raw text of the value cell
      - value         : parsed number
      - value_in      : unit extracted from the column header (e.g. "lacs")
      - small_quantity: True when data-small-insider-quantity attr is present

    ``value_column_header`` is the text of the 4th <th> column
    (e.g. "Value in Rs. Lacs") used to derive ``value_in``.
    """
    # Derive value_in from header text, e.g. "Value in Rs. Lacs" → "lacs"
    header_lower = value_column_header.lower()
    if "cr" in header_lower or "crore" in header_lower:
        value_in = "crores"
    elif "lac" in header_lower or "lakh" in header_lower:
        value_in = "lacs"
    else:
        # Fallback: take the last word
        parts = header_lower.split()
        value_in = parts[-1] if parts else header_lower

    table = section.select_one("table.data-table")
    if not table:
        return []

    rows: list[dict[str, object]] = []
    current_period: str = ""

    for tr in table.select("tbody tr"):
        # Period header row
        tr_classes: list[str] = tr.get("class") or []  # type: ignore[assignment]
        if "stripe" in tr_classes and "sticky-2" in tr_classes:
            period_td = tr.select_one("td")
            if period_td:
                current_period = period_td.get_text(strip=True)
            continue

        cells = tr.select("td")
        if len(cells) < 4:
            continue

        # Person name + category
        person_td = cells[0]
        person = person_td.get_text(" ", strip=True)
        # Category is in a <span> within the person cell
        category_tag = person_td.select_one("span")
        category: str = ""
        if category_tag:
            category = category_tag.get_text(strip=True)
            # Remove category from person text
            person = person.replace(category, "").strip()

        # Quantity cell: direction from CSS class, raw text from content
        qty_td = cells[1]
        _raw_cls = qty_td.get("class")
        qty_classes: list[str] = (
            list(_raw_cls)
            if isinstance(_raw_cls, list)
            else ([_raw_cls] if isinstance(_raw_cls, str) else [])
        )
        direction = (
            "up" if "up" in qty_classes else "down" if "down" in qty_classes else None
        )
        quantity_raw = qty_td.get_text(strip=True)
        quantity = _parse_number(quantity_raw)

        avg_price_raw = cells[2].get_text(strip=True)
        avg_price = _parse_number(avg_price_raw)

        value_raw = cells[3].get_text(strip=True)
        value = _parse_number(value_raw)

        small_quantity = tr.get("data-small-insider-quantity") is not None

        rows.append(
            {
                "period": current_period,
                "person": person,
                "category": category,
                "quantity_raw": quantity_raw,
                "quantity": quantity,
                "direction": direction,
                "avg_price_raw": avg_price_raw,
                "avg_price": avg_price,
                "value_raw": value_raw,
                "value": value,
                "value_in": value_in,
                "small_quantity": small_quantity,
            }
        )

    return rows


def _parse_trades_page(warehouse_id: str, html: str) -> dict[str, object]:
    """
    Parse the screener.in /trades/company-{warehouse_id}/ HTML page.

    Returns a dict with keys:
      - warehouse_id   : the requested warehouse ID
      - insider_trades : list of trade records from the Insider Trades tab
      - bulk_deals     : list of trade records from the Bulk Deals tab
      - block_deals    : list of trade records from the Block Deals tab
    """
    soup = BeautifulSoup(html, "lxml")

    result: dict[str, object] = {
        "warehouse_id": warehouse_id,
        "insider_trades": [],
        "bulk_deals": [],
        "block_deals": [],
    }

    tab_map = {
        "trades-insider-trades": "insider_trades",
        "trades-bulk-deals": "bulk_deals",
        "trades-block-deals": "block_deals",
    }

    for tab_id, key in tab_map.items():
        section = soup.find(id=tab_id)
        if section is None:
            continue

        # Derive value_in from the table's 4th column header
        table = section.select_one("table.data-table")
        headers = (
            [th.get_text(strip=True) for th in table.select("thead th")]
            if table
            else []
        )
        value_header = headers[3] if len(headers) > 3 else ""

        result[key] = _parse_trades_table(section, value_header)

    return result


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
            logger.debug("Screener GET %s q=%r", SEARCH_URL, query)
            t0 = time.perf_counter()
            resp = await self._http.get(
                SEARCH_URL,
                params={"q": query, "v": "3", "fts": "1"},
            )
            elapsed_ms = (time.perf_counter() - t0) * 1000
            await asyncio.sleep(_COURTESY_DELAY)

        logger.info(
            "Screener GET %s → %s (%.0fms)", SEARCH_URL, resp.status_code, elapsed_ms
        )
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
                logger.debug("Screener GET %s", url)
                t0 = time.perf_counter()
                resp = await self._http.get(url)
                elapsed_ms = (time.perf_counter() - t0) * 1000
                await asyncio.sleep(_COURTESY_DELAY)

            logger.info(
                "Screener GET %s → %s (%.0fms)", url, resp.status_code, elapsed_ms
            )
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

    async def get_company_html(
        self,
        symbol: str,
        consolidated: bool = True,
    ) -> str:
        """
        Return the raw HTML for the screener.in company page for `symbol`.

        The result is cached in ``_HTML_CACHE`` for ``HTML_CACHE_TTL`` seconds
        (15 minutes). Both :meth:`get_company` and the quarterly-results endpoint
        call this method so the network request is never duplicated within the
        TTL window.

        Raises:
          - RuntimeError  if not authenticated or client not initialised
          - ValueError    if the symbol returns a 404
          - httpx.HTTPStatusError  on other non-2xx responses
        """
        if not self.is_authenticated:
            raise RuntimeError(
                "screener.in session not available. "
                "Please log in at https://www.screener.in in Chrome and restart the backend."
            )
        if self._http is None:
            raise RuntimeError(
                "ScreenerClient not initialised. Call await client.init() first."
            )

        symbol_upper = symbol.upper()
        mode = "consolidated" if consolidated else "standalone"
        html_key = f"screener:html:{symbol_upper}:{'c' if consolidated else 's'}"

        cached_html = _html_cache_get(html_key)
        if cached_html is not None:
            logger.debug("HTML cache hit for %s (%s)", symbol_upper, mode)
            return cached_html

        url = COMPANY_URL.format(symbol=symbol_upper, mode=mode)

        async with _screener_lock:
            logger.debug("Screener GET %s", url)
            t0 = time.perf_counter()
            resp = await self._http.get(url)
            elapsed_ms = (time.perf_counter() - t0) * 1000
            await asyncio.sleep(_COURTESY_DELAY)

        logger.info("Screener GET %s → %s (%.0fms)", url, resp.status_code, elapsed_ms)

        if resp.status_code == 404:
            raise ValueError(f"Symbol '{symbol}' not found on screener.in")

        if resp.status_code == 200 and _is_login_page(resp.text):
            raise RuntimeError(
                "screener.in session appears invalid (got login page). "
                "Please log in at https://www.screener.in in Chrome and restart the backend."
            )

        resp.raise_for_status()

        _html_cache_set(html_key, resp.text)
        return resp.text

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
        html = await self.get_company_html(symbol, consolidated=consolidated)

        symbol_upper = symbol.upper()
        parsed = _parse_company_page(symbol_upper, html)

        warehouse_id = parsed.get("screener_warehouse_id")
        if warehouse_id:
            quick_ratios = await self._fetch_quick_ratios(warehouse_id)
            if quick_ratios:
                existing_ratios = parsed.get("ratios", {})
                merged_ratios = {**existing_ratios, **quick_ratios}
                parsed["ratios"] = merged_ratios

        return parsed

    async def get_trades(self, warehouse_id: str) -> dict[str, Any]:
        """
        Fetch and parse the trades page for a company identified by its
        screener warehouse ID.

        URL: https://www.screener.in/trades/company-{warehouse_id}/

        Returns a dict with:
          - warehouse_id   : the requested warehouse ID
          - insider_trades : list of insider trade records
          - bulk_deals     : list of bulk deal records
          - block_deals    : list of block deal records

        Each record contains:
          person, category, period, quantity_raw, quantity, direction,
          avg_price_raw, avg_price, value_raw, value, value_in, small_quantity

        Raises:
          - RuntimeError           if client not initialised
          - httpx.HTTPStatusError  on non-2xx from screener.in
          - ValueError             if warehouse_id not found (404)
        """
        if self._http is None:
            raise RuntimeError(
                "ScreenerClient not initialised. Call await client.init() first."
            )

        url = TRADES_URL.format(warehouse_id=warehouse_id)

        async with _screener_lock:
            logger.debug("Screener GET %s", url)
            t0 = time.perf_counter()
            resp = await self._http.get(url)
            elapsed_ms = (time.perf_counter() - t0) * 1000
            await asyncio.sleep(_COURTESY_DELAY)

        logger.info("Screener GET %s → %s (%.0fms)", url, resp.status_code, elapsed_ms)
        if resp.status_code == 404:
            raise ValueError(f"Warehouse ID '{warehouse_id}' not found on screener.in")

        resp.raise_for_status()

        return _parse_trades_page(warehouse_id, resp.text)

    async def get_trades_by_symbol(
        self,
        symbol: str,
        consolidated: bool = True,
    ) -> tuple[dict[str, Any], str]:
        """
        Resolve `symbol` to a screener trades company ID via the company page,
        then fetch and return the trades page along with the resolved ID.

        This is a two-request operation (company page + trades page) but the
        company result is not returned — callers who need both should call
        get_company() and get_trades() separately and combine them.

        Returns:
          A tuple of (trades_data, trades_company_id) so the caller can
          persist the resolved ID to avoid future company-page lookups.

        Raises:
          - RuntimeError           if not authenticated or client not initialised
          - ValueError             if symbol or trades ID not found
          - httpx.HTTPStatusError  on non-2xx from screener.in
        """
        if not self.is_authenticated:
            raise RuntimeError(
                "screener.in session not available. "
                "Please log in at https://www.screener.in in Chrome and restart the backend."
            )

        # Fetch company page to extract trades company ID
        mode = "consolidated" if consolidated else "standalone"
        url = COMPANY_URL.format(symbol=symbol.upper(), mode=mode)

        async with _screener_lock:
            logger.debug("Screener GET %s", url)
            t0 = time.perf_counter()
            resp = await self._http.get(url)  # type: ignore[union-attr]
            elapsed_ms = (time.perf_counter() - t0) * 1000
            await asyncio.sleep(_COURTESY_DELAY)

        logger.info("Screener GET %s → %s (%.0fms)", url, resp.status_code, elapsed_ms)
        if resp.status_code == 404:
            raise ValueError(f"Symbol '{symbol}' not found on screener.in")

        if resp.status_code == 200 and _is_login_page(resp.text):
            raise RuntimeError(
                "screener.in session appears invalid (got login page). "
                "Please log in at https://www.screener.in in Chrome and restart the backend."
            )

        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "lxml")
        trades_company_id = _parse_trades_company_id(soup)
        if not trades_company_id:
            raise ValueError(
                f"Could not determine screener trades ID for symbol '{symbol}'. "
                "The company page was fetched but contained no trades button with a company ID."
            )

        trades_data = await self.get_trades(trades_company_id)
        return trades_data, trades_company_id


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
