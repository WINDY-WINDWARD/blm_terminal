# Screener.in Integration

## Overview

This document describes how to implement a screener.in data endpoint in the FastAPI analytics
backend. Screener.in has no public REST API — access is session-authenticated via Django cookies
obtained through Google OAuth or email login. The approach is to read the `sessionid` cookie
directly from the user's Chrome browser profile using `rookiepy`, then use it to make authenticated
HTTP requests.

The existing `/api/py/[...path]` catch-all proxy in Next.js (`src/app/api/py/[...path]/route.ts`)
already forwards all requests to the FastAPI backend, so **no Next.js changes are required**.

---

## Auth: How It Works

Screener.in uses Django session cookies. There is no API key or OAuth token exposed to third
parties. The full flow is:

1. User logs in via `https://www.screener.in/login/google/` in Chrome on Windows.
2. Django sets a `sessionid` cookie (and a `csrftoken`) scoped to `screener.in`.
3. On FastAPI startup, `rookiepy.chrome(["screener.in"])` reads the Chrome cookie store
   (encrypted via Windows DPAPI, which rookiepy decrypts natively — no extra setup needed).
4. The extracted `sessionid` value is stored in memory and attached to all subsequent
   `httpx` requests as a cookie header.
5. Cookies expire after some period of inactivity; restart the FastAPI server to refresh them.

**Constraint: Chrome on Windows only.** The implementation calls `rookiepy.chrome()` exclusively.
It does not fall back to other browsers.

---

## Files to Create / Modify

### 1. `backend/pyproject.toml` — add dependency

```toml
dependencies = [
    # ... existing deps ...
    "rookiepy>=0.5.6",
]
```

### 2. `backend/app/services/screener_client.py` — fill the empty placeholder

```python
"""
ScreenerClient — authenticated HTTP client for screener.in.

Uses rookiepy to extract the sessionid cookie from the local Chrome profile.
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

# Courtesy delay between requests to screener.in (seconds)
_COURTESY_DELAY = 1.0
_screener_lock = asyncio.Lock()


def _get_chrome_cookies() -> dict[str, str]:
    """
    Extract sessionid and csrftoken for screener.in from the local Chrome profile.
    Returns an empty dict if Chrome is not available or no matching cookies are found.
    Raises RuntimeError with a clear message if rookiepy raises unexpectedly.
    """
    try:
        raw: list[dict[str, Any]] = rookiepy.chrome(["screener.in"])
    except Exception as exc:
        raise RuntimeError(
            f"rookiepy failed to read Chrome cookies: {exc}. "
            "Ensure Chrome is installed and you have logged in to screener.in."
        ) from exc

    cookies: dict[str, str] = {}
    for cookie in raw:
        name = cookie.get("name", "")
        if name in ("sessionid", "csrftoken"):
            cookies[name] = cookie.get("value", "")
    return cookies


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
        """Load Chrome cookies and create the shared httpx client."""
        try:
            self._cookies = _get_chrome_cookies()
            if "sessionid" not in self._cookies:
                logger.warning(
                    "screener.in sessionid not found in Chrome cookies. "
                    "Company fundamentals endpoints will return 503 until you log in."
                )
        except RuntimeError as exc:
            logger.warning(str(exc))
            self._cookies = {}

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
        logger.info("ScreenerClient initialised (authenticated=%s)", bool(self._cookies.get("sessionid")))

    async def close(self) -> None:
        if self._http:
            await self._http.aclose()

    @property
    def is_authenticated(self) -> bool:
        return bool(self._cookies.get("sessionid"))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def search(self, query: str) -> list[dict[str, Any]]:
        """
        Search for companies by name or symbol.
        This endpoint is public — no login required.

        Returns a list of dicts: [{ id, name, url }, ...]
        """
        if self._http is None:
            raise RuntimeError("ScreenerClient not initialised. Call await client.init() first.")

        async with _screener_lock:
            resp = await self._http.get(
                SEARCH_URL,
                params={"q": query, "v": "3", "fts": "1"},
            )
            await asyncio.sleep(_COURTESY_DELAY)

        resp.raise_for_status()
        return resp.json()

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
          - ratios: { market_cap, price, high_52w, low_52w, pe, book_value,
                      dividend_yield, roce, roe, face_value }
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
            raise RuntimeError("ScreenerClient not initialised. Call await client.init() first.")

        mode = "consolidated" if consolidated else "standalone"
        url = COMPANY_URL.format(symbol=symbol.upper(), mode=mode)

        async with _screener_lock:
            resp = await self._http.get(url)
            await asyncio.sleep(_COURTESY_DELAY)

        if resp.status_code == 404:
            raise ValueError(f"Symbol '{symbol}' not found on screener.in")
        resp.raise_for_status()

        return _parse_company_page(symbol.upper(), resp.text)


# ------------------------------------------------------------------
# HTML parsing helpers
# ------------------------------------------------------------------

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

    return {
        "symbol": symbol,
        "name": name,
        "ratios": ratios,
        "quarters": quarters,
    }


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

    Example markup:
        <li>
          <span class="name">Market Cap</span>
          <span class="number">₹ 19,01,041 Cr.</span>
        </li>
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
        value = value_tag.get_text(" ", strip=True)
        key = mapping.get(label)
        if key:
            result[key] = value

    # Split "High / Low" into separate fields if present
    if result.get("high_low_52w"):
        parts = result["high_low_52w"].split("/")
        result["high_52w"] = parts[0].strip() if len(parts) > 0 else None
        result["low_52w"] = parts[1].strip() if len(parts) > 1 else None
    else:
        result["high_52w"] = None
        result["low_52w"] = None

    del result["high_low_52w"]
    return result


def _parse_quarters(soup: BeautifulSoup) -> list[dict[str, str | None]]:
    """
    Parse the quarterly results table. Screener renders it as:
        <section id="quarters">
          <table>
            <thead><tr><th/><th>Sep 2024</th>...</tr></thead>
            <tbody>
              <tr data-row-type="Sales"><td>Sales +</td><td>231,535</td>...</tr>
              <tr data-row-type="Net Profit"><td>Net Profit +</td><td>19,323</td>...</tr>
              <tr data-row-type="EPS in Rs"><td>EPS in Rs</td><td>12.24</td>...</tr>
            </tbody>
          </table>
        </section>

    Returns last 4 quarters (most recent first) as:
        [{ "period": "Dec 2024", "sales": "239,986", "net_profit": "21,930", "eps": "13.70" }, ...]
    """
    section = soup.select_one("#quarters")
    if not section:
        return []

    table = section.select_one("table")
    if not table:
        return []

    # Parse column headers (periods)
    headers = [th.get_text(strip=True) for th in table.select("thead th")]
    # headers[0] is the row-label column; headers[1:] are periods

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

    # Align with period headers — take last 4 columns
    periods = headers[1:]
    n = len(periods)
    start = max(0, n - 4)
    periods = periods[start:]

    quarters = []
    for i, period in enumerate(periods):
        idx = start + i
        quarters.append({
            "period": period,
            "sales": row_map.get("sales", [])[idx] if idx < len(row_map.get("sales", [])) else None,
            "net_profit": row_map.get("net_profit", [])[idx] if idx < len(row_map.get("net_profit", [])) else None,
            "eps": row_map.get("eps", [])[idx] if idx < len(row_map.get("eps", [])) else None,
        })

    return list(reversed(quarters))  # most recent first


# Singleton — imported by routers and main lifespan
screener_client = ScreenerClient()
```

### 3. `backend/app/routers/screener.py` — new router

```python
"""
Screener.in proxy endpoints.
Prefix: /api  →  effective routes: /api/screener/search, /api/screener/company/{symbol}
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Query

from app.services.screener_client import screener_client

logger = logging.getLogger(__name__)
router = APIRouter(tags=["screener"])

# In-process cache reusing the same pattern as nonpersistence.py
import time
_cache: dict[str, tuple[float, object]] = {}
SEARCH_TTL = 60        # seconds
COMPANY_TTL = 15 * 60  # 15 minutes


def _cache_get(key: str) -> object | None:
    entry = _cache.get(key)
    if entry and time.monotonic() < entry[0]:
        return entry[1]
    return None


def _cache_set(key: str, value: object, ttl: float) -> None:
    _cache[key] = (time.monotonic() + ttl, value)


@router.get("/screener/search")
async def screener_search(
    q: str = Query(..., min_length=1, description="Company name or symbol fragment"),
) -> list[dict[str, Any]]:
    """
    Search screener.in for matching companies.
    Public endpoint — no login required.
    """
    cache_key = f"screener:search:{q.lower()}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached  # type: ignore[return-value]

    try:
        results = await screener_client.search(q)
    except httpx.HTTPStatusError as exc:
        logger.error("screener.in search failed: %s", exc)
        raise HTTPException(status_code=502, detail="screener.in request failed")
    except Exception as exc:
        logger.error("screener.in search error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    _cache_set(cache_key, results, SEARCH_TTL)
    return results


@router.get("/screener/company/{symbol}")
async def screener_company(
    symbol: str,
    consolidated: bool = True,
) -> dict[str, Any]:
    """
    Fetch parsed fundamentals for a company from screener.in.
    Requires a valid Chrome sessionid cookie for screener.in.

    Returns: symbol, name, ratios (P/E, ROCE, ROE, etc.), quarters (last 4).
    """
    if not screener_client.is_authenticated:
        raise HTTPException(
            status_code=503,
            detail=(
                "screener.in session not available. "
                "Log in at https://www.screener.in in Chrome, then restart the backend."
            ),
        )

    cache_key = f"screener:company:{symbol.upper()}:{'c' if consolidated else 's'}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached  # type: ignore[return-value]

    try:
        data = await screener_client.get_company(symbol, consolidated=consolidated)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except httpx.HTTPStatusError as exc:
        logger.error("screener.in company fetch failed: %s", exc)
        raise HTTPException(status_code=502, detail="screener.in request failed")
    except Exception as exc:
        logger.error("screener.in company error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    _cache_set(cache_key, data, COMPANY_TTL)
    return data
```

### 4. `backend/main.py` — register the router

In the router registration block (around line 120–130), add:

```python
from app.routers.screener import router as screener_router

# existing registrations ...
app.include_router(screener_router, prefix="/api")
```

In the lifespan startup block, add initialisation and shutdown for the client:

```python
from app.services.screener_client import screener_client

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ... existing startup code ...
    await screener_client.init()   # <-- add this

    yield

    # ... existing shutdown code ...
    await screener_client.close()  # <-- add this
```

---

## API Reference

### `GET /api/screener/search?q={query}`

No authentication. Cached 60 seconds.

**Response** (array):
```json
[
  { "id": 2726, "name": "Reliance Industries Ltd", "url": "/company/RELIANCE/consolidated/" },
  { "id": 2729, "name": "Reliance Power Ltd",      "url": "/company/RPOWER/consolidated/"   }
]
```

---

### `GET /api/screener/company/{symbol}?consolidated=true`

Requires Chrome sessionid cookie for screener.in. Cached 15 minutes.

**Response**:
```json
{
  "symbol": "RELIANCE",
  "name": "Reliance Industries Ltd",
  "ratios": {
    "market_cap":       "₹ 19,01,041 Cr.",
    "price":            "₹ 1,405",
    "high_52w":         "₹ 1,612",
    "low_52w":          "1,115",
    "pe":               "24.8",
    "book_value":       "₹ 648",
    "dividend_yield":   "0.39 %",
    "roce":             "9.69 %",
    "roe":              "8.40 %",
    "face_value":       "₹ 10.0"
  },
  "quarters": [
    { "period": "Dec 2024", "sales": "239,986", "net_profit": "21,930", "eps": "13.70" },
    { "period": "Sep 2024", "sales": "231,535", "net_profit": "19,323", "eps": "12.24" },
    { "period": "Jun 2024", "sales": "231,784", "net_profit": "17,445", "eps": "11.19" },
    { "period": "Mar 2024", "sales": "236,533", "net_profit": "21,243", "eps": "14.01" }
  ]
}
```

**Error responses**:

| HTTP | Condition |
|------|-----------|
| 404  | Symbol not found on screener.in |
| 503  | No valid sessionid cookie — log in via Chrome and restart the backend |
| 502  | screener.in returned a non-2xx response |

---

## Accessing From the Next.js Frontend

No new Next.js proxy routes are needed. The existing catch-all at
`src/app/api/py/[...path]/route.ts` already forwards these:

```ts
// Search
const res = await fetch(`/api/py/screener/search?q=${query}`)

// Company fundamentals
const res = await fetch(`/api/py/screener/company/${symbol}?consolidated=true`)
```

---

## Setup Checklist

1. **Install dependencies** (from `backend/`):
   ```bash
   pip install -e ".[dev]"
   # or just: pip install rookiepy
   ```

2. **Log in to screener.in in Chrome** (Google or email — either works).
   Chrome must be closed or at least the profile must be accessible when the backend starts.
   On Windows, DPAPI decryption is done in the context of the logged-in Windows user,
   so run the backend as the same Windows user who owns the Chrome profile.

3. **Start the backend**:
   ```bash
   uvicorn main:app --reload --port 8000
   ```
   On startup you will see one of:
   - `ScreenerClient initialised (authenticated=True)` — cookies loaded successfully
   - `ScreenerClient initialised (authenticated=False)` — no cookies found; company endpoint returns 503

4. **Test**:
   ```bash
   curl "http://localhost:8000/api/screener/search?q=reliance"
   curl "http://localhost:8000/api/screener/company/RELIANCE"
   ```

---

## Notes and Constraints

- **Session expiry**: screener.in sessions persist for a long time but will eventually expire.
  When requests start returning HTML login pages instead of data, restart the FastAPI server
  to re-read fresh cookies from Chrome.

- **Rate limiting**: All requests share a single `asyncio.Lock` with a 1-second courtesy delay
  between calls, matching the pattern used in `nonpersistence.py` for NSE requests.

- **BeautifulSoup selectors**: Screener.in occasionally redesigns its HTML. The selectors in
  `_parse_ratios` and `_parse_quarters` target stable IDs (`#top`, `#quarters`) and class names
  (`.name`, `.number`). If parsing breaks after a site update, these functions are the first
  place to investigate.

- **`consolidated` vs `standalone`**: Pass `?consolidated=false` for standalone financials.
  Most companies only have consolidated; standalone is relevant for holding companies.

- **`screener_client.py` was an empty placeholder** (`0 bytes`) committed as
  `backend/app/services/screener_client.py`. The implementation above fills it.
