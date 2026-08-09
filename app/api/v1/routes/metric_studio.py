"""Metrics Studio API routes."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_api_key, get_organization_id, get_workspace_id
from app.models.database import (
    Metric,
    MetricStudioRun,
    MetricStudioRunResult,
)
from app.models.schemas import (
    MetricStudioRunCreate,
    MetricStudioRunListResponse,
    MetricStudioRunResponse,
    MetricStudioRunResultListResponse,
    MetricStudioRunResultResponse,
    MetricStudioRunRetryRequest,
)
from app.services.metric_studio.metric_selection import expand_studio_metric_selection
from app.services.metric_studio.source_resolver import resolve_source

router = APIRouter(prefix="/metric-studio", tags=["metric-studio"])


def _serialize_run(run: MetricStudioRun) -> MetricStudioRunResponse:
    return MetricStudioRunResponse(
        id=run.id,
        organization_id=run.organization_id,
        workspace_id=run.workspace_id,
        name=run.name,
        selected_metric_ids=[str(mid) for mid in (run.selected_metric_ids or [])],
        selected_metric_groups=run.selected_metric_groups,
        transcript_source=run.transcript_source or "diarised",
        llm_provider=run.llm_provider,
        llm_model=run.llm_model,
        status=run.status,
        total_items=run.total_items or 0,
        completed_items=run.completed_items or 0,
        failed_items=run.failed_items or 0,
        error_message=run.error_message,
        started_at=run.started_at,
        finished_at=run.finished_at,
        created_at=run.created_at,
        updated_at=run.updated_at,
    )


def _resolve_evaluation_transcript_metadata(
    db: Session,
    *,
    run: MetricStudioRun,
    row: MetricStudioRunResult,
) -> Dict[str, Any]:
    metadata = dict(row.source_metadata or {})
    if metadata.get("evaluation_transcript"):
        metadata.setdefault(
            "transcript_source_used",
            run.transcript_source or "diarised",
        )
        return metadata
    if row.status != "completed":
        return metadata
    try:
        sample = resolve_source(
            db,
            organization_id=run.organization_id,
            workspace_id=run.workspace_id,
            source_kind=row.source_kind,
            source_ref=row.source_ref,
            display_label=row.display_label,
        )
    except HTTPException:
        return metadata
    transcript_source = (run.transcript_source or "diarised").lower()
    if transcript_source == "production":
        transcript = sample.transcript
    else:
        transcript = sample.diarised_transcript or sample.transcript
    if transcript:
        metadata["evaluation_transcript"] = transcript
        metadata["transcript_source_used"] = transcript_source
    return metadata


def _serialize_result(
    row: MetricStudioRunResult,
    *,
    db: Optional[Session] = None,
    run: Optional[MetricStudioRun] = None,
) -> MetricStudioRunResultResponse:
    source_metadata = row.source_metadata
    if db is not None and run is not None:
        source_metadata = _resolve_evaluation_transcript_metadata(db, run=run, row=row)
    return MetricStudioRunResultResponse(
        id=row.id,
        run_id=row.run_id,
        source_kind=row.source_kind,
        source_ref=row.source_ref,
        display_label=row.display_label,
        source_metadata=source_metadata,
        status=row.status,
        metric_scores=row.metric_scores or {},
        error_message=row.error_message,
        started_at=row.started_at,
        finished_at=row.finished_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _rollup_run_status(db: Session, run: MetricStudioRun) -> None:
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
    elif failed:
        run.status = "failed"
    else:
        run.status = "completed"
        run.finished_at = datetime.now(timezone.utc)
    db.flush()


@router.post(
    "/runs",
    response_model=MetricStudioRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="createMetricStudioRun",
)
async def create_metric_studio_run(
    payload: MetricStudioRunCreate,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
) -> MetricStudioRunResponse:
    del api_key

    org_metrics = (
        db.query(Metric)
        .filter(
            Metric.organization_id == organization_id,
            Metric.id.in_(payload.metric_ids),
        )
        .all()
    )
    by_id = {metric.id: metric for metric in org_metrics}
    unknown_ids = [mid for mid in payload.metric_ids if mid not in by_id]
    if unknown_ids:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown metric ids: {', '.join(str(mid) for mid in unknown_ids)}",
        )

    effective_metrics, parent_to_children = expand_studio_metric_selection(
        db, organization_id, payload.metric_ids
    )
    if not effective_metrics:
        raise HTTPException(
            status_code=400,
            detail="No scorable metrics after expanding the selection.",
        )

    leaf_metric_ids = [m.id for m in effective_metrics]
    selected_metric_groups: Dict[str, List[str]] = {
        str(pid): [str(c.id) for c in children]
        for pid, children in parent_to_children.items()
    }

    if payload.llm_provider or payload.llm_model:
        if not (payload.llm_provider and payload.llm_model):
            raise HTTPException(
                status_code=400,
                detail="Both llm_provider and llm_model are required when overriding the run LLM.",
            )

    run = MetricStudioRun(
        id=uuid4(),
        organization_id=organization_id,
        workspace_id=workspace_id,
        name=payload.name,
        selected_metric_ids=[str(mid) for mid in leaf_metric_ids],
        selected_metric_groups=selected_metric_groups or None,
        transcript_source=payload.transcript_source,
        llm_provider=payload.llm_provider,
        llm_model=payload.llm_model,
        llm_credential_id=payload.llm_credential_id,
        llm_config=payload.llm_config,
        metric_llm_overrides=payload.metric_llm_overrides,
        status="pending",
        total_items=len(payload.sources),
        started_at=datetime.now(timezone.utc),
    )
    db.add(run)
    db.flush()

    result_rows: List[MetricStudioRunResult] = []
    for source in payload.sources:
        sample = resolve_source(
            db,
            organization_id=organization_id,
            workspace_id=workspace_id,
            source_kind=source.source_kind,
            source_ref=source.source_ref,
            display_label=source.display_label,
        )
        result_row = MetricStudioRunResult(
            id=uuid4(),
            run_id=run.id,
            workspace_id=workspace_id,
            source_kind=sample.source_kind,
            source_ref=sample.source_ref,
            display_label=sample.label,
            source_metadata=sample.metadata,
            status="pending",
        )
        db.add(result_row)
        result_rows.append(result_row)

    db.commit()
    db.refresh(run)

    from app.workers.tasks.evaluate_studio_run_item import (
        evaluate_studio_run_item_task,
    )

    run.status = "running"
    db.commit()

    for result_row in result_rows:
        async_result = evaluate_studio_run_item_task.delay(str(result_row.id))
        result_row.celery_task_id = async_result.id
        result_row.status = "running"
        result_row.started_at = datetime.now(timezone.utc)
    db.commit()

    return _serialize_run(run)


@router.get("/runs", response_model=MetricStudioRunListResponse)
def list_metric_studio_runs(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
) -> MetricStudioRunListResponse:
    query = (
        db.query(MetricStudioRun)
        .filter(
            MetricStudioRun.organization_id == organization_id,
            MetricStudioRun.workspace_id == workspace_id,
        )
        .order_by(MetricStudioRun.created_at.desc())
    )
    total = query.count()
    runs = query.offset(skip).limit(limit).all()
    return MetricStudioRunListResponse(
        items=[_serialize_run(run) for run in runs],
        total=total,
    )


@router.get("/runs/{run_id}", response_model=MetricStudioRunResponse)
def get_metric_studio_run(
    run_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
) -> MetricStudioRunResponse:
    run = (
        db.query(MetricStudioRun)
        .filter(
            MetricStudioRun.id == run_id,
            MetricStudioRun.organization_id == organization_id,
            MetricStudioRun.workspace_id == workspace_id,
        )
        .first()
    )
    if not run:
        raise HTTPException(status_code=404, detail="Studio run not found.")
    return _serialize_run(run)


@router.get("/runs/{run_id}/results", response_model=MetricStudioRunResultListResponse)
def list_metric_studio_run_results(
    run_id: UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
) -> MetricStudioRunResultListResponse:
    run = (
        db.query(MetricStudioRun)
        .filter(
            MetricStudioRun.id == run_id,
            MetricStudioRun.organization_id == organization_id,
            MetricStudioRun.workspace_id == workspace_id,
        )
        .first()
    )
    if not run:
        raise HTTPException(status_code=404, detail="Studio run not found.")

    query = (
        db.query(MetricStudioRunResult)
        .filter(MetricStudioRunResult.run_id == run_id)
        .order_by(MetricStudioRunResult.created_at.asc())
    )
    total = query.count()
    rows = query.offset(skip).limit(limit).all()
    return MetricStudioRunResultListResponse(
        items=[_serialize_result(row, db=db, run=run) for row in rows],
        total=total,
    )


@router.post("/runs/{run_id}/retry", response_model=MetricStudioRunResponse)
def retry_metric_studio_run(
    run_id: UUID,
    body: MetricStudioRunRetryRequest,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
) -> MetricStudioRunResponse:
    run = (
        db.query(MetricStudioRun)
        .filter(
            MetricStudioRun.id == run_id,
            MetricStudioRun.organization_id == organization_id,
            MetricStudioRun.workspace_id == workspace_id,
        )
        .first()
    )
    if not run:
        raise HTTPException(status_code=404, detail="Studio run not found.")

    query = db.query(MetricStudioRunResult).filter(
        MetricStudioRunResult.run_id == run_id
    )
    if body.result_ids:
        query = query.filter(MetricStudioRunResult.id.in_(body.result_ids))
    else:
        query = query.filter(MetricStudioRunResult.status == "failed")

    rows = query.all()
    if not rows:
        raise HTTPException(status_code=400, detail="No results eligible for retry.")

    from app.workers.tasks.evaluate_studio_run_item import (
        evaluate_studio_run_item_task,
    )

    run.status = "running"
    run.finished_at = None
    for row in rows:
        row.status = "running"
        row.error_message = None
        row.metric_scores = {}
        row.started_at = datetime.now(timezone.utc)
        row.finished_at = None
        async_result = evaluate_studio_run_item_task.delay(str(row.id))
        row.celery_task_id = async_result.id
    db.commit()
    _rollup_run_status(db, run)
    db.commit()
    db.refresh(run)
    return _serialize_run(run)


@router.delete("/runs/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_metric_studio_run(
    run_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
) -> None:
    run = (
        db.query(MetricStudioRun)
        .filter(
            MetricStudioRun.id == run_id,
            MetricStudioRun.organization_id == organization_id,
            MetricStudioRun.workspace_id == workspace_id,
        )
        .first()
    )
    if not run:
        raise HTTPException(status_code=404, detail="Studio run not found.")
    db.delete(run)
    db.commit()
