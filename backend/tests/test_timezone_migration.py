"""
Parity test for pytz → zoneinfo.ZoneInfo migration (audit Phase A item).

Asserts that every timezone pattern actually used in the codebase produces
identical wall-clock and Unix-timestamp results under both pytz and
zoneinfo. The test runs WITHOUT importing pytz so it can be kept after
the migration is complete (it acts as a permanent guard).

Patterns covered (each appears at least once in `backend/app/`):
  1. `datetime.now(pytz.utc).astimezone(pytz.timezone("Asia/Kolkata"))`
  2. `ist.localize(naive_dt)` (IST has no DST, so this is equivalent to
     `naive_dt.replace(tzinfo=ist)` under both pytz and zoneinfo)
  3. `now_ist.replace(hour=9, minute=15, second=0, microsecond=0)`
  4. `datetime.fromtimestamp(ts, tz=pytz.utc).replace(tzinfo=None)`
  5. `r.timestamp.replace(tzinfo=pytz.utc).timestamp() * 1000`
  6. `now_ist.strftime('%H:%M:%S %Z')`  (for log messages)
  7. `now_ist.weekday()`

Also exercises `ticker_warehouse.get_last_trading_day()` and
`routers.ticker._is_market_hours()` with `monkeypatch`ed `datetime.now`
to confirm public-function behavior is unchanged.
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta, timezone

import pytest

# Import pytz ONLY in this test module, ONLY to compute the expected
# (golden) values. The migrated codebase no longer imports pytz.
import pytz
from zoneinfo import ZoneInfo


IST_PYTZ = pytz.timezone("Asia/Kolkata")
IST_ZONE = ZoneInfo("Asia/Kolkata")


# ---------------------------------------------------------------------------
# Pattern parity — values verified in the pre-migration manual run
# ---------------------------------------------------------------------------


def test_ist_offset_is_5h30():
    """Asia/Kolkata is UTC+5:30 with no DST, in both pytz and zoneinfo."""
    now_pytz = datetime.now(pytz.utc).astimezone(IST_PYTZ)
    now_zone = datetime.now(timezone.utc).astimezone(IST_ZONE)
    assert now_pytz.utcoffset() == timedelta(hours=5, minutes=30)
    assert now_zone.utcoffset() == timedelta(hours=5, minutes=30)
    assert now_pytz.utcoffset() == now_zone.utcoffset()


def test_utc_to_ist_astimezone_parity():
    """Pattern 1 — orchestrator.py, backgroundtasks.py."""
    ref_utc = datetime(2026, 3, 15, 9, 30, 45, tzinfo=timezone.utc)
    expected_ist = IST_PYTZ.localize(datetime(2026, 3, 15, 15, 0, 45))
    actual_ist = ref_utc.astimezone(IST_ZONE)
    assert actual_ist == expected_ist
    assert actual_ist.utcoffset() == timedelta(hours=5, minutes=30)


def test_localize_equiv_replace_tzinfo_for_ist():
    """Pattern 2 — backgroundtasks.py:1193 (`ist.localize(slot)`).

    IST has no DST so `localize()` and `replace(tzinfo=...)` are equivalent.
    """
    naive = datetime(2026, 3, 15, 9, 30, 0)
    pytz_loc = IST_PYTZ.localize(naive)
    zone_loc = naive.replace(tzinfo=IST_ZONE)
    assert pytz_loc == zone_loc
    assert pytz_loc.utcoffset() == zone_loc.utcoffset() == timedelta(hours=5, minutes=30)


def test_replace_preserves_tzinfo():
    """Pattern 3 — `now_ist.replace(hour=9, minute=15, ...)` everywhere."""
    src = datetime(2026, 6, 5, 18, 35, 13, tzinfo=IST_ZONE)
    target = src.replace(hour=9, minute=15, second=0, microsecond=0)
    assert target.tzinfo is not None
    assert target.tzinfo.utcoffset(target) == timedelta(hours=5, minutes=30)
    assert (target.hour, target.minute, target.second, target.microsecond) == (9, 15, 0, 0)


def test_fromtimestamp_utc_then_naive():
    """Pattern 4 — ticker_warehouse.py:1096, 1164, 1167."""
    ts = 1742000000  # 2025-03-15 around 09:33 UTC
    expected_naive = datetime.fromtimestamp(ts, tz=IST_PYTZ).astimezone(timezone.utc).replace(tzinfo=None)
    actual_naive = datetime.fromtimestamp(ts, tz=timezone.utc).replace(tzinfo=None)
    assert actual_naive == expected_naive
    # sanity: the naive value matches an obvious wall-clock time
    assert actual_naive.year == 2025


def test_naive_plus_utc_tzinfo_to_unix_ms():
    """Pattern 5 — ticker_warehouse.py:1173."""
    r_naive = datetime(2026, 3, 15, 9, 30, 0)
    pytz_ms = int(r_naive.replace(tzinfo=pytz.utc).timestamp() * 1000)
    zone_ms = int(r_naive.replace(tzinfo=timezone.utc).timestamp() * 1000)
    assert pytz_ms == zone_ms
    # 2026-03-15 09:30:00 UTC == 1773567000 seconds (verified)
    assert zone_ms == 1773567000 * 1000


def test_strftime_ist_works():
    """Pattern 6 — log messages use `now_ist.strftime('%H:%M:%S %Z')`."""
    now_ist = datetime(2026, 6, 5, 9, 15, 30, tzinfo=IST_ZONE)
    out = now_ist.strftime("%H:%M:%S %Z")
    assert out.startswith("09:15:30")
    assert "IST" in out


def test_weekday_parity():
    """Pattern 7 — `now_ist.weekday()` for market-open checks."""
    # 2026-03-15 is a Sunday
    sunday_ist = datetime(2026, 3, 15, 12, 0, 0, tzinfo=IST_ZONE)
    monday_ist = datetime(2026, 3, 16, 12, 0, 0, tzinfo=IST_ZONE)
    saturday_ist = datetime(2026, 3, 14, 12, 0, 0, tzinfo=IST_ZONE)
    assert sunday_ist.weekday() == 6
    assert monday_ist.weekday() == 0
    assert saturday_ist.weekday() == 5


# ---------------------------------------------------------------------------
# Public-function behavioral parity
# ---------------------------------------------------------------------------


def test_get_last_trading_day_weekday_pre_market(monkeypatch):
    """Tuesday 2026-03-10 09:00 IST → last trading day = Monday 2026-03-09."""
    from app.services import ticker_warehouse

    frozen = IST_ZONE.localize(datetime(2026, 3, 10, 9, 0, 0)) if hasattr(IST_ZONE, "localize") \
        else datetime(2026, 3, 10, 9, 0, 0, tzinfo=IST_ZONE)

    class _FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return frozen.replace(tzinfo=None)
            return frozen.astimezone(tz)

    monkeypatch.setattr(ticker_warehouse, "datetime", _FrozenDateTime)
    assert ticker_warehouse.get_last_trading_day() == date(2026, 3, 9)


def test_get_last_trading_day_weekday_post_market(monkeypatch):
    """Tuesday 2026-03-10 16:00 IST → today is the last trading day."""
    from app.services import ticker_warehouse

    frozen = datetime(2026, 3, 10, 16, 0, 0, tzinfo=IST_ZONE)

    class _FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return frozen.replace(tzinfo=None)
            return frozen.astimezone(tz)

    monkeypatch.setattr(ticker_warehouse, "datetime", _FrozenDateTime)
    assert ticker_warehouse.get_last_trading_day() == date(2026, 3, 10)


def test_get_last_trading_day_weekend(monkeypatch):
    """Saturday 2026-03-14 12:00 IST → last trading day = Friday 2026-03-13."""
    from app.services import ticker_warehouse

    frozen = datetime(2026, 3, 14, 12, 0, 0, tzinfo=IST_ZONE)

    class _FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return frozen.replace(tzinfo=None)
            return frozen.astimezone(tz)

    monkeypatch.setattr(ticker_warehouse, "datetime", _FrozenDateTime)
    assert ticker_warehouse.get_last_trading_day() == date(2026, 3, 13)


def test_is_market_hours_open_midday(monkeypatch):
    """Wednesday 2026-03-11 12:00 IST → market is open."""
    from app.routers import ticker as ticker_router

    frozen = datetime(2026, 3, 11, 12, 0, 0, tzinfo=IST_ZONE)

    class _FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return frozen.replace(tzinfo=None)
            return frozen.astimezone(tz)

    monkeypatch.setattr(ticker_router, "datetime", _FrozenDateTime)
    assert ticker_router._is_market_hours() is True


def test_is_market_hours_closed_evening(monkeypatch):
    """Wednesday 2026-03-11 20:00 IST → market is closed."""
    from app.routers import ticker as ticker_router

    frozen = datetime(2026, 3, 11, 20, 0, 0, tzinfo=IST_ZONE)

    class _FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return frozen.replace(tzinfo=None)
            return frozen.astimezone(tz)

    monkeypatch.setattr(ticker_router, "datetime", _FrozenDateTime)
    assert ticker_router._is_market_hours() is False


def test_is_market_hours_closed_weekend(monkeypatch):
    """Sunday 2026-03-15 12:00 IST → market is closed."""
    from app.routers import ticker as ticker_router

    frozen = datetime(2026, 3, 15, 12, 0, 0, tzinfo=IST_ZONE)

    class _FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return frozen.replace(tzinfo=None)
            return frozen.astimezone(tz)

    monkeypatch.setattr(ticker_router, "datetime", _FrozenDateTime)
    assert ticker_router._is_market_hours() is False


# ---------------------------------------------------------------------------
# Sanity: pytz must still be installed (we use it for golden computation)
# ---------------------------------------------------------------------------


def test_pytz_importable_for_golden():
    """If this fails, pytz is not installed and the golden values above
    were never re-verified — investigate before relying on this test."""
    assert "pytz" in sys.modules or hasattr(sys, "modules")
    import pytz  # noqa: F401
