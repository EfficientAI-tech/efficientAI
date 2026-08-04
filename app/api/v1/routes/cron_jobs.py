"""Cron Jobs routes."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import and_
from uuid import UUID
from typing import List, Optional
from datetime import datetime, timedelta
from croniter import croniter
import pytz

from app.database import get_db
from app.dependencies import get_organization_id
from app.models.database import CronJob, Evaluator, EvaluatorSuite
from app.models.enums import CronJobStatus
from app.models.schemas import (
    CronJobCreate,
    CronJobUpdate,
    CronJobResponse,
)

router = APIRouter(prefix="/cron-jobs", tags=["cron-jobs"])


def _expand_evaluator_ids_for_cron(
    db: Session,
    organization_id: UUID,
    evaluator_ids: Optional[List[UUID]],
    evaluator_suite_ids: Optional[List[UUID]],
) -> List[UUID]:
    resolved: List[UUID] = list(evaluator_ids or [])
    if evaluator_suite_ids:
        from app.services.evaluators.evaluator_helpers import expand_suite_runs, load_suite_combinations

        for suite_id in evaluator_suite_ids:
            suite = db.query(EvaluatorSuite).filter(
                and_(
                    EvaluatorSuite.id == suite_id,
                    EvaluatorSuite.organization_id == organization_id,
                )
            ).first()
            if not suite:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Evaluator suite not found: {suite_id}",
                )
            combinations = load_suite_combinations(
                db, suite.id, suite.organization_id, suite.workspace_id
            )
            combo_ids = [c.id for c in combinations]
            runs = suite.default_runs_per_combination or 1
            resolved.extend(expand_suite_runs(combo_ids, runs))
    if not resolved:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide evaluator_ids and/or evaluator_suite_ids",
        )
    return resolved


def calculate_next_run(cron_expression: str, timezone: str) -> Optional[datetime]:
    """Calculate the next run time based on cron expression and timezone."""
    try:
        tz = pytz.timezone(timezone)
        now = datetime.now(tz)
        cron = croniter(cron_expression, now)
        next_run = cron.get_next(datetime)
        # Convert to UTC for storage
        return next_run.astimezone(pytz.UTC)
    except Exception:
        return None


# ============================================
# CRON JOB CRUD ENDPOINTS
# ============================================

@router.post("", response_model=CronJobResponse, status_code=201)
def create_cron_job(
    cron_job_data: CronJobCreate,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """Create a new cron job."""
    # Check if cron job with same name already exists for this organization
    existing = db.query(CronJob).filter(
        and_(
            CronJob.name == cron_job_data.name,
            CronJob.organization_id == organization_id
        )
    ).first()
    
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A cron job with this name already exists"
        )

    # Validate cron expression
    try:
        croniter(cron_job_data.cron_expression)
    except (ValueError, KeyError) as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid cron expression: {str(e)}"
        )

    # Validate timezone
    try:
        pytz.timezone(cron_job_data.timezone)
    except pytz.UnknownTimeZoneError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid timezone: {cron_job_data.timezone}"
        )

    resolved_evaluator_ids = _expand_evaluator_ids_for_cron(
        db,
        organization_id,
        cron_job_data.evaluator_ids,
        cron_job_data.evaluator_suite_ids,
    )

    for evaluator_id in resolved_evaluator_ids:
        evaluator = db.query(Evaluator).filter(
            and_(
                Evaluator.id == evaluator_id,
                Evaluator.organization_id == organization_id
            )
        ).first()
        if not evaluator:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Evaluator not found: {evaluator_id}"
            )

    # Calculate next run time
    next_run = calculate_next_run(cron_job_data.cron_expression, cron_job_data.timezone)

    cron_job = CronJob(
        organization_id=organization_id,
        name=cron_job_data.name,
        cron_expression=cron_job_data.cron_expression,
        timezone=cron_job_data.timezone,
        max_runs=cron_job_data.max_runs,
        current_runs=0,
        evaluator_ids=[str(eid) for eid in resolved_evaluator_ids],
        status=CronJobStatus.ACTIVE.value,
        next_run_at=next_run,
    )
    db.add(cron_job)
    db.commit()
    db.refresh(cron_job)

    return cron_job


@router.get("", response_model=List[CronJobResponse])
def list_cron_jobs(
    status_filter: Optional[CronJobStatus] = None,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """List all cron jobs for the organization."""
    query = db.query(CronJob).filter(CronJob.organization_id == organization_id)
    
    if status_filter:
        query = query.filter(CronJob.status == status_filter.value)
    
    cron_jobs = query.order_by(CronJob.created_at.desc()).all()
    return cron_jobs


@router.get("/{cron_job_id}", response_model=CronJobResponse)
def get_cron_job(
    cron_job_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """Get a specific cron job."""
    cron_job = db.query(CronJob).filter(
        and_(
            CronJob.id == cron_job_id,
            CronJob.organization_id == organization_id
        )
    ).first()

    if not cron_job:
        raise HTTPException(status_code=404, detail="Cron job not found")

    return cron_job


@router.put("/{cron_job_id}", response_model=CronJobResponse)
def update_cron_job(
    cron_job_id: UUID,
    cron_job_data: CronJobUpdate,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """Update a cron job."""
    cron_job = db.query(CronJob).filter(
        and_(
            CronJob.id == cron_job_id,
            CronJob.organization_id == organization_id
        )
    ).first()

    if not cron_job:
        raise HTTPException(status_code=404, detail="Cron job not found")

    # Update fields if provided
    if cron_job_data.name is not None:
        # Check for name conflicts
        existing = db.query(CronJob).filter(
            and_(
                CronJob.name == cron_job_data.name,
                CronJob.organization_id == organization_id,
                CronJob.id != cron_job_id
            )
        ).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A cron job with this name already exists"
            )
        cron_job.name = cron_job_data.name

    recalculate_next_run = False

    if cron_job_data.cron_expression is not None:
        # Validate cron expression
        try:
            croniter(cron_job_data.cron_expression)
        except (ValueError, KeyError) as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid cron expression: {str(e)}"
            )
        cron_job.cron_expression = cron_job_data.cron_expression
        recalculate_next_run = True

    if cron_job_data.timezone is not None:
        # Validate timezone
        try:
            pytz.timezone(cron_job_data.timezone)
        except pytz.UnknownTimeZoneError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid timezone: {cron_job_data.timezone}"
            )
        cron_job.timezone = cron_job_data.timezone
        recalculate_next_run = True

    if cron_job_data.max_runs is not None:
        cron_job.max_runs = cron_job_data.max_runs

    if cron_job_data.evaluator_ids is not None or cron_job_data.evaluator_suite_ids is not None:
        resolved_evaluator_ids = _expand_evaluator_ids_for_cron(
            db,
            organization_id,
            cron_job_data.evaluator_ids,
            cron_job_data.evaluator_suite_ids,
        )
        for evaluator_id in resolved_evaluator_ids:
            evaluator = db.query(Evaluator).filter(
                and_(
                    Evaluator.id == evaluator_id,
                    Evaluator.organization_id == organization_id
                )
            ).first()
            if not evaluator:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Evaluator not found: {evaluator_id}"
                )
        cron_job.evaluator_ids = [str(eid) for eid in resolved_evaluator_ids]

    if cron_job_data.status is not None:
        cron_job.status = cron_job_data.status.value
        # If reactivating, recalculate next run
        if cron_job_data.status == CronJobStatus.ACTIVE:
            recalculate_next_run = True

    # Recalculate next run if needed
    if recalculate_next_run and cron_job.status == CronJobStatus.ACTIVE.value:
        cron_job.next_run_at = calculate_next_run(cron_job.cron_expression, cron_job.timezone)

    db.commit()
    db.refresh(cron_job)

    return cron_job


@router.delete("/{cron_job_id}", status_code=204)
def delete_cron_job(
    cron_job_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """Delete a cron job."""
    cron_job = db.query(CronJob).filter(
        and_(
            CronJob.id == cron_job_id,
            CronJob.organization_id == organization_id
        )
    ).first()

    if not cron_job:
        raise HTTPException(status_code=404, detail="Cron job not found")

    db.delete(cron_job)
    db.commit()

    return None


@router.post("/{cron_job_id}/toggle", response_model=CronJobResponse)
def toggle_cron_job_status(
    cron_job_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
):
    """Toggle a cron job's status between active and paused."""
    cron_job = db.query(CronJob).filter(
        and_(
            CronJob.id == cron_job_id,
            CronJob.organization_id == organization_id
        )
    ).first()

    if not cron_job:
        raise HTTPException(status_code=404, detail="Cron job not found")

    # Don't allow toggling completed jobs
    if cron_job.status == CronJobStatus.COMPLETED.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot toggle a completed cron job"
        )

    # Toggle between active and paused
    if cron_job.status == CronJobStatus.ACTIVE.value:
        cron_job.status = CronJobStatus.PAUSED.value
        cron_job.next_run_at = None
    else:
        cron_job.status = CronJobStatus.ACTIVE.value
        # Recalculate next run time
        cron_job.next_run_at = calculate_next_run(cron_job.cron_expression, cron_job.timezone)

    db.commit()
    db.refresh(cron_job)

    return cron_job
