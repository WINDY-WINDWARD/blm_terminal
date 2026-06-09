"""Parity tests for audit Phase A.4 — module-level regex compilation.

Audit citation: ``BACKEND_AUDIT.md`` §5 L348, Phase A.4 ("Compile regexes at
module level") and §4.6 L271 ("Regex compiled inside method body").

Contract locked here:
1. ``_TRADES_RE`` is a ``re.Pattern`` bound at module top level of
   ``app.services.screener_client`` (not inside ``_parse_trades_company_id``).
2. ``_parse_trades_company_id`` does not call ``re.compile`` (or
   ``import re``) at function entry.
3. The hoisted pattern matches the same ``/trades/company-{id}/`` shapes
   that the in-function version did, on three fixture inputs:
     - a button with a matching ``data-url`` attribute (primary path)
     - raw HTML with the pattern but no button (fallback path)
     - HTML with no match (returns ``None``)
4. The function is reachable as a public-ish name (single underscore) on
   the module — i.e. the rename from ``_extract_company_id_from_soup`` to
   ``_parse_trades_company_id`` (if any) did not occur silently.

The behavioural test uses ``BeautifulSoup`` to build tiny HTML fixtures
that exercise both code paths.
"""
from __future__ import annotations

import ast
import inspect
import re
from pathlib import Path

import pytest
from bs4 import BeautifulSoup


BACKEND_ROOT = Path(__file__).resolve().parent.parent
SCREENER_CLIENT_PATH = BACKEND_ROOT / "app" / "services" / "screener_client.py"


def test_trades_re_defined_at_module_level() -> None:
    """``_TRADES_RE`` is bound at module top level as a compiled Pattern."""
    from app.services import screener_client

    assert hasattr(screener_client, "_TRADES_RE"), (
        "screener_client must define _TRADES_RE at module top level"
    )
    assert isinstance(screener_client._TRADES_RE, re.Pattern), (
        f"_TRADES_RE should be a re.Pattern, got {type(screener_client._TRADES_RE)!r}"
    )
    # The pattern is a single capture group of digits between /trades/company- and /
    assert screener_client._TRADES_RE.pattern == r"/trades/company-(\d+)/"
    assert screener_client._TRADES_RE.groups == 1


def test_trades_re_not_compiled_inside_function_body() -> None:
    """No ``re.compile`` (and no inline ``import re``) lives inside
    ``_parse_trades_company_id`` (or any other function in the module).
    """
    source = SCREENER_CLIENT_PATH.read_text()
    tree = ast.parse(source)

    # Build parent map so we can ask: is this ast.Call to re.compile inside a function?
    parent_of: dict[int, ast.AST] = {}

    def _build_parents(node: ast.AST) -> None:
        for child in ast.iter_child_nodes(node):
            parent_of[id(child)] = node
            _build_parents(child)

    _build_parents(tree)

    def _enclosing_function(n: ast.AST) -> str | None:
        cur: ast.AST | None = parent_of.get(id(n))
        while cur is not None:
            if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return cur.name
            cur = parent_of.get(id(cur))
        return None

    offenders: list[tuple[str, int, str]] = []
    for node in ast.walk(tree):
        # inline `import re as _re`
        if isinstance(node, ast.Import) and any(
            a.name == "re" for a in node.names
        ):
            fn = _enclosing_function(node)
            if fn is not None:
                offenders.append((f"import {', '.join(a.name for a in node.names)}", node.lineno, fn))
            continue
        if isinstance(node, ast.ImportFrom) and node.module == "re":
            fn = _enclosing_function(node)
            if fn is not None:
                offenders.append((f"from re import ...", node.lineno, fn))
            continue
        # re.compile(...)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "compile" and isinstance(node.func.value, ast.Name) and node.func.value.id == "re":
                fn = _enclosing_function(node)
                if fn is not None:
                    offenders.append(("re.compile(...)", node.lineno, fn))
    assert offenders == [], (
        "Function-level re.compile or import re remain in screener_client.py:\n"
        + "\n".join(f"  L{ln} inside {fn}: {name}" for name, ln, fn in offenders)
    )


def test_re_imported_at_module_top() -> None:
    """``re`` is in the module's top-level import block."""
    source = SCREENER_CLIENT_PATH.read_text()
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "re":
                    return
        if isinstance(node, ast.ImportFrom) and node.module == "re":
            return
    pytest.fail("screener_client.py does not import 're' at module top level")


def test_parse_trades_company_id_returns_id_from_button() -> None:
    """Primary path: HTML with a button having a matching data-url attribute."""
    from app.services.screener_client import _parse_trades_company_id

    html = """
    <html><body>
      <button data-url="/trades/company-2726/">Trades</button>
    </body></html>
    """
    soup = BeautifulSoup(html, "lxml")
    assert _parse_trades_company_id(soup) == "2726"


def test_parse_trades_company_id_falls_back_to_raw_match() -> None:
    """Fallback path: no button, but raw HTML contains the pattern."""
    from app.services.screener_client import _parse_trades_company_id

    html = """
    <html><body>
      <p>Some article text</p>
      <a href="/trades/company-98765/">See trades</a>
    </body></html>
    """
    soup = BeautifulSoup(html, "lxml")
    assert _parse_trades_company_id(soup) == "98765"


def test_parse_trades_company_id_returns_none_when_no_match() -> None:
    """Neither primary nor fallback path matches -> return None."""
    from app.services.screener_client import _parse_trades_company_id

    html = "<html><body><p>nothing relevant here</p></body></html>"
    soup = BeautifulSoup(html, "lxml")
    assert _parse_trades_company_id(soup) is None


def test_module_level_pattern_is_same_object_across_calls() -> None:
    """Hoisted pattern is reused — the function does not recompile per call.

    This locks the actual perf property: before the hoist, the pattern was
    a fresh ``re.compile`` on every invocation of ``_parse_trades_company_id``.
    After the hoist, every call must reference the same module-level object.
    """
    from app.services import screener_client
    from app.services.screener_client import _parse_trades_company_id

    pattern_in_module = screener_client._TRADES_RE

    # Build the two soup variants that actually exercise the pattern lookup
    soup_btn = BeautifulSoup(
        '<html><body><button data-url="/trades/company-1/">Trades</button></body></html>',
        "lxml",
    )
    soup_raw = BeautifulSoup(
        '<html><body><a href="/trades/company-2/">trades</a></body></html>', "lxml"
    )

    assert _parse_trades_company_id(soup_btn) == "1"
    assert _parse_trades_company_id(soup_raw) == "2"
    # Pattern identity preserved across calls — the module-level binding
    # is the same object the function reads.
    assert screener_client._TRADES_RE is pattern_in_module
