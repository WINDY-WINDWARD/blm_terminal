"""Pin the move of 4 news + results calendar worker daemons to 2 new modules.

Audit C.1, A.9 step 4.  The workers moved from
``app/backgroundtasks/_impl.py`` to 2 new modules:
- ``app.workers.news`` — news_worker, news_rss_worker, watchlist_news_worker
- ``app.workers.market_calendar`` — results_calendar_worker

Note: ``market_data_worker`` was removed in a later refactor — market data
is now managed by ``Orchestrator`` as pipeline Stage 7 + a dedicated
``*/5 * * * *`` cron scheduler (``_run_market_data_scheduler``).

A.13: ``_impl.py`` is gone — the package shim
``app.backgroundtasks`` re-exports the workers from their final
homes, so callers do ``from app.backgroundtasks import <worker>``.

Contracts pinned here:
1. Each worker symbol exists on its canonical module (final home).
2. Each worker symbol is re-exported from the package shim
   ``app.backgroundtasks`` with ``is``-identity to the new home.
3. Size sentinel: each of the 2 modules ≤ 200 LOC.
4. Each worker's ``__module__`` points at the canonical home
   (catches accidental re-wrapping via the shim).
"""
from __future__ import annotations

import importlib
import os

import pytest


WORKER_HOMES = {
    "news_worker": "app.workers.news",
    "news_rss_worker": "app.workers.news",
    "watchlist_news_worker": "app.workers.news",
    "results_calendar_worker": "app.workers.market_calendar",
}

WORKER_NAMES = list(WORKER_HOMES.keys())


@pytest.fixture(scope="module")
def backgroundtasks():
    return importlib.import_module("app.backgroundtasks")


@pytest.fixture(scope="module")
def homes():
    return {mod: importlib.import_module(mod) for mod in set(WORKER_HOMES.values())}


@pytest.mark.parametrize("name,home_module", list(WORKER_HOMES.items()))
def test_worker_lives_in_canonical_module(homes, name: str, home_module: str) -> None:
    assert hasattr(homes[home_module], name), (
        f"{name!r} not on {home_module} — move not complete"
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
    """`__module__` should be the canonical home, not the shim."""
    fn = getattr(homes[home_module], name)
    assert fn.__module__ == home_module


@pytest.mark.parametrize("home_module", sorted(set(WORKER_HOMES.values())))
def test_workers_module_size_sentinel(home_module: str) -> None:
    """Workers modules cap at 200 LOC (audit contract)."""
    p = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "app", "workers",
                     os.path.basename(home_module.replace(".", os.sep)) + ".py")
    )
    with open(p) as f:
        loc = sum(1 for _ in f)
    assert loc <= 200, f"{p} is {loc} LOC, max 200"


def test_workers_signature_smoke(homes) -> None:
    """All 5 workers are zero-arg callables."""
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
