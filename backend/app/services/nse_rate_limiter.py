"""
Shared NSE rate limiter — used by both the REST API (nonpersistence.py)
and the MCP server (mcp_server.py).

Provides:
- A global semaphore limiting concurrent NSE requests (default: 2)
- Per-endpoint courtesy delay to avoid flooding NSE
- Request coalescing: in-flight requests are shared, not duplicated
- A circuit breaker with OPEN → HALF_OPEN → CLOSED recovery
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import defaultdict

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

NSE_CONCURRENCY_LIMIT: int = int(os.getenv("NSE_CONCURRENCY", "2"))
NSE_COURTESY_DELAY_SECONDS: float = float(os.getenv("NSE_COURTESY_DELAY", "1.5"))
CIRCUIT_FAIL_MAX: int = int(os.getenv("NSE_CIRCUIT_FAIL_MAX", "5"))
CIRCUIT_RESET_TIMEOUT: float = float(os.getenv("NSE_CIRCUIT_RESET_TIMEOUT", "60.0"))

# ---------------------------------------------------------------------------
# Global semaphore — limits concurrent NSE requests across ALL endpoints
# ---------------------------------------------------------------------------

_nse_semaphore = asyncio.Semaphore(NSE_CONCURRENCY_LIMIT)

# ---------------------------------------------------------------------------
# Per-endpoint courtesy delay tracking
# ---------------------------------------------------------------------------

_endpoint_locks: dict[str, asyncio.Lock] = {}
_last_request_at: dict[str, float] = defaultdict(float)


def _get_endpoint_lock(key: str) -> asyncio.Lock:
    """Get or create a lock for the given endpoint key."""
    if key not in _endpoint_locks:
        _endpoint_locks[key] = asyncio.Lock()
    return _endpoint_locks[key]


# ---------------------------------------------------------------------------
# Request coalescing — deduplicate in-flight requests
# ---------------------------------------------------------------------------

_inflight: dict[str, asyncio.Future] = {}


# ---------------------------------------------------------------------------
# Circuit breaker state
# ---------------------------------------------------------------------------

_CONSECUTIVE_FAILURES: dict[str, int] = defaultdict(int)
_CIRCUIT_OPEN: dict[str, bool] = defaultdict(bool)
_CIRCUIT_OPENED_AT: dict[str, float] = defaultdict(float)
_CIRCUIT_HALF_OPEN: dict[str, bool] = defaultdict(bool)


class NSEServiceUnavailableError(Exception):
    """Raised when the NSE circuit breaker is open."""
    pass


def _check_circuit(endpoint_name: str) -> None:
    """
    Check if the circuit is open for this endpoint.

    State machine:
      CLOSED  → normal operation, proceed
      OPEN    → check if CIRCUIT_RESET_TIMEOUT has elapsed
                - If yes: transition to HALF_OPEN, allow this probe through
                - If no: raise NSEServiceUnavailableError immediately
      HALF_OPEN → allow through (this is the probe request)
                   - Success → CLOSED (via _record_success)
                   - Failure → OPEN (via _record_failure, timer restarts)
    """
    if not _CIRCUIT_OPEN.get(endpoint_name, False):
        return

    if _CIRCUIT_HALF_OPEN.get(endpoint_name, False):
        return

    elapsed = time.monotonic() - _CIRCUIT_OPENED_AT.get(endpoint_name, 0)
    if elapsed >= CIRCUIT_RESET_TIMEOUT:
        _CIRCUIT_HALF_OPEN[endpoint_name] = True
        logger.info(
            "Circuit breaker HALF_OPEN for '%s' — allowing probe request after %.0fs",
            endpoint_name,
            elapsed,
        )
        return

    raise NSEServiceUnavailableError(
        f"Circuit breaker is OPEN for '{endpoint_name}' "
        f"(opened {elapsed:.0f}s ago, reset after {CIRCUIT_RESET_TIMEOUT:.0f}s). "
        f"Will retry automatically."
    )


def _record_success(endpoint_name: str) -> None:
    """Reset all circuit breaker state on a successful call."""
    _CONSECUTIVE_FAILURES[endpoint_name] = 0
    _CIRCUIT_OPEN[endpoint_name] = False
    _CIRCUIT_HALF_OPEN[endpoint_name] = False


def _record_failure(endpoint_name: str) -> None:
    """
    Increment failure count; open circuit if threshold is reached.

    Timer restart rule: _CIRCUIT_OPENED_AT is reset when:
      (a) The circuit first transitions CLOSED → OPEN (first failure batch)
      (b) The circuit transitions HALF_OPEN → OPEN (probe failure)

    Without (b), a probe failure would leave _CIRCUIT_OPENED_AT at the time of
    the original open, and the next _check_circuit() would immediately see
    elapsed >= CIRCUIT_RESET_TIMEOUT again, letting another probe through — turning
    the circuit into a permanent HALF_OPEN state.
    """
    _CONSECUTIVE_FAILURES[endpoint_name] += 1
    if _CONSECUTIVE_FAILURES[endpoint_name] >= CIRCUIT_FAIL_MAX:
        was_half_open = _CIRCUIT_HALF_OPEN.get(endpoint_name, False)
        was_already_open = _CIRCUIT_OPEN.get(endpoint_name, False)
        _CIRCUIT_OPEN[endpoint_name] = True
        _CIRCUIT_HALF_OPEN[endpoint_name] = False
        if not was_already_open or was_half_open:
            _CIRCUIT_OPENED_AT[endpoint_name] = time.monotonic()
        logger.warning(
            "Circuit breaker OPEN for '%s' after %d consecutive failures "
            "(half_open_probe_failed=%s, timer_restarted=%s)",
            endpoint_name,
            CIRCUIT_FAIL_MAX,
            was_half_open,
            not was_already_open or was_half_open,
        )


async def throttled_nse_call(
    endpoint_name: str,
    fn,
    *args,
    is_async_fn: bool = False,
):
    """
    Execute an NSE API call with global concurrency limiting, per-endpoint
    courtesy delay, request coalescing, and circuit breaker protection.

    The circuit breaker implements: CLOSED → OPEN → HALF_OPEN → CLOSED.

    Args:
        endpoint_name: Key for per-endpoint lock and courtesy delay tracking.
        fn: Callable to execute. If is_async_fn=True, awaited directly.
            Otherwise run in asyncio.to_thread().
        *args: Positional arguments passed to fn.
        is_async_fn: True when fn is async (Phase 2+), False when using to_thread().

    Returns:
        The result of fn(*args).

    Raises:
        NSEServiceUnavailableError: If the circuit is open for this endpoint.
    """
    _check_circuit(endpoint_name)

    running_loop = asyncio.get_running_loop()

    if endpoint_name in _inflight:
        inflight_future = _inflight[endpoint_name]
        logger.debug(
            "Coalescing request for '%s' — waiting for in-flight result (id=%s)",
            endpoint_name,
            id(inflight_future),
        )
        try:
            return await inflight_future
        except Exception:
            logger.debug("In-flight request for '%s' failed, will retry", endpoint_name)
            del _inflight[endpoint_name]

    inflight_future = running_loop.create_future()
    _inflight[endpoint_name] = inflight_future

    try:
        async with _nse_semaphore:
            endpoint_lock = _get_endpoint_lock(endpoint_name)
            async with endpoint_lock:
                elapsed = time.monotonic() - _last_request_at[endpoint_name]
                wait = NSE_COURTESY_DELAY_SECONDS - elapsed
                if wait > 0:
                    logger.debug(
                        "NSE courtesy delay: sleeping %.2fs before '%s' request",
                        wait,
                        endpoint_name,
                    )
                    await asyncio.sleep(wait)

                try:
                    if is_async_fn:
                        result = await fn(*args)
                    else:
                        result = await asyncio.to_thread(fn, *args)
                    _record_success(endpoint_name)
                    inflight_future.set_result(result)
                    return result
                except Exception as exc:
                    _record_failure(endpoint_name)
                    inflight_future.set_exception(exc)
                    raise
                finally:
                    _last_request_at[endpoint_name] = time.monotonic()

    finally:
        if endpoint_name in _inflight and _inflight[endpoint_name] is inflight_future:
            del _inflight[endpoint_name]
