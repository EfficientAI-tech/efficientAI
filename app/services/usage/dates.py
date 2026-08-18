"""Local calendar dates vs UTC usage_date bucket bounds."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def resolve_usage_timezone(tz: str | None) -> ZoneInfo:
    if not tz:
        return ZoneInfo("UTC")
    try:
        return ZoneInfo(tz)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def usage_local_today(tz: str | None) -> date:
    return datetime.now(resolve_usage_timezone(tz)).date()


def usage_date_filter_bounds(
    start: date,
    end: date,
    tz: str | None,
) -> tuple[date, date]:
    """Map inclusive local calendar days to usage_date (UTC-day) filter bounds."""
    if not tz:
        return start, end

    zone = resolve_usage_timezone(tz)
    start_local = datetime.combine(start, time.min, tzinfo=zone)
    end_exclusive = datetime.combine(end + timedelta(days=1), time.min, tzinfo=zone)
    filter_start = start_local.astimezone(timezone.utc).date()
    filter_end = (
        end_exclusive - timedelta(seconds=1)
    ).astimezone(timezone.utc).date()
    return filter_start, filter_end
