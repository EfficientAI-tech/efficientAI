"""Celery task: failure clusters + prompt suggestions for a finished simulation run."""

from __future__ import annotations

import uuid
from typing import Any
from uuid import UUID

from loguru import logger
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.database import SessionLocal
from app.models.database import SimulationRun
from app.services.call_import_metric_clusters import (
    metric_clusters_raw_is_cancelled,
    metric_clusters_state_to_db,
)
from app.workers.config import celery_app

# Key in ``SimulationRun.metric_clusters`` naming the analysis that owns it.
ANALYSIS_ID_KEY = "analysis_id"


def new_failure_analysis_state() -> dict[str, Any]:
    """Fresh ``metric_clusters`` header for a queued analysis, with its ownership ID."""
    return {"status": "running", ANALYSIS_ID_KEY: uuid.uuid4().hex}


def _owned_by(raw: Any, analysis_id: str | None) -> bool:
    # Tasks queued before ownership IDs existed carry none; let them through.
    if analysis_id is None:
        return True
    return isinstance(raw, dict) and raw.get(ANALYSIS_ID_KEY) == analysis_id


def _lock_run(db: Session, run_id: UUID) -> SimulationRun | None:
    """Re-read the run under a row lock so an ownership check and its write are atomic."""
    return (
        db.query(SimulationRun)
        .filter(SimulationRun.id == run_id)
        .populate_existing()
        .with_for_update()
        .first()
    )


@celery_app.task(name="analyze_simulation_run_failures", bind=True, max_retries=0)
def analyze_simulation_run_failures_task(
    self,
    simulation_run_id: str,
    *,
    provider: str | None = None,
    model: str | None = None,
    credential_id: str | None = None,
    max_llm_calls: int | None = None,
    analysis_id: str | None = None,
):
    from app.services.ai.llm_resolver import get_llm_provider_and_model_for_request
    from app.services.harbor.failure_analysis import (
        failed_prompt_improvements,
        generate_simulation_metric_clusters,
        generate_simulation_prompt_improvements,
    )

    db = SessionLocal()
    run_uuid = UUID(simulation_run_id)
    run: SimulationRun | None = None

    def _with_analysis_id(raw: dict[str, Any]) -> dict[str, Any]:
        return {**raw, ANALYSIS_ID_KEY: analysis_id} if analysis_id else raw

    try:
        run = db.query(SimulationRun).filter(SimulationRun.id == run_uuid).first()
        if run is None:
            logger.error("Simulation failure analysis: run {} not found", simulation_run_id)
            return
        if not _owned_by(run.metric_clusters, analysis_id):
            logger.info("Simulation failure analysis: run {} was superseded, skipping", run.run_id)
            return
        if metric_clusters_raw_is_cancelled(run.metric_clusters):
            logger.info("Simulation failure analysis: run {} cancelled, skipping", run.run_id)
            return

        credential_uuid = UUID(credential_id) if credential_id else None
        provider_enum, model_str = get_llm_provider_and_model_for_request(
            run.organization_id, db, provider, model, credential_uuid
        )

        def _reload_cancelled() -> bool:
            """True when cancelled, or when a newer analysis has taken over this run."""
            db.expire(run, ["metric_clusters"])
            db.refresh(run)
            raw = run.metric_clusters
            return not _owned_by(raw, analysis_id) or metric_clusters_raw_is_cancelled(raw)

        def on_progress(update: dict) -> None:
            locked = _lock_run(db, run_uuid)
            if (
                locked is None
                or not _owned_by(locked.metric_clusters, analysis_id)
                or metric_clusters_raw_is_cancelled(locked.metric_clusters)
            ):
                db.rollback()
                return
            locked.metric_clusters = {
                **(locked.metric_clusters or {}),
                "status": "running",
                "progress": update,
            }
            flag_modified(locked, "metric_clusters")
            db.commit()

        state = generate_simulation_metric_clusters(
            db,
            run,
            provider=provider_enum,
            model=model_str,
            on_progress=on_progress,
            max_llm_calls=max_llm_calls,
            is_cancelled=_reload_cancelled,
            credential_id=credential_uuid,
        )

        run = _lock_run(db, run_uuid)
        if run is None or not _owned_by(run.metric_clusters, analysis_id):
            db.rollback()
            logger.info(
                "Simulation failure analysis for {} superseded; dropping clusters",
                simulation_run_id,
            )
            return
        run.metric_clusters = _with_analysis_id(metric_clusters_state_to_db(state))
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
            prompt_improvements = generate_simulation_prompt_improvements(
                db,
                run,
                state,
                provider=provider_enum.value,
                model=model_str,
                credential_id=credential_uuid,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Simulation prompt suggestions failed for run {}: {}", run.run_id, exc)
            prompt_improvements = failed_prompt_improvements(str(exc))

        run = _lock_run(db, run_uuid)
        if run is None or not _owned_by(run.metric_clusters, analysis_id):
            db.rollback()
            logger.info(
                "Simulation failure analysis for {} superseded; dropping prompt suggestions",
                simulation_run_id,
            )
            return
        run.prompt_improvements = prompt_improvements
        flag_modified(run, "prompt_improvements")
        db.commit()
        logger.info("Simulation failure analysis completed for run {}", run.run_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Simulation failure analysis failed for run {}: {}", simulation_run_id, exc)
        try:
            db.rollback()
            run = _lock_run(db, run_uuid)
            if run is None or not _owned_by(run.metric_clusters, analysis_id):
                db.rollback()
                return
            prior = run.metric_clusters if isinstance(run.metric_clusters, dict) else {}
            run.metric_clusters = {
                **prior,
                "status": "failed",
                "error_message": str(exc)[:500],
            }
            flag_modified(run, "metric_clusters")
            db.commit()
        except Exception:  # noqa: BLE001
            logger.exception(
                "Could not record failure for simulation run {}", simulation_run_id
            )
            db.rollback()
    finally:
        db.close()
