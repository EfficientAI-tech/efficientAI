"""Shared cron scheduling helpers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import pytz
from croniter import croniter


def calculate_next_run(cron_expression: str, tz_name: str) -> Optional[datetime]:
    try:
        tz = pytz.timezone(tz_name)
        now = datetime.now(tz)
        cron = croniter(cron_expression, now)
        return cron.get_next(datetime).astimezone(timezone.utc)
    except Exception:
        return None


def calculate_next_run_for_job(job) -> Optional[datetime]:
    config: dict[str, Any] = job.config if isinstance(job.config, dict) else {}
    interval_days = config.get("interval_days")
    if interval_days:
        try:
            days = int(interval_days)
            if days > 0:
                return datetime.now(timezone.utc) + timedelta(days=days)
        except (TypeError, ValueError):
            pass
    return calculate_next_run(job.cron_expression, job.timezone)
