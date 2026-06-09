"""Parity tests for audit Phase A.3 — function-level imports.

Audit citation: ``BACKEND_AUDIT.md`` §5 L347, Phase A.3, L347 ("Lift
function-level imports to module top").

Contract locked here:
1. No ``ast.Import`` or ``ast.ImportFrom`` node lives inside any
   ``ast.FunctionDef`` / ``ast.AsyncFunctionDef`` body in
   ``app.routers.ticker`` or ``app.routers.news_ws``.
2. The names previously imported inline are reachable from the module's
   top-level namespace (i.e. they have been hoisted).
3. The endpoint behaviour is unchanged — the hoisted names produce the
   same observable behaviour as the in-function imports.

This is a structural + contract test, not a full integration test.
The full pure-unit suite (``pytest -m "not slow"``) covers behavioural
parity of the affected endpoints.
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path
from typing import Iterable

import pytest


BACKEND_ROOT = Path(__file__).resolve().parent.parent
TICKER_ROUTER_PATH = BACKEND_ROOT / "app" / "routers" / "ticker.py"
NEWS_WS_ROUTER_PATH = BACKEND_ROOT / "app" / "routers" / "news_ws.py"


def _import_nodes_inside_functions(source: str) -> list[tuple[str, int, str]]:
    """Return ``(qualified_name, lineno, function_name)`` for every import
    node that is a descendant of a function/method body.

    Uses ``ast.walk`` so it catches imports nested in ``if`` blocks, loops,
    ``try/except`` arms, nested functions, lambdas, etc. — not just direct
    children of the function body.  Lambdas are ignored (they cannot
    contain statements, only expressions, so the check is moot for them).
    """
    tree = ast.parse(source)
    offenders: list[tuple[str, int, str]] = []

    def _name(node: ast.AST) -> str:
        if isinstance(node, ast.Import):
            return ", ".join(a.name for a in node.names)
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            return f"{module}." + ", ".join(a.name for a in node.names) if module else ", ".join(a.name for a in node.names)
        return node.__class__.__name__

    def _enclosing_function(node: ast.AST) -> str | None:
        """Walk parents to find the nearest FunctionDef/AsyncFunctionDef."""
        # ast.NodeVisitor doesn't track parents — build a parent map once
        # by walking the tree.
        return _parent_function_name.get(id(node))

    # Build parent map
    parent_of: dict[int, ast.AST] = {}

    def _build_parents(node: ast.AST) -> None:
        for child in ast.iter_child_nodes(node):
            parent_of[id(child)] = node
            _build_parents(child)

    _build_parents(tree)

    def _function_name_for(n: ast.AST) -> str | None:
        cur: ast.AST | None = parent_of.get(id(n))
        while cur is not None:
            if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return cur.name
            cur = parent_of.get(id(cur))
        return None

    _parent_function_name = {}  # placeholder so the closure above binds
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        func_name = _function_name_for(node)
        if func_name is None:
            continue
        offenders.append((_name(node), node.lineno, func_name))

    return offenders


def test_ticker_router_has_no_function_level_imports() -> None:
    """No import statements live inside any function body in ticker.py."""
    source = TICKER_ROUTER_PATH.read_text()
    offenders = _import_nodes_inside_functions(source)
    assert offenders == [], (
        "Function-level imports remain in ticker.py:\n"
        + "\n".join(f"  L{ln} inside {fn}: {name}" for name, ln, fn in offenders)
    )


def test_news_ws_router_has_no_function_level_imports() -> None:
    """No import statements live inside any function body in news_ws.py."""
    source = NEWS_WS_ROUTER_PATH.read_text()
    offenders = _import_nodes_inside_functions(source)
    assert offenders == [], (
        "Function-level imports remain in news_ws.py:\n"
        + "\n".join(f"  L{ln} inside {fn}: {name}" for name, ln, fn in offenders)
    )


@pytest.mark.parametrize(
    "module_path, expected_hoisted",
    [
        # ticker.py: previously had `import json` (L466), `import logging` (L618),
        # `from datetime import timedelta` (L608), `from app.services.nse_charting_client
        # import fetch_candles_async` (L604). After hoist, all four must be
        # reachable from the module's top-level namespace.
        (TICKER_ROUTER_PATH, ("json", "logging", "timedelta", "fetch_candles_async")),
        # news_ws.py: previously had `from sqlalchemy import nullslast` (L148).
        (NEWS_WS_ROUTER_PATH, ("nullslast",)),
    ],
)
def test_hoisted_names_reachable_at_module_top(
    module_path: Path, expected_hoisted: Iterable[str]
) -> None:
    """Each name previously imported inline is now bound at module top level."""
    import importlib.util
    import sys

    spec = importlib.util.spec_from_file_location("hoisted_target", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # Note: this is an AST-and-namespace check, not an import — we don't want
    # the side effects of running the full module body.
    for name in expected_hoisted:
        # Walk the module's top-level AST and confirm the name appears as a
        # bound target of an import.
        tree = ast.parse(module_path.read_text())
        found = False
        for node in tree.body:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    bound = alias.asname or alias.name.split(".")[0]
                    if bound == name:
                        found = True
                        break
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    bound = alias.asname or alias.name
                    if bound == name:
                        found = True
                        break
            if found:
                break
        assert found, (
            f"{module_path.name} does not import {name!r} at module top level"
        )


def test_ticker_router_timedelta_in_datetime_import() -> None:
    """``timedelta`` must be added to the existing ``from datetime import ...``
    line rather than a new import line, to match the codebase style.
    """
    source = TICKER_ROUTER_PATH.read_text()
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "datetime":
            imported = {a.name for a in node.names}
            assert "timedelta" in imported, (
                "ticker.py should import timedelta alongside date/datetime/timezone"
            )
            return
    pytest.fail("ticker.py has no `from datetime import ...` line at module top")
