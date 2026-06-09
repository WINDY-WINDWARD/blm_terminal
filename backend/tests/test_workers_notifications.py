"""Pin the move of 2 notification worker daemons to app.workers.notifications.

Audit C.1, A.9 step 3.  The 2 workers moved from
``app/backgroundtasks/_impl.py`` to ``app/workers/notifications.py``:
- ``watchlist_notification_worker``
- ``global_scan_worker``

A.13: ``_impl.py`` is gone — the package shim
``app.backgroundtasks`` re-exports the workers from their final
homes, so callers do ``from app.backgroundtasks import <worker>``.

Contracts pinned here:
1. Each worker symbol exists on ``app.workers.notifications`` (final home).
2. Each worker symbol is re-exported from the package shim
   ``app.backgroundtasks`` with ``is``-identity to the new home.
3. Size sentinel: ``app/workers/notifications.py`` ≤ 200 LOC.
4. Each worker's ``__module__`` points at the final home
   (catches accidental re-wrapping via the shim).
"""
from __future__ import annotations

import importlib
import os

import pytest


WORKER_NAMES = [
    "watchlist_notification_worker",
    "global_scan_worker",
]
HOME_MODULE = "app.workers.notifications"


@pytest.fixture(scope="module")
def notifications_module():
    return importlib.import_module(HOME_MODULE)


@pytest.fixture(scope="module")
def backgroundtasks():
    return importlib.import_module("app.backgroundtasks")


@pytest.mark.parametrize("name", WORKER_NAMES)
def test_worker_lives_in_notifications_module(notifications_module, name: str) -> None:
    assert hasattr(notifications_module, name), (
        f"{name!r} not on {HOME_MODULE} — move not complete"
    )


@pytest.mark.parametrize("name", WORKER_NAMES)
def test_worker_reexported_via_shim_with_is_identity(notifications_module, backgroundtasks, name: str) -> None:
    shim_attr = getattr(backgroundtasks, name)
    final_attr = getattr(notifications_module, name)
    assert shim_attr is final_attr, (
        f"app.backgroundtasks.{name} is NOT {HOME_MODULE}.{name} — "
        "shim must re-export the same object (drift-proof identity)"
    )


@pytest.mark.parametrize("name", WORKER_NAMES)
def test_worker_module_attribute_is_final_home(notifications_module, name: str) -> None:
    """`__module__` should be the canonical home, not the shim."""
    fn = getattr(notifications_module, name)
    assert fn.__module__ == HOME_MODULE


def test_notifications_module_size_sentinel() -> None:
    """Workers modules cap at 200 LOC (audit contract)."""
    p = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "app", "workers", "notifications.py")
    )
    with open(p) as f:
        loc = sum(1 for _ in f)
    assert loc <= 200, f"{p} is {loc} LOC, max 200"


def test_notifications_module_signature_smoke(notifications_module) -> None:
    """All workers are zero-arg callables."""
    import inspect

    for name in WORKER_NAMES:
        fn = getattr(notifications_module, name)
        sig = inspect.signature(fn)
        assert len(sig.parameters) == 0, f"{name} should be zero-arg"


def test_notifications_module_callable_smoke(backgroundtasks) -> None:
    """Re-export smoke: each name is callable from the package shim."""
    for name in WORKER_NAMES:
        attr = getattr(backgroundtasks, name)
        assert callable(attr), f"app.backgroundtasks.{name} is not callable"
