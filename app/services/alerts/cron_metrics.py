"""Cron job metrics for org alerting."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.models.database import CronJob
from app.models.enums import AlertMetricType


def compute_cron_jobs_metric(
    db: Session,
    organization_id: UUID,
    metric_type: str,
    window_start: datetime,
) -> float | None:
    mtype = (metric_type or "").lower()
    if mtype not in (AlertMetricType.FAILURE_COUNT.value, "failure_count"):
        return None

    rows = (
        db.query(CronJob)
        .filter(
            and_(
                CronJob.organization_id == organization_id,
                CronJob.is_system.is_(False),
                or_(
                    and_(
                        CronJob.last_dispatch_status == "failed",
                        CronJob.last_dispatch_at.isnot(None),
                        CronJob.last_dispatch_at >= window_start,
                    ),
                    and_(
                        CronJob.last_run_status == "failed",
                        CronJob.last_run_at.isnot(None),
                        CronJob.last_run_at >= window_start,
                    ),
                ),
            )
        )
        .all()
    )
    count = 0
    for job in rows:
        if job.last_dispatch_status == "failed" and _in_window(
            getattr(job, "last_dispatch_at", None), window_start
        ):
            count += 1
            continue
        if job.last_run_status == "failed" and _in_window(job.last_run_at, window_start):
            count += 1
    return float(count)


def _in_window(moment: datetime | None, window_start: datetime) -> bool:
    if moment is None:
        return False
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=window_start.tzinfo)
    start = window_start
    if start.tzinfo is None and moment.tzinfo is not None:
        start = start.replace(tzinfo=moment.tzinfo)
    return moment >= start
