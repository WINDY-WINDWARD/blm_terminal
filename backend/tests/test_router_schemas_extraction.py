"""Tests for audit B.5 — move inline router Pydantic models to ``app/schemas/``.

The 4 routers that defined inline ``BaseModel`` subclasses:

  - ``app/routers/ticker.py``        — 10 classes
  - ``app/routers/news.py``          —  1 class
  - ``app/routers/announcements.py`` —  1 class
  - ``app/routers/stockuniverse.py`` —  5 classes

The refactor moves them to the corresponding ``app/schemas/*.py`` file
(creating ``announcements.py`` since it does not exist yet) and updates
the router to import from the schema module.  The router modules must
not re-define the moved classes inline.

This test file does NOT snapshot every field on every class — that would
duplicate the Pydantic machinery.  Instead it asserts:

  1. Each moved class is importable from its new home.
  2. The class is a ``BaseModel`` subclass.
  3. The router module no longer defines an inline class of the same
     name (the class object identity must differ between the old
     location and the new location — i.e. the router must IMPORT the
     class, not redefine it).
  4. A field snapshot for a representative subset (cheap to maintain).
"""

from __future__ import annotations

import inspect
import sys
from typing import Any

import pytest
from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Routers with inline BaseModel subclasses (BEFORE the refactor)
# ---------------------------------------------------------------------------

# (router_module, schema_module, [class names to move])
MOVED_CLASSES: list[tuple[str, str, str]] = [
    # ticker — 10 classes go to existing app/schemas/ticker.py
    ("app.routers.ticker", "app.schemas.ticker", "ReturnsResponse"),
    ("app.routers.ticker", "app.schemas.ticker", "UniverseReturnsResponse"),
    ("app.routers.ticker", "app.schemas.ticker", "SectorReturnsResponse"),
    ("app.routers.ticker", "app.schemas.ticker", "Position52wResponse"),
    ("app.routers.ticker", "app.schemas.ticker", "MomentumScoreResponse"),
    ("app.routers.ticker", "app.schemas.ticker", "MomentumLeaderboardResponse"),
    ("app.routers.ticker", "app.schemas.ticker", "StreakResponse"),
    ("app.routers.ticker", "app.schemas.ticker", "ScreenerResponse"),
    ("app.routers.ticker", "app.schemas.ticker", "IntradayCandleRow"),
    ("app.routers.ticker", "app.schemas.ticker", "IntradayOHLCVResponse"),
    # news — 1 class to existing app/schemas/news.py
    ("app.routers.news", "app.schemas.news", "CompanyNewsFetchRequest"),
    # announcements — 1 class to new app/schemas/announcements.py
    ("app.routers.announcements", "app.schemas.announcements", "EventCalendarItem"),
    # stockuniverse — 5 classes to existing app/schemas/stockuniverse.py
    ("app.routers.stockuniverse", "app.schemas.stockuniverse", "MatchResultResponse"),
    ("app.routers.stockuniverse", "app.schemas.stockuniverse", "ConfirmMatchRequest"),
    ("app.routers.stockuniverse", "app.schemas.stockuniverse", "StockUniverseErrorSymbol"),
    ("app.routers.stockuniverse", "app.schemas.stockuniverse", "ErrorCategory"),
    ("app.routers.stockuniverse", "app.schemas.stockuniverse", "StockUniverseErrorsResponse"),
    ("app.routers.stockuniverse", "app.schemas.stockuniverse", "ChangeSymbolRequest"),
]


def _import(module_path: str) -> Any:
    """Import a module by dotted path; skip on ImportError so partial
    implementations during incremental migration don't mask other tests."""
    return __import__(module_path, fromlist=["__name__"])


# ---------------------------------------------------------------------------
# Each moved class is importable from its new schema module
# ---------------------------------------------------------------------------

class TestMovedClassesImportable:
    @pytest.mark.parametrize(
        "router_module,schema_module,class_name", MOVED_CLASSES,
        ids=[f"{r.split('.')[-1]}.{c} → {s.split('.')[-1]}.{c}" for r, s, c in MOVED_CLASSES],
    )
    def test_class_importable_from_schema_module(
        self, router_module: str, schema_module: str, class_name: str
    ) -> None:
        schema_mod = _import(schema_module)
        assert hasattr(schema_mod, class_name), (
            f"{class_name} not found in {schema_module}"
        )
        cls = getattr(schema_mod, class_name)
        assert isinstance(cls, type) and issubclass(cls, BaseModel), (
            f"{schema_module}.{class_name} is not a BaseModel subclass"
        )


# ---------------------------------------------------------------------------
# The router module no longer defines the class inline — it must IMPORT it
# ---------------------------------------------------------------------------

class TestRoutersImportDontRedefine:
    @pytest.mark.parametrize(
        "router_module,schema_module,class_name", MOVED_CLASSES,
        ids=[f"{r.split('.')[-1]}.{c}" for r, s, c in MOVED_CLASSES],
    )
    def test_router_imports_class_from_schema(
        self, router_module: str, schema_module: str, class_name: str
    ) -> None:
        """The router must import the class from the schema module —
        class identity between the router's binding and the schema
        module's binding must be the SAME object (import) and must
        differ from the original (i.e. it is no longer a fresh inline
        definition in the router file)."""
        schema_mod = _import(schema_module)
        router_mod = _import(router_module)

        # Schema module owns the canonical class
        schema_cls = getattr(schema_mod, class_name)

        # If the router still has an attribute of this name, it must be
        # the SAME object (imported), not a separately defined class.
        if hasattr(router_mod, class_name):
            router_cls = getattr(router_mod, class_name)
            assert router_cls is schema_cls, (
                f"{router_module}.{class_name} is not the same object as "
                f"{schema_module}.{class_name} — router must import, not "
                "redefine inline"
            )

        # And the class definition must no longer live in the router's
        # source file.  We look at the AST-free shortcut: the class's
        # ``__qualname__`` (set when the class is defined) is namespaced
        # to whichever module defined it.  After the move, the
        # canonical class's ``__module__`` must be the schema module.
        assert schema_cls.__module__ == schema_module, (
            f"{class_name}.__module__ is {schema_cls.__module__!r}, "
            f"expected {schema_module!r} — class is still defined in the "
            "router"
        )


# ---------------------------------------------------------------------------
# Round-trip: instantiating a moved class still works (smoke test)
# ---------------------------------------------------------------------------

class TestMovedClassesInstantiate:
    """Each moved class must still construct from its old kwargs
    (round-trip parity — the field set is unchanged by the move)."""

    def test_company_news_fetch_request(self) -> None:
        from app.schemas.news import CompanyNewsFetchRequest
        req = CompanyNewsFetchRequest(symbol="HDFCBANK")
        assert req.symbol == "HDFCBANK"
        assert req.mc_url is None

    def test_event_calendar_item(self) -> None:
        from app.schemas.announcements import EventCalendarItem
        item = EventCalendarItem(
            symbol="HDFCBANK",
            company="HDFC Bank",
            purpose="Board Meeting",
            description="Q4 results",
            date="20-Apr-2026",
            source="main",
        )
        assert item.symbol == "HDFCBANK"
        assert item.source == "main"

    def test_stockuniverse_change_symbol_request(self) -> None:
        from app.schemas.stockuniverse import ChangeSymbolRequest
        req = ChangeSymbolRequest(newSymbol="NEW")
        assert req.newSymbol == "NEW"

    def test_ticker_intraday_ohlcv_response(self) -> None:
        from app.schemas.ticker import IntradayOHLCVResponse
        resp = IntradayOHLCVResponse(
            symbol="HDFCBANK",
            interval="1h",
            candles=[],
            count=0,
        )
        assert resp.symbol == "HDFCBANK"
        assert resp.count == 0
