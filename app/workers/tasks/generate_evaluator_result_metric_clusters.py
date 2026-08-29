"""Celery task: failure clustering for filtered evaluator-result scopes."""

from __future__ import annotations

from uuid import UUID

from loguru import logger
from sqlalchemy.orm.attributes import flag_modified

from app.database import SessionLocal
from app.models.database import EvaluatorResultClusterJob
from app.services.call_import_metric_clusters import (
    generate_metric_clusters_for_source_rows,
    metric_clusters_raw_is_cancelled,
    metric_clusters_state_to_db,
)
from app.services.evaluators.evaluator_result_metric_clusters import (
    clustering_context_for_job,
    load_completed_evaluator_results,
)
from app.services.metric_cluster_rows import (
    evaluator_result_to_cluster_row,
    filter_cluster_rows_by_ids,
)
from app.workers.config import celery_app


@celery_app.task(name="generate_evaluator_result_metric_clusters", bind=True, max_retries=0)
def generate_evaluator_result_metric_clusters_task(
    self,
    cluster_job_id: str,
    *,
    provider: str | None = None,
    model: str | None = None,
    credential_id: str | None = None,
    max_llm_calls: int | None = None,
    evaluation_row_ids: list[str] | None = None,
):
    from app.services.ai.llm_resolver import get_llm_provider_and_model

    db = SessionLocal()
    job: EvaluatorResultClusterJob | None = None
    try:
        job = (
            db.query(EvaluatorResultClusterJob)
            .filter(EvaluatorResultClusterJob.id == UUID(cluster_job_id))
            .first()
        )
        if job is None:
            logger.error("Evaluator metric clusters: job {} not found", cluster_job_id)
            return

        if metric_clusters_raw_is_cancelled(job.metric_clusters):
            logger.info(
                "Evaluator metric clusters: job {} already cancelled, skipping",
                cluster_job_id,
            )
            return

        provider_enum, model_str = get_llm_provider_and_model(
            job.organization_id,
            db,
            provider,
            model,
            UUID(credential_id) if credential_id else None,
        )

        metrics, aggregates, policies, _source, child_names_by_parent, source_rows, completed_count = (
            clustering_context_for_job(db, job)
        )
        if evaluation_row_ids:
            source_rows = filter_cluster_rows_by_ids(
                source_rows,
                [UUID(rid) for rid in evaluation_row_ids],
            )
        else:
            results = load_completed_evaluator_results(
                db,
                organization_id=job.organization_id,
                workspace_id=job.workspace_id,
                agent_id=job.agent_id,
                suite_id=job.suite_id,
                scenario_id=job.scenario_id,
            )
            source_rows = [evaluator_result_to_cluster_row(r) for r in results]

        def _reload_cancelled() -> bool:
            db.expire(job, ["metric_clusters"])
            db.refresh(job)
            return metric_clusters_raw_is_cancelled(job.metric_clusters)

        def on_progress(completed: int, total: int) -> None:
            if _reload_cancelled():
                return
            job.metric_clusters = {
                **(job.metric_clusters or {}),
                "status": "running",
                "progress": {
                    "completed_llm_calls": completed,
                    "total_llm_calls": total,
                },
            }
            flag_modified(job, "metric_clusters")
            db.commit()

        state = generate_metric_clusters_for_source_rows(
            db,
            job_key=job.id,
            metric_clusters_raw=job.metric_clusters,
            completed_row_count=completed_count,
            organization_id=job.organization_id,
            provider=provider_enum,
            model=model_str,
            source_rows=source_rows,
            metrics=metrics,
            policies=policies,
            on_progress=on_progress,
            max_llm_calls=max_llm_calls,
            is_cancelled=_reload_cancelled,
        )

        job.metric_clusters = metric_clusters_state_to_db(state)
        job.celery_task_id = None
        flag_modified(job, "metric_clusters")
        db.commit()
        logger.info(
            "Evaluator metric clusters completed for job {} status={}",
            cluster_job_id,
            state.status,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Evaluator metric clusters failed for job {}: {}", cluster_job_id, exc)
        if job is not None:
            prior = job.metric_clusters if isinstance(job.metric_clusters, dict) else {}
            job.metric_clusters = {
                **prior,
                "status": "failed",
                "error_message": str(exc)[:500],
                "celery_task_id": None,
            }
            flag_modified(job, "metric_clusters")
            db.commit()
    finally:
        db.close()
