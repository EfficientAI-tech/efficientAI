"""Turn named periods ("this_week", "yesterday") into exact UTC ranges.

Models are unreliable at calendar arithmetic, so tools take a period name and
the server resolves it in the user's time zone. Every answer echoes the
resolved range so the user can see exactly what was counted.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

PERIODS = (
    "today",
    "yesterday",
    "this_week",
    "last_week",
    "last_7_days",
    "this_month",
    "last_month",
    "last_30_days",
    "custom",
)

MAX_CUSTOM_RANGE_DAYS = 366


@dataclass(frozen=True)
class ResolvedPeriod:
    label: str
    start: datetime  # inclusive, UTC
    end: datetime  # exclusive, UTC
    timezone: str

    def as_dict(self) -> dict:
        tz = ZoneInfo(self.timezone)
        local_end = self.end.astimezone(tz) - timedelta(microseconds=1)
        return {
            "period": self.label,
            "timezone": self.timezone,
            "start_local": self.start.astimezone(tz).strftime("%Y-%m-%d %H:%M"),
            "end_local": local_end.strftime("%Y-%m-%d %H:%M"),
            "start_utc": self.start.isoformat(),
            "end_utc": self.end.isoformat(),
        }


def safe_zone(name: Optional[str]) -> ZoneInfo:
    if name:
        try:
            return ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError):
            pass
    return ZoneInfo("UTC")


def _local_midnight(day: date, tz: ZoneInfo) -> datetime:
    return datetime.combine(day, time.min, tzinfo=tz).astimezone(timezone.utc)


def resolve_period(
    period: str,
    tz_name: Optional[str],
    *,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    now: Optional[datetime] = None,
) -> ResolvedPeriod:
    """Weeks start on Monday. ``custom`` uses inclusive local dates."""
    tz = safe_zone(tz_name)
    tz_key = getattr(tz, "key", "UTC")
    today = (now or datetime.now(timezone.utc)).astimezone(tz).date()

    if period == "custom":
        if start_date is None:
            raise ValueError("custom period needs start_date (YYYY-MM-DD)")
        last = end_date or today
        if last < start_date:
            raise ValueError("end_date is before start_date")
        if (last - start_date).days > MAX_CUSTOM_RANGE_DAYS:
            raise ValueError(f"custom range is limited to {MAX_CUSTOM_RANGE_DAYS} days")
        first = start_date
    elif period == "today":
        first, last = today, today
    elif period == "yesterday":
        first = last = today - timedelta(days=1)
    elif period == "this_week":
        first, last = today - timedelta(days=today.weekday()), today
    elif period == "last_week":
        this_monday = today - timedelta(days=today.weekday())
        first, last = this_monday - timedelta(days=7), this_monday - timedelta(days=1)
    elif period == "last_7_days":
        first, last = today - timedelta(days=6), today
    elif period == "this_month":
        first, last = today.replace(day=1), today
    elif period == "last_month":
        this_first = today.replace(day=1)
        last = this_first - timedelta(days=1)
        first = last.replace(day=1)
    elif period == "last_30_days":
        first, last = today - timedelta(days=29), today
    else:
        raise ValueError(f"unknown period {period!r}; use one of {', '.join(PERIODS)}")

    return ResolvedPeriod(
        label=period,
        start=_local_midnight(first, tz),
        end=_local_midnight(last + timedelta(days=1), tz),
        timezone=tz_key,
    )
