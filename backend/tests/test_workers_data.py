"""Pin the move of 7 ticker-data worker daemons to app.workers.{universe,data,ticker_compute}.

Audit C.1, A.9 step 2.  The 7 workers moved from
``app/backgroundtasks/_impl.py`` to 3 new modules:
- ``app.workers.universe`` — stock_universe_worker
- ``app.workers.data`` — ticker_backfill_worker, ticker_daily_update_worker,
  ticker_intraday_hourly_update_worker
- ``app.workers.ticker_compute`` — ticker_scores_worker, ticker_indicators_worker,
  ticker_intraday_hourly_indicators_worker

Contracts pinned here:
1. Each worker symbol exists on its canonical module (final home).
2. Each worker symbol does NOT exist on ``app.backgroundtasks._impl``
   (move is complete, no stale local copy).
3. Each worker symbol is re-exported from the package shim
   ``app.backgroundtasks`` with ``is``-identity to the new home.
4. Size sentinel: each of the 3 modules ≤ 200 LOC.
5. Each worker's ``__module__`` points at the canonical home
   (catches accidental re-wrapping via the shim).
"""
from __future__ import annotations

import importlib
import os

import pytest


WORKER_HOMES = {
    "stock_universe_worker": "app.workers.universe",
    "ticker_backfill_worker": "app.workers.data",
    "ticker_daily_update_worker": "app.workers.data",
    "ticker_intraday_hourly_update_worker": "app.workers.data",
    "ticker_scores_worker": "app.workers.ticker_compute",
    "ticker_indicators_worker": "app.workers.ticker_compute",
    "ticker_intraday_hourly_indicators_worker": "app.workers.ticker_compute",
}

WORKER_NAMES = list(WORKER_HOMES.keys())


@pytest.fixture(scope="module")
def backgroundtasks():
    return importlib.import_module("app.backgroundtasks")


@pytest.fixture(scope="module")
def bg_impl():
    return importlib.import_module("app.backgroundtasks._impl")


@pytest.fixture(scope="module")
def homes():
    return {mod: importlib.import_module(mod) for mod in set(WORKER_HOMES.values())}


@pytest.mark.parametrize("name,home_module", list(WORKER_HOMES.items()))
def test_worker_lives_in_canonical_module(homes, name: str, home_module: str) -> None:
    assert hasattr(homes[home_module], name), (
        f"{name!r} not on {home_module} — move not complete"
    )


@pytest.mark.parametrize("name", WORKER_NAMES)
def test_worker_not_in_impl(bg_impl, name: str) -> None:
    assert not hasattr(bg_impl, name), (
        f"{name!r} still on app.backgroundtasks._impl — "
        "stale local copy, remove it from _impl"
    )


@pytest.mark.parametrize("name,home_module", list(WORKER_HOMES.items()))
def test_worker_reexported_via_shim_with_is_identity(homes, backgroundtasks, name: str, home_module: str) -> None:
    shim_attr = getattr(backgroundtasks, name)
    final_attr = getattr(homes[home_module], name)
    assert shim_attr is final_attr, (
        f"app.backgroundtasks.{name} is NOT {home_module}.{name} — "
        "shim must re-export the same object (drift-proof identity)"
    )


@pytest.mark.parametrize("name,home_module", list(WORKER_HOMES.items()))
def test_worker_module_attribute_is_canonical_home(homes, name: str, home_module: str) -> None:
    """`__module__` should be the canonical home, not the shim.

    If the shim does `from app.workers.X import foo` and you look up
    `foo` via `app.backgroundtasks.foo`, the function's `__module__`
    is still `app.workers.X` (not `app.backgroundtasks`).  This
    guards against accidental `app.backgroundtasks.foo = some_wrapper`
    shadowing.
    """
    fn = getattr(homes[home_module], name)
    assert fn.__module__ == home_module


@pytest.mark.parametrize("home_module", sorted(set(WORKER_HOMES.values())))
def test_workers_module_size_sentinel(home_module: str) -> None:
    """Workers modules cap at 200 LOC (audit contract)."""
    rel = home_module.replace(".", os.sep) + ".py"
    p = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "app", "workers", rel.split(os.sep)[-1])
    )
    with open(p) as f:
        loc = sum(1 for _ in f)
    assert loc <= 200, f"{p} is {loc} LOC, max 200"


def test_workers_signature_smoke(homes) -> None:
    """All 7 workers are zero-arg callables."""
    import inspect

    for name, home_module in WORKER_HOMES.items():
        fn = getattr(homes[home_module], name)
        sig = inspect.signature(fn)
        assert len(sig.parameters) == 0, f"{name} should be zero-arg"


def test_workers_callable_smoke(backgroundtasks) -> None:
    """Re-export smoke: each name is callable from the package shim."""
    for name in WORKER_NAMES:
        attr = getattr(backgroundtasks, name)
        assert callable(attr), f"app.backgroundtasks.{name} is not callable"
