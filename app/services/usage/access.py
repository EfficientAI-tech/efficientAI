"""Usage read access policy — date window clamping and SQL floor for OSS tier."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional
from uuid import UUID

from loguru import logger

from app.core.usage_entitlement import (
    OSS_USAGE_HISTORY_DAYS,
    UsagePolicySnapshot,
    get_usage_policy,
    has_enterprise_entitlement,
)
from app.services.usage.dates import usage_date_filter_bounds, usage_local_today


@dataclass(frozen=True)
class UsageAccessResult:
    display_start: date
    display_end: date
    filter_start: date
    filter_end: date
    enforced_filter_floor: Optional[date]
    policy: UsagePolicySnapshot
    range_clamped: bool


def oss_usage_min_local_date(tz: Optional[str]) -> date:
    """Earliest inclusive local calendar day allowed for OSS tier."""
    today = usage_local_today(tz)
    return today - timedelta(days=OSS_USAGE_HISTORY_DAYS - 1)


class UsageAccessPolicy:
    @staticmethod
    def resolve(
        organization_id: UUID,
        start: Optional[date],
        end: Optional[date],
        tz: Optional[str],
    ) -> UsageAccessResult:
        today = usage_local_today(tz)
        display_start = start or today
        display_end = end or today
        policy = get_usage_policy(organization_id)
        range_clamped = False
        enforced_floor: Optional[date] = None

        if not has_enterprise_entitlement(organization_id):
            oss_min = oss_usage_min_local_date(tz)
            if display_start < oss_min:
                display_start = oss_min
                range_clamped = True
            enforced_floor = usage_date_filter_bounds(oss_min, oss_min, tz)[0]

        filter_start, filter_end = usage_date_filter_bounds(
            display_start, display_end, tz
        )

        if enforced_floor is not None and filter_start < enforced_floor:
            filter_start = enforced_floor

        if range_clamped:
            logger.info(
                "usage_history_clamped org_id={} effective_start={} effective_end={}",
                organization_id,
                display_start,
                display_end,
            )

        return UsageAccessResult(
            display_start=display_start,
            display_end=display_end,
            filter_start=filter_start,
            filter_end=filter_end,
            enforced_filter_floor=enforced_floor,
            policy=policy,
            range_clamped=range_clamped,
        )
