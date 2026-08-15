"""Dispatch due cron jobs to Celery workers."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List
from uuid import UUID

from loguru import logger
from sqlalchemy.orm import Session

from app.models.database import CronJob, Evaluator
from app.models.enums import CronJobStatus
from app.services.cron.scheduling import calculate_next_run


def list_due_cron_jobs(db: Session, *, now: datetime | None = None) -> List[CronJob]:
    moment = now or datetime.now(timezone.utc)
    return (
        db.query(CronJob)
        .filter(
            CronJob.status == CronJobStatus.ACTIVE.value,
            CronJob.next_run_at.isnot(None),
            CronJob.next_run_at <= moment,
        )
        .order_by(CronJob.next_run_at.asc())
        .all()
    )


def advance_cron_job(db: Session, job: CronJob, *, now: datetime | None = None) -> None:
    moment = now or datetime.now(timezone.utc)
    job.last_run_at = moment
    job.current_runs = int(job.current_runs or 0) + 1
    if job.current_runs >= int(job.max_runs or 0):
        job.status = CronJobStatus.COMPLETED.value
        job.next_run_at = None
    else:
        job.next_run_at = calculate_next_run(job.cron_expression, job.timezone)
    db.add(job)


def enqueue_cron_job(job: CronJob) -> Dict[str, Any]:
    job_type = (job.job_type or "evaluator_run").strip()

    if job_type == "usage_flush":
        from app.workers.tasks.flush_usage_counters import flush_usage_counters_task

        result = flush_usage_counters_task.delay()
        return {"task": "flush_usage_counters", "celery_task_id": result.id}

    if job_type == "alert_evaluate":
        from app.workers.tasks.evaluate_alerts import evaluate_alerts_task

        result = evaluate_alerts_task.delay()
        return {"task": "evaluate_alerts", "celery_task_id": result.id}

    if job_type == "oss_usage_prune":
        from app.workers.tasks.prune_oss_usage_history import (
            prune_oss_usage_history_task,
        )

        result = prune_oss_usage_history_task.delay()
        return {"task": "prune_oss_usage_history", "celery_task_id": result.id}

    if job_type == "fx_rate_refresh":
        from app.workers.tasks.refresh_fx_rates import refresh_fx_rates_task

        result = refresh_fx_rates_task.delay()
        return {"task": "refresh_fx_rates", "celery_task_id": result.id}

    if job_type == "evaluator_run":
        from app.workers.tasks.run_cron_evaluator_job import run_cron_evaluator_job_task

        result = run_cron_evaluator_job_task.delay(str(job.id))
        return {"task": "run_cron_evaluator_job", "celery_task_id": result.id}

    logger.warning("Unknown cron job_type {} for job {}", job_type, job.id)
    return {"task": "unknown", "job_type": job_type}


def run_evaluator_cron_job(db: Session, job: CronJob) -> Dict[str, Any]:
    from app.services.evaluators.evaluator_run_service import queue_evaluator_runs

    if job.organization_id is None:
        return {"error": "evaluator_run requires organization_id"}

    raw_ids = job.evaluator_ids or []
    evaluator_ids: List[UUID] = []
    for value in raw_ids:
        try:
            evaluator_ids.append(UUID(str(value)))
        except (TypeError, ValueError):
            continue

    if not evaluator_ids:
        return {"error": "no evaluator_ids configured"}

    by_workspace: dict[UUID, List[UUID]] = defaultdict(list)
    for evaluator_id in evaluator_ids:
        evaluator = (
            db.query(Evaluator)
            .filter(
                Evaluator.id == evaluator_id,
                Evaluator.organization_id == job.organization_id,
            )
            .first()
        )
        if evaluator is None:
            logger.warning(
                "cron evaluator_run skipped missing evaluator {} for job {}",
                evaluator_id,
                job.id,
            )
            continue
        by_workspace[evaluator.workspace_id].append(evaluator_id)

    task_ids: List[str] = []
    for workspace_id, ids in by_workspace.items():
        try:
            ws_task_ids, _results = queue_evaluator_runs(
                db,
                job.organization_id,
                workspace_id,
                ids,
            )
            task_ids.extend(ws_task_ids)
        except Exception as exc:
            logger.warning(
                "cron evaluator_run failed for job {} workspace {}: {}",
                job.id,
                workspace_id,
                exc,
            )

    return {"evaluator_tasks": len(task_ids), "celery_task_ids": task_ids[:20]}
