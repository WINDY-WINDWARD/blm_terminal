"""Schedule math and cron utilities for automated AI workflows."""

from datetime import datetime, timedelta, timezone
import zoneinfo
import croniter

SCHEDULE_TYPES = ("daily", "weekdays", "weekly", "hourly", "once", "custom")

DAY_NAMES = {
    0: "Sunday",
    1: "Monday",
    2: "Tuesday",
    3: "Wednesday",
    4: "Thursday",
    5: "Friday",
    6: "Saturday",
    7: "Sunday",
}


class ScheduleError(ValueError):
    """Raised when schedule parameters or cron expressions are invalid."""


def build_cron(
    schedule_type: str,
    *,
    time_of_day: str | int | None = None,
    days_of_week: list[int] | str | int | None = None,
    once_at: datetime | None = None,
    tz: str | zoneinfo.ZoneInfo = "Asia/Kolkata",
) -> str:
    """Build a standard 5-part cron expression for a schedule type."""
    if schedule_type not in SCHEDULE_TYPES:
        raise ScheduleError(f"Unsupported schedule type: {schedule_type}")

    if schedule_type == "custom":
        raise ScheduleError("use cron_expression")

    if schedule_type == "hourly":
        minute = 0
        if time_of_day is not None:
            if isinstance(time_of_day, int):
                minute = time_of_day
            elif ":" in str(time_of_day):
                minute = int(str(time_of_day).split(":")[-1])
            else:
                minute = int(str(time_of_day))
        return f"{minute} * * * *"

    if schedule_type == "once":
        if once_at is None:
            raise ScheduleError("once_at is required for once schedule")
        tz_obj = zoneinfo.ZoneInfo(tz) if isinstance(tz, str) else tz
        if once_at.tzinfo is None:
            aware_dt = once_at.replace(tzinfo=timezone.utc)
        else:
            aware_dt = once_at.astimezone(timezone.utc)
        local_dt = aware_dt.astimezone(tz_obj)
        return f"{local_dt.minute} {local_dt.hour} {local_dt.day} {local_dt.month} *"

    # daily, weekdays, weekly
    h, m = 9, 0
    if time_of_day is not None:
        if ":" in str(time_of_day):
            parts = str(time_of_day).split(":")
            h = int(parts[0]) if parts[0] else 0
            m = int(parts[1]) if len(parts) > 1 and parts[1] else 0
        else:
            h = int(time_of_day)
            m = 0

    if schedule_type == "daily":
        return f"{m} {h} * * *"

    if schedule_type == "weekdays":
        return f"{m} {h} * * 1-5"

    if schedule_type == "weekly":
        if days_of_week is None:
            dow_str = "1"
        elif isinstance(days_of_week, (list, tuple, set)):
            dow_str = ",".join(str(d) for d in sorted(days_of_week))
        else:
            dow_str = str(days_of_week).strip()
        return f"{m} {h} * * {dow_str}"

    raise ScheduleError(f"Unhandled schedule type: {schedule_type}")


def validate_cron(expr: str, tz: str | zoneinfo.ZoneInfo = "Asia/Kolkata") -> None:
    """Validate a cron expression and timezone. Raise ScheduleError on error."""
    try:
        if isinstance(tz, str):
            zoneinfo.ZoneInfo(tz)
    except Exception as e:
        raise ScheduleError(f"Invalid timezone: {tz}") from e

    if not croniter.croniter.is_valid(expr):
        raise ScheduleError(f"Invalid cron expression: {expr}")


def next_run(expr: str, tz: str | zoneinfo.ZoneInfo, after_utc: datetime) -> datetime:
    """Compute the next run timestamp as naive UTC datetime."""
    validate_cron(expr, tz)
    tz_obj = zoneinfo.ZoneInfo(tz) if isinstance(tz, str) else tz
    if after_utc.tzinfo is None:
        after_aware = after_utc.replace(tzinfo=timezone.utc)
    else:
        after_aware = after_utc.astimezone(timezone.utc)

    local_start = after_aware.astimezone(tz_obj)
    it = croniter.croniter(expr, local_start)
    nxt = it.get_next(datetime)

    cron_parts = expr.strip().split()
    if len(cron_parts) >= 2 and cron_parts[1].isdigit():
        expected_hour = int(cron_parts[1])
        if nxt.hour != expected_hour:
            advance_dt = (nxt + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            it_retry = croniter.croniter(expr, advance_dt)
            nxt = it_retry.get_next(datetime)

    utc_dt = nxt.astimezone(timezone.utc)
    return utc_dt.replace(tzinfo=None)


def next_runs(
    expr: str,
    tz: str | zoneinfo.ZoneInfo,
    after_utc: datetime,
    count: int = 3,
) -> list[datetime]:
    """Compute count successive naive UTC run timestamps."""
    runs: list[datetime] = []
    current_after = after_utc
    for _ in range(count):
        nr = next_run(expr, tz, current_after)
        runs.append(nr)
        current_after = nr
    return runs


def describe(schedule_type: str, cron: str, tz: str | zoneinfo.ZoneInfo = "Asia/Kolkata") -> str:
    """Return a human-readable description for a schedule."""
    if schedule_type == "custom":
        return f"Custom ({cron})"

    parts = cron.strip().split()
    if len(parts) < 5:
        return f"Custom ({cron})"

    minute = int(parts[0]) if parts[0].isdigit() else 0
    hour = int(parts[1]) if parts[1].isdigit() else 0

    if schedule_type == "hourly":
        return f"Every hour at :{minute:02d}"

    tz_obj = zoneinfo.ZoneInfo(tz) if isinstance(tz, str) else tz
    tz_abbr = datetime.now(tz_obj).strftime("%Z")

    if schedule_type == "daily":
        return f"Every day at {hour:02d}:{minute:02d} {tz_abbr}"

    if schedule_type == "weekdays":
        return f"Weekdays at {hour:02d}:{minute:02d} {tz_abbr}"

    if schedule_type == "weekly":
        dow_part = parts[4]
        if "," in dow_part:
            days = [DAY_NAMES.get(int(x), x) for x in dow_part.split(",") if x.isdigit()]
            day_str = ", ".join(days)
        elif dow_part.isdigit():
            day_str = DAY_NAMES.get(int(dow_part), dow_part)
        elif dow_part == "1-5":
            day_str = "Mon-Fri"
        else:
            day_str = dow_part
        return f"Every {day_str} at {hour:02d}:{minute:02d} {tz_abbr}"

    if schedule_type == "once":
        day = int(parts[2]) if parts[2].isdigit() else 1
        month = int(parts[3]) if parts[3].isdigit() else 1
        now = datetime.now(tz_obj)
        year = int(parts[5]) if len(parts) > 5 and parts[5].isdigit() else now.year
        if len(parts) <= 5 and (month, day) < (now.month, now.day):
            year += 1
        dt = datetime(year, month, day, hour, minute)
        return f"Once on {dt.strftime('%d %b %Y')} at {hour:02d}:{minute:02d} {tz_abbr}"

    return f"Custom ({cron})"


def default_catch_up_hours(schedule_type: str) -> int:
    """Return the default catch-up window in hours for a schedule type."""
    mapping = {
        "daily": 12,
        "weekdays": 12,
        "weekly": 24,
        "hourly": 2,
        "once": 24,
        "custom": 12,
    }
    return mapping.get(schedule_type, 12)


def slot_key(workflow_id: int | str, scheduled_for_utc: datetime) -> str:
    """Generate a unique slot key for an execution occurrence."""
    return f"{workflow_id}:{scheduled_for_utc:%Y%m%dT%H%M%S}"
