"""Generic async-SQLAlchemy pagination helper (audit B.8).

``routers/news.py`` had 4 near-identical pagination blocks (count stmt
+ page stmt + ``has_more=(offset+limit) < total``).  This helper
collapses them to one call.

Usage::

    from app.services.pagination import paginate

    total, items, has_more = await paginate(
        db, count_stmt, page_stmt, offset=offset, limit=limit,
    )
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession


async def paginate(
    db: AsyncSession,
    count_stmt: Any,
    page_stmt: Any,
    offset: int,
    limit: int,
    *,
    precomputed_total: int | None = None,
) -> tuple[int, list[Any], bool]:
    """Run a count + page query and return ``(total, items, has_more)``.

    Args:
        db: Async SQLAlchemy session.
        count_stmt: A ``select(func.count())`` (or equivalent) statement.
            Ignored if ``precomputed_total`` is provided.
        page_stmt: A ``select(...)`` statement with ``.limit()`` and
            ``.offset()`` applied.
        offset: Pagination offset (echoed back for response building).
        limit: Pagination limit (echoed back for response building).
        precomputed_total: If the caller already ran the count query
            (e.g. for an early-exit 404 check), pass the result here to
            avoid a duplicate round-trip.

    Returns:
        ``(total, items, has_more)`` where ``has_more`` is True iff
        ``offset + limit < total`` (i.e. another page is available).
    """
    if precomputed_total is not None:
        total = precomputed_total
    else:
        total = (await db.scalar(count_stmt)) or 0
    result = await db.execute(page_stmt)
    items: list[Any] = list(result.scalars().all())
    has_more = (offset + limit) < total
    return total, items, has_more
