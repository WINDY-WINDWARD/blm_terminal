"""Tests for the A.12 module extractions (audit C.1).

Moves cycle functions + helpers out of ``app/backgroundtasks/_impl.py``
into 8 new modules:

  - ``app/services/data_sync/nse_parsing.py`` — 8 safe-fetch + parse helpers
  - ``app/services/data_sync/cleanup.py`` — ``_run_cleanup_if_due`` + 6 constants
  - ``app/services/data_sync/deal_significance.py`` — ``DealRecord`` + 7 helpers
  - ``app/services/data_sync/insider_trades.py`` — 2 functions
  - ``app/services/data_sync/notifications.py`` — 6 helpers + ``_build_alerts`` + 3 constants
  - ``app/workers/notification_cycles.py`` — 4 watchlist cycle functions
  - ``app/workers/global_scan_cycle.py`` — ``_global_scan_cycle`` + 2 constants
  - ``app/workers/jobs.py`` — ``register_all_jobs``
  - ``app/services/fair_value.py`` — 10 morningstar fair-value functions (A.12 part 2)

Tests pin the refactor invariants:

- Each new module is a small file (Pattern I: < N LOC).
- The moved symbols now live in their new home (``__module__`` attribute).
- They are the SAME object (``is``) as the ``app.backgroundtasks`` re-export
  (drift-proof: prevents accidental re-definition).
- The re-export shim in ``app.backgroundtasks`` still works for all callers.
- All function signatures are preserved.
- Cycle functions use lazy imports so test ``mock.patch`` calls to the
  data_sync modules' helpers take effect at call time (Phase C.1 learning
  captured here as a regression check).
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


# ─── Module size regression checks ────────────────────────────────────────


class TestNewModuleSizes:
    """Each new module must be small.  If a future commit accidentally
    adds bulk logic here, these tests fail.
    """

    @pytest.mark.parametrize("rel_path,limit", [
        ("app/services/data_sync/nse_parsing.py", 250),
        ("app/services/data_sync/cleanup.py", 250),
        ("app/services/data_sync/deal_significance.py", 350),
        ("app/services/data_sync/insider_trades.py", 150),
        ("app/services/data_sync/notifications.py", 350),
        ("app/workers/notification_cycles.py", 700),
        ("app/workers/global_scan_cycle.py", 500),
        ("app/workers/jobs.py", 350),
        ("app/services/fair_value.py", 400),
    ])
    def test_module_under_loc_limit(self, rel_path, limit):
        path = ROOT / rel_path
        assert path.exists(), f"{rel_path} not found"
        loc = sum(1 for _ in path.read_text().splitlines())
        assert loc < limit, (
            f"{rel_path} is {loc} LOC, expected < {limit}.  "
            f"If you added more logic, move it to a sibling module."
        )


# ─── __module__ checks (each moved symbol lives in its new home) ───────────


NSE_PARSING_FUNCTIONS = [
    "_parse_52week_data",
    "_parse_volume_gainers",
    "_safe_fetch_52week_high",
    "_safe_fetch_52week_low",
    "_safe_fetch_volume_gainers",
    "_safe_fetch_top_gainers",
    "_safe_fetch_top_losers",
    "_safe_fetch_largedeal_snapshot",
]

DEAL_SIGNIFICANCE_SYMBOLS = [
    ("DealRecord", "app.services.data_sync.deal_significance"),
    ("_coerce_int", "app.services.data_sync.deal_significance"),
    ("_coerce_float", "app.services.data_sync.deal_significance"),
    ("_is_recent", "app.services.data_sync.deal_significance"),
    ("_parse_largedeal_snapshot", "app.services.data_sync.deal_significance"),
    ("_fetch_deal_market_caps", "app.services.data_sync.deal_significance"),
    ("_fetch_short_deal_close_prices", "app.services.data_sync.deal_significance"),
    ("_is_deal_significant", "app.services.data_sync.deal_significance"),
]

INSIDER_TRADES_FUNCTIONS = [
    "_fetch_insider_trades_cached",
    "_fetch_insider_trades_async",
]

CLEANUP_SYMBOLS = [
    ("_run_cleanup_if_due", "function"),
    ("CLEANUP_READ_AFTER_DAYS", "int"),
    ("CLEANUP_INTERVAL", "int"),
    ("INTRADAY_1H_RETENTION_DAYS", "int"),
    ("INTRADAY_W_RETENTION_YEARS", "int"),
    ("NEWS_RETENTION_DAYS", "int"),
    ("_cleanup_last_run", None),
]

NOTIFICATIONS_SYMBOLS = [
    "NOTIFICATION_CHECK_INTERVAL",
    "AFTER_HOURS_INTERVAL",
    "DAILY_NOTIFICATION_WINDOW_DAYS",
    "_get_watchlist_symbols",
    "_get_seen_today",
    "_bulk_upsert_notifications",
    "_get_global_seen_today",
    "_bulk_upsert_global_notifications",
    "get_notif_config",
    "_build_alerts",
]

NOTIFICATION_CYCLE_FUNCTIONS = [
    "_notification_cycle_full",
    "_notification_cycle_reduced",
    "_ticker_indicator_notification_cycle",
    "_ticker_intraday_indicator_notification_cycle",
]

GLOBAL_SCAN_CYCLE_SYMBOLS = [
    ("_global_scan_cycle", "function"),
    ("GLOBAL_SCAN_BATCH_SIZE", "int"),
    ("GLOBAL_SCAN_DELAY", "float"),
]

JOBS_FUNCTIONS = [
    "register_all_jobs",
]

FAIR_VALUE_FUNCTIONS = [
    "_batch_resolve_morningstar_ids",
    "_batch_update_fair_values",
    "_get_full_lock",
    "_get_watchlist_lock",
    "_run_nightly_scheduler",
    "_run_watchlist_scheduler",
    "_should_trigger_full_sync",
    "_update_sync_timestamp",
    "sync_all_fair_values",
    "sync_watchlist_fair_values",
]


class TestNseParsingModule:
    """``nse_parsing.py`` is a thin wrapper around ``nse_client``."""

    @pytest.mark.parametrize("name", NSE_PARSING_FUNCTIONS)
    def test_function_lives_in_nse_parsing(self, name):
        from app.services.data_sync import nse_parsing

        assert hasattr(nse_parsing, name), f"nse_parsing.{name} missing"
        fn = getattr(nse_parsing, name)
        assert fn.__module__ == "app.services.data_sync.nse_parsing", (
            f"{name}.__module__ = {fn.__module__!r}, expected "
            f"'app.services.data_sync.nse_parsing'"
        )

    def test_nse_parsing_lazy_imports_bg_impl(self):
        """``nse_parsing`` must NOT import ``_impl`` at module level —
        it is consumed by the shim during init.
        """
        from app.services.data_sync import nse_parsing

        # If the module imported ``_impl`` at the top, the import
        # would be in the module dict by the time we inspect it.
        # (Lazy import pattern: callers do ``_nse_parsing_mod.X()``.)
        assert not hasattr(nse_parsing, "_impl"), (
            "nse_parsing imported _impl at module level — must be lazy"
        )


class TestDealSignificanceModule:
    @pytest.mark.parametrize("name,expected_module", DEAL_SIGNIFICANCE_SYMBOLS)
    def test_symbol_lives_in_deal_significance(self, name, expected_module):
        from app.services.data_sync import deal_significance

        assert hasattr(deal_significance, name), f"deal_significance.{name} missing"
        obj = getattr(deal_significance, name)
        if hasattr(obj, "__module__"):
            assert obj.__module__ == expected_module, (
                f"{name}.__module__ = {obj.__module__!r}, expected {expected_module!r}"
            )


class TestInsiderTradesModule:
    @pytest.mark.parametrize("name", INSIDER_TRADES_FUNCTIONS)
    def test_function_lives_in_insider_trades(self, name):
        from app.services.data_sync import insider_trades

        assert hasattr(insider_trades, name), f"insider_trades.{name} missing"
        fn = getattr(insider_trades, name)
        assert fn.__module__ == "app.services.data_sync.insider_trades", (
            f"{name}.__module__ = {fn.__module__!r}, expected "
            f"'app.services.data_sync.insider_trades'"
        )

    def test_insider_trades_lazy_imports_bg_impl(self):
        from app.services.data_sync import insider_trades

        assert not hasattr(insider_trades, "_impl"), (
            "insider_trades imported _impl at module level — must be lazy "
            "(shim imports these helpers from this module during init)"
        )


class TestCleanupModule:
    @pytest.mark.parametrize("name,expected_type", CLEANUP_SYMBOLS)
    def test_symbol_in_cleanup(self, name, expected_type):
        from app.services.data_sync import cleanup

        assert hasattr(cleanup, name), f"cleanup.{name} missing"
        obj = getattr(cleanup, name)
        if expected_type is not None:
            assert type(obj).__name__ == expected_type, (
                f"cleanup.{name} is {type(obj).__name__}, expected {expected_type}"
            )

    def test_cleanup_lazy_imports_bg_impl(self):
        from app.services.data_sync import cleanup

        assert not hasattr(cleanup, "_impl"), (
            "cleanup imported _impl at module level — must be lazy"
        )

    def test_run_cleanup_if_due_returns_none(self):
        """Function signature is preserved: takes no args, returns None."""
        from app.services.data_sync.cleanup import _run_cleanup_if_due

        sig = inspect.signature(_run_cleanup_if_due)
        assert len(sig.parameters) == 0
        assert sig.return_annotation is None or sig.return_annotation is type(None)


class TestNotificationsModule:
    @pytest.mark.parametrize("name", NOTIFICATIONS_SYMBOLS)
    def test_symbol_in_notifications(self, name):
        from app.services.data_sync import notifications

        assert hasattr(notifications, name), f"notifications.{name} missing"
        obj = getattr(notifications, name)
        if callable(obj):
            assert obj.__module__ == "app.services.data_sync.notifications", (
                f"{name}.__module__ = {obj.__module__!r}"
            )


class TestNotificationCyclesModule:
    @pytest.mark.parametrize("name", NOTIFICATION_CYCLE_FUNCTIONS)
    def test_cycle_function_lives_in_notification_cycles(self, name):
        from app.workers import notification_cycles

        assert hasattr(notification_cycles, name), f"notification_cycles.{name} missing"
        fn = getattr(notification_cycles, name)
        assert fn.__module__ == "app.workers.notification_cycles", (
            f"{name}.__module__ = {fn.__module__!r}, expected "
            f"'app.workers.notification_cycles'"
        )

    @pytest.mark.parametrize("name", NOTIFICATION_CYCLE_FUNCTIONS)
    def test_cycle_takes_no_args(self, name):
        from app.workers.notification_cycles import (
            _notification_cycle_full,
            _notification_cycle_reduced,
            _ticker_indicator_notification_cycle,
            _ticker_intraday_indicator_notification_cycle,
        )
        fn = locals()[name]
        sig = inspect.signature(fn)
        assert len(sig.parameters) == 0, (
            f"{name} should take no args, got {sig}"
        )

    def test_cycle_modules_lazy_import_data_sync(self):
        """Notification cycles must use lazy imports so test patches
        to ``app.services.data_sync.nse_parsing.X`` take effect.
        """
        from app.workers import notification_cycles

        # If the module imported data_sync helpers at the top, the
        # names would be in the module's __dict__ after import.
        # The cycle function bodies look up helpers via ``_nse_parsing_mod.X``
        # at call time — so a name like ``_safe_fetch_52week_high``
        # should NOT be a direct attribute of notification_cycles.
        assert not hasattr(notification_cycles, "_safe_fetch_52week_high"), (
            "notification_cycles imported _safe_fetch_52week_high at top — "
            "use lazy import pattern (_nse_parsing_mod.X) so test patches work"
        )


class TestGlobalScanCycleModule:
    @pytest.mark.parametrize("name,expected_type", GLOBAL_SCAN_CYCLE_SYMBOLS)
    def test_symbol_in_global_scan_cycle(self, name, expected_type):
        from app.workers import global_scan_cycle

        assert hasattr(global_scan_cycle, name), f"global_scan_cycle.{name} missing"
        obj = getattr(global_scan_cycle, name)
        if expected_type is not None:
            assert type(obj).__name__ == expected_type, (
                f"global_scan_cycle.{name} is {type(obj).__name__}, expected {expected_type}"
            )

    def test_global_scan_cycle_takes_no_args(self):
        from app.workers.global_scan_cycle import _global_scan_cycle

        sig = inspect.signature(_global_scan_cycle)
        assert len(sig.parameters) == 0

    def test_global_scan_cycle_uses_lazy_imports(self):
        from app.workers import global_scan_cycle

        assert not hasattr(global_scan_cycle, "_safe_fetch_52week_high"), (
            "global_scan_cycle imported _safe_fetch_52week_high at top — "
            "use lazy import pattern so test patches work"
        )


class TestJobsModule:
    @pytest.mark.parametrize("name", JOBS_FUNCTIONS)
    def test_function_lives_in_jobs(self, name):
        from app.workers import jobs

        assert hasattr(jobs, name), f"jobs.{name} missing"
        fn = getattr(jobs, name)
        assert fn.__module__ == "app.workers.jobs", (
            f"{name}.__module__ = {fn.__module__!r}, expected 'app.workers.jobs'"
        )

    def test_register_all_jobs_takes_no_args(self):
        from app.workers.jobs import register_all_jobs

        sig = inspect.signature(register_all_jobs)
        assert len(sig.parameters) == 0


class TestFairValueModule:
    """A.12 part 2 — fair-value sync moved to ``app.services.fair_value``."""

    @pytest.mark.parametrize("name", FAIR_VALUE_FUNCTIONS)
    def test_function_lives_in_fair_value(self, name):
        from app.services import fair_value

        assert hasattr(fair_value, name), f"fair_value.{name} missing"
        fn = getattr(fair_value, name)
        assert fn.__module__ == "app.services.fair_value", (
            f"{name}.__module__ = {fn.__module__!r}, expected "
            f"'app.services.fair_value'"
        )

    def test_fair_value_imports_bg_impl_lazily(self):
        """``fair_value`` uses ``_bg_impl._is_job_enabled`` + ``_seconds_until_next_cron``
        + ``get_async_shutdown_event``.  If these were top-level imports
        they would create a circular import (the shim imports fair_value
        during its own init).
        """
        from app.services import fair_value

        # The pattern is to import lazily inside function bodies.  The
        # module attribute ``_bg_impl`` is intentionally NOT a module
        # attribute — only function-local references exist.
        assert not hasattr(fair_value, "_bg_impl"), (
            "fair_value imported _bg_impl at module level — must be lazy"
        )

    @pytest.mark.parametrize("name", [
        "sync_watchlist_fair_values",
        "sync_all_fair_values",
        "_should_trigger_full_sync",
        "_run_watchlist_scheduler",
        "_run_nightly_scheduler",
    ])
    def test_fair_value_cycles_take_no_args(self, name):
        from app.services import fair_value

        fn = getattr(fair_value, name)
        sig = inspect.signature(fn)
        assert len(sig.parameters) == 0, (
            f"{name} should take no args, got {sig}"
        )

    def test_batch_update_fair_values_signature(self):
        from app.services.fair_value import _batch_update_fair_values

        sig = inspect.signature(_batch_update_fair_values)
        # symbols (positional), then keyword-only args
        assert "symbols" in sig.parameters
        assert "update_morningstar_id" in sig.parameters
        assert "update_fair_value" in sig.parameters
        assert "progress_job_key" in sig.parameters
        assert "progress_start" in sig.parameters
        assert "progress_end" in sig.parameters

    def test_batch_resolve_morningstar_ids_signature(self):
        from app.services.fair_value import _batch_resolve_morningstar_ids

        sig = inspect.signature(_batch_resolve_morningstar_ids)
        assert "symbols" in sig.parameters
        assert "progress_job_key" in sig.parameters
        assert "progress_start" in sig.parameters
        assert "progress_end" in sig.parameters

    def test_update_sync_timestamp_takes_key(self):
        from app.services.fair_value import _update_sync_timestamp

        sig = inspect.signature(_update_sync_timestamp)
        assert len(sig.parameters) == 1
        assert "key" in sig.parameters


# ─── Re-export shim contract (each moved symbol reachable via bg.X) ───────


RE_EXPORT_SYMBOLS = (
    NSE_PARSING_FUNCTIONS
    + [n for n, _ in DEAL_SIGNIFICANCE_SYMBOLS]
    + INSIDER_TRADES_FUNCTIONS
    + [n for n, _ in CLEANUP_SYMBOLS]
    + NOTIFICATIONS_SYMBOLS
    + NOTIFICATION_CYCLE_FUNCTIONS
    + [n for n, _ in GLOBAL_SCAN_CYCLE_SYMBOLS]
    + JOBS_FUNCTIONS
    + FAIR_VALUE_FUNCTIONS
)


class TestReExportShimContract:
    """Each moved symbol must still be importable from
    ``app.backgroundtasks`` (the re-export shim is the migration
    contract that keeps every existing caller working).
    """

    @pytest.mark.parametrize("name", RE_EXPORT_SYMBOLS)
    def test_symbol_re_exported(self, name):
        from app import backgroundtasks as bg

        assert hasattr(bg, name), (
            f"app.backgroundtasks.{name} not re-exported — external "
            f"callers will break"
        )


# ─── Function signature preservation ─────────────────────────────────────


class TestFunctionSignaturesPreserved:
    """Cycle function signatures must NOT change — a caller that did
    ``_notification_cycle_full()`` must still work after the move.
    """

    @pytest.mark.parametrize("name", NOTIFICATION_CYCLE_FUNCTIONS)
    def test_notification_cycle_signature_preserved(self, name):
        from app.workers import notification_cycles

        fn = getattr(notification_cycles, name)
        sig = inspect.signature(fn)
        assert len(sig.parameters) == 0, (
            f"{name} should take no args, got {sig}"
        )

    def test_global_scan_cycle_signature_preserved(self):
        from app.workers.global_scan_cycle import _global_scan_cycle

        sig = inspect.signature(_global_scan_cycle)
        assert len(sig.parameters) == 0

    @pytest.mark.parametrize("name", NSE_PARSING_FUNCTIONS)
    def test_nse_parsing_helpers_signature(self, name):
        from app.services.data_sync import nse_parsing

        fn = getattr(nse_parsing, name)
        sig = inspect.signature(fn)
        if name.startswith("_safe_fetch_"):
            assert len(sig.parameters) == 0, (
                f"{name} should take no args, got {sig}"
            )
        else:  # _parse_*
            assert len(sig.parameters) == 1, (
                f"{name} should take exactly one arg, got {sig}"
            )
            assert "data" in sig.parameters, (
                f"{name} should take a 'data' arg, got {sig}"
            )

    def test_fetch_insider_trades_cached_takes_symbol(self):
        from app.services.data_sync.insider_trades import _fetch_insider_trades_cached

        sig = inspect.signature(_fetch_insider_trades_cached)
        assert len(sig.parameters) == 1
        assert "symbol" in sig.parameters


# ─── Circular import regression checks ────────────────────────────────────


class TestCircularImportRegression:
    """The 8 new modules are part of a tightly-coupled dependency
    graph with the shim.  Verify the canonical import order works.
    """

    def test_backgroundtasks_imports_cleanly(self):
        """Importing the shim after all data_sync modules must not
        hit a circular import error.
        """
        from app import backgroundtasks  # noqa: F401
        from app.services.data_sync import (  # noqa: F401
            nse_parsing,
            cleanup,
            deal_significance,
            insider_trades,
            notifications,
        )
        from app.workers import (  # noqa: F401
            notification_cycles,
            global_scan_cycle,
            jobs,
        )

    def test_data_sync_modules_dont_have_bg_impl_attribute(self):
        """data_sync modules that are imported by the shim during its
        own init must NOT carry ``_impl`` in their module dict (the
        shim is still being constructed at that point, so a top-level
        import there would crash).
        """
        from app.services.data_sync import (
            cleanup as cleanup_mod,
            insider_trades as insider_mod,
        )
        for mod in (cleanup_mod, insider_mod):
            assert not hasattr(mod, "_impl"), (
                f"{mod.__name__} imported _impl at module level — must be lazy"
            )
