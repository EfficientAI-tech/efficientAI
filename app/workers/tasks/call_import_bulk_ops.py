"""Celery tasks for bulk call-import API operations."""

from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from loguru import logger

from app.database import SessionLocal
from app.models.database import CallImport
from app.models.schemas import CallImportTranscribeRequest
from app.services.call_imports.bulk_ops import (
    execute_bulk_diarization,
    execute_bulk_row_delete,
    execute_call_import_delete,
    execute_call_import_materialization,
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


@celery_app.task(name="materialize_call_import_rows", bind=True, max_retries=1)
def materialize_call_import_rows_task(
    self,
    call_import_id: str,
    organization_id: str,
    workspace_id: str,
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
