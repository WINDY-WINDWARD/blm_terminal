"""Shared pytest fixtures and configuration for backend tests.

Design goals:
- Zero side effects at import time (no DB creation, no app imports).
- `test_db_path` fixture points at the pre-built ``data_test.db`` file in
  the backend root (created once via ``alembic upgrade head``).  The
  production ``data.db`` is never touched.
- `in_memory_db` fixture builds a per-test SQLite in memory with the
  full schema — used by pure-function tests that need a DB but not data.
- `golden_*` helpers are intentionally NOT a pytest plugin dependency
  (no ``pytest-snapshot``) — they are hand-rolled dict comparisons so
  the test suite has zero new dev-dep requirements.
- `monkeypatch_test_db` patches ``settings.db_path`` so any test that
  uses ``from app.config import settings; sqlite3.connect(settings.db_path)``
  points at the test DB.

This module is deliberately small.  Feature-specific fixtures belong in
their respective test files.
"""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any

import pytest

# Repo paths ────────────────────────────────────────────────────────────────────
BACKEND_ROOT = Path(__file__).resolve().parent.parent
TEST_DB_PATH = BACKEND_ROOT / "data_test.db"
PROD_DB_PATH = BACKEND_ROOT / "data.db"

# Markers ────────────────────────────────────────────────────────────────────────

def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers (idempotent; respects existing markers)."""
    config.addinivalue_line(
        "markers",
        "perf: performance regression tests (run on a schedule, not every PR)",
    )
    config.addinivalue_line(
        "markers",
        "parity: side-by-side parity tests between old and new implementations",
    )
    config.addinivalue_line(
        "markers",
        "golden: golden / snapshot tests (output diff'd against checked-in JSON)",
    )


# Fixtures ──────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def test_db_path() -> Path:
    """Absolute path to the pre-built test database (``data_test.db``).

    The file must exist (created once via ``DB_PATH=./data_test.db
    alembic upgrade head``).  If missing, the fixture fails with a clear
    message rather than silently falling back to ``data.db``.
    """
    if not TEST_DB_PATH.exists():
        pytest.fail(
            f"Test DB not found at {TEST_DB_PATH}.  Create it with:\n"
            f"  cd backend && DB_PATH=./data_test.db .venv/bin/alembic upgrade head"
        )
    assert TEST_DB_PATH.resolve() != PROD_DB_PATH.resolve(), (
        "test_db_path resolved to the production data.db — refusing to run"
    )
    return TEST_DB_PATH


@pytest.fixture
def monkeypatch_test_db(monkeypatch: pytest.MonkeyPatch, test_db_path: Path) -> Path:
    """Point ``settings.db_path`` at the test DB for the lifetime of one test.

    Use this when the code under test reads ``settings.db_path`` directly
    (e.g. ``app.services.screener``).  For code that uses SQLAlchemy
    engines, the engines will already have been bound to the import-time
    value, so pair this with ``importlib.reload()`` if needed.
    """
    from app.config import settings
    monkeypatch.setattr(settings, "db_path", str(test_db_path))
    return test_db_path


@pytest.fixture
def in_memory_db() -> sqlite3.Connection:
    """A throwaway in-memory SQLite with the full schema pre-built.

    Suitable for pure-function tests that need a DB but not real data.
    The connection lives only as long as the test.
    """
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row

    from app.database import Base, _set_sqlite_pragma
    # Import all models so Base.metadata is fully populated
    import app.models  # noqa: F401
    import app.models.ticker  # noqa: F401
    import app.models.news  # noqa: F401
    import app.models.stockuniverse  # noqa: F401
    import app.models.watchlist  # noqa: F401
    import app.models.notification  # noqa: F401
    import app.models.corporatefilings  # noqa: F401
    import app.models.job  # noqa: F401
    import app.models.system_config  # noqa: F401
    import app.models.marketcategory  # noqa: F401
    import app.models.ai_chat  # noqa: F401

    from sqlalchemy import create_engine, event
    eng = create_engine("sqlite:///:memory:")
    event.listen(eng, "connect", _set_sqlite_pragma)
    Base.metadata.create_all(eng)
    # Copy the schema into our sqlite3 connection by querying sqlite_master
    with eng.connect() as sa_con:
        rows = sa_con.exec_driver_sql(
            "SELECT name, sql FROM sqlite_master WHERE type IN ('table', 'index') AND sql IS NOT NULL"
        ).fetchall()
    eng.dispose()
    for _, sql in rows:
        con.execute(sql)
    con.commit()
    yield con
    con.close()


# Golden helpers ────────────────────────────────────────────────────────────────

def _normalize(obj: Any) -> Any:
    """JSON-safe normalization for stable comparison."""
    if isinstance(obj, dict):
        return {k: _normalize(v) for k, v in sorted(obj.items())}
    if isinstance(obj, (list, tuple)):
        return [_normalize(v) for v in obj]
    if isinstance(obj, float):
        # round to 8 decimal places to avoid float noise
        return round(obj, 8)
    return obj


@pytest.fixture
def golden_compare():
    """Return a callable that compares an actual value against a golden JSON file.

    Usage::

        def test_foo(golden_compare):
            actual = my_function()
            golden_compare("foo_response", actual, tests_golden_dir)
    """
    def _compare(name: str, actual: Any, golden_dir: Path | str) -> None:
        golden_dir = Path(golden_dir)
        golden_path = golden_dir / f"{name}.json"
        if os.environ.get("UPDATE_GOLDEN") == "1":
            golden_dir.mkdir(parents=True, exist_ok=True)
            with open(golden_path, "w") as f:
                json.dump(_normalize(actual), f, indent=2, default=str)
            return
        if not golden_path.exists():
            pytest.fail(
                f"Golden file missing: {golden_path}\n"
                f"Run with UPDATE_GOLDEN=1 to create it."
            )
        with open(golden_path) as f:
            expected = json.load(f)
        if _normalize(actual) != _normalize(expected):
            pytest.fail(
                f"Golden mismatch for {name}.\n"
                f"Run with UPDATE_GOLDEN=1 to refresh."
            )
    return _compare


# Auto-mark tests by filename suffix ────────────────────────────────────────────
# Tests with a `_parity_` infix are auto-marked `parity`.
# Tests with a `_perf_` infix are auto-marked `perf`.
# Tests with a `golden_` infix are auto-marked `golden`.

def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    for item in items:
        name = item.nodeid.lower()
        if "_parity_" in name:
            item.add_marker(pytest.mark.parity)
        elif "_perf_" in name:
            item.add_marker(pytest.mark.perf)
        elif "golden_" in name or "_golden_" in name:
            item.add_marker(pytest.mark.golden)
