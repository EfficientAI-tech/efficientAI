"""Celery task: per-metric failure clustering for internal diagnostics."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from loguru import logger
from sqlalchemy.orm.attributes import flag_modified

try:  # Celery raises this inside the task body on the soft limit
    from celery.exceptions import SoftTimeLimitExceeded
except Exception:  # pragma: no cover - celery is always installed at runtime
    class SoftTimeLimitExceeded(Exception):  # type: ignore[no-redef]
        pass

from app.database import SessionLocal
from app.models.database import CallImportEvaluation
from app.services.call_import_metric_clusters import (
    ClusterOutputTruncated,
    metric_clusters_raw_is_cancelled,
    metric_clusters_state_to_db,
)
from app.services.call_import_metric_clusters_wave import (
    process_metric_clusters_wave_step,
    resume_metric_clusters_job_header,
    start_metric_clusters_job_header,
)
from app.services.evaluation_analysis_checkpoints import (
    analysis_header_matches_run,
    new_job_run_id,
    normalize_transcript_source,
    stamp_job_heartbeat,
)
from app.workers.config import celery_app


def _reload_clusters_cancelled(db, evaluation: CallImportEvaluation) -> bool:
    db.expire(evaluation, ["metric_clusters"])
    db.refresh(evaluation)
    return metric_clusters_raw_is_cancelled(evaluation.metric_clusters)


@celery_app.task(name="generate_evaluation_metric_clusters", bind=True, max_retries=0)
def generate_evaluation_metric_clusters_task(
    self,
    evaluation_id: str,
    *,
    provider: str | None = None,
    model: str | None = None,
    credential_id: str | None = None,
    max_llm_calls: int | None = None,
    evaluation_row_ids: list[str] | None = None,
    transcript_source: str | None = None,
    resume: bool = False,
    job_run_id: str | None = None,
    **_ignored_kwargs: object,
):
    del max_llm_calls, evaluation_row_ids, _ignored_kwargs
    from app.api.v1.routes.call_import_evaluations import _child_names_by_parent
    from app.api.v1.routes.call_import_evaluations.clusters import (
        _metrics_for_clustering,
    )
    from app.services.metric_failure_policy import effective_policies
    from app.services.ai.llm_resolver import get_llm_provider_and_model_for_request

    db = SessionLocal()
    evaluation: CallImportEvaluation | None = None
    run_id: UUID | None = None
    # Needed by the soft-time-limit re-enqueue path, which can fire before the
    # in-try assignments have run.
    llm_provider: str | None = provider
    llm_model: str | None = model
    source: str | None = transcript_source
    try:
        evaluation = (
            db.query(CallImportEvaluation)
            .filter(CallImportEvaluation.id == UUID(evaluation_id))
            .first()
        )
        if evaluation is None:
            logger.error("Metric clusters: evaluation {} not found", evaluation_id)
            return

        if _reload_clusters_cancelled(db, evaluation):
            logger.info(
                "Metric clusters: evaluation {} already cancelled, skipping",
                evaluation_id,
            )
            return

        raw_for_llm = (
            evaluation.metric_clusters
            if isinstance(evaluation.metric_clusters, dict)
            else {}
        )
        if job_run_id and not analysis_header_matches_run(raw_for_llm, job_run_id):
            logger.info(
                "Metric clusters: stale task for run {} ignored; header is {}",
                job_run_id,
                raw_for_llm.get("job_run_id"),
            )
            return
        llm_provider = (provider or "").strip() or (
            raw_for_llm.get("provider")
            if isinstance(raw_for_llm.get("provider"), str)
            else None
        )
        llm_model = (model or "").strip() or (
            raw_for_llm.get("model") if isinstance(raw_for_llm.get("model"), str) else None
        )

        provider_enum, model_str = get_llm_provider_and_model_for_request(
            evaluation.organization_id,
            db,
            llm_provider,
            llm_model,
            UUID(credential_id) if credential_id else None,
        )
        # The re-enqueue path must carry a concrete provider/model pair.
        llm_provider = provider_enum.value if hasattr(provider_enum, "value") else str(provider_enum)
        llm_model = model_str

        from app.db_sharding.scatter_gather import load_evaluation_score_rows_for_aggregate
        from app.services.call_imports.metric_aggregate_cache import (
            evaluation_metric_aggregates_for_analysis,
        )

        score_rows = load_evaluation_score_rows_for_aggregate(db, evaluation.id)
        aggregates = evaluation_metric_aggregates_for_analysis(db, evaluation)
        eval_rows = score_rows
        metrics = _metrics_for_clustering(db, evaluation, eval_rows)
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

        raw = evaluation.metric_clusters if isinstance(evaluation.metric_clusters, dict) else {}
        source = normalize_transcript_source(
            transcript_source or raw.get("transcript_source") or evaluation.transcript_source
        )

        if raw.get("job_run_id"):
            run_id = UUID(str(raw["job_run_id"]))
            if resume or raw.get("status") != "running":
                evaluation.metric_clusters = resume_metric_clusters_job_header(
                    db,
                    evaluation,
                    raw,
                    transcript_source=source,
                    provider=provider_enum.value,
                    model=model_str,
                )
                flag_modified(evaluation, "metric_clusters")
                db.commit()
        else:
            run_id = new_job_run_id()
            merged_raw = {**raw} if isinstance(raw, dict) else {}
            evaluation.metric_clusters = start_metric_clusters_job_header(
                evaluation,
                db,
                job_run_id=run_id,
                transcript_source=source,
                provider=provider_enum.value,
                model=model_str,
                metric_clusters_raw=merged_raw,
            )
            flag_modified(evaluation, "metric_clusters")
            db.commit()

        def _reload_cancelled() -> bool:
            db.expire(evaluation, ["metric_clusters"])
            db.refresh(evaluation)
            current = (
                evaluation.metric_clusters
                if isinstance(evaluation.metric_clusters, dict)
                else {}
            )
            if metric_clusters_raw_is_cancelled(current):
                return True
            if not analysis_header_matches_run(current, run_id):
                logger.info(
                    "Metric clusters: task for run {} stopped; header is {}",
                    run_id,
                    current.get("job_run_id"),
                )
                return True
            return False

        def on_progress(update: dict) -> None:
            if _reload_cancelled():
                return
            current = (
                evaluation.metric_clusters
                if isinstance(evaluation.metric_clusters, dict)
                else {}
            )
            if metric_clusters_raw_is_cancelled(current):
                return
            evaluation.metric_clusters = stamp_job_heartbeat({
                **current,
                "status": "running",
                "progress": update,
            })
            if isinstance(update.get("completed_llm_calls"), (int, float)):
                evaluation.metric_clusters["llm_calls_used"] = int(
                    update["completed_llm_calls"]
                )
            flag_modified(evaluation, "metric_clusters")
            db.commit()

        from app.services.usage.call_import_context import usage_context_for_evaluation
        from app.services.usage.context import llm_usage_context

        with llm_usage_context(usage_context_for_evaluation(evaluation)):
            action, terminal_state = process_metric_clusters_wave_step(
                db,
                evaluation,
                evaluation.organization_id,
                provider_enum,
                model_str,
                metrics=metrics,
                policies=policies,
                job_run_id=run_id,
                on_progress=on_progress,
                is_cancelled=_reload_cancelled,
            )

        if _reload_cancelled():
            return

        if terminal_state is not None:
            if terminal_state.status == "cancelled":
                return
            persisted = metric_clusters_state_to_db(terminal_state)
            persisted["job_run_id"] = str(run_id)
            persisted["transcript_source"] = source
            persisted["celery_task_id"] = None
            if isinstance(evaluation.metric_clusters, dict):
                cursor = evaluation.metric_clusters.get("cursor")
                if cursor:
                    persisted["cursor"] = cursor
                if evaluation.metric_clusters.get("discovered_problems") is not None:
                    persisted["discovered_problems"] = evaluation.metric_clusters.get(
                        "discovered_problems"
                    )
            evaluation.metric_clusters = persisted
            flag_modified(evaluation, "metric_clusters")
            db.commit()
            return

        if _reload_cancelled():
            return

        flag_modified(evaluation, "metric_clusters")
        db.commit()

        if action == "continue":
            async_result = generate_evaluation_metric_clusters_task.apply_async(
                kwargs={
                    "evaluation_id": evaluation_id,
                    "provider": llm_provider,
                    "model": llm_model,
                    "credential_id": credential_id,
                    "transcript_source": source,
                    "resume": True,
                    "job_run_id": str(run_id),
                },
                queue="imports",
            )
            # Cancel could have landed while we were enqueuing; revoke the
            # follow-up task instead of letting it resurrect the job.
            db.expire(evaluation, ["metric_clusters"])
            db.refresh(evaluation)
            if metric_clusters_raw_is_cancelled(evaluation.metric_clusters) or (
                isinstance(evaluation.metric_clusters, dict)
                and not analysis_header_matches_run(evaluation.metric_clusters, run_id)
            ):
                from app.workers.celery_revoke import revoke_celery_tasks

                revoke_celery_tasks([async_result.id])
                return
            if isinstance(evaluation.metric_clusters, dict):
                evaluation.metric_clusters["status"] = "running"
                evaluation.metric_clusters["celery_task_id"] = async_result.id
                stamp_job_heartbeat(evaluation.metric_clusters)
                flag_modified(evaluation, "metric_clusters")
                db.commit()
    except SoftTimeLimitExceeded:
        # A single 500-row page can outlast the 25 minute soft limit. The
        # extraction sub-batches are already checkpointed, so hand the next
        # step to a fresh task instead of failing the whole job.
        logger.warning(
            "Metric clusters hit the soft time limit for evaluation {}; "
            "re-enqueuing from the last checkpoint",
            evaluation_id,
        )
        try:
            db.rollback()
            evaluation = (
                db.query(CallImportEvaluation)
                .filter(CallImportEvaluation.id == UUID(evaluation_id))
                .first()
            )
            if evaluation is None or metric_clusters_raw_is_cancelled(
                evaluation.metric_clusters
            ):
                return
            prior = (
                evaluation.metric_clusters
                if isinstance(evaluation.metric_clusters, dict)
                else {}
            )
            if run_id is not None and not analysis_header_matches_run(prior, run_id):
                return
            header_run_id = prior.get("job_run_id")
            if not header_run_id:
                logger.warning(
                    "Metric clusters soft time limit for evaluation {} with no "
                    "job_run_id; leaving it resumable instead of re-enqueuing",
                    evaluation_id,
                )
                return
            evaluation.metric_clusters = stamp_job_heartbeat(
                {**prior, "status": "running", "celery_task_id": None}
            )
            flag_modified(evaluation, "metric_clusters")
            db.commit()
        except Exception:  # noqa: BLE001
            db.rollback()
            return
        try:
            async_result = generate_evaluation_metric_clusters_task.apply_async(
                kwargs={
                    "evaluation_id": evaluation_id,
                    "provider": llm_provider,
                    "model": llm_model,
                    "credential_id": credential_id,
                    "transcript_source": source,
                    "resume": True,
                    "job_run_id": str(header_run_id),
                },
                queue="imports",
            )
            if isinstance(evaluation.metric_clusters, dict):
                evaluation.metric_clusters["status"] = "running"
                evaluation.metric_clusters["celery_task_id"] = async_result.id
                flag_modified(evaluation, "metric_clusters")
                db.commit()
        except Exception:  # noqa: BLE001
            logger.exception(
                "Failed to re-enqueue metric clusters after soft time limit "
                "for evaluation {}",
                evaluation_id,
            )
    except ClusterOutputTruncated as exc:
        logger.exception(
            "Metric clusters output truncated for evaluation {}: {}",
            evaluation_id,
            exc,
        )
        try:
            db.rollback()
            evaluation = (
                db.query(CallImportEvaluation)
                .filter(CallImportEvaluation.id == UUID(evaluation_id))
                .first()
            )
            if evaluation is not None and not metric_clusters_raw_is_cancelled(
                evaluation.metric_clusters
            ):
                prior = (
                    evaluation.metric_clusters
                    if isinstance(evaluation.metric_clusters, dict)
                    else {}
                )
                if run_id is None or analysis_header_matches_run(prior, run_id):
                    evaluation.metric_clusters = {
                        **prior,
                        "status": "failed",
                        "error_message": str(exc) or "Cluster output was truncated.",
                        "generated_at": datetime.now(timezone.utc).isoformat(),
                        "celery_task_id": None,
                    }
                    flag_modified(evaluation, "metric_clusters")
                    db.commit()
        except Exception:  # noqa: BLE001
            db.rollback()
        raise
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
                prior = (
                    evaluation.metric_clusters
                    if isinstance(evaluation.metric_clusters, dict)
                    else {}
                )
                if run_id is not None and not analysis_header_matches_run(
                    prior, run_id
                ):
                    return
                evaluation.metric_clusters = {
                    **prior,
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
