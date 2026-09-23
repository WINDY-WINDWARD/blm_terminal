"""Tests for the missed-schedule catch-up (desktop opportunistic runs).

 pure logic (prev-fire, missed detection, plan ordering) is tested without
a DB; the runner path is tested with fakes.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.workers import catchup as cu

IST = ZoneInfo("Asia/Kolkata")


def _ist(y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=IST)


class TestPrevFire:
    def test_daily_midnight(self):
        # Tuesday 10:00 IST → previous 00:00 fire is today at midnight.
        now = _ist(2026, 9, 22, 10, 0)
        assert cu.prev_fire_ist("0 0 * * *", now) == _ist(2026, 9, 22, 0, 0).astimezone(timezone.utc)

    def test_weekly_sunday(self):
        # Tuesday → previous Sunday 04:00.
        now = _ist(2026, 9, 22, 10, 0)
        assert cu.prev_fire_ist("0 4 * * 0", now) == _ist(2026, 9, 20, 4, 0).astimezone(timezone.utc)

    def test_weekday_only_skips_weekend(self):
        # Monday 09:00, 11:00 MF job → previous fire Friday 11:00.
        now = _ist(2026, 9, 21, 9, 0)
        assert cu.prev_fire_ist("0 11 * * 1-5", now) == _ist(2026, 9, 18, 11, 0).astimezone(timezone.utc)

    def test_startup_and_none_yield_none(self):
        now = _ist(2026, 9, 22, 10, 0)
        assert cu.prev_fire_ist("@startup", now) is None
        assert cu.prev_fire_ist(None, now) is None
        assert cu.prev_fire_ist("not a cron", now) is None


class TestIsMissed:
    def test_never_ran_is_missed(self):
        now = _ist(2026, 9, 22, 10, 0)
        assert cu.is_missed("0 0 * * *", None, now) is True

    def test_recent_success_not_missed(self):
        now = _ist(2026, 9, 22, 10, 0)
        assert cu.is_missed("0 0 * * *", _ist(2026, 9, 22, 0, 5).astimezone(timezone.utc), now) is False

    def test_stale_success_is_missed(self):
        now = _ist(2026, 9, 22, 10, 0)
        assert cu.is_missed("0 0 * * *", _ist(2026, 9, 21, 0, 5).astimezone(timezone.utc), now) is True

    def test_naive_success_assumed_utc(self):
        now = _ist(2026, 9, 22, 10, 0)
        naive = datetime(2026, 9, 22, 0, 5)  # 00:05 UTC == 05:35 IST, after midnight fire
        assert cu.is_missed("0 0 * * *", naive, now) is False


class TestCatchupPlan:
    def test_order_and_filtering(self):
        now = _ist(2026, 9, 22, 10, 0)
        defs = [
            ("job.stock_universe", "0 0 * * *"),
            ("job.vacuum", "0 4 * * 0"),
            ("job.news", "*/5 * * * *"),
        ]
        successes = {
            # universe ran at 00:05 today → covered.
            "job.stock_universe": _ist(2026, 9, 22, 0, 5).astimezone(timezone.utc),
            # vacuum last ran 8 days ago → missed (prev Sunday).
            "job.vacuum": _ist(2026, 9, 14, 4, 5).astimezone(timezone.utc),
            # news ran 3 min ago → its */5 prev-fire (10:00) is covered.
            "job.news": (now - timedelta(minutes=3)),
        }
        assert cu.catchup_plan(defs, successes, now) == ["job.vacuum"]


class TestRunMissedCatchup:
    @pytest.mark.asyncio
    async def test_runs_missed_serialized(self, monkeypatch: pytest.MonkeyPatch):
        import app.workers.catchup as m

        monkeypatch.setattr(m, "_CATCHUP_INITIAL_DELAY_S", 0)
        monkeypatch.setattr(m, "_CATCHUP_STAGGER_S", 0)
        monkeypatch.setattr(m, "CATCHUP_JOB_KEYS", ["job.fundamentals", "job.vacuum"])

        from app.jobs.registry import JobDefinition, JobRegistry

        for key, cron in [("job.fundamentals", "30 1 * * *"), ("job.vacuum", "0 4 * * 0")]:
            JobRegistry.register(JobDefinition(
                job_key=key, name=key.split(".")[1], description="t",
                category="t", cron_expression=cron, callable=lambda: None))

        ran: list[str] = []

        class FakeStatus:
            def __init__(self, status, success):
                self.status = status
                self.last_success_at = success

        async def fake_status(key):
            return FakeStatus("idle", None)  # never ran → missed

        async def fake_run(key):
            ran.append(key)

        monkeypatch.setattr(m, "get_job_status", fake_status)
        monkeypatch.setattr(m, "run_job_async", fake_run)
        import app.backgroundtasks._runtime as rt
        monkeypatch.setattr(rt, "_is_job_enabled", lambda k: True)
        monkeypatch.setattr(rt, "_shutdown_event", SimpleNamespace(is_set=lambda: False))

        out = await m.run_missed_catchup()
        assert out["missed"] == 2
        assert ran == ["job.fundamentals", "job.vacuum"]
        assert out["completed"] == 2

    @pytest.mark.asyncio
    async def test_skips_running_and_disabled(self, monkeypatch: pytest.MonkeyPatch):
        import app.workers.catchup as m

        monkeypatch.setattr(m, "_CATCHUP_INITIAL_DELAY_S", 0)
        monkeypatch.setattr(m, "_CATCHUP_STAGGER_S", 0)
        monkeypatch.setattr(m, "CATCHUP_JOB_KEYS", ["job.a", "job.b"])

        from app.jobs.registry import JobDefinition, JobRegistry

        for key in ["job.a", "job.b"]:
            JobRegistry.register(JobDefinition(
                job_key=key, name=key, description="t",
                category="t", cron_expression="0 0 * * *", callable=lambda: None))

        async def fake_status(key):
            class S:
                status = "running" if key == "job.a" else "idle"
                last_success_at = None
            return S()

        ran: list[str] = []

        async def fake_run(key):
            ran.append(key)

        monkeypatch.setattr(m, "get_job_status", fake_status)
        monkeypatch.setattr(m, "run_job_async", fake_run)
        enabled = {"job.a": True, "job.b": False}
        import app.backgroundtasks._runtime as rt
        monkeypatch.setattr(rt, "_is_job_enabled", lambda k: enabled[k])
        monkeypatch.setattr(rt, "_shutdown_event", SimpleNamespace(is_set=lambda: False))

        out = await m.run_missed_catchup()
        assert ran == []
        assert out["skipped"] == 2
