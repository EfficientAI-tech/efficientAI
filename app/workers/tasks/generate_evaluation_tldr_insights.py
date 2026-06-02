"""Celery task: LLM TLDR summary for a call import evaluation (Visualizations tab)."""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import HTTPException
from loguru import logger
from sqlalchemy.orm.attributes import flag_modified

from app.database import SessionLocal
from app.models.database import CallImportEvaluation
from app.workers.config import celery_app


@celery_app.task(
    name="generate_evaluation_tldr_insights",
    bind=True,
    max_retries=0,
    time_limit=30 * 60,
    soft_time_limit=25 * 60,
)
def generate_evaluation_tldr_insights_task(
    self,
    evaluation_id: str,
    *,
    call_import_id: str,
    organization_id: str,
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> dict:
    """Run the TLDR LLM call on the imports worker and persist the result."""
    db = SessionLocal()
    try:
        from app.api.v1.routes.call_import_evaluations import (
            _generate_and_persist_tldr_summary,
        )

        eval_uuid = UUID(evaluation_id)
        evaluation = (
            db.query(CallImportEvaluation)
            .filter(
                CallImportEvaluation.id == eval_uuid,
                CallImportEvaluation.call_import_id == UUID(call_import_id),
                CallImportEvaluation.organization_id == UUID(organization_id),
            )
            .first()
        )
        if not evaluation:
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
            return {
                "error": exc.detail,
                "status_code": exc.status_code,
            }

        return summary.model_dump(mode="json")
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "TLDR insights task failed for evaluation {}: {}",
            evaluation_id,
            exc,
        )
        raise
    finally:
        db.close()
