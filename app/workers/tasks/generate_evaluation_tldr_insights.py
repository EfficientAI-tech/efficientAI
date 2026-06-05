"""Celery task: generate TLDR summary for a call-import evaluation."""

from __future__ import annotations

from uuid import UUID

from loguru import logger
from app.database import SessionLocal
from app.models.database import CallImportEvaluation
from app.workers.config import celery_app


@celery_app.task(name="generate_evaluation_tldr_insights", bind=True, max_retries=0)
def generate_evaluation_tldr_insights_task(
    self,
    *,
    evaluation_id: str,
    call_import_id: str,
    organization_id: str,
    provider: str | None = None,
    model: str | None = None,
):
    """Run TLDR LLM generation and persist on the evaluation row."""
    from app.api.v1.routes.call_import_evaluations import (
        _generate_and_persist_tldr_summary,
    )
    from fastapi import HTTPException

    db = SessionLocal()
    try:
        evaluation = (
            db.query(CallImportEvaluation)
            .filter(
                CallImportEvaluation.id == UUID(evaluation_id),
                CallImportEvaluation.call_import_id == UUID(call_import_id),
                CallImportEvaluation.organization_id == UUID(organization_id),
            )
            .first()
        )
        if evaluation is None:
            return {"error": "evaluation_not_found", "status_code": 404}

        try:
            summary = _generate_and_persist_tldr_summary(
                db,
                evaluation,
                organization_id=UUID(organization_id),
                provider=provider,
                model=model,
            )
        except HTTPException as exc:
            return {"error": exc.detail, "status_code": exc.status_code}

        return summary.model_dump(mode="json")
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "TLDR generation failed for evaluation {}: {}",
            evaluation_id,
            exc,
        )
        return {"error": str(exc), "status_code": 502}
    finally:
        db.close()
