"""Tests for the new ``app.services.data_sync`` package skeleton
(audit C.1, A.2).

After Phase C.1 A.1 split ``app/backgroundtasks`` into a package,
A.2 creates ``app/services/data_sync`` as the target home for the
sync cores (the business logic that runs in a worker thread).

This file tests the **skeleton**:

- The package is importable.
- Caller imports (``main.py``, ``orchestrator.py``) still work.

The actual re-exports from ``app.services.data_sync.X`` were
added in A.3-A.12.  The per-symbol re-export contract is
exhaustively pinned by
``tests/test_backgroundtasks_split.py::TestMovedWorkers`` (identity
to canonical home) and ``tests/test_workers_data.py`` / the
per-module split tests.  The previous ``TestSyncCoresStillAccessible``
class was removed in A.12 part 3 because it became redundant
(its assertions — "symbol is in ``_impl``" — are no longer
true post-A.3).
"""
from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


# ─── Package shape ────────────────────────────────────────────────────────


class TestDataSyncPackageShape:
    """``app.services.data_sync`` must be a package (not a module)."""

    def test_data_sync_is_a_package(self):
        spec = importlib.util.find_spec("app.services.data_sync")
        assert spec is not None, (
            "app.services.data_sync must be importable — this is "
            "the new home for the sync cores per audit C.1.A.2"
        )
        assert spec.submodule_search_locations is not None, (
            "app.services.data_sync must be a PACKAGE (with __init__.py), "
            "not a single module"
        )

    def test_data_sync_init_imports(self):
        pkg = importlib.import_module("app.services.data_sync")
        assert pkg is not None
        assert "__init__.py" in pkg.__file__


# ─── Caller import smoke test ─────────────────────────────────────────────


class TestCallerImports:
    """All current callers must still import."""

    def test_orchestrator_imports(self):
        from app import orchestrator  # noqa: F401

    def test_main_imports(self):
        import main  # noqa: F401

    def test_data_sync_package_imports(self):
        from app.services import data_sync  # noqa: F401
