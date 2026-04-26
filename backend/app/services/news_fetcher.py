"""News fetcher service for MoneyControl global and company-specific news."""

import asyncio
import logging
import random
import re
from datetime import datetime, timezone
from typing import Any

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import select, update as sa_update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.news import NewsArticle
from app.models.stockuniverse import StockUniverse

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

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
]

UA_FIREFOX = "Mozilla/5.0 (X11; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/148.0"

CONCURRENCY_LIMIT = 3
REQUEST_DELAY = 1.0
ARTICLE_BATCH_SIZE = 10


def _build_headers(ua: str | None = None) -> dict:
    """Build request headers with realistic browser headers."""
    user_agent = ua or random.choice(USER_AGENTS)
    return {
        "User-Agent": user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Connection": "keep-alive",
        "Referer": "https://www.moneycontrol.com/",
        "Origin": "https://www.moneycontrol.com",
    }


class NewsFetcher:
    """Service to fetch and parse news articles from MoneyControl."""

    def __init__(self) -> None:
        self._semaphore: asyncio.Semaphore | None = None
        self._semaphore_loop: asyncio.AbstractEventLoop | None = None
        self._headers = _build_headers(UA_FIREFOX)
        self._cookies_loaded = False
        self._client: httpx.AsyncClient | None = None
        self._client_loop: asyncio.AbstractEventLoop | None = None

    def _get_semaphore(self) -> asyncio.Semaphore:
        """Lazily create Semaphore in the current event loop to avoid loop-mismatch errors."""
        current_loop = asyncio.get_running_loop()
        if self._semaphore is None or self._semaphore_loop is not current_loop:
            self._semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)
            self._semaphore_loop = current_loop
        return self._semaphore

    async def init(self) -> None:
        """Initialize persistent httpx client with cookies. Call in lifespan startup."""
        current_loop = asyncio.get_running_loop()
        if self._client is not None and self._client_loop is current_loop:
            return

        # Close stale client if there's a loop mismatch before creating a new one
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:
                logger.debug("NewsFetcher: error closing stale client", exc_info=True)
            self._client = None

        self._client = httpx.AsyncClient(
            headers=self._headers,
            timeout=httpx.Timeout(30.0, connect=10.0, pool=5.0),
            follow_redirects=True,
            limits=httpx.Limits(
                max_connections=10,
                max_keepalive_connections=5,
                keepalive_expiry=30.0,
            ),
        )
        self._client_loop = current_loop

        from app.services.cookie_loader import load_cookies_from_pickle

        pickle_cookies = await asyncio.to_thread(load_cookies_from_pickle, "moneycontrol")
        if pickle_cookies:
            for c in pickle_cookies:
                raw_domain = c.get("domain")
                domain_str: str = str(raw_domain) if raw_domain is not None else ""
                name_str: str = str(c.get("name")) if c.get("name") else ""
                value_str: str = str(c.get("value")) if c.get("value") else ""
                self._client.cookies.set(
                    name_str, value_str, domain=domain_str if domain_str else ""
                )
            self._cookies_loaded = True
            logger.info("NewsFetcher: loaded %d cookies from pickle", len(pickle_cookies))
        else:
            try:
                import rookiepy
                raw = await asyncio.to_thread(rookiepy.firefox, ["moneycontrol.com"])
                if raw:
                    for c in raw:
                        raw_domain = c.get("domain")
                        domain_str: str = str(raw_domain) if raw_domain is not None else ""
                        name_str: str = str(c.get("name")) if c.get("name") else ""
                        value_str: str = str(c.get("value")) if c.get("value") else ""
                        self._client.cookies.set(
                            name_str, value_str, domain=domain_str if domain_str else ""
                        )
                    self._cookies_loaded = True
                    logger.info("NewsFetcher: loaded %d cookies into persistent httpx client", len(raw))
            except Exception:
                logger.warning("NewsFetcher: could not load cookies — proceeding without authentication")
                self._cookies_loaded = False

    async def _get_client(self) -> httpx.AsyncClient:
        """Return the persistent client, initializing lazily if needed."""
        if self._client is None:
            await self.init()
        assert self._client is not None
        return self._client

    async def _refresh_cookies(self) -> bool:
        """Force-refresh cookies from Firefox profile (e.g. after a 403)."""
        self._cookies_loaded = False
        await self.init()
        return self._cookies_loaded

    async def _get_page(self, url: str) -> httpx.Response:
        """Fetch a page with 403-handling: retry once with fresh cookies."""
        try:
            client = await self._get_client()
            response = await client.get(url)
        except RuntimeError as e:
            # Client was closed (e.g., during shutdown) — reinitialize and retry
            if "client has been closed" in str(e).lower():
                logger.debug("httpx client was closed, reinitializing for %s", url)
                self._client = None
                self._client_loop = None
                await self.init()
                client = await self._get_client()
                response = await client.get(url)
            else:
                raise
        if response.status_code == 403:
            logger.warning("Got 403 on %s — refreshing cookies and retrying", url)
            await asyncio.sleep(2)
            await self._refresh_cookies()
            response = await client.get(url)
        response.raise_for_status()
        return response

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

    # Matches only real article URLs: end with -NNNNNN.html (6+ digits)
    _ARTICLE_PATTERN = re.compile(r"-\d{6,}\.html$")

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
        ]
    )

    def _extract_article_urls(self, html: str) -> list[str]:
        """Extract article URLs from listing page HTML."""
        soup = BeautifulSoup(html, "lxml")
        urls: list[str] = []

        for link in soup.find_all("a", href=True):
            raw = link.get("href", "")
            href = str(raw) if raw else ""
            if not href or "/news/" not in href:
                continue
            # Must end with -NNNNNN.html
            if not self._ARTICLE_PATTERN.search(href):
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

    async def _fetch_and_parse_article(
        self, url: str, source: str = SOURCE_NAME
    ) -> dict[str, Any] | None:
        """Fetch and parse a single article using httpx."""
        async with self._get_semaphore():
            try:
                logger.debug("Parsing article: %s", url)
                response = await self._get_page(url)

                soup = BeautifulSoup(response.text, "lxml")

                title = None
                title_tag = soup.find("h1")
                if title_tag:
                    title = title_tag.get_text(strip=True)
                if not title:
                    title_tag = soup.find("title")
                    if title_tag:
                        title = title_tag.get_text(strip=True)

                text = None
                article_body = soup.find("div", class_="article_body")
                if article_body:
                    text = article_body.get_text(strip=True)
                if not text:
                    article_body = soup.find("div", {"id": "article_body"})
                    if article_body:
                        text = article_body.get_text(strip=True)
                if not text:
                    article_body = soup.find("div", class_="article_consum_wrapper")
                    if article_body:
                        text = article_body.get_text(strip=True)

                top_image = None
                og_image = soup.find("meta", property="og:image")
                if og_image:
                    top_image = str(og_image.get("content") or "") or None

                publish_date = None
                date_meta = soup.find("meta", property="article:published_time")
                if date_meta:
                    raw_date = date_meta.get("content")
                    if raw_date:
                        try:
                            publish_date = datetime.fromisoformat(
                                str(raw_date).replace("Z", "+00:00")
                            )
                            if publish_date.tzinfo is not None:
                                publish_date = publish_date.replace(tzinfo=None)
                        except Exception:
                            pass

                authors = None
                author_meta = soup.find("meta", attrs={"name": "author"})
                if author_meta:
                    raw_author = author_meta.get("content")
                    if raw_author:
                        authors = [str(raw_author)]

                await asyncio.sleep(REQUEST_DELAY)

                result = {
                    "url": url,
                    "source": source,
                    "title": title,
                    "text": text,
                    "authors": authors,
                    "top_image": top_image,
                    "publish_date": publish_date,
                }
                logger.debug(
                    f"Parsed article: {title[:30] if title else 'No title'}..."
                )
                return result
            except Exception:
                logger.exception("Failed to parse article: %s", url)
                return None

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

        all_results = await asyncio.gather(
            *[bounded_fetch(url) for url in new_urls],
            return_exceptions=True,
        )

        logger.debug(f"Got {len(all_results)} results, filtering None values")
        valid_results = [r for r in all_results if r is not None]
        logger.debug(f"Valid results: {len(valid_results)}")

        pending_batch = []
        for i, parsed in enumerate(valid_results):
            try:
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
                    logger.debug(f"Stored batch of {len(pending_batch)} ({i + 1}/{len(valid_results)} total)")
                    pending_batch = []
            except Exception:
                logger.exception(f"Error storing article {i}: {parsed.get('url')}")

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

        # Backfill any articles (old or new) that still have NULL text or date
        backfilled = await self.backfill_null_articles(db)
        if backfilled:
            logger.info(
                "Backfilled %d articles with previously missing fields", backfilled
            )

        return stored_count

    async def backfill_null_articles(self, db: AsyncSession) -> int:
        """Re-fetch and update any stored articles that have NULL text or publish_date.

        Returns the number of articles successfully updated.
        """
        from sqlalchemy import or_

        stmt = select(NewsArticle.url).where(
            or_(NewsArticle.text.is_(None), NewsArticle.publish_date.is_(None))
        )
        result = await db.execute(stmt)
        null_urls = [row[0] for row in result]

        if not null_urls:
            logger.debug("backfill: no articles with NULL fields — nothing to do")
            return 0

        logger.info(
            "backfill: re-fetching %d articles with NULL fields", len(null_urls)
        )

        tasks = [self._fetch_and_parse_article(url) for url in null_urls]
        results = await asyncio.gather(*tasks)

        updated = 0
        for parsed in results:
            if parsed is None:
                continue
            # Only update the fields that were NULL; skip if still missing
            url = parsed.get("url")
            if not url:
                continue
            update_fields: dict[str, Any] = {}
            if parsed.get("text"):
                update_fields["text"] = parsed["text"]
            if parsed.get("publish_date"):
                update_fields["publish_date"] = parsed["publish_date"]
            if parsed.get("top_image"):
                update_fields["top_image"] = parsed["top_image"]
            if parsed.get("authors"):
                update_fields["authors"] = parsed["authors"]
            if not update_fields:
                logger.debug("backfill: still no data for %s", url)
                continue
            try:
                from sqlalchemy import update as sa_update

                await db.execute(
                    sa_update(NewsArticle)
                    .where(NewsArticle.url == url)
                    .values(**update_fields)
                )
                updated += 1
            except Exception:
                logger.exception("backfill: failed to update %s", url)

        await db.commit()
        logger.info("backfill: updated %d articles", updated)
        return updated

    def _extract_company_article_urls(self, html: str) -> list[str]:
        """Extract article URLs from a MoneyControl stock quote page's #news section.

        Only links inside the ``<div id="news">`` block are considered so that
        unrelated site-wide navigation links are excluded.
        """
        soup = BeautifulSoup(html, "lxml")
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
            if not self._ARTICLE_PATTERN.search(href):
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

        backfilled = await self.backfill_null_articles(db)
        if backfilled:
            logger.info(
                "fetch_company_news: backfilled %d articles with missing fields for %s",
                backfilled,
                symbol_upper,
            )

        return total


news_fetcher = NewsFetcher()
