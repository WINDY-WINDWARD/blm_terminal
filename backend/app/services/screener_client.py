"""
ScreenerClient — HTTP and browser harvester client for screener.in.
All requests are made with httpx or headless browser harvester, sharing a single async client.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any, Union

import httpx
from bs4 import BeautifulSoup, Tag

from app.services.nse_rate_limiter import throttled_nse_call

logger = logging.getLogger(__name__)

BASE_URL = "https://www.screener.in"
SEARCH_URL = f"{BASE_URL}/api/company/search/"
COMPANY_URL = f"{BASE_URL}/company/{{symbol}}/{{mode}}/"
QUICK_RATIOS_URL = f"{BASE_URL}/api/company/{{warehouse_id}}/quick_ratios/"
TRADES_URL = f"{BASE_URL}/trades/company-{{warehouse_id}}/"

# Trades button URL pattern — see _parse_trades_company_id below.
# Compiled once at import time so the regex cache lives for the process.
_TRADES_RE = re.compile(r"/trades/company-(\d+)/")

# Concurrency, courtesy delay, and circuit breaker for screener.in
# requests are now delegated to ``nse_rate_limiter.throttled_nse_call``
# (audit B.7) so all three external services (NSE, screener.in,
# morningstar.in) share one global concurrency budget.

# Stable mapping of symbol → trades company ID.
# These IDs don't change, so no TTL is needed — the dict lives for the
# lifetime of the process and is populated on first access per symbol.
_trades_id_cache: dict[str, str] = {}

from app.services.cache import screener_html_cache as _HTML_CACHE
from app.services.browser_harvester import harvest_public_html
from app.services.persistent_cache import get_cached_json, set_cached_json


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
        """Create the shared httpx client for anonymous public requests."""
        self._cookies = {}

        self._http = httpx.AsyncClient(
            base_url=BASE_URL,
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
            limits=httpx.Limits(
                max_connections=10,
                max_keepalive_connections=5,
                keepalive_expiry=30.0,
            ),
        )
        logger.info("ScreenerClient initialised (anonymous mode)")

    async def close(self) -> None:
        if self._http:
            await self._http.aclose()

    @property
    def is_authenticated(self) -> bool:
        # Screener uses anonymous + browser harvester fallback; authenticated only when
        # either HTTP succeeds or consent allows harvester. This preserves 503 checks.
        # Keep True for anonymous path but allow callers to check harvester availability.
        return True

    @property
    def is_usable(self) -> bool:
        """True if screener can fulfill a request (anonymous HTTP or consented harvester)."""
        try:
            # Defer import to avoid cycle; check consent without I/O
            from app.services.browser_harvester import _consent_cache_val
            _ = _consent_cache_val  # noqa
        except Exception:
            pass
        return True  # anonymous HTTP is primary; harvester is best-effort fallback

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

        async def _do_search():
            return await self._http.get(
                SEARCH_URL,
                params={"q": query, "v": "3", "fts": "1"},
            )

        logger.debug("Screener GET %s q=%r", SEARCH_URL, query)
        t0 = time.perf_counter()
        resp = await throttled_nse_call(
            "screener", _do_search, is_async_fn=True,
            coalesce_key=f"screener.search:{query}"
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000

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
            async def _do_get():
                return await self._http.get(url)

            logger.debug("Screener GET %s", url)
            t0 = time.perf_counter()
            resp = await throttled_nse_call(
                "screener", _do_get, is_async_fn=True,
                coalesce_key=f"screener.quick_ratios:{warehouse_id}"
            )
            elapsed_ms = (time.perf_counter() - t0) * 1000

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
          - RuntimeError  if client not initialised
          - ValueError    if the symbol returns a 404
          - httpx.HTTPStatusError  on other non-2xx responses
        """
        if not self._http:
            raise RuntimeError("Client not initialised. Use async with ScreenerClient().")

        symbol_upper = symbol.upper()
        mode = "consolidated" if consolidated else "standalone"
        html_key = f"screener:html:{symbol_upper}:{'c' if consolidated else 's'}"

        cached_html = _HTML_CACHE.get(html_key)
        if cached_html is not None:
            logger.debug("HTML cache hit for %s (%s)", symbol_upper, mode)
            return cached_html

        url = COMPANY_URL.format(symbol=symbol_upper, mode=mode)

        async def _do_get():
            return await self._http.get(url)

        logger.debug("Screener GET %s", url)
        t0 = time.perf_counter()
        resp = await throttled_nse_call(
            "screener", _do_get, is_async_fn=True,
            coalesce_key=f"screener.company_html:{symbol_upper}:{mode}"
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000

        logger.info("Screener GET %s → %s (%.0fms)", url, resp.status_code, elapsed_ms)

        if resp.status_code == 404:
            raise ValueError(f"Symbol '{symbol}' not found on screener.in")

        if resp.status_code == 200 and _is_login_page(resp.text):
            logger.info("screener.in returned login page via HTTP; falling back to anonymous browser harvester for %s", url)
            harvester_html = await harvest_public_html(url)
            if harvester_html:
                _HTML_CACHE[html_key] = harvester_html
                return harvester_html
            raise RuntimeError(
                "screener.in requires authentication or advanced extraction consent is disabled."
            )

        resp.raise_for_status()

        _HTML_CACHE[html_key] = resp.text
        return resp.text

    async def get_company(
        self,
        symbol: str,
        consolidated: bool = True,
    ) -> dict[str, Any]:
        """
        Fetch and parse the company page for `symbol`.
        """
        symbol_upper = symbol.upper()
        mode_str = "c" if consolidated else "s"
        cache_key = f"screener:company:{symbol_upper}:{mode_str}"
        cached = await get_cached_json(cache_key)
        if cached:
            if cached.get("ratios", {}).get("piotroski_score") is not None:
                logger.debug(f"Screener company persistent cache hit for {symbol_upper}")
                return cached
            logger.info("Cached screener data lacks piotroski_score, refreshing for %s", symbol_upper)

        try:
            html = await self.get_company_html(symbol, consolidated=consolidated)
            parsed = _parse_company_page(symbol_upper, html)

            warehouse_id = parsed.get("screener_warehouse_id")
            if warehouse_id:
                quick_ratios = await self._fetch_quick_ratios(warehouse_id)
                if quick_ratios:
                    existing_ratios = parsed.get("ratios", {})
                    merged_ratios = {**existing_ratios, **quick_ratios}
                    parsed["ratios"] = merged_ratios

            await set_cached_json(cache_key, parsed, ttl_hours=24)
            return parsed
        except Exception as exc:
            if cached:
                logger.warning(
                    "Failed to refresh screener for %s, falling back to cached: %s",
                    symbol_upper,
                    exc,
                )
                return cached
            raise

    async def get_trades(self, warehouse_id: str) -> dict[str, Any]:
        """
        Fetch and parse the trades page for a company identified by its
        screener warehouse ID.
        """
        cache_key = f"screener:trades:{warehouse_id}"
        cached = await get_cached_json(cache_key)
        if cached:
            logger.debug(f"Screener trades persistent cache hit for {warehouse_id}")
            return cached

        if self._http is None:
            raise RuntimeError(
                "ScreenerClient not initialised. Call await client.init() first."
            )

        url = TRADES_URL.format(warehouse_id=warehouse_id)

        async def _do_get():
            return await self._http.get(url)

        logger.debug("Screener GET %s", url)
        t0 = time.perf_counter()
        resp = await throttled_nse_call(
            "screener", _do_get, is_async_fn=True,
            coalesce_key=f"screener.trades:{warehouse_id}"
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000

        logger.info("Screener GET %s → %s (%.0fms)", url, resp.status_code, elapsed_ms)
        if resp.status_code == 404:
            raise ValueError(f"Warehouse ID '{warehouse_id}' not found on screener.in")

        resp.raise_for_status()

        parsed = _parse_trades_page(warehouse_id, resp.text)
        await set_cached_json(cache_key, parsed, ttl_hours=24)
        return parsed

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

        async def _do_get():
            return await self._http.get(url)

        logger.debug("Screener GET %s", url)
        t0 = time.perf_counter()
        resp = await throttled_nse_call(
            "screener", _do_get, is_async_fn=True,
            coalesce_key=f"screener.company:{symbol.upper()}:{mode}"
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000

        logger.info("Screener GET %s → %s (%.0fms)", url, resp.status_code, elapsed_ms)
        if resp.status_code == 404:
            raise ValueError(f"Symbol '{symbol}' not found on screener.in")

        text = resp.text
        if resp.status_code == 200 and _is_login_page(text):
            logger.info("screener.in returned login page via HTTP; falling back to anonymous browser harvester for %s", url)
            harvester_html = await harvest_public_html(url)
            if harvester_html:
                text = harvester_html
            else:
                raise RuntimeError(
                    "screener.in requires authentication or advanced extraction consent is disabled."
                )

        resp.raise_for_status()

        soup = BeautifulSoup(text, "lxml")
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
    return "<title>Login" in html or 'action="/login/"' in html.lower()


def _parse_shareholding(soup: BeautifulSoup) -> list[dict[str, Any]]:
    """Parse the shareholding pattern table."""
    section = soup.select_one("#shareholding")
    if not section:
        return []

    q_div = section.select_one("#quarterly-shp")
    table = q_div.select_one("table") if q_div else section.select_one("table")
    if not table:
        return []

    headers = [th.get_text(strip=True) for th in table.select("thead th")]
    periods = headers[1:]

    row_map = {}
    target_rows = {"Promoters", "FIIs", "DIIs", "Public", "Government"}

    for tr in table.select("tbody tr"):
        cells = [td.get_text(strip=True) for td in tr.select("td")]
        if not cells:
            continue
        label = cells[0].replace("+", "").strip()
        if label in target_rows:
            vals = []
            for cell in cells[1:]:
                try:
                    vals.append(float(cell.replace("%", "").strip()))
                except ValueError:
                    vals.append(None)
            row_map[label.lower()] = vals

    if not row_map:
        return []

    results = []
    for i, period in enumerate(periods):
        data = {"period": period}
        for k, v in row_map.items():
            data[k] = v[i] if i < len(v) else None
        results.append(data)
    
    return results


def _calculate_piotroski_score(soup: BeautifulSoup) -> float | None:
    """
    Calculate the 9-point Piotroski F-Score deterministically from Screener's
    public financial statement tables (#profit-loss, #balance-sheet, #cash-flow).

    Signals (1 point each):
    1. Positive Net Income: Net Profit_t > 0
    2. Positive Operating Cash Flow: CFO_t > 0 (or fallback to positive operating profit)
    3. Higher ROA: (Net Profit_t / Total Assets_t) > (Net Profit_{t-1} / Total Assets_{t-1})
    4. Accrual / Quality of Earnings: CFO_t > Net Profit_t
    5. Lower Leverage: (Borrowings_t / Total Assets_t) <= (Borrowings_{t-1} / Total Assets_{t-1}) or debt-free
    6. Higher Liquidity: (Other Assets_t / Other Liabilities_t) > (Other Assets_{t-1} / Other Liabilities_{t-1})
    7. No Dilution: Equity Capital_t <= Equity Capital_{t-1}
    8. Higher Margin: OPM%_t > OPM%_{t-1}
    9. Higher Asset Turnover: (Sales_t / Total Assets_t) > (Sales_{t-1} / Total Assets_{t-1})
    """
    def _parse_table(sec_id: str) -> tuple[dict[str, list[float | None]], list[str]]:
        sec = soup.select_one(f"#{sec_id}")
        if not sec:
            return {}, []
        tbl = sec.select_one("table.data-table, table")
        if not tbl:
            return {}, []
        headers = [th.get_text(strip=True) for th in tbl.select("thead th")]
        periods = headers[1:] if len(headers) > 1 else []
        row_map: dict[str, list[float | None]] = {}
        for tr in tbl.select("tbody tr"):
            tds = tr.select("td")
            if not tds:
                continue
            raw_label = tds[0].get_text(" ", strip=True).replace("+", "").strip().lower()
            vals: list[float | None] = []
            for td in tds[1:]:
                txt = td.get_text(strip=True).replace(",", "").replace("%", "")
                if not txt or txt in ("-", "—", "N/A", "None", ""):
                    vals.append(None)
                else:
                    try:
                        vals.append(float(txt))
                    except ValueError:
                        vals.append(None)
            row_map[raw_label] = vals
        return row_map, periods

    pl, pl_periods = _parse_table("profit-loss")
    bs, bs_periods = _parse_table("balance-sheet")
    cf, cf_periods = _parse_table("cash-flow")

    common = [p for p in pl_periods if p != "TTM" and p in bs_periods]
    if len(common) < 2:
        return None

    t_per = common[-1]
    prev_per = common[-2]

    i_pl_t = pl_periods.index(t_per)
    i_pl_prev = pl_periods.index(prev_per)
    i_bs_t = bs_periods.index(t_per)
    i_bs_prev = bs_periods.index(prev_per)
    i_cf_t = cf_periods.index(t_per) if t_per in cf_periods else None

    def _find_val(data: dict[str, list[float | None]], keywords: list[str], idx: int | None) -> float | None:
        if idx is None:
            return None
        for kw in keywords:
            for k, vals in data.items():
                if kw in k:
                    if idx < len(vals):
                        return vals[idx]
        return None

    np_t = _find_val(pl, ["net profit", "pat"], i_pl_t)
    np_prev = _find_val(pl, ["net profit", "pat"], i_pl_prev)
    sales_t = _find_val(pl, ["sales", "revenue"], i_pl_t)
    sales_prev = _find_val(pl, ["sales", "revenue"], i_pl_prev)
    opm_t = _find_val(pl, ["opm"], i_pl_t)
    opm_prev = _find_val(pl, ["opm"], i_pl_prev)

    ta_t = _find_val(bs, ["total assets"], i_bs_t)
    ta_prev = _find_val(bs, ["total assets"], i_bs_prev)
    eq_t = _find_val(bs, ["equity capital", "share capital"], i_bs_t)
    eq_prev = _find_val(bs, ["equity capital", "share capital"], i_bs_prev)
    debt_t = _find_val(bs, ["borrowings", "total debt"], i_bs_t)
    debt_prev = _find_val(bs, ["borrowings", "total debt"], i_bs_prev)
    ca_t = _find_val(bs, ["other assets", "current assets"], i_bs_t)
    ca_prev = _find_val(bs, ["other assets", "current assets"], i_bs_prev)
    cl_t = _find_val(bs, ["other liabilities", "current liabilities"], i_bs_t)
    cl_prev = _find_val(bs, ["other liabilities", "current liabilities"], i_bs_prev)

    cfo_t = _find_val(cf, ["operating activity", "cash from operating", "cfo"], i_cf_t)

    score = 0
    # 1. Net Income > 0
    if np_t is not None and np_t > 0:
        score += 1
    # 2. Operating Cash Flow > 0
    if cfo_t is not None:
        if cfo_t > 0:
            score += 1
    elif np_t is not None and np_t > 0:
        score += 1
    # 3. Higher ROA
    roa_t = (np_t / ta_t) if (np_t is not None and ta_t and ta_t > 0) else None
    roa_prev = (np_prev / ta_prev) if (np_prev is not None and ta_prev and ta_prev > 0) else None
    if roa_t is not None and roa_prev is not None and roa_t > roa_prev:
        score += 1
    # 4. CFO > Net Income
    if cfo_t is not None and np_t is not None:
        if cfo_t > np_t:
            score += 1
    elif roa_t is not None and roa_prev is not None and roa_t > roa_prev:
        score += 1
    # 5. Lower Leverage
    lev_t = (debt_t / ta_t) if (debt_t is not None and ta_t and ta_t > 0) else (debt_t if debt_t is not None else 0.0)
    lev_prev = (debt_prev / ta_prev) if (debt_prev is not None and ta_prev and ta_prev > 0) else (debt_prev if debt_prev is not None else 0.0)
    if (debt_t == 0.0 and debt_prev == 0.0) or (lev_t <= lev_prev):
        score += 1
    # 6. Higher Current Ratio
    cr_t = (ca_t / cl_t) if (ca_t is not None and cl_t and cl_t > 0) else None
    cr_prev = (ca_prev / cl_prev) if (ca_prev is not None and cl_prev and cl_prev > 0) else None
    if cr_t is not None and cr_prev is not None and cr_t > cr_prev:
        score += 1
    # 7. No Dilution
    if eq_t is not None and eq_prev is not None and eq_t <= eq_prev:
        score += 1
    # 8. Higher Margin
    if opm_t is not None and opm_prev is not None and opm_t > opm_prev:
        score += 1
    # 9. Higher Asset Turnover
    turn_t = (sales_t / ta_t) if (sales_t is not None and ta_t and ta_t > 0) else None
    turn_prev = (sales_prev / ta_prev) if (sales_prev is not None and ta_prev and ta_prev > 0) else None
    if turn_t is not None and turn_prev is not None and turn_t > turn_prev:
        score += 1

    return float(score)


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
    shareholding = _parse_shareholding(soup)
    warehouse_id = _parse_warehouse_id(soup)

    piotroski = _calculate_piotroski_score(soup)
    if piotroski is not None:
        ratios["piotroski_score"] = f"{piotroski:.2f}"

    return {
        "symbol": symbol,
        "name": name,
        "screener_warehouse_id": warehouse_id,
        "ratios": ratios,
        "quarters": quarters,
        "shareholding": shareholding,
    }


screener_client = ScreenerClient()
