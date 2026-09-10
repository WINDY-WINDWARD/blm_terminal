"""In-flight request coalescing registry.

Prevents duplicate concurrent upstream requests for the same symbol/resource
from multiple widgets (e.g. Chart + Screener).
"""
from __future__ import annotations

import asyncio
from typing import Any, Callable, Coroutine

_in_flight: dict[str, asyncio.Task] = {}
_semaphore: asyncio.Semaphore | None = None  # Lazy-init to avoid binding to wrong event loop


def _get_semaphore() -> asyncio.Semaphore:
    """Return the module-level semaphore, creating it on first use inside a running loop."""
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(5)  # Max 5 concurrent upstream fetches
    return _semaphore


async def coalesce(key: str, coro_fn: Callable[[], Coroutine[Any, Any, Any]]) -> Any:
    """Coalesce multiple concurrent calls with the same key into a single execution."""
    task = _in_flight.get(key)
    if task is not None and not task.done():
        return await task

    async def _runner():
        async with _get_semaphore():
            return await coro_fn()

    task = asyncio.create_task(_runner())
    _in_flight[key] = task
    try:
        return await task
    finally:
        if _in_flight.get(key) is task:
            _in_flight.pop(key, None)
