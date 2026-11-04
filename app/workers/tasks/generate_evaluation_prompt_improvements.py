"""Celery task: prompt improvement suggestions from evaluation clusters."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from loguru import logger
from sqlalchemy.orm.attributes import flag_modified

from app.database import SessionLocal
from app.models.database import CallImportEvaluation, PromptPartial
from app.services.call_import_metric_clusters import metric_clusters_state_from_raw
from app.services.call_import_prompt_improvements import (
    is_imported_agent,
    prompt_improvements_state_to_db,
)
from app.services.call_import_prompt_improvements_wave import (
    process_prompt_improvements_wave_step,
)
from app.services.evaluation_analysis_checkpoints import (
    new_job_run_id,
    prompt_improvements_raw_is_cancelled,
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
    credential_id: str | None = None,
    resume: bool = False,
):
    from app.api.v1.routes.call_import_evaluations import (
        _aggregate_to_dict,
        _compute_metric_aggregates,
        _period_deltas_from_evaluation,
        _resolve_baseline_evaluation,
    )
    from app.models.database import CallImportEvaluationRow

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

        if prompt_improvements_raw_is_cancelled(evaluation.prompt_improvements):
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

        raw = (
            evaluation.prompt_improvements
            if isinstance(evaluation.prompt_improvements, dict)
            else {}
        )
        if raw.get("job_run_id"):
            run_id = UUID(str(raw["job_run_id"]))
        elif resume:
            run_id = new_job_run_id()
            evaluation.prompt_improvements = {
                **raw,
                "status": "running",
                "imported_agent_id": str(imported_agent_id),
                "imported_agent_name": imported_agent.name,
                "job_run_id": str(run_id),
                "completed_group_metric_ids": raw.get("completed_group_metric_ids") or [],
            }
            flag_modified(evaluation, "prompt_improvements")
            db.commit()
        else:
            run_id = new_job_run_id()
            prior_suggestions = raw.get("suggestions") if isinstance(raw.get("suggestions"), list) else []
            evaluation.prompt_improvements = {
                **raw,
                "status": "running",
                "imported_agent_id": str(imported_agent_id),
                "imported_agent_name": imported_agent.name,
                "job_run_id": str(run_id),
                "completed_group_metric_ids": [],
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "generated_at_completed_rows": evaluation.completed_rows,
                "provider": provider,
                "model": model,
                "error_message": None,
                "suggestions": prior_suggestions if raw.get("status") == "completed" else raw.get("suggestions", []),
            }
            flag_modified(evaluation, "prompt_improvements")
            db.commit()

        def _reload_cancelled() -> bool:
            db.expire(evaluation, ["prompt_improvements"])
            db.refresh(evaluation)
            return prompt_improvements_raw_is_cancelled(evaluation.prompt_improvements)

        from app.services.usage.call_import_context import usage_context_for_evaluation
        from app.services.usage.context import llm_usage_context

        with llm_usage_context(usage_context_for_evaluation(evaluation)):
            action, terminal_state = process_prompt_improvements_wave_step(
                db,
                evaluation,
                imported_agent,
                clusters_state,
                evaluation.organization_id,
                job_run_id=run_id,
                provider=provider,
                model=model,
                credential_id=UUID(credential_id) if credential_id else None,
                period_deltas=period_deltas,
                is_cancelled=_reload_cancelled,
            )

        if _reload_cancelled():
            return

        if terminal_state is not None:
            payload = prompt_improvements_state_to_db(terminal_state)
            payload["compose_base_prompt"] = imported_agent.content or ""
            payload["job_run_id"] = str(run_id)
            payload["celery_task_id"] = None
            evaluation.prompt_improvements = payload
            flag_modified(evaluation, "prompt_improvements")
            db.commit()
            if terminal_state.status == "completed":
                from app.services.billing.flexprice_service import (
                    record_call_import_prompt_improvements_generated,
                )

                record_call_import_prompt_improvements_generated(
                    evaluation.organization_id,
                    uuid4(),
                    workspace_id=evaluation.workspace_id,
                    evaluation_id=evaluation.id,
                    imported_agent_id=UUID(imported_agent_id),
                )
            logger.info(
                "Prompt improvements completed for evaluation {} ({} suggestions)",
                evaluation_id,
                len(terminal_state.suggestions),
            )
            return

        flag_modified(evaluation, "prompt_improvements")
        db.commit()

        if action == "continue":
            generate_evaluation_prompt_improvements_task.apply_async(
                kwargs={
                    "evaluation_id": evaluation_id,
                    "imported_agent_id": imported_agent_id,
                    "provider": provider,
                    "model": model,
                    "credential_id": credential_id,
                    "resume": True,
                },
                queue="imports",
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
                "celery_task_id": None,
            }
            flag_modified(evaluation, "prompt_improvements")
            db.commit()
    finally:
        db.close()
