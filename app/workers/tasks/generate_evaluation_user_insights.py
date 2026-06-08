"""Celery task: generate map-reduce user insights for a call-import evaluation."""

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
from app.services.call_import_user_insights import (
    generate_user_insights,
    user_insights_state_to_db,
)
from app.workers.config import celery_app


@celery_app.task(name="generate_evaluation_user_insights", bind=True, max_retries=0)
def generate_evaluation_user_insights_task(
    self,
    evaluation_id: str,
    *,
    provider: str | None = None,
    model: str | None = None,
    max_llm_calls: int | None = None,
):
    from app.api.v1.routes.call_import_evaluations import (
        _compute_metric_aggregates,
        _metrics_for_ids,
        _serialize_selected_metric_ids,
    )
    from app.services.ai.llm_resolver import get_llm_provider_and_model

    db = SessionLocal()
    try:
        evaluation = (
            db.query(CallImportEvaluation)
            .filter(CallImportEvaluation.id == UUID(evaluation_id))
            .first()
        )
        if evaluation is None:
            logger.error("User insights: evaluation {} not found", evaluation_id)
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
        selected_ids = _serialize_selected_metric_ids(evaluation.selected_metric_ids)
        metrics = _metrics_for_ids(db, evaluation.organization_id, selected_ids)
        aggregate = _compute_metric_aggregates(
            db, evaluation, [er for er, _ in rows]
        )

        def on_progress(completed: int, total: int) -> None:
            evaluation.user_insights = {
                **(evaluation.user_insights or {}),
                "status": "running",
                "progress": {
                    "completed_llm_calls": completed,
                    "total_llm_calls": total,
                },
            }
            flag_modified(evaluation, "user_insights")
            db.commit()

        state = generate_user_insights(
            db,
            evaluation,
            evaluation.organization_id,
            provider_enum,
            model_str,
            completed_row_pairs=completed_pairs,
            metrics=metrics,
            aggregate=aggregate,
            on_progress=on_progress,
            max_llm_calls=max_llm_calls,
        )
        evaluation.user_insights = user_insights_state_to_db(state)
        flag_modified(evaluation, "user_insights")
        db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "User insights generation failed for evaluation {}: {}",
            evaluation_id,
            exc,
        )
        try:
            evaluation = (
                db.query(CallImportEvaluation)
                .filter(CallImportEvaluation.id == UUID(evaluation_id))
                .first()
            )
            if evaluation is not None:
                evaluation.user_insights = {
                    "status": "failed",
                    "error_message": str(exc),
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                }
                flag_modified(evaluation, "user_insights")
                db.commit()
        except Exception:  # noqa: BLE001
            db.rollback()
    finally:
        db.close()
