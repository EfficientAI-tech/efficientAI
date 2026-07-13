"""Celery task: audio-metric phase for call-import evaluation rows.

Runs on the ``audio-metrics`` queue (``worker`` service) so torch/Praat/UTMOS
stay off the lightweight ``worker-imports`` pool.
"""

from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from loguru import logger

from app.database import SessionLocal
from app.models.database import (
    CallImportEvaluation,
    CallImportEvaluationRow,
    CallImportRow,
)
from app.workers.config import celery_app
from app.workers.concurrency.eval_dispatch import EVALUATIONS_QUEUE
from app.workers.tasks.evaluate_call_import_row_core import (
    as_json_dict,
    categorize_row_metrics,
    load_enabled_metrics,
    now_utc,
    parse_restricted_metric_uuids,
    rollup_parent,
    row_needs_llm_phase,
    was_cancelled_externally,
)


@celery_app.task(
    name="evaluate_call_import_row_audio",
    bind=True,
    max_retries=2,
    time_limit=10 * 60,
    soft_time_limit=8 * 60,
)
def evaluate_call_import_row_audio_task(
    self,
    eval_row_id: str,
    restricted_metric_ids: Optional[List[str]] = None,
    _eval_slot_task_id: Optional[str] = None,
):
    """Score audio-only metrics; chain LLM phase or finalize when done."""
    db = SessionLocal()
    slot_task_id = _eval_slot_task_id or self.request.id
    chain_llm = False
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
            eval_row.finished_at = now_utc()
            db.commit()
            rollup_parent(db, evaluation)
            db.commit()
            return {"status": "failed", "reason": "source_row_missing"}

        eval_row.status = "running"
        eval_row.celery_task_id = self.request.id
        eval_row.error_message = None
        eval_row.started_at = eval_row.started_at or now_utc()
        if evaluation.status == "pending":
            evaluation.status = "running"
            evaluation.started_at = evaluation.started_at or now_utc()
        db.commit()

        restricted_uuids = parse_restricted_metric_uuids(restricted_metric_ids)
        if restricted_metric_ids is not None and restricted_uuids is not None:
            selected_raw = {str(x) for x in (evaluation.selected_metric_ids or [])}
            if restricted_uuids and not any(
                str(mid) in selected_raw for mid in restricted_uuids
            ):
                eval_row.status = "completed"
                eval_row.error_message = None
                eval_row.finished_at = now_utc()
                db.commit()
                rollup_parent(db, evaluation)
                db.commit()
                return {
                    "status": "skipped",
                    "reason": "restricted_metric_ids_no_match",
                }

        metrics = load_enabled_metrics(
            db, evaluation, restricted_metric_ids=restricted_metric_ids
        )
        if not metrics:
            eval_row.status = "failed"
            eval_row.error_message = "No enabled metrics selected for this evaluation"
            eval_row.finished_at = now_utc()
            db.commit()
            rollup_parent(db, evaluation)
            db.commit()
            return {"status": "failed", "reason": "no_metrics"}

        (
            _transcript_metrics,
            audio_metrics,
            _comparison_metrics,
            metric_scores,
        ) = categorize_row_metrics(db, evaluation, source_row, metrics)

        recording_s3_key = (source_row.recording_s3_key or "").strip() or None
        result_id = f"call-import-eval:{eval_row.id}"
        audio_failed = False

        if audio_metrics and recording_s3_key:
            from app.workers.tasks.helpers.audio_evaluation import (
                evaluate_audio_metrics,
                handle_audio_evaluation_error,
            )

            try:
                audio_scores = evaluate_audio_metrics(
                    audio_s3_key=recording_s3_key,
                    audio_metrics=audio_metrics,
                    result_id=result_id,
                )
                metric_scores.update(audio_scores)
            except Exception as audio_err:  # noqa: BLE001
                logger.exception(
                    "[CallImportEval {}] Audio analysis failed", eval_row.id
                )
                metric_scores.update(
                    handle_audio_evaluation_error(audio_metrics, audio_err)
                )
                audio_failed = True

        if was_cancelled_externally(db, eval_row):
            try:
                rollup_parent(db, evaluation)
                db.commit()
            except Exception:  # noqa: BLE001
                db.rollback()
            return {"status": "cancelled", "eval_row_id": eval_row_id}

        existing = (
            eval_row.metric_scores if isinstance(eval_row.metric_scores, dict) else {}
        )
        merged = dict(existing)
        for key, value in as_json_dict(metric_scores).items():
            merged[key] = value
        eval_row.metric_scores = merged
        db.commit()

        needs_llm = row_needs_llm_phase(
            db,
            evaluation,
            source_row,
            restricted_metric_ids=restricted_metric_ids,
        )

        if needs_llm:
            from app.workers.tasks.evaluate_call_import_row import (
                evaluate_call_import_row_task,
            )

            chain_kwargs: dict = {
                "_skip_audio": True,
                "_eval_slot_task_id": slot_task_id,
            }
            if restricted_metric_ids:
                chain_kwargs["restricted_metric_ids"] = restricted_metric_ids
            evaluate_call_import_row_task.apply_async(
                args=(str(eval_row.id),),
                kwargs=chain_kwargs,
                queue=EVALUATIONS_QUEUE,
            )
            chain_llm = True
            return {
                "status": "chained",
                "eval_row_id": eval_row_id,
                "next": "llm_phase",
            }

        if audio_failed:
            eval_row.status = "failed"
            eval_row.error_message = "Evaluation failed for one or more audio metrics"
        else:
            eval_row.status = "completed"
            eval_row.error_message = None

        eval_row.finished_at = now_utc()
        db.commit()
        rollup_parent(db, evaluation)
        db.commit()

        return {
            "status": eval_row.status,
            "eval_row_id": eval_row_id,
            "phase": "audio_only",
        }
    finally:
        db.close()
        if not chain_llm:
            from app.workers.concurrency.fair_dispatch import (
                finish_eval_work_and_redispatch,
            )

            finish_eval_work_and_redispatch(
                slot_task_id,
                restricted_metric_ids=restricted_metric_ids,
            )
