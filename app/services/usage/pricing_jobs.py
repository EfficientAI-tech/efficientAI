"""Usage cost recompute job lifecycle."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Dict, Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.database import UsageCostRecomputeJob

ACTIVE_JOB_STATUSES = ("pending", "running")
TERMINAL_JOB_STATUSES = ("completed", "failed")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def get_recompute_job(
    db: Session,
    *,
    organization_id: UUID,
    job_id: UUID,
) -> UsageCostRecomputeJob:
    job = (
        db.query(UsageCostRecomputeJob)
        .filter(
            UsageCostRecomputeJob.id == job_id,
            UsageCostRecomputeJob.organization_id == organization_id,
        )
        .first()
    )
    if job is None:
        raise HTTPException(status_code=404, detail="Recompute job not found")
    return job


def create_recompute_job(
    db: Session,
    *,
    organization_id: UUID,
    model: Optional[str] = None,
    usage_kind: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> UsageCostRecomputeJob:
    active = (
        db.query(UsageCostRecomputeJob)
        .filter(
            UsageCostRecomputeJob.organization_id == organization_id,
            UsageCostRecomputeJob.status.in_(ACTIVE_JOB_STATUSES),
        )
        .first()
    )
    if active is not None:
        raise HTTPException(
            status_code=409,
            detail="A usage cost recompute job is already in progress",
        )

    job = UsageCostRecomputeJob(
        organization_id=organization_id,
        status="pending",
        model=model,
        usage_kind=usage_kind,
        start_date=start_date,
        end_date=end_date,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def enqueue_recompute_job(db: Session, job: UsageCostRecomputeJob) -> str:
    from app.workers.tasks import recompute_usage_costs_task

    result = recompute_usage_costs_task.delay(job_id=str(job.id))
    job.celery_task_id = result.id
    job.updated_at = _utcnow()
    db.commit()
    return result.id


def mark_job_running(db: Session, job_id: UUID) -> None:
    job = db.query(UsageCostRecomputeJob).filter(UsageCostRecomputeJob.id == job_id).first()
    if job is None:
        return
    job.status = "running"
    job.updated_at = _utcnow()
    db.commit()


def update_job_progress(db: Session, job_id: UUID, updated_rows: int) -> None:
    job = db.query(UsageCostRecomputeJob).filter(UsageCostRecomputeJob.id == job_id).first()
    if job is None:
        return
    job.updated_rows = updated_rows
    job.updated_at = _utcnow()
    db.commit()


def mark_job_completed(db: Session, job_id: UUID, updated_rows: int) -> None:
    job = db.query(UsageCostRecomputeJob).filter(UsageCostRecomputeJob.id == job_id).first()
    if job is None:
        return
    now = _utcnow()
    job.status = "completed"
    job.updated_rows = updated_rows
    job.updated_at = now
    job.completed_at = now
    db.commit()


def mark_job_failed(db: Session, job_id: UUID, error_message: str) -> None:
    job = db.query(UsageCostRecomputeJob).filter(UsageCostRecomputeJob.id == job_id).first()
    if job is None:
        return
    now = _utcnow()
    job.status = "failed"
    job.error_message = error_message[:4000]
    job.updated_at = now
    job.completed_at = now
    db.commit()


def job_to_dict(job: UsageCostRecomputeJob) -> Dict[str, Any]:
    return {
        "id": job.id,
        "organization_id": job.organization_id,
        "status": job.status,
        "model": job.model,
        "usage_kind": job.usage_kind,
        "start_date": job.start_date,
        "end_date": job.end_date,
        "updated_rows": int(job.updated_rows or 0),
        "error_message": job.error_message,
        "celery_task_id": job.celery_task_id,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "completed_at": job.completed_at,
    }
