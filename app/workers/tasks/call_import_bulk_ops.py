"""Celery tasks for bulk call-import API operations."""

from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from loguru import logger

from app.database import SessionLocal
from app.models.database import CallImport, CallImportEvaluation
from app.models.schemas import CallImportTranscribeRequest
from app.services.call_imports.bulk_ops import (
    execute_bulk_diarization,
    execute_bulk_row_delete,
    execute_call_import_delete,
    execute_call_import_materialization,
    execute_evaluation_cancel,
    execute_evaluation_retry,
    materialize_and_enqueue_evaluation,
)
from app.workers.config import celery_app


@celery_app.task(name="bulk_diarize_call_import", bind=True, max_retries=1)
def bulk_diarize_call_import_task(
    self,
    call_import_id: str,
    organization_id: str,
    payload_dict: dict,
    row_ids: Optional[List[str]] = None,
) -> dict:
    """Enqueue diarization for many import rows (runs off the API thread)."""
    del self
    db = SessionLocal()
    try:
        call_import = (
            db.query(CallImport)
            .filter(
                CallImport.id == UUID(call_import_id),
                CallImport.organization_id == UUID(organization_id),
            )
            .first()
        )
        if not call_import:
            logger.warning(
                "bulk_diarize_call_import_task: import {} not found",
                call_import_id,
            )
            return {"queued": 0, "skipped_rows": 0, "skipped_reason_counts": {}}

        payload = CallImportTranscribeRequest.model_validate(payload_dict)
        parsed_row_ids = [UUID(rid) for rid in row_ids] if row_ids else None
        result = execute_bulk_diarization(
            db,
            call_import,
            payload,
            requested_row_ids=parsed_row_ids,
        )
        return {
            "queued": result.queued,
            "skipped_rows": result.skipped_rows,
            "skipped_reason_counts": result.skipped_reason_counts,
        }
    except ValueError as exc:
        logger.warning(
            "bulk_diarize_call_import_task validation failed for {}: {}",
            call_import_id,
            exc,
        )
        return {"queued": 0, "error": str(exc)}
    finally:
        db.close()


@celery_app.task(name="materialize_call_import_evaluation", bind=True, max_retries=1)
def materialize_call_import_evaluation_task(
    self,
    evaluation_id: str,
    *,
    transcribe_overwrite: bool = False,
) -> dict:
    """Bulk-insert eval rows and start throttled dispatch."""
    del self
    db = SessionLocal()
    try:
        materialize_and_enqueue_evaluation(
            db,
            UUID(evaluation_id),
            transcribe_overwrite=transcribe_overwrite,
        )
        return {"evaluation_id": evaluation_id, "status": "materialized"}
    finally:
        db.close()


@celery_app.task(
    name="materialize_mapped_call_import_evaluation",
    bind=True,
    max_retries=1,
)
def materialize_mapped_call_import_evaluation_task(
    self,
    call_import_id: str,
    organization_id: str,
    workspace_id: str,
    evaluation_id: str,
    *,
    transcribe_overwrite: bool = False,
) -> dict:
    """Materialize import rows from staged source, then start eval dispatch.

    Runs off the API thread so large CSV/Excel batches (10k+ rows) do not
    block the Run Evaluation request.
    """
    del self
    logger.info(
        "materialize_mapped_call_import_evaluation starting "
        "(call_import={} evaluation={})",
        call_import_id,
        evaluation_id,
    )
    db = SessionLocal()
    eval_uuid = UUID(evaluation_id)
    try:
        mat_result = execute_call_import_materialization(
            db,
            UUID(call_import_id),
            UUID(organization_id),
            UUID(workspace_id),
            schedule_import_dispatch=False,
        )
        logger.info(
            "materialize_mapped_call_import_evaluation materialization finished "
            "(call_import={} evaluation={} status={} total_rows={})",
            call_import_id,
            evaluation_id,
            mat_result.get("status"),
            mat_result.get("total_rows"),
        )
        status = mat_result.get("status")
        if status == "failed":
            call_import = (
                db.query(CallImport)
                .filter(CallImport.id == UUID(call_import_id))
                .first()
            )
            _fail_evaluation_materialization(
                db,
                eval_uuid,
                error_message=(
                    (call_import.error_message if call_import else None)
                    or "Failed to materialize import rows for evaluation."
                ),
            )
            return {
                "evaluation_id": evaluation_id,
                "status": "failed",
                "materialization": mat_result,
            }

        materialize_and_enqueue_evaluation(
            db,
            eval_uuid,
            transcribe_overwrite=transcribe_overwrite,
        )
        return {
            "evaluation_id": evaluation_id,
            "status": "materialized",
            "materialization": mat_result,
        }
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "materialize_mapped_call_import_evaluation failed for eval {}",
            evaluation_id,
        )
        _fail_evaluation_materialization(
            db,
            eval_uuid,
            error_message=f"Failed to start evaluation: {exc}",
        )
        return {"evaluation_id": evaluation_id, "status": "failed", "error": str(exc)}
    finally:
        db.close()


def _fail_evaluation_materialization(
    db,
    evaluation_id: UUID,
    *,
    error_message: str,
) -> None:
    evaluation = (
        db.query(CallImportEvaluation)
        .filter(CallImportEvaluation.id == evaluation_id)
        .first()
    )
    if evaluation is None:
        return
    evaluation.status = "failed"
    evaluation.error_message = error_message
    db.commit()


@celery_app.task(name="retry_call_import_evaluation", bind=True, max_retries=1)
def retry_call_import_evaluation_task(
    self,
    evaluation_id: str,
    payload_dict: dict,
) -> dict:
    """Reset failed eval rows and start throttled dispatch off the API thread."""
    del self
    db = SessionLocal()
    try:
        eval_row_ids_raw = payload_dict.get("eval_row_ids")
        metric_ids_raw = payload_dict.get("metric_ids")
        return execute_evaluation_retry(
            db,
            UUID(evaluation_id),
            eval_row_ids=(
                [UUID(rid) for rid in eval_row_ids_raw]
                if eval_row_ids_raw
                else None
            ),
            metric_ids=(
                [UUID(mid) for mid in metric_ids_raw] if metric_ids_raw else None
            ),
            include_completed=bool(payload_dict.get("include_completed", False)),
            transcribe_overwrite=bool(payload_dict.get("transcribe_overwrite", False)),
        )
    finally:
        db.close()


@celery_app.task(name="cancel_call_import_evaluation", bind=True, max_retries=1)
def cancel_call_import_evaluation_task(
    self,
    evaluation_id: str,
    *,
    mode: str,
) -> dict:
    """Cancel eval rows in chunks off the API thread."""
    del self
    db = SessionLocal()
    try:
        if mode not in {"abort", "force_fail_pending"}:
            raise ValueError(f"Unknown cancel mode: {mode}")
        return execute_evaluation_cancel(
            db,
            UUID(evaluation_id),
            mode=mode,  # type: ignore[arg-type]
        )
    finally:
        db.close()


@celery_app.task(name="materialize_call_import_rows", bind=True, max_retries=1)
def materialize_call_import_rows_task(
    self,
    call_import_id: str,
    organization_id: str,
    workspace_id: str,
    *,
    schedule_import_dispatch: bool = False,
) -> dict:
    """Parse staged source file and bulk-insert rows off the API thread."""
    del self
    db = SessionLocal()
    try:
        return execute_call_import_materialization(
            db,
            UUID(call_import_id),
            UUID(organization_id),
            UUID(workspace_id),
            schedule_import_dispatch=schedule_import_dispatch,
        )
    finally:
        db.close()


@celery_app.task(name="delete_call_import", bind=True, max_retries=1)
def delete_call_import_task(
    self,
    call_import_id: str,
    organization_id: str,
) -> dict:
    """Delete a call-import batch and all associated storage off the API thread."""
    del self
    db = SessionLocal()
    try:
        return execute_call_import_delete(
            db,
            UUID(call_import_id),
            UUID(organization_id),
        )
    finally:
        db.close()


@celery_app.task(name="bulk_delete_call_import_rows", bind=True, max_retries=1)
def bulk_delete_call_import_rows_task(
    self,
    call_import_id: str,
    organization_id: str,
    row_ids: List[str],
) -> dict:
    """Delete many import rows and their blob recordings off the API thread."""
    del self
    db = SessionLocal()
    try:
        call_import = (
            db.query(CallImport)
            .filter(
                CallImport.id == UUID(call_import_id),
                CallImport.organization_id == UUID(organization_id),
            )
            .first()
        )
        if not call_import:
            logger.warning(
                "bulk_delete_call_import_rows_task: import {} not found",
                call_import_id,
            )
            return {"deleted": 0}

        deleted = execute_bulk_row_delete(
            db,
            UUID(organization_id),
            call_import,
            [UUID(rid) for rid in row_ids],
        )
        return {"deleted": deleted}
    finally:
        db.close()
