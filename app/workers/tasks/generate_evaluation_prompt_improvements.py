"""Celery task: prompt improvement suggestions from evaluation clusters."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from loguru import logger
from sqlalchemy.orm.attributes import flag_modified

from app.database import SessionLocal
from app.models.database import (
    CallImportEvaluation,
    CallImportEvaluationRow,
    PromptPartial,
)
from app.services.call_import_metric_clusters import metric_clusters_state_from_raw
from app.services.call_import_prompt_improvements import (
    generate_prompt_improvements,
    is_imported_agent,
    prompt_improvements_state_to_db,
)
from app.workers.config import celery_app


@celery_app.task(name="generate_evaluation_prompt_improvements", bind=True, max_retries=0)
def generate_evaluation_prompt_improvements_task(
    self,
    evaluation_id: str,
    imported_agent_id: str,
    *,
    provider: str | None = None,
    model: str | None = None,
):
    from app.api.v1.routes.call_import_evaluations import (
        _aggregate_to_dict,
        _compute_metric_aggregates,
        _period_deltas_from_evaluation,
        _resolve_baseline_evaluation,
    )

    db = SessionLocal()
    evaluation: CallImportEvaluation | None = None
    try:
        evaluation = (
            db.query(CallImportEvaluation)
            .filter(CallImportEvaluation.id == UUID(evaluation_id))
            .first()
        )
        if evaluation is None:
            logger.error("Prompt improvements: evaluation {} not found", evaluation_id)
            return

        raw = evaluation.prompt_improvements
        if isinstance(raw, dict) and raw.get("status") == "cancelled":
            logger.info(
                "Prompt improvements: evaluation {} cancelled, skipping",
                evaluation_id,
            )
            return

        imported_agent = (
            db.query(PromptPartial)
            .filter(
                PromptPartial.id == UUID(imported_agent_id),
                PromptPartial.organization_id == evaluation.organization_id,
                PromptPartial.workspace_id == evaluation.workspace_id,
            )
            .first()
        )
        if imported_agent is None or not is_imported_agent(imported_agent):
            raise ValueError("Imported agent not found")

        clusters_state = metric_clusters_state_from_raw(
            evaluation.metric_clusters,
            completed_rows=evaluation.completed_rows,
        )
        if clusters_state is None or clusters_state.status != "completed":
            raise ValueError("Metric clusters must be completed")

        period_deltas: dict[str, dict[str, str]] = {}
        eval_rows = (
            db.query(CallImportEvaluationRow)
            .filter(CallImportEvaluationRow.evaluation_id == evaluation.id)
            .all()
        )
        if eval_rows:
            aggregates = _compute_metric_aggregates(db, evaluation, eval_rows)
            metric_aggregates = [
                _aggregate_to_dict(aggregate) for aggregate in aggregates
            ]
            baseline = _resolve_baseline_evaluation(
                db,
                evaluation.organization_id,
                evaluation.workspace_id,
                evaluation,
                None,
                None,
            )
            if baseline is not None:
                period_deltas = _period_deltas_from_evaluation(
                    db,
                    baseline,
                    metric_aggregates,
                    evaluation,
                    eval_rows,
                )

        state = generate_prompt_improvements(
            evaluation=evaluation,
            imported_agent=imported_agent,
            clusters_state=clusters_state,
            organization_id=evaluation.organization_id,
            db=db,
            provider=provider,
            model=model,
            period_deltas=period_deltas,
        )
        evaluation.prompt_improvements = prompt_improvements_state_to_db(state)
        flag_modified(evaluation, "prompt_improvements")
        db.commit()
        logger.info(
            "Prompt improvements completed for evaluation {} ({} suggestions)",
            evaluation_id,
            len(state.suggestions),
        )
    except Exception as exc:
        logger.exception(
            "Prompt improvements failed for evaluation {}: {}",
            evaluation_id,
            exc,
        )
        if evaluation is not None:
            prior = (
                evaluation.prompt_improvements
                if isinstance(evaluation.prompt_improvements, dict)
                else {}
            )
            evaluation.prompt_improvements = {
                **prior,
                "status": "failed",
                "imported_agent_id": imported_agent_id,
                "error_message": str(exc),
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }
            flag_modified(evaluation, "prompt_improvements")
            db.commit()
    finally:
        db.close()
