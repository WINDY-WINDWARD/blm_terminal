"""News aggregator service - orchestrates RSS fetching and NLP processing.

This module combines RSS parsing with NLP analysis and database storage.
"""

import asyncio
import json
import logging
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.news import NewsArticle
from app.services.nlp_service import analyze_article_dict, Sentiment
from app.services.rss_parser import ParsedArticle, fetch_all_feeds, FetchResult
from app.services.news_sources import (
    ALL_SOURCES,
    HIGH_PRIORITY_SOURCES,
    NewsSource,
    SOURCES_BY_ID,
    get_source_by_id,
)

logger = logging.getLogger(__name__)

# Concurrency settings
DEFAULT_CONCURRENCY = 5
FETCH_TIMEOUT = 15.0


def _parsed_article_to_db_dict(article: ParsedArticle) -> dict[str, Any]:
    """Convert a ParsedArticle to a dictionary suitable for database insertion."""
    # Perform NLP analysis
    nlp = analyze_article_dict(
        headline=article.title or "",
        summary=article.summary or "",
        source_name=article.source_name,
    )

    return {
        "url": article.url,
        "source": article.source_id,
        "title": article.title,
        "text": article.summary,  # Use summary as text
        "publish_date": article.published,
        "fetched_at": datetime.now(timezone.utc),
        # New NLP fields
        "sentiment": nlp["sentiment"],
        "sentiment_score": nlp["sentiment_score"],
        "confidence": nlp["confidence"],
        "language": nlp["language"],
        "entities": json.dumps(nlp["entities"]),
        "threat_level": nlp["threat_level"],
        "threat_category": nlp["threat_category"],
        "source_credibility": nlp["source_credibility"],
    }


async def fetch_and_process_source(
    source: NewsSource,
    concurrency: int = DEFAULT_CONCURRENCY,
    timeout: float = FETCH_TIMEOUT,
) -> tuple[list[dict[str, Any]], FetchResult]:
    """Fetch a single source and process articles with NLP.

    Returns tuple of (processed_article_dicts, fetch_result).
    """
    results = await fetch_all_feeds([source], concurrency=concurrency, timeout=timeout)
    result = results[0]

    processed: list[dict[str, Any]] = []
    for article in result.articles:
        try:
            article_dict = _parsed_article_to_db_dict(article)
            processed.append(article_dict)
        except Exception as e:
            logger.debug(f"Failed to process article {article.url}: {e}")

    return processed, result


async def fetch_and_process_all(
    concurrency: int = DEFAULT_CONCURRENCY,
    timeout: float = FETCH_TIMEOUT,
    sources: list[NewsSource] | None = None,
) -> tuple[list[dict[str, Any]], list[FetchResult]]:
    """Fetch all sources and process articles with NLP.

    Args:
        concurrency: Max concurrent requests
        timeout: Request timeout per feed
        sources: Specific sources to fetch (default: all sources)

    Returns:
        Tuple of (all_processed_articles, all_fetch_results)
    """
    if sources is None:
        sources = ALL_SOURCES

    all_articles, results = await fetch_all_feeds(sources, concurrency, timeout)

    processed: list[dict[str, Any]] = []
    for article in all_articles:
        try:
            article_dict = _parsed_article_to_db_dict(article)
            processed.append(article_dict)
        except Exception as e:
            logger.debug(f"Failed to process article {article.url}: {e}")

    return processed, results


async def store_articles(
    db: AsyncSession,
    articles: list[dict[str, Any]],
    batch_size: int = 50,
) -> int:
    """Store articles in database with upsert (skip duplicates).

    Args:
        db: Database session
        articles: List of article dictionaries
        batch_size: Number of articles per batch

    Returns:
        Number of articles stored
    """
    stored = 0

    for i in range(0, len(articles), batch_size):
        batch = articles[i:i + batch_size]

        for article in batch:
            try:
                # Convert datetime objects to strings for JSON serialization
                if article.get("publish_date"):
                    if hasattr(article["publish_date"], "isoformat"):
                        article["publish_date"] = article["publish_date"].isoformat()

                stmt = sqlite_insert(NewsArticle).values(article)
                stmt = stmt.on_conflict_do_nothing(index_elements=["url"])
                await db.execute(stmt)
                stored += 1
            except Exception as e:
                logger.debug(f"Failed to store article {article.get('url')}: {e}")

    await db.commit()
    return stored


async def fetch_store_and_return(
    db: AsyncSession,
    concurrency: int = DEFAULT_CONCURRENCY,
    timeout: float = FETCH_TIMEOUT,
    sources: list[NewsSource] | None = None,
) -> tuple[list[dict[str, Any]], list[FetchResult]]:
    """Fetch, process with NLP, and store all articles.

    Returns:
        Tuple of (stored_articles, fetch_results)
    """
    processed, results = await fetch_and_process_all(
        concurrency=concurrency,
        timeout=timeout,
        sources=sources,
    )

    if processed:
        await store_articles(db, processed)

    return processed, results


async def fetch_source_by_id(
    db: AsyncSession,
    source_id: str,
    concurrency: int = DEFAULT_CONCURRENCY,
    timeout: float = FETCH_TIMEOUT,
) -> tuple[list[dict[str, Any]], FetchResult | None]:
    """Fetch and process articles from a specific source by ID.

    Returns:
        Tuple of (processed_articles, fetch_result or None if source not found)
    """
    source = get_source_by_id(source_id)
    if not source:
        return [], None

    processed, result = await fetch_and_process_source(source, concurrency, timeout)

    if processed:
        await store_articles(db, processed)

    return processed, result


async def get_stored_articles(
    db: AsyncSession,
    sources: list[str] | None = None,
    categories: list[str] | None = None,
    sentiment: str | None = None,
    threat_level: str | None = None,
    language: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[NewsArticle], int]:
    """Get stored articles with optional filtering.

    Returns:
        Tuple of (articles, total_count)
    """
    # Build query
    conditions = []
    if sources:
        conditions.append(NewsArticle.source.in_(sources))
    if sentiment:
        conditions.append(NewsArticle.sentiment == sentiment.upper())
    if threat_level:
        conditions.append(NewsArticle.threat_level == threat_level.upper())
    if language:
        conditions.append(NewsArticle.language == language.lower())

    # Build and execute count query
    count_query = select(NewsArticle)
    if conditions:
        from sqlalchemy import and_
        count_query = count_query.where(and_(*conditions))

    from sqlalchemy import func
    count_query = select(func.count()).select_from(count_query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Build and execute main query
    query = select(NewsArticle).order_by(NewsArticle.publish_date.desc())
    if conditions:
        from sqlalchemy import and_
        query = query.where(and_(*conditions))
    query = query.limit(limit).offset(offset)

    result = await db.execute(query)
    articles = list(result.scalars().all())

    return articles, total


def article_to_dict(article: NewsArticle) -> dict[str, Any]:
    """Convert a NewsArticle ORM object to a dictionary."""
    result = {
        "url": article.url,
        "source": article.source,
        "title": article.title,
        "text": article.text,
        "publish_date": article.publish_date.isoformat() if article.publish_date else None,
        "fetched_at": article.fetched_at.isoformat() if article.fetched_at else None,
        "company_symbol": article.company_symbol,
    }

    # Add new NLP fields if they exist
    if hasattr(article, "sentiment") and article.sentiment:
        result["sentiment"] = article.sentiment
    if hasattr(article, "sentiment_score") and article.sentiment_score is not None:
        result["sentiment_score"] = article.sentiment_score
    if hasattr(article, "confidence") and article.confidence is not None:
        result["confidence"] = article.confidence
    if hasattr(article, "language") and article.language:
        result["language"] = article.language
    if hasattr(article, "entities") and article.entities:
        result["entities"] = article.entities if isinstance(article.entities, dict) else json.loads(article.entities)
    if hasattr(article, "threat_level") and article.threat_level:
        result["threat_level"] = article.threat_level
    if hasattr(article, "threat_category") and article.threat_category:
        result["threat_category"] = article.threat_category
    if hasattr(article, "source_credibility") and article.source_credibility:
        result["source_credibility"] = article.source_credibility

    return result
