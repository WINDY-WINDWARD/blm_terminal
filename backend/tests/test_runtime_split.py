"""Pin the A.10 move: cross-cutting runtime helpers to app.backgroundtasks._runtime.

Audit C.1, A.10.  Moved from ``app/backgroundtasks/_impl.py`` to a
new module ``app/backgroundtasks/_runtime.py``:

Module-level state:
- ``_shutdown_event`` (threading.Event)
- ``_worker_threads`` (list[threading.Thread])
- ``_startup_stock_universe_done`` / ``_startup_ticker_backfill_done`` /
  ``_startup_ticker_indicators_done`` / ``_startup_ticker_scores_done`` /
  ``_startup_ticker_hourly_done``
- ``_pipeline_lock`` / ``_pipeline_idle``

Functions:
- ``_is_job_enabled``
- ``_wait_for_startup_event``, ``_wait_for_pipeline``
- ``get_async_shutdown_event``, ``reset_async_shutdown_event``,
  ``set_async_shutdown_event``
- ``_is_first_run``, ``_set_first_run_complete``
- ``_sleep_interruptible``, ``_run_async``, ``_seconds_until_next_cron``,
  ``_report_job_waiting``

Contracts pinned here:
1. Each symbol exists on ``app.backgroundtasks._runtime`` (final home).
2. Each symbol is re-exported from the package shim
   ``app.backgroundtasks`` with ``is``-identity to the new home.
   Workers do ``from app.backgroundtasks import X`` (or import
   lazily ``from app.backgroundtasks._runtime import X``).
3. Size sentinel: ``app/backgroundtasks/_runtime.py`` ≤ 300 LOC.

A.13 note: the intermediate ``_impl.py`` shim is gone.  All
runtime symbols now live exclusively in ``_runtime`` and are
re-exported by the package ``__init__.py`` with ``is``-identity.
"""
from __future__ import annotations

import importlib
import os

import pytest


RUNTIME_SYMBOLS = [
    # Module-level state
    "_shutdown_event",
    "_worker_threads",
    "_startup_stock_universe_done",
    "_startup_ticker_backfill_done",
    "_startup_ticker_indicators_done",
    "_startup_ticker_scores_done",
    "_startup_ticker_hourly_done",
    "_pipeline_lock",
    "_pipeline_idle",
    # Functions
    "_is_job_enabled",
    "_wait_for_startup_event",
    "_wait_for_pipeline",
    "get_async_shutdown_event",
    "reset_async_shutdown_event",
    "set_async_shutdown_event",
    "_is_first_run",
    "_set_first_run_complete",
    "_sleep_interruptible",
    "_run_async",
    "_seconds_until_next_cron",
    "_report_job_waiting",
]


@pytest.fixture(scope="module")
def runtime():
    return importlib.import_module("app.backgroundtasks._runtime")


@pytest.fixture(scope="module")
def backgroundtasks():
    return importlib.import_module("app.backgroundtasks")


@pytest.mark.parametrize("name", RUNTIME_SYMBOLS)
def test_symbol_lives_in_runtime_module(runtime, name: str) -> None:
    assert hasattr(runtime, name), (
        f"{name!r} not on app.backgroundtasks._runtime — move not complete"
    )


@pytest.mark.parametrize("name", RUNTIME_SYMBOLS)
def test_symbol_reexported_from_shim_with_is_identity(runtime, backgroundtasks, name: str) -> None:
    shim_attr = getattr(backgroundtasks, name, None)
    rt_attr = getattr(runtime, name, None)
    assert shim_attr is not None, f"app.backgroundtasks.{name} missing — shim re-export broken"
    assert shim_attr is rt_attr, (
        f"app.backgroundtasks.{name} is NOT app.backgroundtasks._runtime.{name} — "
        "shim must re-export with is-identity"
    )


def test_runtime_module_size_sentinel() -> None:
    """Runtime module caps at 300 LOC (audit contract)."""
    p = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "app", "backgroundtasks", "_runtime.py")
    )
    with open(p) as f:
        loc = sum(1 for _ in f)
    assert loc <= 300, f"{p} is {loc} LOC, max 300"


def test_runtime_helpers_are_callable_or_state(runtime) -> None:
    """Sanity: each function is callable, each state object is the right type."""
    import threading

    callable_names = [
        "_is_job_enabled",
        "_wait_for_startup_event",
        "_wait_for_pipeline",
        "get_async_shutdown_event",
        "reset_async_shutdown_event",
        "set_async_shutdown_event",
        "_is_first_run",
        "_set_first_run_complete",
        "_sleep_interruptible",
        "_run_async",
        "_seconds_until_next_cron",
        "_report_job_waiting",
    ]
    for name in callable_names:
        attr = getattr(runtime, name)
        assert callable(attr), f"{name} should be callable"

    # State objects
    assert isinstance(runtime._shutdown_event, threading.Event)
    assert isinstance(runtime._pipeline_lock, type(threading.Lock()))
    assert isinstance(runtime._pipeline_idle, threading.Event)
    assert isinstance(runtime._startup_stock_universe_done, threading.Event)
    assert isinstance(runtime._startup_ticker_backfill_done, threading.Event)
    assert isinstance(runtime._startup_ticker_indicators_done, threading.Event)
    assert isinstance(runtime._startup_ticker_scores_done, threading.Event)
    assert isinstance(runtime._startup_ticker_hourly_done, threading.Event)
    assert isinstance(runtime._worker_threads, list)
