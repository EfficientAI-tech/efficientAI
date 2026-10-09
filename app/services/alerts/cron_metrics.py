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
                    CronJob.last_dispatch_status == "failed",
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
        if job.last_dispatch_status == "failed":
            count += 1
            continue
        if job.last_run_status == "failed" and job.last_run_at is not None:
            if job.last_run_at >= window_start:
                count += 1
    return float(count)
