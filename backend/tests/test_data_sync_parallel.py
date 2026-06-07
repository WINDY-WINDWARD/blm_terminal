"""Tests for the parallel sync core extraction (audit C.1, A.11 part 1).

Moves 1 function from ``app/backgroundtasks/_impl.py`` into
``app/services/data_sync/parallel.py``:

- ``_parallel_indicator_sync()`` — thin wrapper around
  ``app.services.parallel_sync.parallel_indicator_sync`` that wires
  in the orchestrator's ``_shutdown_event``, ``update_job_status``
  callbacks, and default logging.

Tests pin the refactor invariants:

- ``parallel.py`` is a small file (Pattern I: < 200 LOC).
- The function now lives in ``app.services.data_sync.parallel``
  (``__module__`` attribute).
- It is the SAME object (``is``) as its backgroundtasks
  re-export (drift-proof: prevents accidental re-definition).
- The re-export shim in ``app.backgroundtasks`` still works.
- The function signature is preserved (caller compat).
- A trivial call to the wrapper delegates to
  ``parallel_sync.parallel_indicator_sync`` with the expected
  arguments (smoke test that the lazy wiring is correct).
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


# ─── Module size regression check ──────────────────────────────────────────


class TestParallelModuleSize:
    """``parallel.py`` must be small.  If a future commit
    accidentally adds bulk logic here, this test fails.
    """

    def test_parallel_file_under_200_loc(self):
        path = (
            ROOT / "app" / "services" / "data_sync" / "parallel.py"
        )
        assert path.exists(), f"parallel.py not found at {path}"
        loc = sum(1 for _ in path.read_text().splitlines())
        # _parallel_indicator_sync wrapper is ~60 LOC.  Allow 200
        # for imports + docstring + lazy-resolve helpers.
        assert loc < 200, (
            f"parallel.py is {loc} LOC, expected < 200.  This file "
            f"should only contain the parallel sync core + helpers.  "
            f"If you added more, move it to a sibling module."
        )


# ─── __module__ check ─────────────────────────────────────────────────────


class TestParallelCoreExtraction:
    """The wrapper now lives in ``app.services.data_sync.parallel``."""

    def test_function_lives_in_parallel_module(self):
        from app.services.data_sync.parallel import _parallel_indicator_sync

        assert _parallel_indicator_sync.__module__ == (
            "app.services.data_sync.parallel"
        ), (
            f"Expected _parallel_indicator_sync.__module__ to be "
            f"'app.services.data_sync.parallel', got "
            f"{_parallel_indicator_sync.__module__!r}"
        )

    def test_function_importable_from_backgroundtasks_shim(self):
        """Existing callers use ``from app.backgroundtasks import
        _parallel_indicator_sync``.  The shim must re-export it."""
        from app.backgroundtasks import _parallel_indicator_sync as bg_fn
        from app.services.data_sync.parallel import _parallel_indicator_sync as new_fn

        assert bg_fn is new_fn, (
            "app.backgroundtasks._parallel_indicator_sync is not the "
            "same object as app.services.data_sync.parallel."
            "_parallel_indicator_sync — re-export broken"
        )

    def test_function_signature_preserved(self):
        """Callers depend on the exact signature; refactor must not
        rename/remove/change parameter order."""
        from app.services.data_sync.parallel import _parallel_indicator_sync

        sig = inspect.signature(_parallel_indicator_sync)
        params = list(sig.parameters)
        assert params == [
            "items",
            "prepare_fn",
            "flush_fn",
            "job_key",
            "pipeline_job_key",
            "pipeline_progress_start",
            "pipeline_progress_end",
            "num_compute_workers",
            "queue_maxsize",
            "writer_batch_size",
            "heartbeat_every_s",
            "progress_every",
            "slow_threshold_s",
        ], (
            f"Signature drift in _parallel_indicator_sync — "
            f"parameters changed: {params}"
        )

    def test_function_signature_default_values(self):
        """Defaults are part of the public contract — pin them."""
        from app.services.data_sync.parallel import _parallel_indicator_sync

        sig = inspect.signature(_parallel_indicator_sync)
        defaults = {
            name: p.default
            for name, p in sig.parameters.items()
            if p.default is not inspect.Parameter.empty
        }
        assert defaults == {
            "pipeline_job_key": None,
            "pipeline_progress_start": None,
            "pipeline_progress_end": None,
            "num_compute_workers": 3,
            "queue_maxsize": 100,
            "writer_batch_size": 50,
            "heartbeat_every_s": 10.0,
            "progress_every": 10,
            "slow_threshold_s": 5.0,
        }, f"Default value drift: {defaults}"


# ─── Lazy wiring smoke test ───────────────────────────────────────────────


class TestParallelCoreWiring:
    """The wrapper must pass the orchestrator's ``_shutdown_event``
    and the ``update_job_status_sync`` callback into the underlying
    ``parallel_indicator_sync``.  We patch the underlying call and
    inspect the kwargs to verify.
    """

    def test_wrapper_passes_shutdown_event_and_update_job(self):
        from app.services.data_sync.parallel import _parallel_indicator_sync

        captured: dict = {}

        def fake_parallel(**kwargs):
            captured.update(kwargs)
            return {"wrote": 0, "errors": 0}

        # Stub the downstream helper that the wrapper imports lazily.
        fake_module = type(sys)("fake")
        fake_module.parallel_indicator_sync = fake_parallel
        with patch.dict(sys.modules, {"app.services.parallel_sync": fake_module}):
            # Stub update_job_status_sync via its canonical home
            # (A.13 — the wrapper imports directly from
            # ``app.jobs.runner``, not via the shim).
            from app.backgroundtasks import _runtime
            from app.jobs import runner as jobs_runner

            captured_status: list = []
            with patch.object(
                jobs_runner,
                "update_job_status_sync",
                side_effect=lambda *a, **kw: captured_status.append((a, kw)),
            ):
                _parallel_indicator_sync(
                    items=[("sym1",)],
                    prepare_fn=lambda *a: [{"id": 1}],
                    flush_fn=lambda rows: None,
                    job_key="job.test",
                )

        # The wrapper must wire the shutdown event from _runtime
        # and the status callback that calls update_job_status_sync.
        assert captured["shutdown_event"] is _runtime._shutdown_event
        assert callable(captured["update_job_status_fn"])
        assert captured["job_key"] == "job.test"
        assert captured["items"] == [("sym1",)]
        # Defaults forwarded
        assert captured["num_compute_workers"] == 3
        assert captured["queue_maxsize"] == 100
        # Heartbeat + progress callbacks installed
        assert callable(captured["heartbeat_fn"])
        assert callable(captured["progress_fn"])

    def test_update_job_callback_calls_update_job_status_sync(self):
        from app.services.data_sync.parallel import _parallel_indicator_sync

        captured: dict = {}

        def fake_parallel(**kwargs):
            captured.update(kwargs)
            return {"wrote": 0, "errors": 0}

        fake_module = type(sys)("fake")
        fake_module.parallel_indicator_sync = fake_parallel
        with patch.dict(sys.modules, {"app.services.parallel_sync": fake_module}):
            from app.jobs import runner as jobs_runner

            status_calls: list = []
            with patch.object(
                jobs_runner,
                "update_job_status_sync",
                side_effect=lambda key, status, **kw: status_calls.append((key, status, kw)),
            ):
                _parallel_indicator_sync(
                    items=[],
                    prepare_fn=lambda *a: [],
                    flush_fn=lambda rows: None,
                    job_key="job.test",
                )
                # Invoke the wrapped update_job callback
                captured["update_job_status_fn"]("job.test", "running", 50, "halfway")

        assert status_calls == [
            ("job.test", "running", {"progress": 50, "message": "halfway"})
        ]
