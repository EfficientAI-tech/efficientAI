"""Cron job metrics for org alerting."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.models.database import CronJob
from app.models.enums import AlertMetricType, CronJobStatus


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
                CronJob.status == CronJobStatus.ACTIVE.value,
                or_(
                    CronJob.last_dispatch_status == "failed",
                    CronJob.last_run_status == "failed",
                ),
            )
        )
        .all()
    )
    count = 0
    for job in rows:
        if job.last_dispatch_status == "failed":
            count += 1
            continue
        ts = job.last_run_at or job.updated_at
        if ts is not None and ts >= window_start:
            count += 1
    return float(count)
