"""Tests for audit B.7 — consolidate 3 rate limiters behind ``throttled_nse_call``.

Three ``asyncio.Semaphore`` instances existed:

  - ``nse_rate_limiter._nse_semaphore`` (with the existing
    ``throttled_nse_call`` wrapper)
  - ``screener_client._screener_semaphore`` (5 call sites)
  - ``morningstar_client.MorningstarClient._semaphore`` (1 call site)

The audit consolidates all 3 to use the shared ``throttled_nse_call``
wrapper so NSE, screener.in, and morningstar.in requests share one
global concurrency budget (limit=2 by default) and the per-endpoint
courtesy delay, circuit breaker, and request coalescing benefit all
callers.

The refactor must NOT change observable behaviour for legitimate
callers: the HTTP method still runs, the courtesy delay still applies,
the circuit breaker still opens after CIRCUIT_FAIL_MAX failures, and
the result is still returned.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import nse_rate_limiter, screener_client, morningstar_client


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_rate_limiter_state():
    """Reset all rate-limiter module-level state between tests.

    The semaphore, endpoint locks, inflight futures, and circuit
    breaker dicts are module-level.  We clear them (without restoring)
    so a test that opens the circuit or creates an in-flight future
    does not leak loop-bound objects into the next test.
    """
    nse_rate_limiter._inflight.clear()
    nse_rate_limiter._endpoint_locks.clear()
    nse_rate_limiter._last_request_at.clear()
    nse_rate_limiter._CONSECUTIVE_FAILURES.clear()
    nse_rate_limiter._CIRCUIT_OPEN.clear()
    nse_rate_limiter._CIRCUIT_OPENED_AT.clear()
    nse_rate_limiter._CIRCUIT_HALF_OPEN.clear()

    yield

    nse_rate_limiter._inflight.clear()
    nse_rate_limiter._endpoint_locks.clear()
    nse_rate_limiter._last_request_at.clear()
    nse_rate_limiter._CONSECUTIVE_FAILURES.clear()
    nse_rate_limiter._CIRCUIT_OPEN.clear()
    nse_rate_limiter._CIRCUIT_OPENED_AT.clear()
    nse_rate_limiter._CIRCUIT_HALF_OPEN.clear()


# ---------------------------------------------------------------------------
# B.7 — semaphore consolidation
# ---------------------------------------------------------------------------

class TestSemaphoresRemoved:
    """The two client-local semaphores must be removed; only the global
    ``nse_rate_limiter`` semaphore should remain."""

    def test_screener_module_has_no_local_semaphore(self) -> None:
        """screener_client must not define its own ``_screener_semaphore``."""
        assert not hasattr(screener_client, "_screener_semaphore"), (
            "screener_client still defines _screener_semaphore — B.7 refactor incomplete"
        )

    def test_morningstar_module_has_no_local_semaphore(self) -> None:
        """morningstar_client must not define a per-instance semaphore."""
        assert not hasattr(morningstar_client, "MAX_CONCURRENT_REQUESTS"), (
            "morningstar_client still defines MAX_CONCURRENT_REQUESTS — B.7 refactor incomplete"
        )
        # And the class must not store a per-instance semaphore
        client = morningstar_client.MorningstarClient()
        assert not hasattr(client, "_semaphore"), (
            "MorningstarClient._semaphore still exists — B.7 refactor incomplete"
        )


# ---------------------------------------------------------------------------
# B.7 — the call sites go through throttled_nse_call
# ---------------------------------------------------------------------------

class TestScreenerRoutesThroughThrottledCall:
    """The 5 screener HTTP calls must route through throttled_nse_call."""

    def test_screener_imports_throttled_nse_call(self) -> None:
        """screener_client must import throttled_nse_call."""
        from app.services import screener_client as sc

        assert hasattr(sc, "throttled_nse_call"), (
            "screener_client does not expose throttled_nse_call — must be imported"
        )

    def test_screener_call_sites_use_throttled_nse_call(self) -> None:
        """The 5 former ``async with _screener_semaphore:`` sites must be
        inside a throttled_nse_call() call.  We verify by inspecting the
        source — there must be ZERO remaining ``async with _screener``
        substrings (or ``MAX_CONCURRENT_REQUESTS`` from morningstar)."""
        import inspect
        from app.services import screener_client

        source = inspect.getsource(screener_client)
        # The old semaphore name must be gone
        assert "_screener_semaphore" not in source
        # And the courtesy delay constant used inside the semaphore
        # block must also be gone (the delay is now applied by
        # throttled_nse_call via NSE_COURTESY_DELAY_SECONDS).
        assert "_COURTESY_DELAY" not in source, (
            "screener_client still uses _COURTESY_DELAY — the delay is "
            "now applied by throttled_nse_call"
        )
        # throttled_nse_call must be referenced
        assert "throttled_nse_call" in source


class TestMorningstarRoutesThroughThrottledCall:
    """Morningstar's get_fair_value must route through throttled_nse_call."""

    def test_morningstar_imports_throttled_nse_call(self) -> None:
        from app.services import morningstar_client as mc
        assert hasattr(mc, "throttled_nse_call"), (
            "morningstar_client does not expose throttled_nse_call — must be imported"
        )

    def test_morningstar_call_site_uses_throttled_nse_call(self) -> None:
        import inspect
        from app.services import morningstar_client

        source = inspect.getsource(morningstar_client)
        assert "self._semaphore" not in source, (
            "morningstar_client still references self._semaphore"
        )
        assert "throttled_nse_call" in source


# ---------------------------------------------------------------------------
# B.7 — behavioural parity (the refactor preserves correct throttling)
# ---------------------------------------------------------------------------

class TestThrottledCallConcurrency:
    """The shared semaphore still enforces a global concurrency limit
    across all services."""

    def test_global_semaphore_limits_concurrency(self) -> None:
        """Even if screener, morningstar, and NSE all call at once,
        only NSE_CONCURRENCY_LIMIT (default 2) may be active at a
        time."""
        from app.services.nse_rate_limiter import throttled_nse_call, NSE_CONCURRENCY_LIMIT

        active = 0
        peak = 0
        lock = asyncio.Lock()

        async def slow():
            nonlocal active, peak
            async with lock:
                active += 1
                peak = max(peak, active)
            await asyncio.sleep(0.05)
            async with lock:
                active -= 1
            return "ok"

        async def go():
            return await asyncio.gather(*[
                throttled_nse_call(
                    f"test.concurrency.{i}", slow, is_async_fn=True
                )
                for i in range(8)
            ])

        asyncio.run(go())

        assert peak == NSE_CONCURRENCY_LIMIT, (
            f"global semaphore should cap at {NSE_CONCURRENCY_LIMIT}, "
            f"observed peak {peak}"
        )

    def test_courtesy_delay_applies_per_endpoint(self) -> None:
        """Two calls to the same endpoint with no gap should be spaced
        by NSE_COURTESY_DELAY_SECONDS."""
        from app.services.nse_rate_limiter import (
            throttled_nse_call,
            NSE_COURTESY_DELAY_SECONDS,
        )

        async def fast():
            return "ok"

        async def go():
            t0 = time.monotonic()
            await asyncio.gather(
                throttled_nse_call("test.delay.a", fast, is_async_fn=True),
                throttled_nse_call("test.delay.a", fast, is_async_fn=True),
            )
            return time.monotonic() - t0

        elapsed = asyncio.run(go())

        # The second call should wait ~NSE_COURTESY_DELAY_SECONDS.
        # Allow some slack.
        assert elapsed >= NSE_COURTESY_DELAY_SECONDS * 0.8, (
            f"expected >= {NSE_COURTESY_DELAY_SECONDS * 0.8:.2f}s elapsed, "
            f"got {elapsed:.2f}s — courtesy delay not applied"
        )

    def test_circuit_breaker_opens_after_failures(self) -> None:
        """After CIRCUIT_FAIL_MAX consecutive failures, the circuit
        opens and subsequent calls raise NSEServiceUnavailableError."""
        from app.services.nse_rate_limiter import (
            throttled_nse_call,
            CIRCUIT_FAIL_MAX,
            NSEServiceUnavailableError,
        )

        async def boom():
            raise RuntimeError("simulated NSE failure")

        async def drive_failures():
            for _ in range(CIRCUIT_FAIL_MAX):
                try:
                    await throttled_nse_call(
                        "test.cb.boom", boom, is_async_fn=True
                    )
                except RuntimeError:
                    pass
                else:
                    raise AssertionError("expected RuntimeError")

        asyncio.run(drive_failures())

        async def next_call():
            await throttled_nse_call(
                "test.cb.boom", boom, is_async_fn=True
            )

        with pytest.raises(NSEServiceUnavailableError):
            asyncio.run(next_call())
