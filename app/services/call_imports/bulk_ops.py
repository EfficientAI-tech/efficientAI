"""Bulk call-import operations (diarization enqueue, evaluation materialize, row delete).

Heavy work runs here so API handlers can return 202 quickly. Uses batched
blob/Redis/DB operations suitable for multi-thousand row imports.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID, uuid4

from loguru import logger
from sqlalchemy.orm import Session, load_only

from app.models.database import (
    CallImport,
    CallImportEvaluation,
    CallImportEvaluationRow,
    CallImportRow,
    CallImportRowStatus,
)
from app.models.schemas import CallImportTranscribeRequest

_BULK_INSERT_CHUNK = 1000
_REVOKE_TASK_BATCH = 500

_ROW_TRANSCRIBE_COLUMNS = (
    CallImportRow.id,
    CallImportRow.row_index,
    CallImportRow.recording_s3_key,
    CallImportRow.diarised_transcript,
    CallImportRow.diarised_transcript_status,
    CallImportRow.diarised_transcript_error,
    CallImportRow.celery_task_id,
)

_ROW_DELETE_COLUMNS = (
    CallImportRow.id,
    CallImportRow.recording_s3_key,
    CallImportRow.celery_task_id,
    CallImportRow.status,
)

_EVAL_SOURCE_COLUMNS = (
    CallImportRow.id,
    CallImportRow.recording_s3_key,
    CallImportRow.diarised_transcript,
)


@dataclass(frozen=True)
class BulkDiarizationResult:
    queued: int
    skipped_rows: int
    skipped_reason_counts: Dict[str, int]


def select_rows_for_transcription(
    db: Session,
    call_import: CallImport,
    payload: CallImportTranscribeRequest,
    requested_row_ids: Optional[List[UUID]] = None,
) -> tuple[List[CallImportRow], Dict[str, int]]:
    """Pick rows to diarise, loading only columns needed for the decision."""
    query = (
        db.query(CallImportRow)
        .options(load_only(*_ROW_TRANSCRIBE_COLUMNS))
        .filter(CallImportRow.call_import_id == call_import.id)
    )
    if requested_row_ids:
        query = query.filter(CallImportRow.id.in_(requested_row_ids))
    rows = query.order_by(CallImportRow.row_index.asc()).all()

    if requested_row_ids:
        found_ids = {r.id for r in rows}
        missing = [rid for rid in requested_row_ids if rid not in found_ids]
        if missing:
            raise ValueError(
                "Some row ids were not found on this import: "
                f"{[str(m) for m in missing]}"
            )

    selected: List[CallImportRow] = []
    skip_counts: Dict[str, int] = {}

    for row in rows:
        recording = (row.recording_s3_key or "").strip()
        if not recording:
            skip_counts["no_recording"] = skip_counts.get("no_recording", 0) + 1
            continue
        existing = (row.diarised_transcript or "").strip()
        if existing and payload.only_missing and not payload.overwrite_existing:
            skip_counts["transcript_present"] = (
                skip_counts.get("transcript_present", 0) + 1
            )
            continue
        selected.append(row)

    return selected, skip_counts


def execute_bulk_diarization(
    db: Session,
    call_import: CallImport,
    payload: CallImportTranscribeRequest,
    requested_row_ids: Optional[List[UUID]] = None,
) -> BulkDiarizationResult:
    """Mark rows pending, store Redis params in a pipeline, schedule dispatch."""
    from app.workers.concurrency.diarization_dispatch import (
        _REDIS_PARAMS_STORE_ERROR,
        build_diarization_params_from_request,
        store_row_diarization_params_batch,
    )
    from app.workers.concurrency.fair_diarization_dispatch import (
        schedule_fair_diarization_dispatch,
    )

    rows, skip_counts = select_rows_for_transcription(
        db, call_import, payload, requested_row_ids=requested_row_ids
    )

    for row in rows:
        row.diarised_transcript_status = "pending"
        row.diarised_transcript_error = None
        row.celery_task_id = None
    db.commit()

    if not rows:
        return BulkDiarizationResult(
            queued=0,
            skipped_rows=sum(skip_counts.values()),
            skipped_reason_counts=skip_counts,
        )

    diarization_params = build_diarization_params_from_request(
        stt_provider=payload.stt_provider,
        stt_model=payload.stt_model,
        credential_id=payload.credential_id,
        language=payload.language,
        overwrite_existing=payload.overwrite_existing,
        diarization_llm_provider=payload.diarization_llm_provider,
        diarization_llm_model=payload.diarization_llm_model,
        diarization_llm_credential_id=payload.diarization_llm_credential_id,
        diarization_prompt=payload.diarization_prompt,
        mode=payload.mode,
    )

    stored_ids, failed_ids = store_row_diarization_params_batch(
        [row.id for row in rows],
        diarization_params,
    )
    if failed_ids:
        failed_set = set(failed_ids)
        for row in rows:
            if row.id in failed_set:
                row.diarised_transcript_status = "failed"
                row.diarised_transcript_error = _REDIS_PARAMS_STORE_ERROR
        db.commit()

    queued = len(stored_ids)
    if queued > 0:
        schedule_fair_diarization_dispatch(max_workspace_turns=999)

    return BulkDiarizationResult(
        queued=queued,
        skipped_rows=sum(skip_counts.values()),
        skipped_reason_counts=skip_counts,
    )


def count_completed_source_rows(db: Session, call_import_id: UUID) -> int:
    from sqlalchemy import func

    return int(
        db.query(func.count(CallImportRow.id))
        .filter(
            CallImportRow.call_import_id == call_import_id,
            CallImportRow.status == CallImportRowStatus.COMPLETED,
        )
        .scalar()
        or 0
    )


def _completed_source_row_ids(db: Session, call_import_id: UUID) -> List[UUID]:
    return [
        row_id
        for (row_id,) in (
            db.query(CallImportRow.id)
            .filter(
                CallImportRow.call_import_id == call_import_id,
                CallImportRow.status == CallImportRowStatus.COMPLETED,
            )
            .order_by(CallImportRow.row_index.asc())
            .all()
        )
    ]


def bulk_insert_evaluation_rows(
    db: Session,
    evaluation_id: UUID,
    source_row_ids: List[UUID],
) -> None:
    """Insert eval-row stubs in chunks without per-row ORM overhead."""
    if not source_row_ids:
        return

    for start in range(0, len(source_row_ids), _BULK_INSERT_CHUNK):
        chunk = source_row_ids[start : start + _BULK_INSERT_CHUNK]
        mappings = [
            {
                "id": uuid4(),
                "evaluation_id": evaluation_id,
                "call_import_row_id": source_row_id,
                "status": "pending",
                "metric_scores": {},
            }
            for source_row_id in chunk
        ]
        db.bulk_insert_mappings(CallImportEvaluationRow, mappings)
    db.flush()


def materialize_and_enqueue_evaluation(
    db: Session,
    evaluation_id: UUID,
    *,
    transcribe_overwrite: bool = False,
) -> None:
    """Create eval-row records for every completed import row and start dispatch."""
    from app.api.v1.routes.call_import_evaluations import (
        _enqueue_eval_rows_with_optional_transcribe,
    )

    evaluation = (
        db.query(CallImportEvaluation)
        .filter(CallImportEvaluation.id == evaluation_id)
        .first()
    )
    if evaluation is None:
        logger.warning(
            "materialize_and_enqueue_evaluation: evaluation {} not found",
            evaluation_id,
        )
        return

    source_row_ids = _completed_source_row_ids(db, evaluation.call_import_id)
    evaluation.total_rows = len(source_row_ids)

    if not source_row_ids:
        evaluation.status = "completed"
        db.commit()
        return

    bulk_insert_evaluation_rows(db, evaluation_id, source_row_ids)
    db.commit()

    eval_rows = (
        db.query(CallImportEvaluationRow)
        .filter(CallImportEvaluationRow.evaluation_id == evaluation_id)
        .all()
    )
    source_rows = (
        db.query(CallImportRow)
        .options(load_only(*_EVAL_SOURCE_COLUMNS))
        .filter(CallImportRow.id.in_(source_row_ids))
        .all()
    )
    source_by_id = {row.id: row for row in source_rows}
    bucket: List[Tuple[CallImportEvaluationRow, CallImportRow]] = []
    for eval_row in eval_rows:
        source_row = source_by_id.get(eval_row.call_import_row_id)
        if source_row is not None:
            bucket.append((eval_row, source_row))

    try:
        _enqueue_eval_rows_with_optional_transcribe(
            db,
            evaluation,
            bucket,
            transcribe_overwrite=transcribe_overwrite,
        )
        evaluation.status = "running"
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "Failed to enqueue evaluation {} after materialize",
            evaluation_id,
        )
        evaluation.status = "failed"
        evaluation.error_message = f"Failed to enqueue evaluation: {exc}"
    db.commit()


def execute_bulk_row_delete(
    db: Session,
    organization_id: UUID,
    call_import: CallImport,
    row_ids: List[UUID],
) -> int:
    """Revoke tasks, batch-delete blob recordings, bulk-delete DB rows."""
    from app.api.v1.routes.call_imports import (
        _delete_s3_objects,
        _recompute_call_import_counters,
        _revoke_pending_tasks,
    )

    if not row_ids:
        return 0

    rows = (
        db.query(CallImportRow)
        .options(load_only(*_ROW_DELETE_COLUMNS))
        .filter(
            CallImportRow.id.in_(row_ids),
            CallImportRow.call_import_id == call_import.id,
        )
        .all()
    )
    if not rows:
        return 0

    _revoke_pending_tasks(rows)
    _delete_s3_objects(organization_id, call_import.id, rows)

    deleted_ids = [row.id for row in rows]
    deleted = (
        db.query(CallImportRow)
        .filter(
            CallImportRow.id.in_(deleted_ids),
            CallImportRow.call_import_id == call_import.id,
        )
        .delete(synchronize_session=False)
    )
    db.flush()

    _recompute_call_import_counters(db, call_import)
    db.commit()

    logger.info(
        "Bulk-deleted {} call_import_rows (call_import={}, org={})",
        deleted,
        call_import.id,
        organization_id,
    )
    return int(deleted or 0)


def _revoke_call_import_task_ids(db: Session, call_import_id: UUID) -> int:
    """Revoke in-flight Celery tasks for an import without loading full rows."""
    task_id_rows = [
        task_id
        for (task_id,) in (
            db.query(CallImportRow.celery_task_id)
            .filter(
                CallImportRow.call_import_id == call_import_id,
                CallImportRow.celery_task_id.isnot(None),
                CallImportRow.status.in_(
                    (CallImportRowStatus.PENDING, CallImportRowStatus.PROCESSING)
                ),
            )
            .all()
        )
        if task_id
    ]
    if not task_id_rows:
        return 0

    try:
        from app.workers.celery_app import celery_app

        revoked = 0
        for start in range(0, len(task_id_rows), _REVOKE_TASK_BATCH):
            chunk = task_id_rows[start : start + _REVOKE_TASK_BATCH]
            celery_app.control.revoke(chunk, terminate=False)
            revoked += len(chunk)
        logger.info(
            "Revoked {} pending call-import tasks for import {}",
            revoked,
            call_import_id,
        )
        return revoked
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Failed to revoke pending call-import tasks for {}: {}",
            call_import_id,
            exc,
        )
        return 0


def execute_call_import_delete(
    db: Session,
    call_import_id: UUID,
    organization_id: UUID,
) -> dict:
    """Tear down a call-import batch, its rows, and S3 artefacts off the API thread."""
    from app.models.enums import CallImportStatus
    from app.services.storage.s3_service import s3_service

    call_import = (
        db.query(CallImport)
        .filter(
            CallImport.id == call_import_id,
            CallImport.organization_id == organization_id,
        )
        .first()
    )
    if call_import is None:
        logger.info(
            "execute_call_import_delete: import {} already removed",
            call_import_id,
        )
        return {"status": "completed", "deleted_rows": 0}

    total_rows = int(call_import.total_rows or 0)
    _revoke_call_import_task_ids(db, call_import_id)

    deleted_objects = 0
    s3_errors = 0
    if s3_service.is_enabled():
        sweep_prefix = (
            f"{s3_service.prefix}organizations/{organization_id}/"
            f"call_imports/{call_import_id}/"
        )
        try:
            deleted_objects, errs = s3_service.delete_keys_by_prefix(sweep_prefix)
            s3_errors = len(errs)
            if errs:
                logger.warning(
                    "S3 prefix sweep reported {} errors for call_import {}",
                    s3_errors,
                    call_import_id,
                )
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "S3 prefix sweep failed for call_import {}: {}",
                call_import_id,
                exc,
            )

    try:
        db.delete(call_import)
        db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "Failed to delete call_import {} from database",
            call_import_id,
        )
        db.rollback()
        call_import = (
            db.query(CallImport)
            .filter(
                CallImport.id == call_import_id,
                CallImport.organization_id == organization_id,
            )
            .first()
        )
        if call_import is not None:
            call_import.status = CallImportStatus.FAILED
            call_import.error_message = f"Failed to delete import: {exc}"
            db.commit()
        return {"status": "failed", "deleted_rows": 0, "error": str(exc)}

    logger.info(
        "Deleted call_import {} (org={}, rows={}, s3_objects_deleted={}, s3_errors={})",
        call_import_id,
        organization_id,
        total_rows,
        deleted_objects,
        s3_errors,
    )
    return {
        "status": "completed",
        "deleted_rows": total_rows,
        "s3_objects_deleted": deleted_objects,
        "s3_errors": s3_errors,
    }


def bulk_materialize_call_import_rows(
    db: Session,
    call_import: CallImport,
    parsed_rows: List[Dict[str, Any]],
    organization_id: UUID,
) -> int:
    """Insert import rows in chunks without per-row ORM overhead."""
    from app.api.v1.routes.call_imports import _parse_recording_date_cell

    if not parsed_rows:
        return 0

    for start in range(0, len(parsed_rows), _BULK_INSERT_CHUNK):
        chunk = parsed_rows[start : start + _BULK_INSERT_CHUNK]
        mappings = []
        for offset, row in enumerate(chunk):
            idx = start + offset
            csv_transcript = row["transcript"]
            mappings.append(
                {
                    "id": uuid4(),
                    "call_import_id": call_import.id,
                    "organization_id": organization_id,
                    "row_index": idx,
                    "conversation_id": row["conversation_id"],
                    "recording_date": (
                        _parse_recording_date_cell(row["recording_date"])
                        if row.get("recording_date")
                        else None
                    ),
                    "recording_url": row["recording_url"],
                    "transcript": csv_transcript,
                    "transcript_source": (
                        "csv" if csv_transcript and csv_transcript.strip() else None
                    ),
                    "raw_columns": row["parameter_values"] or None,
                    "status": CallImportRowStatus.PENDING,
                }
            )
        db.bulk_insert_mappings(CallImportRow, mappings)
    db.flush()
    return len(parsed_rows)


def execute_call_import_materialization(
    db: Session,
    call_import_id: UUID,
    organization_id: UUID,
    workspace_id: UUID,
) -> dict:
    """Download staged source, parse, bulk-insert rows, and start import dispatch."""
    from app.api.v1.routes.call_imports import (
        _clean_skipped_columns,
        _enqueue_row_tasks,
        _parse_source_file,
        _resolve_schema,
    )
    from app.models.enums import CallImportStatus
    from app.services.billing.flexprice_service import record_call_import_batch_created
    from app.services.storage.s3_service import StorageError, s3_service

    call_import = (
        db.query(CallImport)
        .filter(
            CallImport.id == call_import_id,
            CallImport.organization_id == organization_id,
            CallImport.workspace_id == workspace_id,
        )
        .first()
    )
    if call_import is None:
        logger.warning(
            "execute_call_import_materialization: import {} not found",
            call_import_id,
        )
        return {"total_rows": 0, "status": "not_found"}

    if call_import.status != CallImportStatus.PROCESSING:
        logger.warning(
            "execute_call_import_materialization: import {} in unexpected status {}",
            call_import_id,
            call_import.status,
        )
        return {"total_rows": 0, "status": call_import.status.value}

    existing_rows = (
        db.query(CallImportRow.id)
        .filter(CallImportRow.call_import_id == call_import.id)
        .limit(1)
        .first()
    )
    if existing_rows is not None:
        logger.info(
            "execute_call_import_materialization: import {} already has rows; scheduling dispatch",
            call_import_id,
        )
        _enqueue_row_tasks(db, call_import, [])
        return {"total_rows": call_import.total_rows, "status": "already_materialized"}

    if not call_import.source_s3_key or not call_import.source_format:
        call_import.status = CallImportStatus.FAILED
        call_import.error_message = "Missing staged source file."
        db.commit()
        return {"total_rows": 0, "status": "failed"}

    if not call_import.schema_id:
        call_import.status = CallImportStatus.FAILED
        call_import.error_message = "Missing mapped schema."
        db.commit()
        return {"total_rows": 0, "status": "failed"}

    if not s3_service.is_enabled():
        call_import.status = CallImportStatus.FAILED
        call_import.error_message = (
            s3_service.get_status_message()
            or "Cloud blob storage is not enabled or not configured"
        )
        db.commit()
        return {"total_rows": 0, "status": "failed"}

    try:
        file_bytes = s3_service.download_file_by_key(call_import.source_s3_key)
    except StorageError as exc:
        call_import.status = CallImportStatus.FAILED
        call_import.error_message = f"Could not read staged source file from S3: {exc}"
        db.commit()
        return {"total_rows": 0, "status": "failed"}

    schema = _resolve_schema(
        db, organization_id, workspace_id, call_import.schema_id
    )
    parameters = list(schema.parameters)
    cleaned_skipped = _clean_skipped_columns(list(call_import.skipped_columns or []))
    parsed_rows = _parse_source_file(
        file_bytes,
        call_import.source_format,
        call_import.sheet_name,
        parameters,
        dict(call_import.parameter_mapping or {}),
        cleaned_skipped,
    )

    call_import.total_rows = len(parsed_rows)
    call_import.completed_rows = 0
    call_import.failed_rows = 0

    try:
        row_count = bulk_materialize_call_import_rows(
            db,
            call_import,
            parsed_rows,
            organization_id,
        )
        db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "Failed to materialize rows for call import {}",
            call_import_id,
        )
        db.rollback()
        call_import.status = CallImportStatus.FAILED
        call_import.error_message = f"Failed to materialize import rows: {exc}"
        db.commit()
        return {"total_rows": 0, "status": "failed"}

    record_call_import_batch_created(
        organization_id,
        call_import.id,
        workspace_id=workspace_id,
        total_rows=call_import.total_rows,
        source="csv",
        provider=call_import.provider,
    )
    _enqueue_row_tasks(db, call_import, [])

    logger.info(
        "Materialized {} call_import_rows for import {} (org={})",
        row_count,
        call_import.id,
        organization_id,
    )
    return {"total_rows": row_count, "status": "processing"}
