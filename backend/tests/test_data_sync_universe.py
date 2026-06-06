"""Tests for the universe sync core extraction (audit C.1, A.3).

Moves 3 functions from \`\`app/backgroundtasks/_impl.py\`\` into
\`\`app/services/data_sync/universe.py\`\`:

- \`\`_stock_universe_sync()\`\`       — NSE universe refresh (the
  sync core that \`\`stock_universe_worker\`\` runs)
- \`\`_update_symbol_error_status()\`\` — mark a symbol as 'unknown'
  after SymbolNotFoundError
- \`\`_bulk_insert_stock_universe()\`\` — batch INSERT to
  \`\`stock_universe\`\` table

Tests pin the refactor invariants:

- \`\`universe.py\`\` is a small file (Pattern I: < 200 LOC).
- The 3 symbols now live in \`\`app.services.data_sync.universe\`\`
  (\`\`__module__\`\` attribute).
- They are the SAME object (\`\`is\`\`) as their backgroundtasks
  re-exports (drift-proof: prevents accidental re-definition).
- The re-export shim in \`\`app.backgroundtasks\`\` still works.
- All current callers (orchestrator, mcp_server) still work.
- The 3 functions are importable from BOTH the new module and the
  old package (the bridge shim).
"""
from __future__ import annotations

import importlib
import inspect
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


# ─── Module size regression check ──────────────────────────────────────────


class TestUniverseModuleSize:
    """\`\`universe.py\`\` must be small.  If a future commit
    accidentally adds bulk logic here, this test fails.
    """

    def test_universe_file_under_300_loc(self):
        path = (
            ROOT / "app" / "services" / "data_sync" / "universe.py"
        )
        assert path.exists(), f"universe.py not found at {path}"
        loc = sum(1 for _ in path.read_text().splitlines())
        # The 3 functions are ~150 LOC total.  Allow 300 for
        # imports + a docstring + trivial re-exports.
        assert loc < 300, (
            f"universe.py is {loc} LOC, expected < 300.  This file "
            f"should only contain the universe sync core + helpers.  "
            f"If you added more, move it to a sibling module."
        )


# ─── __module__ check ─────────────────────────────────────────────────────


MOVED_FUNCTIONS = [
    "_stock_universe_sync",
    "_update_symbol_error_status",
    "_bulk_insert_stock_universe",
]


class TestFunctionsMovedToUniverse:
    """The 3 functions must have \`\`__module__ == 'app.services.data_sync.universe'\`\`."""

    @pytest.mark.parametrize("name", MOVED_FUNCTIONS)
    def test_function_lives_in_universe_module(self, name):
        from app.services.data_sync import universe

        assert hasattr(universe, name), (
            f"universe.{name} not found — the move was incomplete"
        )
        fn = getattr(universe, name)
        assert fn.__module__ == "app.services.data_sync.universe", (
            f"{name}.__module__ is {fn.__module__!r}, expected "
            f"'app.services.data_sync.universe'.  The function was "
            f"not moved (or was re-defined locally)."
        )


# ─── Identity check ───────────────────────────────────────────────────────


class TestReExportIdentity:
    """The functions in \`\`universe\`\` must be the SAME object as
    their \`\`app.backgroundtasks\`\` re-exports.
    """

    @pytest.mark.parametrize("name", MOVED_FUNCTIONS)
    def test_universe_is_backgroundtasks(self, name):
        from app import backgroundtasks as bg
        from app.services.data_sync import universe

        assert getattr(bg, name) is getattr(universe, name), (
            f"app.backgroundtasks.{name} is not the same object as "
            f"app.services.data_sync.universe.{name} — the re-export "
            f"is broken or the function was re-defined locally"
        )


# ─── Caller import smoke test ─────────────────────────────────────────────


class TestCallerImports:
    """All current callers must still work after the move."""

    def test_orchestrator_imports(self):
        from app import orchestrator  # noqa: F401

    def test_mcp_server_imports(self):
        from app import mcp_server  # noqa: F401

    def test_universe_module_imports(self):
        from app.services.data_sync import universe  # noqa: F401

    def test_legacy_imports_still_work(self):
        """The old import path \`\`from app.backgroundtasks import _stock_universe_sync\`\`
        must still resolve (re-export shim).
        """
        from app.backgroundtasks import (
            _stock_universe_sync,
            _update_symbol_error_status,
            _bulk_insert_stock_universe,
        )
        assert callable(_stock_universe_sync)
        assert callable(_update_symbol_error_status)
        assert callable(_bulk_insert_stock_universe)


# ─── Function signature preservation ──────────────────────────────────────


class TestFunctionSignaturesPreserved:
    """The 3 functions must keep their original signatures
    (a caller that did \`\`_stock_universe_sync()\`\` must still work).
    """

    def test_stock_universe_sync_signature(self):
        from app.services.data_sync.universe import _stock_universe_sync
        sig = inspect.signature(_stock_universe_sync)
        assert len(sig.parameters) == 0, (
            f"_stock_universe_sync should take no arguments, got {sig}"
        )

    def test_update_symbol_error_status_signature(self):
        from app.services.data_sync.universe import _update_symbol_error_status
        sig = inspect.signature(_update_symbol_error_status)
        params = list(sig.parameters.keys())
        # (session, symbol, reason, series=None) — session is positional
        # We don't pin 'series' specifically because the move should
        # preserve whatever the original signature was.
        assert "session" in params
        assert "symbol" in params
        assert "reason" in params

    def test_bulk_insert_stock_universe_signature(self):
        from app.services.data_sync.universe import _bulk_insert_stock_universe
        sig = inspect.signature(_bulk_insert_stock_universe)
        params = list(sig.parameters.keys())
        assert "session" in params
        assert "batch" in params
