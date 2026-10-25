"""Celery task: failure clusters + prompt suggestions for a finished simulation run."""

from __future__ import annotations

from uuid import UUID

from loguru import logger
from sqlalchemy.orm.attributes import flag_modified

from app.database import SessionLocal
from app.models.database import SimulationRun
from app.services.call_import_metric_clusters import (
    metric_clusters_raw_is_cancelled,
    metric_clusters_state_to_db,
)
from app.workers.config import celery_app


@celery_app.task(name="analyze_simulation_run_failures", bind=True, max_retries=0)
def analyze_simulation_run_failures_task(
    self,
    simulation_run_id: str,
    *,
    provider: str | None = None,
    model: str | None = None,
    credential_id: str | None = None,
    max_llm_calls: int | None = None,
):
    from app.services.ai.llm_resolver import get_llm_provider_and_model_for_request
    from app.services.harbor.failure_analysis import (
        failed_prompt_improvements,
        generate_simulation_metric_clusters,
        generate_simulation_prompt_improvements,
    )

    db = SessionLocal()
    run: SimulationRun | None = None
    try:
        run = db.query(SimulationRun).filter(SimulationRun.id == UUID(simulation_run_id)).first()
        if run is None:
            logger.error("Simulation failure analysis: run {} not found", simulation_run_id)
            return
        if metric_clusters_raw_is_cancelled(run.metric_clusters):
            logger.info("Simulation failure analysis: run {} cancelled, skipping", run.run_id)
            return

        credential_uuid = UUID(credential_id) if credential_id else None
        provider_enum, model_str = get_llm_provider_and_model_for_request(
            run.organization_id, db, provider, model, credential_uuid
        )

        def _reload_cancelled() -> bool:
            db.expire(run, ["metric_clusters"])
            db.refresh(run)
            return metric_clusters_raw_is_cancelled(run.metric_clusters)

        def on_progress(update: dict) -> None:
            if _reload_cancelled():
                return
            run.metric_clusters = {
                **(run.metric_clusters or {}),
                "status": "running",
                "progress": update,
            }
            flag_modified(run, "metric_clusters")
            db.commit()

        state = generate_simulation_metric_clusters(
            db,
            run,
            provider=provider_enum,
            model=model_str,
            on_progress=on_progress,
            max_llm_calls=max_llm_calls,
            is_cancelled=_reload_cancelled,
        )
        run.metric_clusters = metric_clusters_state_to_db(state)
        flag_modified(run, "metric_clusters")
        if state.status != "completed":
            run.prompt_improvements = None
            db.commit()
            logger.info(
                "Simulation failure analysis for run {} ended with clusters status={}",
                run.run_id,
                state.status,
            )
            return

        run.prompt_improvements = {"status": "running"}
        db.commit()
        try:
            run.prompt_improvements = generate_simulation_prompt_improvements(
                db,
                run,
                state,
                provider=provider_enum.value,
                model=model_str,
                credential_id=credential_uuid,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Simulation prompt suggestions failed for run {}: {}", run.run_id, exc)
            run.prompt_improvements = failed_prompt_improvements(str(exc))
        flag_modified(run, "prompt_improvements")
        db.commit()
        logger.info("Simulation failure analysis completed for run {}", run.run_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Simulation failure analysis failed for run {}: {}", simulation_run_id, exc)
        if run is not None:
            db.rollback()
            prior = run.metric_clusters if isinstance(run.metric_clusters, dict) else {}
            run.metric_clusters = {
                **prior,
                "status": "failed",
                "error_message": str(exc)[:500],
            }
            flag_modified(run, "metric_clusters")
            db.commit()
    finally:
        db.close()
