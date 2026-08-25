"""Shared cron scheduling helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

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
