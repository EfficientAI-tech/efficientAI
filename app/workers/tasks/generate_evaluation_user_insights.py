"""Celery task: generate LLM user insights for a call import evaluation."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
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
    normalize_max_llm_calls,
    total_llm_calls_for_rows,
    user_insights_state_to_db,
)
from app.workers.config import celery_app


def _now():
    return datetime.now(timezone.utc)


@celery_app.task(
    name="generate_evaluation_user_insights",
    bind=True,
    max_retries=1,
    time_limit=60 * 60,
    soft_time_limit=55 * 60,
)
def generate_evaluation_user_insights_task(
    self,
    evaluation_id: str,
    *,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    max_llm_calls: Optional[int] = None,
):
    """Map-reduce user insights generation for one evaluation run."""
    db = SessionLocal()
    try:
        llm_budget = normalize_max_llm_calls(max_llm_calls)
        eval_uuid = UUID(evaluation_id)
        evaluation = (
            db.query(CallImportEvaluation)
            .filter(CallImportEvaluation.id == eval_uuid)
            .first()
        )
        if not evaluation:
            logger.warning("CallImportEvaluation {} not found for user insights", evaluation_id)
            return {"status": "skipped", "reason": "evaluation_not_found"}

        row_pairs = (
            db.query(CallImportEvaluationRow, CallImportRow)
            .join(CallImportRow, CallImportRow.id == CallImportEvaluationRow.call_import_row_id)
            .filter(
                CallImportEvaluationRow.evaluation_id == eval_uuid,
                CallImportEvaluationRow.status == "completed",
            )
            .order_by(CallImportRow.row_index.asc())
            .all()
        )

        n_rows = len(row_pairs)
        total_calls = total_llm_calls_for_rows(n_rows, max_llm_calls=llm_budget)
        evaluation.user_insights = {
            "status": "running",
            "insights": [],
            "generated_at": _now().isoformat(),
            "generated_at_completed_rows": evaluation.completed_rows,
            "progress": {"completed_llm_calls": 0, "total_llm_calls": total_calls},
            "provider": provider,
            "model": model,
            "max_llm_calls": llm_budget,
            "llm_calls_used": 0,
            "error_message": None,
        }
        flag_modified(evaluation, "user_insights")
        db.commit()

        if n_rows == 0:
            evaluation.user_insights = {
                "status": "failed",
                "insights": [],
                "generated_at": _now().isoformat(),
                "generated_at_completed_rows": evaluation.completed_rows,
                "error_message": "No completed rows to analyze.",
                "llm_calls_used": 0,
            }
            flag_modified(evaluation, "user_insights")
            db.commit()
            return {"status": "failed", "reason": "no_completed_rows"}

        from app.api.v1.routes.call_import_evaluations import (
            _compute_metric_aggregates,
            _metrics_for_ids,
        )
        from app.services.ai.llm_resolver import get_llm_provider_and_model

        eval_rows = [pair[0] for pair in row_pairs]
        aggregate = _compute_metric_aggregates(db, evaluation, eval_rows)

        metric_ids: list[UUID] = []
        for mid in evaluation.selected_metric_ids or []:
            try:
                metric_ids.append(UUID(str(mid)))
            except (TypeError, ValueError):
                continue
        metrics = _metrics_for_ids(db, evaluation.organization_id, metric_ids)

        provider_enum, model_str = get_llm_provider_and_model(
            evaluation.organization_id, db, provider, model
        )

        eval_id_str = str(evaluation.id)

        def on_progress(completed: int, total: int) -> None:
            db.refresh(evaluation)
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

        result = generate_user_insights(
            db,
            evaluation,
            evaluation.organization_id,
            provider_enum,
            model_str,
            completed_row_pairs=row_pairs,
            metrics=metrics,
            aggregate=aggregate,
            on_progress=on_progress,
            max_llm_calls=llm_budget,
        )

        evaluation.user_insights = user_insights_state_to_db(result)
        flag_modified(evaluation, "user_insights")
        db.commit()

        logger.info(
            "User insights {} for evaluation {} ({} LLM calls, {} insights)",
            result.status,
            eval_id_str,
            result.llm_calls_used,
            len(result.insights),
        )
        return {
            "status": result.status,
            "insight_count": len(result.insights),
            "llm_calls_used": result.llm_calls_used,
        }
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "User insights task failed for evaluation {}: {}",
            evaluation_id,
            exc,
        )
        try:
            evaluation = (
                db.query(CallImportEvaluation)
                .filter(CallImportEvaluation.id == UUID(evaluation_id))
                .first()
            )
            if evaluation:
                evaluation.user_insights = {
                    "status": "failed",
                    "insights": (
                        (evaluation.user_insights or {}).get("insights", [])
                        if isinstance(evaluation.user_insights, dict)
                        else []
                    ),
                    "generated_at": _now().isoformat(),
                    "generated_at_completed_rows": evaluation.completed_rows,
                    "error_message": str(exc),
                    "llm_calls_used": (
                        (evaluation.user_insights or {}).get("llm_calls_used", 0)
                        if isinstance(evaluation.user_insights, dict)
                        else 0
                    ),
                }
                flag_modified(evaluation, "user_insights")
                db.commit()
        except Exception:  # noqa: BLE001
            pass
        raise
    finally:
        db.close()
