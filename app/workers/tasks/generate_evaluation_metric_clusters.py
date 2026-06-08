"""Celery task: per-metric failure clustering for internal diagnostics."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from loguru import logger
from sqlalchemy.orm.attributes import flag_modified

from app.database import SessionLocal
from app.models.database import (
    CallImportEvaluation,
    CallImportEvaluationRow,
    CallImportRow,
)
from app.services.call_import_metric_clusters import (
    filter_completed_row_pairs,
    generate_metric_clusters,
    metric_clusters_raw_is_cancelled,
    metric_clusters_state_to_db,
)
from app.workers.config import celery_app


@celery_app.task(name="generate_evaluation_metric_clusters", bind=True, max_retries=0)
def generate_evaluation_metric_clusters_task(
    self,
    evaluation_id: str,
    *,
    provider: str | None = None,
    model: str | None = None,
    max_llm_calls: int | None = None,
    evaluation_row_ids: list[str] | None = None,
):
    from app.api.v1.routes.call_import_evaluations import (
        _child_names_by_parent,
        _compute_metric_aggregates,
        _metrics_for_clustering,
    )
    from app.services.metric_failure_policy import effective_policies
    from app.services.ai.llm_resolver import get_llm_provider_and_model

    db = SessionLocal()
    evaluation: CallImportEvaluation | None = None
    try:
        evaluation = (
            db.query(CallImportEvaluation)
            .filter(CallImportEvaluation.id == UUID(evaluation_id))
            .first()
        )
        if evaluation is None:
            logger.error("Metric clusters: evaluation {} not found", evaluation_id)
            return

        if metric_clusters_raw_is_cancelled(evaluation.metric_clusters):
            logger.info(
                "Metric clusters: evaluation {} already cancelled, skipping",
                evaluation_id,
            )
            return

        provider_enum, model_str = get_llm_provider_and_model(
            evaluation.organization_id,
            db,
            provider,
            model,
        )

        rows = (
            db.query(CallImportEvaluationRow, CallImportRow)
            .join(
                CallImportRow,
                CallImportRow.id == CallImportEvaluationRow.call_import_row_id,
            )
            .filter(CallImportEvaluationRow.evaluation_id == evaluation.id)
            .all()
        )
        completed_pairs = [
            (eval_row, source_row)
            for eval_row, source_row in rows
            if eval_row.status == "completed"
        ]
        if evaluation_row_ids:
            completed_pairs = filter_completed_row_pairs(
                completed_pairs,
                [UUID(rid) for rid in evaluation_row_ids],
            )
        eval_rows = [eval_row for eval_row, _source_row in rows]
        metrics = _metrics_for_clustering(db, evaluation, eval_rows)
        aggregates = _compute_metric_aggregates(db, evaluation, eval_rows)
        parent_ids = [
            m.id
            for m in metrics
            if getattr(m, "selection_mode", None)
            and not getattr(m, "parent_metric_id", None)
        ]
        child_names_by_parent = _child_names_by_parent(
            db, evaluation.organization_id, parent_ids
        )
        policies, _policy_source = effective_policies(
            evaluation,
            metrics,
            aggregates,
            child_names_by_parent=child_names_by_parent,
        )

        def _reload_cancelled() -> bool:
            db.expire(evaluation, ["metric_clusters"])
            db.refresh(evaluation)
            return metric_clusters_raw_is_cancelled(evaluation.metric_clusters)

        def on_progress(completed: int, total: int) -> None:
            if _reload_cancelled():
                return
            evaluation.metric_clusters = {
                **(evaluation.metric_clusters or {}),
                "status": "running",
                "progress": {
                    "completed_llm_calls": completed,
                    "total_llm_calls": total,
                },
            }
            flag_modified(evaluation, "metric_clusters")
            db.commit()

        state = generate_metric_clusters(
            db,
            evaluation,
            evaluation.organization_id,
            provider_enum,
            model_str,
            completed_row_pairs=completed_pairs,
            metrics=metrics,
            policies=policies,
            on_progress=on_progress,
            max_llm_calls=max_llm_calls,
            is_cancelled=_reload_cancelled,
        )

        if _reload_cancelled():
            return

        persisted = metric_clusters_state_to_db(state)
        if isinstance(evaluation.metric_clusters, dict):
            evaluation.metric_clusters = {
                **persisted,
                "celery_task_id": None,
            }
        else:
            evaluation.metric_clusters = persisted
        flag_modified(evaluation, "metric_clusters")
        db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "Metric clusters generation failed for evaluation {}: {}",
            evaluation_id,
            exc,
        )
        try:
            evaluation = (
                db.query(CallImportEvaluation)
                .filter(CallImportEvaluation.id == UUID(evaluation_id))
                .first()
            )
            if evaluation is not None and not metric_clusters_raw_is_cancelled(
                evaluation.metric_clusters
            ):
                evaluation.metric_clusters = {
                    "status": "failed",
                    "error_message": str(exc),
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "celery_task_id": None,
                }
                flag_modified(evaluation, "metric_clusters")
                db.commit()
        except Exception:  # noqa: BLE001
            db.rollback()
    finally:
        db.close()
