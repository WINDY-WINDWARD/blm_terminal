"""Tests for the sync NSE client facade (audit B.10).

These tests verify:

1. The facade class (``NSEClient`` in ``nse_client.py``) is the SAME
   class as the one re-exported from ``nse_client_async.py`` — proving
   there's only one implementation, not two.
2. The module-level singletons (``nse_client``, ``nse_client_async``)
   exist and have the expected types.
3. ``SymbolNotFoundError`` is still importable from the legacy path
   (callers' ``except`` blocks depend on it).
4. Sync-only methods (``get_stock_list`` with nsepython fallback,
   ``get_corporate_filing_comparison``) work without ``asyncio.run``.
5. Async methods that the facade delegates via ``asyncio.run`` are at
   least callable as bound methods (the real network calls are
   short-circuited via ``AsyncMock`` to avoid hitting NSE in tests).
6. The legacy module no longer contains the duplicated class body —
   re-exports only.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


# ─── Single-source-of-truth ────────────────────────────────────────────────


class TestFacadeIsCanonical:
    def test_nse_client_class_is_nse_client_async_class(self):
        """The legacy NSEClient is the SAME class as NSEClientAsync's
        facade — there is only one implementation.
        """
        from app.services.nse_client import NSEClient as Legacy
        from app.services.nse_client_async import NSEClient as Facade

        assert Legacy is Facade, (
            "Drift detected: nse_client.NSEClient and "
            "nse_client_async.NSEClient are different classes. "
            "The facade pattern is broken."
        )

    def test_legacy_module_does_not_define_its_own_class(self):
        """The legacy module should NOT contain its own NSEClient class
        body — only re-exports.  Drift-prone duplicate code is the exact
        problem the refactor was meant to eliminate.
        """
        from app.services import nse_client as legacy_mod

        class FakeNSEClient:
            pass

        # The legacy module should not have a class object that is NOT
        # the same as the async module's facade.  If it does, drift has
        # crept back in.
        async_facade = getattr(legacy_mod, "NSEClient")
        # Walk the module's class attributes and check none of them are
        # classes other than the re-exported one.
        for name in dir(legacy_mod):
            obj = getattr(legacy_mod, name)
            if isinstance(obj, type) and name in ("NSEClient", "NSEClientAsync"):
                # Either it is the re-exported class itself, or it is
                # a different class (drift).
                assert obj is getattr(
                    __import__("app.services.nse_client_async", fromlist=[name]),
                    name,
                ), f"Class {name} drifted between modules"

    def test_singletons_exist(self):
        from app.services.nse_client import nse_client, nse_client_async
        from app.services.nse_client import NSEClient, NSEClientAsync

        # ``nse_client`` is an instance of the SYNC facade (``NSEClient``)
        # and ``nse_client_async`` is an instance of the async class
        # (``NSEClientAsync``).  They are different types, but the facade
        # delegates to the async class — so the assertion is that the
        # facade's ``_async`` attribute is an NSEClientAsync instance.
        assert isinstance(nse_client, NSEClient)
        assert isinstance(nse_client_async, NSEClientAsync)
        assert isinstance(nse_client._async, NSEClientAsync)


class TestSymbolNotFoundError:
    def test_importable_from_legacy_path(self):
        from app.services.nse_client import SymbolNotFoundError
        err = SymbolNotFoundError("RELIANCE", reason="not tradeable")
        assert err.symbol == "RELIANCE"
        assert "not tradeable" in str(err)

    def test_same_class_as_async_path(self):
        from app.services.nse_client import SymbolNotFoundError as A
        from app.services.nse_client_async import SymbolNotFoundError as B
        assert A is B


# ─── Sync-only methods (no asyncio.run needed) ────────────────────────────


class TestSyncOnlyMethods:
    def test_get_stock_list_falls_back_to_nsepython(self):
        """The async ``get_stock_list`` raises ``NotImplementedError``; the
        facade should fall back to ``nsepython.nse_eq_symbols`` to
        preserve the pre-refactor behaviour.
        """
        from app.services.nse_client import NSEClient

        with patch("nsepython.nse_eq_symbols", return_value=["RELIANCE", "TCS"]) as m:
            client = NSEClient()
            result = client.get_stock_list()
        assert result == ["RELIANCE", "TCS"]
        m.assert_called_once()

    def test_get_corporate_filing_comparison_delegates(self):
        """This is a sync method on the async client; the facade should
        delegate without spinning up an event loop.
        """
        from app.services.nse_client import NSEClient

        # Mock the helper module + nsepython
        with patch("app.services.helpers.json_to_csv.dict_to_csv_text", return_value="csv"), \
             patch("nsepython.nse_past_results", return_value={"data": "x"}) as m:
            client = NSEClient()
            result = client.get_corporate_filing_comparison("RELIANCE")
        assert result == "csv"
        m.assert_called_once_with("RELIANCE")


# ─── Async methods (delegated via asyncio.run) ──────────────────────────────


class TestAsyncDelegation:
    def test_get_top_gainers_delegates_to_async(self):
        """The facade should call ``NSEClientAsync.get_top_gainers`` and
        return its result.  We mock the async method to return a fake
        DataFrame so we don't hit NSE.
        """
        from app.services.nse_client import NSEClient

        fake_df = MagicMock(name="DataFrame")
        with patch.object(
            NSEClient.__init__.__globals__["NSEClientAsync"],
            "get_top_gainers",
            new=AsyncMock(return_value=fake_df),
        ) as m:
            client = NSEClient()
            result = client.get_top_gainers()
        assert result is fake_df
        m.assert_awaited_once()

    def test_get_52week_high_delegates_to_async(self):
        from app.services.nse_client import NSEClient

        fake_dict = {"symbols": ["RELIANCE"]}
        with patch.object(
            NSEClient.__init__.__globals__["NSEClientAsync"],
            "get_52week_high_stocks",
            new=AsyncMock(return_value=fake_dict),
        ):
            client = NSEClient()
            result = client.get_52week_high_stocks()
        assert result == {"symbols": ["RELIANCE"]}

    def test_close_delegates_to_async(self):
        """``close`` is async on the facade; callers that already
        ``await nse_client.close()`` should still work.
        """
        from app.services.nse_client import NSEClient

        with patch.object(
            NSEClient.__init__.__globals__["NSEClientAsync"],
            "close",
            new=AsyncMock(),
        ) as m:
            client = NSEClient()
            # Use asyncio.run to drive the coroutine
            import asyncio
            asyncio.run(client.close())
        m.assert_awaited_once()


# ─── Module size regression check ───────────────────────────────────────────


class TestModuleSizeRegression:
    def test_nse_client_py_under_60_lines(self):
        """The legacy module should now be a thin re-export.  If it
        grows above 60 lines, the drift-prone class body has crept
        back in.
        """
        from app.services import nse_client

        path = Path(nse_client.__file__)
        line_count = sum(1 for _ in path.open())
        assert line_count < 60, (
            f"nse_client.py is {line_count} lines — should be a thin "
            f"re-export (<60 lines).  Has the class body drifted back in?"
        )

    def test_nse_client_py_imports_nse_client_async(self):
        """The legacy module must import from nse_client_async to prove
        it is a re-export and not a duplicate.
        """
        from app.services import nse_client

        source = Path(nse_client.__file__).read_text()
        assert "nse_client_async" in source, (
            "nse_client.py should re-export from nse_client_async"
        )
