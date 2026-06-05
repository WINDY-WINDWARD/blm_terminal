"""RSS/Atom feed parser using feedparser library.

This module provides async RSS/Atom parsing capabilities for news aggregation.
"""

import asyncio
import logging
import random
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import feedparser
import httpx
from dateutil.parser import parse as parse_date

from app.services.news_sources import NewsSource

logger = logging.getLogger(__name__)

# Module-level shared httpx client (audit win #10: pool HTTP connections).
# Recreated per event loop so tests / server reloads don't reuse a closed client.
_SHARED_CLIENT_TIMEOUT = 15.0
_shared_client: httpx.AsyncClient | None = None
_shared_client_loop: asyncio.AbstractEventLoop | None = None


def _get_shared_client() -> httpx.AsyncClient:
    """Return the module-level shared httpx.AsyncClient for the current event loop.

    Lazy-initialized on first call; rebuilt when the running event loop changes
    (e.g. FastAPI reload, pytest-asyncio new loop per test). Safe to call from
    sync code — returns the cached client when no loop is running.
    """
    global _shared_client, _shared_client_loop
    try:
        current_loop = asyncio.get_running_loop()
    except RuntimeError:
        if _shared_client is None:
            _shared_client = httpx.AsyncClient(
                timeout=_SHARED_CLIENT_TIMEOUT,
                follow_redirects=True,
            )
        return _shared_client
    if _shared_client is None or _shared_client_loop is not current_loop:
        _shared_client = httpx.AsyncClient(
            timeout=_SHARED_CLIENT_TIMEOUT,
            follow_redirects=True,
        )
        _shared_client_loop = current_loop
    return _shared_client


# Browser user agents for RSS fetching (RSS is less restrictive but we use realistic headers)
BROWSER_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
]


@dataclass
class ParsedArticle:
    """A normalized article extracted from an RSS feed."""
    url: str
    title: str | None
    summary: str | None
    published: datetime | None
    author: str | None
    source_id: str
    source_name: str
    source_category: str
    source_tier: int


@dataclass
class FetchResult:
    """Result of fetching a single feed."""
    source: NewsSource
    articles: list[ParsedArticle]
    error: str | None = None


def _get_random_headers() -> dict[str, str]:
    """Get headers with random browser user agent."""
    return {
        "User-Agent": random.choice(BROWSER_USER_AGENTS),
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
    }


def _parse_rss_entry(entry: dict[str, Any], source: NewsSource) -> ParsedArticle | None:
    """Parse a single RSS/Atom entry into a normalized article."""
    try:
        # URL - try multiple possible fields
        url = None
        for url_field in ('link', 'id', 'guid'):
            if url_field in entry and entry[url_field]:
                url = entry[url_field]
                if isinstance(url, dict):
                    url = url.get('href') or url.get('#text')
                break
        if not url:
            return None

        # Title
        title = None
        for title_field in ('title', 'title_detail'):
            if title_field in entry and entry[title_field]:
                if isinstance(entry[title_field], dict):
                    title = entry[title_field].get('value')
                else:
                    title = entry[title_field]
                break

        # Summary/description - try multiple fields
        summary = None
        for summary_field in ('summary', 'summary_detail', 'description', 'content'):
            if summary_field in entry and entry[summary_field]:
                if isinstance(entry[summary_field], dict):
                    summary = entry[summary_field].get('value')
                else:
                    summary = entry[summary_field]
                break

        # Strip HTML from summary
        if summary:
            import re
            summary = re.sub(r'<[^>]+>', '', summary)
            summary = summary.strip()

        # Published date
        published = None
        for date_field in ('published', 'updated', 'created', 'modified'):
            if date_field in entry and entry[date_field]:
                date_str = entry[date_field]
                if isinstance(date_str, dict):
                    date_str = date_str.get('value')
                if date_str:
                    try:
                        published = parse_date(date_str)
                        if published.tzinfo is None:
                            published = published.replace(tzinfo=timezone.utc)
                        else:
                            published = published.astimezone(timezone.utc)
                        break
                    except (ValueError, TypeError):
                        continue

        # Author
        author = None
        for author_field in ('author', 'author_detail', 'dc_creator'):
            if author_field in entry and entry[author_field]:
                if isinstance(entry[author_field], dict):
                    author = entry[author_field].get('name')
                else:
                    author = str(entry[author_field])
                break

        return ParsedArticle(
            url=url,
            title=title.strip() if title else None,
            summary=summary[:2000] if summary else None,  # Limit summary length
            published=published,
            author=author,
            source_id=source.id,
            source_name=source.name,
            source_category=source.category.value,
            source_tier=source.tier.value,
        )
    except Exception as e:
        logger.debug(f"Failed to parse RSS entry: {e}")
        return None


async def fetch_feed(source: NewsSource, timeout: float = 15.0) -> FetchResult:
    """Fetch and parse a single RSS feed.

    Args:
        source: The news source to fetch
        timeout: Request timeout in seconds

    Returns:
        FetchResult with list of parsed articles or error
    """
    articles: list[ParsedArticle] = []

    try:
        client = _get_shared_client()
        response = await client.get(source.url, headers=_get_random_headers(), timeout=timeout)
        response.raise_for_status()

        # Parse the feed
        feed = feedparser.parse(response.text)

        if feed.bozo:
            # Check if it's a serious error vs just a warning
            if isinstance(feed.bozo_exception, feedparser.exceptions.CharacterEncodingOverride):
                # Try to recover from encoding issues
                pass
            elif isinstance(feed.bozo_exception, feedparser.exceptions.FeedparserError):
                # Try with alternative encoding
                feed = feedparser.parse(response.text, encoding='utf-8')
                if feed.bozo and isinstance(feed.bozo_exception, feedparser.exceptions.FeedparserError):
                    logger.warning(f"Feed parse error for {source.id}: {feed.bozo_exception}")
                    return FetchResult(source=source, articles=[], error=str(feed.bozo_exception))

        for entry in feed.entries:
            article = _parse_rss_entry(entry, source)
            if article:
                articles.append(article)

        logger.debug(f"Fetched {len(articles)} articles from {source.id}")

    except httpx.TimeoutException:
        logger.warning(f"Timeout fetching {source.id}")
        return FetchResult(source=source, articles=[], error="Timeout")
    except httpx.HTTPStatusError as e:
        logger.warning(f"HTTP error fetching {source.id}: {e.response.status_code}")
        return FetchResult(source=source, articles=[], error=f"HTTP {e.response.status_code}")
    except Exception as e:
        logger.error(f"Error fetching {source.id}: {e}")
        return FetchResult(source=source, articles=[], error=str(e))

    return FetchResult(source=source, articles=articles)


async def fetch_multiple_feeds(
    sources: list[NewsSource],
    concurrency: int = 5,
    timeout: float = 15.0,
) -> list[FetchResult]:
    """Fetch multiple RSS feeds concurrently.

    Args:
        sources: List of news sources to fetch
        concurrency: Maximum concurrent requests
        timeout: Request timeout per feed

    Returns:
        List of FetchResult for each source
    """
    semaphore = asyncio.Semaphore(concurrency)

    async def fetch_with_semaphore(source: NewsSource) -> FetchResult:
        async with semaphore:
            return await fetch_feed(source, timeout)

    tasks = [fetch_with_semaphore(source) for source in sources]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Convert exceptions to FetchResult with error
    processed_results: list[FetchResult] = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            processed_results.append(FetchResult(
                source=sources[i],
                articles=[],
                error=str(result)
            ))
        else:
            processed_results.append(result)

    return processed_results


async def fetch_all_feeds(
    sources: list[NewsSource],
    concurrency: int = 5,
    timeout: float = 15.0,
) -> tuple[list[ParsedArticle], list[FetchResult]]:
    """Fetch all feeds and return combined articles with results.

    Args:
        sources: List of news sources to fetch
        concurrency: Maximum concurrent requests
        timeout: Request timeout per feed

    Returns:
        Tuple of (all_articles, all_results)
    """
    results = await fetch_multiple_feeds(sources, concurrency, timeout)

    all_articles: list[ParsedArticle] = []
    errors: list[FetchResult] = []

    for result in results:
        all_articles.extend(result.articles)
        if result.error:
            errors.append(result)

    return all_articles, results
