"""Tests for the maintenance workers extraction (audit C.1, A.9).

Moves ``vacuum_worker`` from ``app/backgroundtasks/_impl.py`` to
``app/workers/maintenance.py``.

The original 4994-LOC ``app.backgroundtasks`` file is being split
into ``app/workers/`` and ``app/services/data_sync/`` modules.  This
test pins the refactor invariants:

- ``maintenance.py`` is a small file (Pattern I: < 200 LOC).
- The worker now lives in ``app.workers.maintenance``
  (``__module__`` attribute).
- It is the SAME object (``is``) as its backgroundtasks
  re-export (drift-proof: prevents accidental re-definition).
- The re-export shim in ``app.backgroundtasks`` and
  ``app.workers`` still works.
- All current callers (orchestrator, main.py) still work.
- The worker is importable from BOTH the new module and the
  old package (the bridge shim).
- The function signature is preserved.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


# ─── Module size regression check ──────────────────────────────────────────


class TestMaintenanceModuleSize:
    """``maintenance.py`` must be small.  If a future commit
    accidentally adds bulk logic here, this test fails.
    """

    def test_maintenance_file_under_200_loc(self):
        path = ROOT / "app" / "workers" / "maintenance.py"
        assert path.exists(), f"maintenance.py not found at {path}"
        loc = sum(1 for _ in path.read_text().splitlines())
        # vacuum_worker is ~45 LOC.  Allow 200 for imports + the
        # _run_vacuum helper + docstring.
        assert loc < 200, (
            f"maintenance.py is {loc} LOC, expected < 200.  This file "
            f"should only contain the maintenance workers.  If you "
            f"added more, move them to a sibling module."
        )


# ─── __module__ check ─────────────────────────────────────────────────────


MOVED_WORKERS = [
    "vacuum_worker",
]


class TestWorkersMovedToMaintenance:
    """The worker must have ``__module__ == 'app.workers.maintenance'``."""

    @pytest.mark.parametrize("name", MOVED_WORKERS)
    def test_worker_lives_in_maintenance_module(self, name):
        from app.workers import maintenance

        assert hasattr(maintenance, name), (
            f"maintenance.{name} not found — the move was incomplete"
        )
        fn = getattr(maintenance, name)
        assert fn.__module__ == "app.workers.maintenance", (
            f"{name}.__module__ is {fn.__module__!r}, expected "
            f"'app.workers.maintenance'.  The function was not moved "
            f"(or was re-defined locally)."
        )


# ─── Identity check ───────────────────────────────────────────────────────


class TestReExportIdentity:
    """The worker in ``maintenance`` must be the SAME object as its
    ``app.backgroundtasks`` and ``app.workers`` re-exports.
    """

    @pytest.mark.parametrize("name", MOVED_WORKERS)
    def test_maintenance_is_backgroundtasks(self, name):
        from app import backgroundtasks as bg
        from app import workers
        from app.workers import maintenance

        assert getattr(bg, name) is getattr(maintenance, name), (
            f"app.backgroundtasks.{name} is not the same object as "
            f"app.workers.maintenance.{name} — the re-export is "
            f"broken or the function was re-defined locally"
        )
        assert getattr(workers, name) is getattr(maintenance, name), (
            f"app.workers.{name} is not the same object as "
            f"app.workers.maintenance.{name} — the re-export shim "
            f"in app.workers is broken"
        )


# ─── Caller import smoke test ─────────────────────────────────────────────


class TestCallerImports:
    """All current callers must still work after the move."""

    def test_orchestrator_imports(self):
        from app import orchestrator  # noqa: F401

    def test_maintenance_module_imports(self):
        from app.workers import maintenance  # noqa: F401

    def test_legacy_imports_still_work(self):
        """The old import path ``from app.backgroundtasks import vacuum_worker``
        must still resolve (re-export shim).
        """
        from app.backgroundtasks import vacuum_worker
        assert callable(vacuum_worker)
        from app.workers import vacuum_worker as vw
        assert callable(vw)


# ─── Function signature preservation ──────────────────────────────────────


class TestFunctionSignaturesPreserved:
    """The worker must keep its original signature."""

    def test_vacuum_worker_signature(self):
        from app.workers.maintenance import vacuum_worker
        sig = inspect.signature(vacuum_worker)
        assert len(sig.parameters) == 0, (
            f"vacuum_worker should take no arguments, got {sig}"
        )
