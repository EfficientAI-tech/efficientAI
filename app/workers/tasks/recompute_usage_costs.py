"""Celery task: recompute stored usage costs for rollup rows."""

from __future__ import annotations

from datetime import date
from typing import Optional
from uuid import UUID

from loguru import logger

from app.database import SessionLocal
from app.workers.config import celery_app


@celery_app.task(name="recompute_usage_costs")
def recompute_usage_costs_task(
    job_id: Optional[str] = None,
    organization_id: Optional[str] = None,
    model: Optional[str] = None,
    usage_kind: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> dict:
    from app.models.database import UsageCostRecomputeJob
    from app.services.usage.pricing import recompute_usage_costs
    from app.services.usage.pricing_jobs import (
        mark_job_completed,
        mark_job_failed,
        mark_job_running,
        update_job_progress,
    )

    db = SessionLocal()
    try:
        if job_id:
            job = (
                db.query(UsageCostRecomputeJob)
                .filter(UsageCostRecomputeJob.id == UUID(job_id))
                .first()
            )
            if job is None:
                return {"updated_rows": 0, "error": "job not found"}
            mark_job_running(db, job.id)
            org_uuid = job.organization_id
            model = job.model
            usage_kind = job.usage_kind
            start = job.start_date
            end = job.end_date
            progress_job_id = job.id
        else:
            org_uuid = UUID(organization_id) if organization_id else None
            start = date.fromisoformat(start_date) if start_date else None
            end = date.fromisoformat(end_date) if end_date else None
            progress_job_id = None

        def _on_progress(updated_rows: int) -> None:
            if progress_job_id is not None:
                update_job_progress(db, progress_job_id, updated_rows)

        updated = recompute_usage_costs(
            db,
            organization_id=org_uuid,
            model=model,
            usage_kind=usage_kind,
            start_date=start,
            end_date=end,
            on_progress=_on_progress if progress_job_id else None,
        )
        if progress_job_id is not None:
            mark_job_completed(db, progress_job_id, updated)
        if updated:
            logger.info("Recomputed usage costs for {} rollup row(s)", updated)
        return {"updated_rows": updated, "job_id": job_id}
    except Exception as exc:
        if job_id:
            mark_job_failed(db, UUID(job_id), str(exc))
        raise
    finally:
        db.close()
