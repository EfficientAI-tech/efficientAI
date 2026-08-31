"""Shared Metrics Studio run rollup + Flexprice emission."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.database import MetricStudioRun, MetricStudioRunResult


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def rollup_metric_studio_run(
    db: Session,
    run: MetricStudioRun,
    *,
    emit_flexprice: bool = True,
    commit: bool = True,
) -> None:
    results = (
        db.query(MetricStudioRunResult)
        .filter(MetricStudioRunResult.run_id == run.id)
        .all()
    )
    completed = sum(1 for r in results if r.status == "completed")
    failed = sum(1 for r in results if r.status == "failed")
    pending = sum(1 for r in results if r.status in {"pending", "running"})
    run.completed_items = completed
    run.failed_items = failed
    if pending:
        run.status = "running"
    elif failed and completed:
        run.status = "partial"
        run.finished_at = run.finished_at or _now_utc()
    elif failed:
        run.status = "failed"
        run.finished_at = run.finished_at or _now_utc()
    else:
        run.status = "completed"
        run.finished_at = run.finished_at or _now_utc()

    if commit:
        db.commit()
    else:
        db.flush()

    if emit_flexprice and pending == 0 and run.finished_at is not None:
        from app.services.billing.flexprice_service import record_metric_studio_run_completed

        record_metric_studio_run_completed(
            run.organization_id,
            run.id,
            workspace_id=run.workspace_id,
            run_status=run.status,
            total_items=int(run.total_items or 0),
            completed_items=completed,
            failed_items=failed,
        )
