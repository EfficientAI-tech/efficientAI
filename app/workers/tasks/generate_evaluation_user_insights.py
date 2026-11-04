"""Celery task: generate map-reduce user insights for a call-import evaluation."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from loguru import logger
from sqlalchemy.orm.attributes import flag_modified

from app.database import SessionLocal
from app.models.database import CallImportEvaluation
from app.services.call_import_user_insights import user_insights_state_to_db
from app.services.call_import_user_insights_wave import (
    process_user_insights_wave_step,
    start_user_insights_job_header,
)
from app.services.evaluation_analysis_checkpoints import (
    new_job_run_id,
    normalize_transcript_source,
    user_insights_raw_is_cancelled,
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
    transcript_source: str | None = None,
    resume: bool = False,
):
    del max_llm_calls  # full corpus; budget follows row batches
    from app.api.v1.routes.call_import_evaluations import (
        _metrics_for_ids,
        _serialize_selected_metric_ids,
    )
    from app.services.ai.llm_resolver import get_llm_provider_and_model_for_request

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

        if user_insights_raw_is_cancelled(evaluation.user_insights):
            logger.info(
                "User insights: evaluation {} cancelled, skipping",
                evaluation_id,
            )
            return

        provider_enum, model_str = get_llm_provider_and_model_for_request(
            evaluation.organization_id,
            db,
            provider,
            model,
        )

        from app.services.call_imports.metric_aggregate_cache import (
            evaluation_metric_aggregates_for_analysis,
        )

        selected_ids = _serialize_selected_metric_ids(evaluation.selected_metric_ids)
        metrics = _metrics_for_ids(db, evaluation.organization_id, selected_ids)
        aggregate = evaluation_metric_aggregates_for_analysis(db, evaluation)

        raw = evaluation.user_insights if isinstance(evaluation.user_insights, dict) else {}
        source = normalize_transcript_source(
            transcript_source or raw.get("transcript_source")
        )

        if raw.get("job_run_id"):
            run_id = UUID(str(raw["job_run_id"]))
        elif resume:
            run_id = new_job_run_id()
            evaluation.user_insights = start_user_insights_job_header(
                evaluation,
                db,
                job_run_id=run_id,
                transcript_source=source,
                provider=provider_enum.value,
                model=model_str,
                prior_insights=[],
            )
            flag_modified(evaluation, "user_insights")
            db.commit()
        else:
            run_id = new_job_run_id()
            prior_insights = raw.get("insights") if isinstance(raw.get("insights"), list) else []
            evaluation.user_insights = start_user_insights_job_header(
                evaluation,
                db,
                job_run_id=run_id,
                transcript_source=source,
                provider=provider_enum.value,
                model=model_str,
                prior_insights=prior_insights if raw.get("status") == "completed" else [],
            )
            flag_modified(evaluation, "user_insights")
            db.commit()

        def _reload_cancelled() -> bool:
            db.expire(evaluation, ["user_insights"])
            db.refresh(evaluation)
            return user_insights_raw_is_cancelled(evaluation.user_insights)

        def on_progress(update: dict) -> None:
            if _reload_cancelled():
                return
            merged = {
                **(evaluation.user_insights or {}),
                "status": "running",
                "progress": update,
            }
            evaluation.user_insights = merged
            flag_modified(evaluation, "user_insights")
            db.commit()

        from app.services.usage.call_import_context import usage_context_for_evaluation
        from app.services.usage.context import llm_usage_context

        with llm_usage_context(usage_context_for_evaluation(evaluation)):
            action, terminal_state = process_user_insights_wave_step(
                db,
                evaluation,
                evaluation.organization_id,
                provider_enum,
                model_str,
                metrics=metrics,
                aggregate=aggregate,
                transcript_source=source,
                job_run_id=run_id,
                on_progress=on_progress,
                is_cancelled=_reload_cancelled,
            )

        if _reload_cancelled():
            return

        if terminal_state is not None:
            payload = user_insights_state_to_db(terminal_state)
            payload["job_run_id"] = str(run_id)
            payload["transcript_source"] = source
            payload["celery_task_id"] = None
            if isinstance(evaluation.user_insights, dict):
                cursor = evaluation.user_insights.get("cursor")
                if cursor:
                    payload["cursor"] = cursor
            evaluation.user_insights = payload
            flag_modified(evaluation, "user_insights")
            db.commit()
            if terminal_state.status == "completed":
                from app.services.billing.flexprice_service import (
                    record_call_import_user_insights_generated,
                )

                record_call_import_user_insights_generated(
                    evaluation.organization_id,
                    uuid4(),
                    workspace_id=evaluation.workspace_id,
                    evaluation_id=evaluation.id,
                )
            return

        flag_modified(evaluation, "user_insights")
        db.commit()

        if action == "continue":
            generate_evaluation_user_insights_task.apply_async(
                kwargs={
                    "evaluation_id": evaluation_id,
                    "provider": provider,
                    "model": model,
                    "transcript_source": source,
                    "resume": True,
                },
                queue="imports",
            )
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
            if evaluation is not None and not user_insights_raw_is_cancelled(
                evaluation.user_insights
            ):
                prior = (
                    evaluation.user_insights
                    if isinstance(evaluation.user_insights, dict)
                    else {}
                )
                evaluation.user_insights = {
                    **prior,
                    "status": "failed",
                    "error_message": str(exc),
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "celery_task_id": None,
                }
                flag_modified(evaluation, "user_insights")
                db.commit()
        except Exception:  # noqa: BLE001
            db.rollback()
    finally:
        db.close()
