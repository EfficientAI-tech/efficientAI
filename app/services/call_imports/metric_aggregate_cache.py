"""Persist and serve evaluation metric aggregates without full-table rescans on every poll."""

from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from loguru import logger
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.models.database import CallImportEvaluation
from app.models.schemas import CallImportMetricAggregate

_AGGREGATE_REFRESH_EVERY_N_ROWS = 25
_TERMINAL_EVAL_STATUSES = frozenset(
    {"completed", "failed", "partial", "cancelled", "aborted"}
)


def aggregates_from_cache(
    evaluation: CallImportEvaluation,
) -> Optional[List[CallImportMetricAggregate]]:
    completed = int(evaluation.completed_rows or 0)
    cached_at = evaluation.cached_metric_aggregates_at_count
    raw = evaluation.cached_metric_aggregates
    if cached_at is None or raw is None or not isinstance(raw, list):
        return None
    if int(cached_at) != completed:
        return None
    try:
        return [CallImportMetricAggregate.model_validate(item) for item in raw]
    except Exception:
        return None


def save_aggregate_cache(
    db: Session,
    evaluation: CallImportEvaluation,
    aggregates: List[CallImportMetricAggregate],
) -> None:
    from app.api.v1.routes.call_import_evaluations import _aggregate_to_dict

    evaluation.cached_metric_aggregates = [
        _aggregate_to_dict(item) for item in aggregates
    ]
    evaluation.cached_metric_aggregates_at_count = int(
        evaluation.completed_rows or 0
    )
    flag_modified(evaluation, "cached_metric_aggregates")
    db.flush()


def rebuild_evaluation_metric_aggregate_cache(
    db: Session,
    evaluation_id: UUID,
) -> List[CallImportMetricAggregate]:
    from app.api.v1.routes.call_import_evaluations import _compute_metric_aggregates
    from app.db_sharding.scatter_gather import load_evaluation_score_rows_for_aggregate

    evaluation = (
        db.query(CallImportEvaluation)
        .filter(CallImportEvaluation.id == evaluation_id)
        .first()
    )
    if evaluation is None:
        return []
    eval_rows = load_evaluation_score_rows_for_aggregate(db, evaluation_id)
    aggregates = _compute_metric_aggregates(db, evaluation, eval_rows)
    save_aggregate_cache(db, evaluation, aggregates)
    return aggregates


def metrics_for_aggregate_endpoint(
    db: Session,
    evaluation: CallImportEvaluation,
) -> List[CallImportMetricAggregate]:
    cached = aggregates_from_cache(evaluation)
    if cached is not None:
        return cached
    from app.api.v1.routes.call_import_evaluations import _compute_metric_aggregates
    from app.db_sharding.scatter_gather import load_evaluation_score_rows_for_aggregate

    eval_rows = load_evaluation_score_rows_for_aggregate(db, evaluation.id)
    aggregates = _compute_metric_aggregates(db, evaluation, eval_rows)
    try:
        save_aggregate_cache(db, evaluation, aggregates)
        db.flush()
    except Exception as exc:
        logger.warning(
            "aggregate cache save failed for evaluation {}: {}",
            evaluation.id,
            exc,
        )
        db.rollback()
    return aggregates


def maybe_refresh_aggregate_cache_after_row(
    db: Session,
    evaluation: CallImportEvaluation,
    *,
    new_row_status: str | None,
) -> None:
    status = (new_row_status or "").lower()
    if status != "completed":
        return
    completed = int(evaluation.completed_rows or 0)
    cached_at = int(evaluation.cached_metric_aggregates_at_count or -1)
    parent_status = (evaluation.status or "").lower()
    if parent_status in _TERMINAL_EVAL_STATUSES:
        force = completed != cached_at
    elif completed == 0:
        return
    else:
        force = completed % _AGGREGATE_REFRESH_EVERY_N_ROWS == 0
        if not force and cached_at >= 0:
            force = completed - cached_at >= _AGGREGATE_REFRESH_EVERY_N_ROWS
    if not force:
        return
    try:
        rebuild_evaluation_metric_aggregate_cache(db, evaluation.id)
        db.commit()
    except Exception as exc:
        logger.warning(
            "aggregate cache refresh failed for evaluation {}: {}",
            evaluation.id,
            exc,
        )
        db.rollback()
