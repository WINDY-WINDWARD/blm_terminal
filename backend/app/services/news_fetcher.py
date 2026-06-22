"""News fetcher service for MoneyControl global and company-specific news."""

import asyncio
import logging
import random
import re
import ssl
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import select, update as sa_update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

# Pre-create one SSL context at import time (module level, single-threaded).
# ssl.SSLContext.__new__ is NOT thread-safe in Python 3.13 — constructing
# httpx.AsyncClient concurrently from multiple threads (e.g. background workers
# each spinning up their own event loop) causes a segfault.  Reusing a single
# pre-built context eliminates that race entirely.
_SSL_CONTEXT = ssl.create_default_context()

from app.models.news import NewsArticle
from app.models.stockuniverse import StockUniverse
from app.services.nlp_service import analyze_article_dict


@dataclass
class _PageResult:
    """Minimal wrapper returned by _get_page so callers are path-agnostic."""

    text: str


class _ArticleNotFound(Exception):
    """Raised by _get_page when the server returns 404 — caller should skip the article."""

logger = logging.getLogger(__name__)

MONEYCONTROL_BASE_URL = "https://www.moneycontrol.com"
MONEYCONTROL_NEWS_ALL = f"{MONEYCONTROL_BASE_URL}/news/news-all"
SOURCE_NAME = "moneycontrol_global"
SOURCE_NAME_COMPANY = "moneycontrol_company"

# Fallback URL map for known symbols — used when DB lookup and autocomplete API fail
# These URLs are verified via MC autocomplete API
_FALLBACK_MC_URL_MAP: dict[str, str] = {
    "RELIANCE": "https://www.moneycontrol.com/india/stockpricequote/refineries/relianceindustries/RI",
    "INFY": "https://www.moneycontrol.com/india/stockpricequote/computers-software/infosys/IT",
    "TCS": "https://www.moneycontrol.com/india/stockpricequote/computers-software/tataconsultancyservices/TCS",
    "HDFCBANK": "https://www.moneycontrol.com/india/stockpricequote/banks-private-sector/hdfcbank/HDF01",
    "ICICIBANK": "https://www.moneycontrol.com/india/stockpricequote/banks-private-sector/icicibank/ICI",
    "HINDUNILVR": "https://www.moneycontrol.com/india/stockpricequote/fmcg-personal-care/hindustanunilever/HLU",
    "ITC": "https://www.moneycontrol.com/india/stockpricequote/cigarettes/itc/ITC",
    "SBIN": "https://www.moneycontrol.com/india/stockpricequote/banks-public-sector/statebankindia/SBI",
    "BAJFINANCE": "https://www.moneycontrol.com/india/stockpricequote/finance-nbfc/bajajfinance/BAF",
    "MARUTI": "https://www.moneycontrol.com/india/stockpricequote/automobiles-maruti-suzuki/MSIL",
    "TATASTEEL": "https://www.moneycontrol.com/india/stockpricequote/metals-minerals/tatasteel/TS",
    "WIPRO": "https://www.moneycontrol.com/india/stockpricequote/computers-software/wipro/WRI",
}

# Matches only real article URLs: end with -NNNNNN.html (6+ digits)
ARTICLE_PATTERN = re.compile(r"-\d{6,}\.html$")

CONCURRENCY_LIMIT = 3
REQUEST_DELAY = 1.0
ARTICLE_BATCH_SIZE = 10

# ── Realistic Browser Presets (fully consistent header sets) ──────────────
# Chrome has ~65% global market share — weight it higher
BROWSER_WEIGHTS = {
    "chrome_windows": 25,
    "chrome_mac": 20,
    "chrome_linux": 20,
    "firefox_windows": 15,
    "firefox_linux": 20,
}

BROWSER_PRESETS = [
    # Chrome on Windows 11
    {
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "sec-ch-ua": '"Not A;Brand";v="99", "Chromium";v="147", "Google Chrome";v="147"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
    },
    # Chrome on macOS
    {
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "sec-ch-ua": '"Not A;Brand";v="99", "Chromium";v="147", "Google Chrome";v="147"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"macOS"',
    },
    # Chrome on Linux
    {
        "user_agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "sec-ch-ua": '"Not A;Brand";v="99", "Chromium";v="147", "Google Chrome";v="147"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Linux"',
    },
    # Firefox on Windows
    {
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:149.0) Gecko/20100101 Firefox/149.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        # NOTE: Firefox does NOT send sec-ch-ua* headers
    },
    # Firefox on Linux
    {
        "user_agent": "Mozilla/5.0 (X11; Linux x86_64; rv:149.0) Gecko/20100101 Firefox/149.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
    },
]


def get_weighted_preset() -> dict:
    """Return a random browser preset weighted by real market share."""
    presets = list(BROWSER_WEIGHTS.keys())
    weights = list(BROWSER_WEIGHTS.values())
    chosen = random.choices(presets, weights=weights, k=1)[0]
    idx = list(BROWSER_WEIGHTS.keys()).index(chosen)
    return BROWSER_PRESETS[idx].copy()


def adjust_headers_for_request(headers: dict, url: str, referer: str | None = None) -> dict:
    """Adjust Sec-Fetch-* headers based on request type.
    
    Real browsers send different values:
    - Initial navigation: Sec-Fetch-Site: none
    - Same-origin XHR: Sec-Fetch-Site: same-origin, Sec-Fetch-Mode: cors
    - Cross-origin: Sec-Fetch-Site: cross-site
    """
    result = headers.copy()
    
    # Determine request type based on URL
    is_article = "/news/" in url and ARTICLE_PATTERN.search(url)
    is_company = "/stockpricequote/" in url
    is_listing = "/news-all" in url or "/page-" in url
    
    if is_article or is_company:
        # These are typically navigations from listing pages
        if referer and "moneycontrol.com" in referer:
            result["Sec-Fetch-Site"] = "same-origin"
            result["Sec-Fetch-Mode"] = "navigate"
            result["Sec-Fetch-Dest"] = "document"
        else:
            result["Sec-Fetch-Site"] = "none"
    elif is_listing:
        # Top-level navigation
        result["Sec-Fetch-Site"] = "none"
        result["Sec-Fetch-Mode"] = "navigate"
        result["Sec-Fetch-Dest"] = "document"
    
    if referer:
        result["Referer"] = referer
    elif "Referer" in result:
        # Remove static referer for non-initial requests
        del result["Referer"]
    
    return result


def _build_headers(url: str | None = None, referer: str | None = None) -> dict:
    """Build fully realistic, browser-consistent request headers."""
    preset = get_weighted_preset()
    
    # Adjust Sec-Fetch-* based on request type
    if url:
        preset = adjust_headers_for_request(preset, url, referer)
    
    return preset


class NewsFetcher:
    """Service to fetch and parse news articles from MoneyControl."""

    def __init__(self) -> None:
        self._semaphore: asyncio.Semaphore | None = None
        self._semaphore_loop: asyncio.AbstractEventLoop | None = None
        self._headers = _build_headers()
        self._cookies_loaded = False
        self._client: httpx.AsyncClient | None = None
        self._client_loop: asyncio.AbstractEventLoop | None = None
        self._init_lock: asyncio.Lock | None = None
        self._init_lock_loop: asyncio.AbstractEventLoop | None = None

    def _get_init_lock(self) -> asyncio.Lock:
        """Lazily create the init lock bound to the current event loop."""
        current_loop = asyncio.get_running_loop()
        if self._init_lock is None or self._init_lock_loop is not current_loop:
            self._init_lock = asyncio.Lock()
            self._init_lock_loop = current_loop
        return self._init_lock

    def _get_semaphore(self) -> asyncio.Semaphore:
        """Lazily create Semaphore in the current event loop to avoid loop-mismatch errors."""
        current_loop = asyncio.get_running_loop()
        if self._semaphore is None or self._semaphore_loop is not current_loop:
            self._semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)
            self._semaphore_loop = current_loop
        return self._semaphore

    async def init(self, reload_cookies: bool = True) -> None:
        """Initialize persistent httpx client with cookies.

        Safe to call multiple times — the httpx client is only (re)created when
        missing or when the event loop has changed.
        Set reload_cookies=False to skip cookie loading (for retries).
        """
        async with self._get_init_lock():
            await self._init_locked(reload_cookies=reload_cookies)

    async def _init_locked(self, reload_cookies: bool = True) -> None:
        """Inner init body — must only be called while holding _init_lock."""
        current_loop = asyncio.get_running_loop()

        # --- httpx client ---
        if self._client is None or self._client_loop is not current_loop:
            # Close stale client if there's a loop mismatch before creating a new one
            if self._client is not None:
                try:
                    await self._client.aclose()
                except Exception:
                    logger.debug("NewsFetcher: error closing stale client", exc_info=True)
                self._client = None

            self._client = httpx.AsyncClient(
                headers=self._headers,
                verify=_SSL_CONTEXT,
                timeout=httpx.Timeout(30.0, connect=10.0, pool=5.0),
                follow_redirects=True,
                limits=httpx.Limits(
                    max_connections=10,
                    max_keepalive_connections=5,
                    keepalive_expiry=30.0,
                ),
            )
            self._client_loop = current_loop

            # Only load cookies on initial creation, not on retries
            if reload_cookies:
                await self._load_cookies()
    
    async def _load_cookies(self) -> None:
        """Load cookies into the httpx client (called once on init, not on retries)."""
        if self._cookies_loaded:
            return
        # Try rookiepy first (live Firefox cookies)
        try:
            import rookiepy
            raw = await asyncio.to_thread(rookiepy.firefox, ["moneycontrol.com"])
            if raw:
                for c in raw:
                    raw_domain = c.get("domain")
                    domain_str: str = str(raw_domain) if raw_domain is not None else ""
                    name_str: str = str(c.get("name")) if c.get("name") else ""
                    value_str: str = str(c.get("value")) if c.get("value") else ""
                    if self._client:
                        self._client.cookies.set(
                            name_str, value_str, domain=domain_str if domain_str else ""
                        )
                self._cookies_loaded = True
                logger.info(
                    "NewsFetcher: loaded %d cookies via rookiepy", len(raw)
                )
                return
        except Exception as e:
            logger.warning("NewsFetcher: rookiepy failed: %s", str(e)[:80])

        # Fallback: try loading from pickle
        try:
            from app.services.cookie_loader import load_cookies_from_pickle

            pickle_cookies = await asyncio.to_thread(
                load_cookies_from_pickle, "moneycontrol"
            )
            if pickle_cookies:
                for c in pickle_cookies:
                    raw_domain = c.get("domain")
                    domain_str: str = str(raw_domain) if raw_domain is not None else ""
                    name_str: str = str(c.get("name")) if c.get("name") else ""
                    value_str: str = str(c.get("value")) if c.get("value") else ""
                    if self._client:
                        self._client.cookies.set(
                            name_str, value_str, domain=domain_str if domain_str else ""
                        )
                self._cookies_loaded = True
                logger.info(
                    "NewsFetcher: loaded %d cookies from pickle", len(pickle_cookies)
                )
                return
        except Exception as e:
            logger.warning(
                "NewsFetcher: pickle cookie load failed: %s", str(e)[:80]
            )

        logger.warning(
            "NewsFetcher: could not load cookies — proceeding without"
        )
    
    async def _get_client(self) -> httpx.AsyncClient:
        """Return the persistent client, reinitializing if missing or if the event loop changed."""
        current_loop = asyncio.get_running_loop()
        if self._client is None or self._client_loop is not current_loop:
            await self.init()
        assert self._client is not None
        return self._client

    async def _refresh_cookies(self) -> bool:
        """Force-refresh cookies by recreating client (called after 403)."""
        self._cookies_loaded = False
        
        # Recreate client without reloading cookies (cookies were just refreshed)
        self._client = None
        self._client_loop = None
        await self.init(reload_cookies=False)
        return True

    async def _get_page(self, url: str, max_retries: int = 3) -> _PageResult:
        """Fetch a page via httpx with retry, validation, and stale-client recovery."""
        last_error = None

        for attempt in range(max_retries):
            try:
                client = await self._get_client()

                # Build FRESH headers for each attempt (rotates browser preset)
                referer = "https://www.moneycontrol.com/" if attempt == 0 else None
                headers = _build_headers(url, referer)

                # Per-request headers — do NOT mutate the shared client.
                # Passing headers=... keeps each request isolated even when
                # _get_page is awaited concurrently from multiple coroutines.
                response = await client.get(url, headers=headers)

                # Handle HTTP errors with retry
                if response.status_code == 404:
                    raise _ArticleNotFound(url)

                if response.status_code in (403, 429):
                    logger.warning(
                        "Got %s on %s, attempt %d/%d",
                        response.status_code, url, attempt + 1, max_retries,
                    )
                    if attempt < max_retries - 1:
                        backoff = 2 ** attempt
                        logger.debug("Retrying in %ds...", backoff)
                        await asyncio.sleep(backoff)
                        if response.status_code == 403:
                            await self.init(reload_cookies=False)
                        continue
                    response.raise_for_status()

                response.raise_for_status()

                # Validate response content
                is_valid, reason = self._is_valid_response(response.text, url)
                if not is_valid:
                    logger.warning(
                        "Invalid response (%s) for %s, attempt %d/%d",
                        reason, url, attempt + 1, max_retries,
                    )
                    if attempt < max_retries - 1:
                        backoff = 2 ** attempt
                        logger.debug("Retrying in %ds...", backoff)
                        await asyncio.sleep(backoff)
                        await self.init(reload_cookies=False)
                        continue
                    # On final attempt, return what we got

                return _PageResult(text=response.text)

            except (RuntimeError, httpx.ReadError) as e:
                msg = str(e).lower()
                if "client has been closed" in msg or "different event loop" in msg:
                    logger.debug(
                        "httpx client stale (%s), reinitializing for %s",
                        str(e)[:80], url,
                    )
                    self._client = None
                    self._client_loop = None
                    await self.init(reload_cookies=False)
                    if attempt < max_retries - 1:
                        continue
                else:
                    last_error = e
                    if attempt == max_retries - 1:
                        raise

            except Exception as e:
                last_error = e
                if attempt < max_retries - 1:
                    backoff = 2 ** attempt
                    logger.debug(
                        "Fetch failed (%s), retrying in %ds...", str(e)[:80], backoff
                    )
                    await asyncio.sleep(backoff)
                else:
                    raise

        raise last_error or RuntimeError(
            f"Failed to fetch {url} after {max_retries} retries"
        )

    async def close(self) -> None:
        """Close the persistent httpx client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
            self._client_loop = None

    async def _fetch_listing_page(self, page: int) -> str:
        """Fetch the HTML content of a news listing page."""
        if page == 1:
            url = MONEYCONTROL_NEWS_ALL
        else:
            url = f"{MONEYCONTROL_NEWS_ALL}/page-{page}/"

        logger.debug("Fetching listing page: %s", url)
        response = await self._get_page(url)
        return response.text

    # Reject non-textual content types — videos, photo galleries, podcasts, tag/paginated pages,
    # and liveblogs. Liveblogs are React-rendered rolling feeds whose body content lives in
    # JSX-hashed divs that our static HTML parser cannot reliably extract.
    # Topic categories (/india/, /politics/, /trends/, /opinion/, /fintech/, etc.) are kept —
    # they are valid text articles.
    _REJECT_SEGMENTS = frozenset(
        [
            "/videos/",
            "/photos/",
            "/podcast/",
            "/tags/",
            "/gold-rates-today/",
            "/silver-rates-today/",
            "/page-",
            "-liveblog-",
            "-live-",
        ]
    )

    def _extract_article_urls(self, html: str) -> list[str]:
        """Extract article URLs from listing page HTML."""
        soup = BeautifulSoup(html, "html5lib")
        urls: list[str] = []

        for link in soup.find_all("a", href=True):
            raw = link.get("href", "")
            href = str(raw) if raw else ""
            if not href or "/news/" not in href:
                continue
            # Must end with -NNNNNN.html
            if not ARTICLE_PATTERN.search(href):
                continue
            # Must not contain any rejected path segment
            if any(seg in href for seg in self._REJECT_SEGMENTS):
                continue
            full_url = (
                href if href.startswith("http") else f"{MONEYCONTROL_BASE_URL}{href}"
            )
            if "moneycontrol.com/news/" in full_url and full_url not in urls:
                urls.append(full_url)

        logger.debug("Extracted %d article URLs from listing page", len(urls))
        return urls

    def _is_valid_response(self, html: str, url: str) -> tuple[bool, str]:
        """Validate that HTML response has expected content.

        Returns (is_valid, reason).
        """
        soup = BeautifulSoup(html, "html5lib")

        # Check for Cloudflare/challenge pages (quick check, no size threshold)
        title = soup.find("title")
        if title and "just a moment" in title.get_text().lower():
            return False, "Cloudflare challenge page detected"

        if len(html) < 10000:  # 10KB minimum for a real page
            return False, f"Response too small: {len(html)} bytes"

        # For company pages, check #news div exists
        if "/stockpricequote/" in url:
            if soup.find(id="news") is None:
                return False, "Missing #news div on company page"

        # For news ARTICLE pages (not listing pages), check article body exists
        # Only check URLs that look like individual articles (end with -NNNNNN.html)
        if "/news/" in url and ARTICLE_PATTERN.search(url):
            has_body = (
                soup.find("div", class_="article_body")
                or soup.find(id="article_body")
                or soup.find("div", class_="article_consum_wrapper")
                or soup.find("div", class_="content_wrapper")
                or soup.find("article")
            )
            if not has_body:
                return False, "Missing article body"

        return True, "OK"

    async def _fetch_and_parse_article(
        self, url: str, source: str = SOURCE_NAME
    ) -> dict[str, Any] | None:
        """Fetch and parse a single article using httpx with multiple selector fallbacks.

        The semaphore is held only for the duration of the HTTP fetch and
        the synchronous parse work.  The politeness sleep is intentionally
        outside the ``async with`` block so other tasks can acquire the
        semaphore (and start their own HTTP fetches) while we're sleeping.
        Error paths still return early without sleeping, preserving the
        existing behaviour for 404s and parse failures.
        """
        result: dict[str, Any] | None = None
        async with self._get_semaphore():
            try:
                logger.debug("Parsing article: %s", url)
                response = await self._get_page(url)

                soup = BeautifulSoup(response.text, "html5lib")

                # --- Title extraction with multiple selectors ---
                title = None
                title_selectors = ["h1", "title", "h2.title", "h2.artTitle"]
                for selector in title_selectors:
                    if " " in selector:  # CSS selector
                        title_tag = soup.select_one(selector)
                    else:  # tag name
                        title_tag = soup.find(selector)
                    if title_tag:
                        title = title_tag.get_text(strip=True)
                        if title:
                            break

                # --- Article body extraction with multiple selectors ---
                text = None
                body_selectors = [
                    {"class": "article_body"},
                    {"id": "article_body"},
                    {"class": "article_consum_wrapper"},
                    {"class": "content_wrapper"},
                    {"class": "artical_content"},
                    {"itemprop": "articleBody"},
                    {"class": "entry-content"},
                    {"class": "post-content"},
                ]
                for selector in body_selectors:
                    # Try div with selector
                    element = soup.find("div", selector) or soup.find("article", selector)
                    if element:
                        text = element.get_text(strip=True)
                        if text and len(text) > 100:  # Must have meaningful content
                            break

                # Fallback: try CSS selectors
                if not text or len(text) < 100:
                    css_selectors = [
                        ".article_body", ".article_consum_wrapper",
                        ".content_wrapper", "article", ".entry-content",
                    ]
                    for css_sel in css_selectors:
                        element = soup.select_one(css_sel)
                        if element:
                            text = element.get_text(strip=True)
                            if text and len(text) > 100:
                                break

                top_image = None
                og_image = soup.find("meta", property="og:image")
                if og_image:
                    top_image = str(og_image.get("content") or "") or None

                publish_date = None
                # Try multiple date extraction strategies
                date_meta_candidates = [
                    soup.find("meta", property="article:published_time"),
                    soup.find("meta", property="og:article:published_time"),
                    soup.find("meta", property="datePublished"),
                    soup.find("meta", attrs={"name": "date"}),
                    soup.find("meta", attrs={"name": "publish-date"}),
                    soup.find("meta", attrs={"name": "DC.date.issued"}),
                ]
                for date_meta in date_meta_candidates:
                    if date_meta:
                        raw_date = date_meta.get("content")
                        if raw_date:
                            try:
                                publish_date = datetime.fromisoformat(
                                    str(raw_date).replace("Z", "+00:00")
                                )
                                if publish_date.tzinfo is not None:
                                    publish_date = publish_date.replace(tzinfo=None)
                                break
                            except Exception:
                                continue

                # Fallback 1: <time datetime="..."> tags
                if not publish_date:
                    time_tag = soup.find("time", datetime=True)
                    if time_tag:
                        try:
                            raw_date = time_tag.get("datetime")
                            if raw_date:
                                publish_date = datetime.fromisoformat(
                                    str(raw_date).replace("Z", "+00:00")
                                )
                                if publish_date.tzinfo is not None:
                                    publish_date = publish_date.replace(tzinfo=None)
                        except Exception:
                            pass

                # Fallback 2: use current time so the article is not filtered out by date range queries
                if not publish_date:
                    publish_date = datetime.now(timezone.utc).replace(tzinfo=None)

                authors = None
                author_meta = soup.find("meta", attrs={"name": "author"})
                if author_meta:
                    raw_author = author_meta.get("content")
                    if raw_author:
                        authors = [str(raw_author)]

                nlp = analyze_article_dict(
                    headline=title or "",
                    summary=text or "",
                    source_name=source,
                )

                result = {
                    "url": url,
                    "source": source,
                    "title": title,
                    "text": text,
                    "authors": authors,
                    "top_image": top_image,
                    "publish_date": publish_date,
                    "sentiment": nlp["sentiment"],
                    "sentiment_score": nlp["sentiment_score"],
                    "confidence": nlp["confidence"],
                    "language": nlp["language"],
                    "entities": nlp["entities"],
                    "threat_level": nlp["threat_level"],
                    "threat_category": nlp["threat_category"],
                    "source_credibility": nlp["source_credibility"],
                }
                logger.debug(
                    f"Parsed article: {title[:30] if title else 'No title'}..."
                )
            except _ArticleNotFound:
                logger.debug("Article not found (404), skipping: %s", url)
                return None
            except Exception:
                logger.exception("Failed to parse article: %s", url)
                return None
        # Semaphore released here.  Politeness sleep throttles call rate
        # independently of in-flight concurrency, and only fires on success
        # (mirroring the previous behaviour where 404s / parse errors
        # returned early before reaching the sleep).
        if result is not None:
            await asyncio.sleep(REQUEST_DELAY)
        return result

    async def crawl_and_store(self, pages: int, db: AsyncSession) -> int:
        """Crawl the specified number of listing pages and store new articles.

        Returns the number of new articles stored.
        """
        logger.info("Starting news crawl for %d pages", pages)

        all_urls: list[str] = []
        for page in range(1, pages + 1):
            try:
                html = await self._fetch_listing_page(page)
                urls = self._extract_article_urls(html)
                all_urls.extend(urls)
                logger.debug("Page %d: found %d URLs", page, len(urls))
            except Exception:
                logger.exception("Failed to fetch listing page %d", page)

        if not all_urls:
            logger.warning("No article URLs found")
            return 0

        unique_urls = list(dict.fromkeys(all_urls))
        logger.info("Found %d unique article URLs", len(unique_urls))

        existing_urls = set()
        stmt = select(NewsArticle.url).where(NewsArticle.url.in_(unique_urls))
        result = await db.execute(stmt)
        for row in result:
            existing_urls.add(row[0])

        new_urls = [url for url in unique_urls if url not in existing_urls]
        logger.info(
            "%d new URLs to fetch (already have %d)", len(new_urls), len(existing_urls)
        )

        if not new_urls:
            return 0

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        stored_count = 0

        sem = asyncio.Semaphore(CONCURRENCY_LIMIT)

        async def bounded_fetch(url: str):
            async with sem:
                return await self._fetch_and_parse_article(url)

        tasks = [asyncio.create_task(bounded_fetch(url)) for url in new_urls]

        pending_batch = []
        for i, task in enumerate(asyncio.as_completed(tasks)):
            try:
                parsed = await task
                if parsed is None:
                    continue

                parsed["fetched_at"] = now
                pending_batch.append(parsed)

                if len(pending_batch) >= ARTICLE_BATCH_SIZE:
                    stmt = (
                        sqlite_insert(NewsArticle)
                        .values(pending_batch)
                        .on_conflict_do_nothing(index_elements=["url"])
                    )
                    await db.execute(stmt)
                    stored_count += len(pending_batch)
                    logger.debug(f"Stored batch of {len(pending_batch)} ({i + 1}/{len(new_urls)} processed)")
                    pending_batch = []
            except Exception:
                logger.exception("Error storing article")

        if pending_batch:
            stmt = (
                sqlite_insert(NewsArticle)
                .values(pending_batch)
                .on_conflict_do_nothing(index_elements=["url"])
            )
            await db.execute(stmt)
            stored_count += len(pending_batch)

        await db.commit()
        logger.info("Stored %d new articles", stored_count)

        return stored_count

    def _extract_company_article_urls(self, html: str) -> list[str]:
        """Extract article URLs from a MoneyControl stock quote page's #news section.

        Only links inside the ``<div id="news">`` block are considered so that
        unrelated site-wide navigation links are excluded.
        """
        soup = BeautifulSoup(html, "html5lib")
        news_div = soup.find(id="news")
        if news_div is None:
            logger.warning("No #news section found on company page")
            return []

        urls: list[str] = []
        for link in news_div.find_all("a", href=True):
            raw = link.get("href", "")
            href = str(raw) if raw else ""
            if not href:
                continue
            if not ARTICLE_PATTERN.search(href):
                continue
            if any(seg in href for seg in self._REJECT_SEGMENTS):
                continue
            full_url = (
                href if href.startswith("http") else f"{MONEYCONTROL_BASE_URL}{href}"
            )
            if "moneycontrol.com/news/" in full_url and full_url not in urls:
                urls.append(full_url)

        logger.debug("Extracted %d article URLs from company #news section", len(urls))
        return urls

    async def resolve_mc_url(self, symbol: str, db: AsyncSession) -> str | None:
        """Resolve a MoneyControl stock quote URL for a given NSE symbol.

        Resolution order:
        1. Look up cached mc_url from StockUniverse table
        2. Call MC autocomplete API to get the URL
        3. Fall back to _FALLBACK_MC_URL_MAP
        4. Return None if all resolution attempts fail

        If resolution succeeds, the URL is persisted back to StockUniverse.
        """
        symbol_upper = symbol.upper()

        # Step 1: Check DB for cached mc_url
        try:
            stmt = select(StockUniverse.mc_url).where(
                StockUniverse.symbol == symbol_upper
            )
            result = await db.execute(stmt)
            row = result.fetchone()
            if row and row[0]:
                logger.debug("resolve_mc_url: found cached URL for %s", symbol_upper)
                return row[0]
        except Exception:
            logger.warning("resolve_mc_url: DB lookup failed for %s", symbol_upper)

        # Step 2: Call MC autocomplete API
        mc_url = await self._resolve_via_autocomplete(symbol_upper)
        if mc_url:
            # Cache the result back to DB
            try:
                await db.execute(
                    sa_update(StockUniverse)
                    .where(StockUniverse.symbol == symbol_upper)
                    .values(mc_url=mc_url)
                )
                await db.commit()
                logger.info(
                    "resolve_mc_url: resolved and cached %s -> %s", symbol_upper, mc_url
                )
            except Exception:
                logger.warning(
                    "resolve_mc_url: failed to cache URL for %s", symbol_upper
                )
            return mc_url

        # Step 3: Fall back to hardcoded map
        fallback = _FALLBACK_MC_URL_MAP.get(symbol_upper)
        if fallback:
            logger.info("resolve_mc_url: using fallback URL for %s", symbol_upper)
            return fallback

        logger.warning("resolve_mc_url: could not resolve URL for %s", symbol_upper)
        return None

    async def _resolve_via_autocomplete(self, symbol: str) -> str | None:
        """Resolve MC URL via MoneyControl's autocomplete API."""
        import json

        url = (
            f"https://www.moneycontrol.com/mccode/common/autosuggestion_solr.php"
            f"?classic=yes&query={symbol}&type=1&format=json&callback=?"
        )
        try:
            client = await self._get_client()
            response = await client.get(url)
        except RuntimeError as e:
            # Client was closed (e.g., during shutdown) — reinitialize and retry
            if "client has been closed" in str(e).lower():
                logger.debug("httpx client was closed, reinitializing for autocomplete %s", symbol)
                self._client = None
                self._client_loop = None
                await self.init()
                client = await self._get_client()
                response = await client.get(url)
            else:
                raise
        except Exception:
            logger.exception(
                "resolve_mc_url: autocomplete API call failed for %s", symbol
            )
            return None

        try:
            if response.status_code != 200:
                logger.warning(
                    "resolve_mc_url: autocomplete API returned %s for %s",
                    response.status_code,
                    symbol,
                )
                return None

            text = response.text
            # Strip JSONP wrapper: "?([{...}])" -> "[{...}]"
            if text.startswith("?(") and text.endswith(")"):
                text = text[2:-1]
            data = json.loads(text)
            if not isinstance(data, list) or len(data) == 0:
                return None

            # Find exact NSE symbol match in pdt_dis_nm (e.g. ", INFY," or ", INFY<")
            symbol_pattern = f", {symbol},"
            symbol_pattern_alt = f", {symbol}<"
            for item in data:
                pdt_dis_nm = item.get("pdt_dis_nm", "")
                if symbol_pattern in pdt_dis_nm or symbol_pattern_alt in pdt_dis_nm:
                    link_src = item.get("link_src")
                    if link_src:
                        return link_src

            # If no exact match, return first result (e.g. RELIANCE -> Reliance Industries)
            first = data[0]
            link_src = first.get("link_src")
            if link_src:
                logger.debug(
                    "resolve_mc_url: no exact match for %s, using first result: %s",
                    symbol,
                    first.get("name"),
                )
                return link_src

            return None
        except Exception:
            logger.exception(
                "resolve_mc_url: autocomplete API call failed for %s", symbol
            )
            return None

    async def fetch_company_news(
        self, symbol: str, db: AsyncSession, mc_url: str | None = None
    ) -> int:
        """Fetch news articles from a MoneyControl stock quote page's #news section.

        If *mc_url* is not provided, it will be auto-resolved using resolve_mc_url()
        which queries the StockUniverse table, then the MC autocomplete API,
        and finally falls back to a hardcoded map.

        For articles already stored from the global crawl (``company_symbol IS NULL``),
        the existing row is updated to set ``company_symbol = symbol`` rather than
        creating a duplicate.

        Returns the total number of newly stored + newly tagged articles.
        """
        from sqlalchemy import update as sa_update, or_

        symbol_upper = symbol.upper()

        # Resolve mc_url if not provided
        if not mc_url:
            mc_url = await self.resolve_mc_url(symbol_upper, db)
            if not mc_url:
                logger.error(
                    "fetch_company_news: could not resolve MC URL for %s", symbol_upper
                )
                return 0

        logger.info("fetch_company_news: symbol=%s url=%s", symbol_upper, mc_url)

        # 1. Fetch the stock quote page (with concurrency limiting)
        try:
            async with self._get_semaphore():
                response = await self._get_page(mc_url)
        except Exception:
            logger.exception(
                "fetch_company_news: failed to fetch company page %s", mc_url
            )
            return 0

        # 2. Extract article URLs from the #news section
        article_urls = self._extract_company_article_urls(response.text)
        if not article_urls:
            logger.warning(
                "fetch_company_news: no article URLs found for %s", symbol_upper
            )
            return 0

        # 3. Check which URLs already exist in the DB
        stmt = select(NewsArticle.url, NewsArticle.company_symbol).where(
            NewsArticle.url.in_(article_urls)
        )
        result = await db.execute(stmt)
        existing: dict[str, str | None] = {row[0]: row[1] for row in result}

        new_urls = [u for u in article_urls if u not in existing]
        tag_urls = [u for u, sym in existing.items() if sym is None]

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        total = 0

        # 4. Fetch and store brand-new articles
        if new_urls:
            tasks = [
                self._fetch_and_parse_article(u, source=SOURCE_NAME_COMPANY)
                for u in new_urls
            ]
            fetch_results = await asyncio.gather(*tasks)
            valid = [r for r in fetch_results if r is not None]

            pending_batch = []
            for parsed in valid:
                try:
                    parsed["fetched_at"] = now
                    parsed["company_symbol"] = symbol_upper
                    pending_batch.append(parsed)

                    if len(pending_batch) >= ARTICLE_BATCH_SIZE:
                        stmt = (
                            sqlite_insert(NewsArticle)
                            .values(pending_batch)
                            .on_conflict_do_nothing(index_elements=["url"])
                        )
                        await db.execute(stmt)
                        total += len(pending_batch)
                        pending_batch = []
                except Exception:
                    logger.exception(
                        "fetch_company_news: error storing %s", parsed.get("url")
                    )

            if pending_batch:
                stmt = (
                    sqlite_insert(NewsArticle)
                    .values(pending_batch)
                    .on_conflict_do_nothing(index_elements=["url"])
                )
                await db.execute(stmt)
                total += len(pending_batch)

        # 5. Tag already-stored articles that came from the global crawl
        if tag_urls:
            try:
                await db.execute(
                    sa_update(NewsArticle)
                    .where(
                        NewsArticle.url.in_(tag_urls),
                        or_(
                            NewsArticle.company_symbol.is_(None),
                            NewsArticle.company_symbol != symbol_upper,
                        ),
                    )
                    .values(company_symbol=symbol_upper)
                )
                total += len(tag_urls)
                logger.info(
                    "fetch_company_news: tagged %d existing articles with symbol=%s",
                    len(tag_urls),
                    symbol_upper,
                )
            except Exception:
                logger.exception(
                    "fetch_company_news: failed to tag existing articles for %s",
                    symbol_upper,
                )

        # 6. Stamp fetched_at=now on ALL articles for this symbol so the
        #    staleness check in get_company_news sees a fresh timestamp even
        #    for articles that were already stored before this run.
        try:
            await db.execute(
                sa_update(NewsArticle)
                .where(NewsArticle.company_symbol == symbol_upper)
                .values(fetched_at=now)
            )
        except Exception:
            logger.exception(
                "fetch_company_news: failed to update fetched_at for %s", symbol_upper
            )

        await db.commit()
        logger.info(
            "fetch_company_news: done — %d articles stored/tagged for %s",
            total,
            symbol_upper,
        )

        return total


news_fetcher = NewsFetcher()


# ── iinvest news pipeline ────────────────────────────────────────────────────


async def fetch_iinvest_company_news(
    symbol: str,
    db: AsyncSession,
    days: int = 30,
    limit: int = 50,
) -> int:
    """Fetch and store iinvest news articles for a company.

    iinvest does NOT pre-tag sentiment/threat — NLP is run locally via
    ``nlp_service.analyze_article_dict`` on each article after the fetch,
    same as the MoneyControl and RSS flows.

    Articles are upserted by ``iinvest_story_id`` (unique-indexed). Returns
    the number of new/updated articles. Returns 0 (does not raise) when
    the symbol has no ISIN cached or when the iinvest client is unavailable.
    """
    from sqlalchemy import select as sa_select
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert
    from app.models.stockuniverse import StockUniverse as _SU
    from app.services.iinvest_client import get_iinvest_client

    symbol_upper = symbol.upper()
    row = (await db.execute(
        sa_select(_SU.isin).where(_SU.symbol == symbol_upper)
    )).first()
    isin = row[0] if row else None

    # If the ISIN isn't cached in stock_universe (which is the common case for
    # symbols that were never enriched by an iinvest-path-resolving action),
    # fall back to the iinvest client's path resolver. The client itself
    # uses NSE's GetQuoteApi as tier 3, so this works for any NSE symbol
    # even with no prior enrichment.
    if not isin:
        try:
            isin, _path = await get_iinvest_client().resolve_path(
                symbol_upper, db=db
            )
        except Exception as exc:
            logger.debug(
                "fetch_iinvest_company_news: %s path resolution failed: %s",
                symbol_upper, exc,
            )
        if not isin:
            logger.info(
                "fetch_iinvest_company_news: %s has no ISIN and path "
                "resolution failed — skipping iinvest",
                symbol_upper,
            )
            return 0

    try:
        data = await get_iinvest_client().get_news([isin], size=limit)
    except Exception as exc:
        logger.warning(
            "fetch_iinvest_company_news: iinvest unavailable for %s: %s",
            symbol_upper, exc,
        )
        return 0

    stories = (data.get("response", {}) or {}).get("data") or []
    if not stories:
        return 0

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    new_count = 0
    for story in stories:
        url = story.get("sourceLink") or f"iinvest://{story.get('id', '')}"
        if not url:
            continue
        headline = story.get("headline") or ""
        synopsis = story.get("synopsis") or ""
        body = story.get("story") or synopsis
        source_dt = story.get("sourceDateTime")
        publish_date = _parse_iso_datetime(source_dt) if source_dt else None
        source_name = story.get("sourceName") or "cogencis"

        # NLP is run AFTER fetch — iinvest does not pre-tag.
        nlp = analyze_article_dict(
            headline=headline,
            summary=synopsis,
            source_name=source_name,
        )

        isins = story.get("isins") or [isin]
        tickers: list[str] = []
        # iinvest doesn't expose tickers directly; the ISIN → ticker map is
        # done at read-time by the frontend from the company_symbol field.
        entities = {
            **nlp["entities"],
            "isins": isins,
            "tickers": tickers,
        }

        parsed = {
            "url": url,
            "source": f"iinvest:{source_name}",
            "title": headline,
            "text": body,
            "top_image": story.get("thumbNailImage"),
            "publish_date": publish_date,
            "fetched_at": now,
            "company_symbol": symbol_upper,
            "sentiment": nlp["sentiment"],
            "sentiment_score": nlp["sentiment_score"],
            "confidence": nlp["confidence"],
            "language": nlp["language"],
            "entities": entities,
            "threat_level": nlp["threat_level"],
            "threat_category": nlp["threat_category"],
            "source_credibility": nlp["source_credibility"],
            "iinvest_story_id": str(story.get("id", "")),
            "iinvest_published_at": publish_date,
        }
        # Upsert by url (the primary key). The same iinvest story can be
        # returned for multiple unrelated companies; the first symbol to
        # write the row owns the company_symbol tag — later symbols
        # update the metadata but never overwrite the original tag, and
        # they get a tickers entry in the entities JSON so downstream
        # readers can still see they were related. See
        # backend/tests/test_iinvest_news_fetcher.py for the regression
        # test that pins this behaviour.
        from sqlalchemy import case

        update_set = {
            "source": parsed["source"],
            "title": parsed["title"],
            "text": parsed["text"],
            "top_image": parsed["top_image"],
            "publish_date": parsed["publish_date"],
            "fetched_at": parsed["fetched_at"],
            "sentiment": parsed["sentiment"],
            "sentiment_score": parsed["sentiment_score"],
            "confidence": parsed["confidence"],
            "language": parsed["language"],
            "entities": parsed["entities"],
            "threat_level": parsed["threat_level"],
            "threat_category": parsed["threat_category"],
            "source_credibility": parsed["source_credibility"],
            "iinvest_story_id": parsed["iinvest_story_id"],
            "iinvest_published_at": parsed["iinvest_published_at"],
            "company_symbol": case(
                (NewsArticle.company_symbol.is_(None), parsed["company_symbol"]),
                else_=NewsArticle.company_symbol,
            ),
        }
        stmt = sqlite_insert(NewsArticle).values(**parsed)
        stmt = stmt.on_conflict_do_update(
            index_elements=["url"],
            set_=update_set,
        )
        await db.execute(stmt)
        new_count += 1

    await db.commit()
    logger.info(
        "fetch_iinvest_company_news: %d articles upserted for %s",
        new_count, symbol_upper,
    )
    return new_count


def _parse_iso_datetime(value: str) -> datetime | None:
    """Parse an ISO 8601 string into a naive datetime (matches news_articles schema)."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is not None:
            dt = dt.replace(tzinfo=None)
        return dt
    except (ValueError, TypeError):
        return None
