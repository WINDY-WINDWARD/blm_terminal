"""Unit tests for automated AI workflow scheduling and cron math."""

from datetime import datetime, timezone
import pytest

from app.services.workflow_schedule import (
    ScheduleError,
    build_cron,
    default_catch_up_hours,
    describe,
    next_run,
    next_runs,
    slot_key,
    validate_cron,
)


def test_build_cron_daily() -> None:
    expr = build_cron("daily", time_of_day="10:00")
    assert expr == "0 10 * * *"


def test_build_cron_weekdays() -> None:
    expr = build_cron("weekdays", time_of_day="10:00")
    assert expr == "0 10 * * 1-5"


def test_build_cron_weekly() -> None:
    expr = build_cron("weekly", time_of_day="10:00", days_of_week=[1, 3])
    assert expr == "0 10 * * 1,3"


def test_build_cron_hourly() -> None:
    expr = build_cron("hourly", time_of_day=15)
    assert expr == "15 * * * *"


def test_build_cron_once() -> None:
    # 04:30 UTC is 10:00 IST on 03 Nov 2026
    dt_utc = datetime(2026, 11, 3, 4, 30)
    expr = build_cron("once", once_at=dt_utc, tz="Asia/Kolkata")
    assert expr == "0 10 3 11 *"


def test_build_cron_custom_raises() -> None:
    with pytest.raises(ScheduleError, match="use cron_expression"):
        build_cron("custom")


def test_validate_cron_invalid() -> None:
    with pytest.raises(ScheduleError, match="Invalid cron expression"):
        validate_cron("invalid cron expression", "Asia/Kolkata")


def test_validate_cron_invalid_tz() -> None:
    with pytest.raises(ScheduleError, match="Invalid timezone"):
        validate_cron("0 10 * * *", "Invalid/Timezone_Name")


def test_next_run_ist_to_utc_conversion() -> None:
    # 10:00 IST is 04:30 UTC
    after_utc = datetime(2026, 11, 1, 0, 0)
    nr = next_run("0 10 * * *", "Asia/Kolkata", after_utc)
    assert nr == datetime(2026, 11, 1, 4, 30)
    assert nr.tzinfo is None


def test_next_run_across_weekend() -> None:
    # Friday 2026-11-06 12:00 UTC (17:30 IST) -> next weekday run is Monday 2026-11-09 10:00 IST (04:30 UTC)
    after_utc = datetime(2026, 11, 6, 12, 0)
    nr = next_run("0 10 * * 1-5", "Asia/Kolkata", after_utc)
    assert nr == datetime(2026, 11, 9, 4, 30)


def test_next_run_dst_gap_london() -> None:
    # DST transition in London: 2026-03-29 jumps from 01:00 GMT to 02:00 BST.
    # 01:30 does not exist on that date.
    # Schedule math detects DST gap and advances one day to Monday 2026-03-30.
    # On 2026-03-30, 01:30 BST is 00:30 UTC.
    after_utc = datetime(2026, 3, 28, 12, 0)
    nr = next_run("30 1 * * *", "Europe/London", after_utc)
    assert nr == datetime(2026, 3, 30, 0, 30)


def test_next_runs_successive() -> None:
    after_utc = datetime(2026, 11, 1, 0, 0)
    runs = next_runs("0 10 * * *", "Asia/Kolkata", after_utc, count=3)
    assert len(runs) == 3
    assert runs[0] == datetime(2026, 11, 1, 4, 30)
    assert runs[1] == datetime(2026, 11, 2, 4, 30)
    assert runs[2] == datetime(2026, 11, 3, 4, 30)


def test_describe_daily() -> None:
    text = describe("daily", "0 10 * * *", "Asia/Kolkata")
    assert text == "Every day at 10:00 IST"


def test_describe_weekdays() -> None:
    text = describe("weekdays", "15 9 * * 1-5", "Asia/Kolkata")
    assert text == "Weekdays at 09:15 IST"


def test_describe_weekly() -> None:
    text = describe("weekly", "0 8 * * 1", "Asia/Kolkata")
    assert text == "Every Monday at 08:00 IST"


def test_describe_hourly() -> None:
    text = describe("hourly", "15 * * * *", "Asia/Kolkata")
    assert text == "Every hour at :15"


def test_describe_once() -> None:
    text = describe("once", "0 10 3 11 *", "Asia/Kolkata")
    assert text == "Once on 03 Nov 2026 at 10:00 IST"


def test_describe_custom() -> None:
    text = describe("custom", "0 10 * * 1-5", "Asia/Kolkata")
    assert text == "Custom (0 10 * * 1-5)"


def test_default_catch_up_hours() -> None:
    assert default_catch_up_hours("daily") == 12
    assert default_catch_up_hours("weekdays") == 12
    assert default_catch_up_hours("weekly") == 24
    assert default_catch_up_hours("hourly") == 2
    assert default_catch_up_hours("once") == 24
    assert default_catch_up_hours("custom") == 12


def test_slot_key_format() -> None:
    dt = datetime(2026, 11, 3, 10, 0, 0)
    assert slot_key(42, dt) == "42:20261103T100000"
    assert slot_key("wf_abc", dt) == "wf_abc:20261103T100000"
