"""Celery task: evaluate one CallImport row against selected metrics."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from loguru import logger

from app.database import SessionLocal
from app.models.database import (
    AIProvider,
    CallImportEvaluation,
    CallImportEvaluationRow,
    CallImportRow,
    Metric,
)
from app.workers.config import celery_app
from app.workers.tasks.helpers.llm_evaluation import (
    evaluate_with_llm,
    handle_llm_evaluation_error,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_json_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _rollup_parent(db, evaluation: CallImportEvaluation) -> None:
    rows = (
        db.query(CallImportEvaluationRow.status)
        .filter(CallImportEvaluationRow.evaluation_id == evaluation.id)
        .all()
    )
    total = len(rows)
    completed = sum(1 for (status,) in rows if status == "completed")
    failed = sum(1 for (status,) in rows if status == "failed")
    in_progress = sum(1 for (status,) in rows if status in {"pending", "running"})

    evaluation.total_rows = total
    evaluation.completed_rows = completed
    evaluation.failed_rows = failed

    if in_progress > 0:
        evaluation.status = "running"
        if not evaluation.started_at:
            evaluation.started_at = _now()
        return

    evaluation.finished_at = _now()
    if total == 0:
        evaluation.status = "completed"
    elif failed == 0:
        evaluation.status = "completed"
    elif completed == 0:
        evaluation.status = "failed"
    else:
        evaluation.status = "partial"


@celery_app.task(name="evaluate_call_import_row", bind=True, max_retries=2)
def evaluate_call_import_row_task(self, eval_row_id: str):
    """Evaluate one row transcript with selected LLM metrics."""
    db = SessionLocal()
    try:
        row_uuid = UUID(eval_row_id)
        eval_row = (
            db.query(CallImportEvaluationRow)
            .filter(CallImportEvaluationRow.id == row_uuid)
            .first()
        )
        if not eval_row:
            logger.warning("CallImportEvaluationRow {} not found", eval_row_id)
            return {"status": "skipped", "reason": "row_not_found"}

        evaluation = (
            db.query(CallImportEvaluation)
            .filter(CallImportEvaluation.id == eval_row.evaluation_id)
            .first()
        )
        if not evaluation:
            logger.warning("CallImportEvaluation {} missing", eval_row.evaluation_id)
            eval_row.status = "failed"
            eval_row.error_message = "Evaluation parent not found"
            db.commit()
            return {"status": "failed", "reason": "evaluation_missing"}

        source_row = (
            db.query(CallImportRow)
            .filter(CallImportRow.id == eval_row.call_import_row_id)
            .first()
        )
        if not source_row:
            eval_row.status = "failed"
            eval_row.error_message = "Source call import row not found"
            eval_row.finished_at = _now()
            db.commit()
            _rollup_parent(db, evaluation)
            db.commit()
            return {"status": "failed", "reason": "source_row_missing"}

        eval_row.status = "running"
        eval_row.celery_task_id = self.request.id
        eval_row.error_message = None
        eval_row.started_at = eval_row.started_at or _now()
        if evaluation.status == "pending":
            evaluation.status = "running"
            evaluation.started_at = evaluation.started_at or _now()
        db.commit()

        transcript = (source_row.transcript or "").strip()
        if not transcript:
            eval_row.status = "failed"
            eval_row.error_message = "Transcript is empty for this row"
            eval_row.finished_at = _now()
            db.commit()
            _rollup_parent(db, evaluation)
            db.commit()
            return {"status": "failed", "reason": "missing_transcript"}

        metric_ids_raw = evaluation.selected_metric_ids or []
        metric_ids = []
        for item in metric_ids_raw:
            try:
                metric_ids.append(UUID(str(item)))
            except (TypeError, ValueError):
                continue

        metrics = (
            db.query(Metric)
            .filter(
                Metric.organization_id == evaluation.organization_id,
                Metric.id.in_(metric_ids),
                Metric.enabled.is_(True),
            )
            .all()
            if metric_ids
            else []
        )
        if not metrics:
            eval_row.status = "failed"
            eval_row.error_message = "No enabled metrics selected for this evaluation"
            eval_row.finished_at = _now()
            db.commit()
            _rollup_parent(db, evaluation)
            db.commit()
            return {"status": "failed", "reason": "no_metrics"}

        ai_providers = (
            db.query(AIProvider)
            .filter(
                AIProvider.organization_id == evaluation.organization_id,
                AIProvider.is_active.is_(True),
            )
            .all()
        )

        try:
            metric_scores, _ = evaluate_with_llm(
                transcription=transcript,
                llm_metrics=metrics,
                ai_providers=ai_providers,
                organization_id=evaluation.organization_id,
                result_id=f"call-import-eval:{eval_row.id}",
                db=db,
                evaluator=None,
                agent=None,
                persona=None,
                scenario=None,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("LLM evaluation failed for eval_row {}", eval_row.id)
            metric_scores = handle_llm_evaluation_error(metrics, exc)
            eval_row.status = "failed"
            eval_row.error_message = str(exc)
        else:
            eval_row.status = "completed"
            eval_row.error_message = None

        eval_row.metric_scores = _as_json_dict(metric_scores)
        eval_row.finished_at = _now()
        db.commit()

        _rollup_parent(db, evaluation)
        db.commit()

        return {
            "status": eval_row.status,
            "eval_row_id": eval_row_id,
            "metrics": len(eval_row.metric_scores or {}),
        }
    finally:
        db.close()
