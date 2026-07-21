"""Bulk call-import operations (diarization enqueue, evaluation materialize, row delete).

Heavy work runs here so API handlers can return 202 quickly. Uses batched
blob/Redis/DB operations suitable for multi-thousand row imports.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional, Tuple
from uuid import UUID, uuid4

from loguru import logger
from sqlalchemy.orm import Session, load_only
from sqlalchemy import func

from app.db_sharding.sessions import is_sharding_enabled

from app.models.database import (
    CallImport,
    CallImportEvaluation,
    CallImportEvaluationRow,
    CallImportRow,
)
from app.models.enums import CallImportRowStatus, CallImportStatus
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
    CallImportRow.recording_url,
    CallImportRow.status,
    CallImportRow.diarised_transcript,
    CallImportRow.diarised_transcript_status,
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
    from app.db_sharding.scatter_gather import load_call_import_rows_for_transcription

    rows = load_call_import_rows_for_transcription(
        db,
        call_import.id,
        requested_row_ids=requested_row_ids,
    )

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
    """Store Redis params, then mark rows pending so dispatch never races ahead."""
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
    stored_set = set(stored_ids)
    failed_set = set(failed_ids)

    updates: List[dict] = []
    queued = 0
    for row in rows:
        if row.id in stored_set:
            updates.append(
                {
                    "id": row.id,
                    "row_index": row.row_index,
                    "diarised_transcript_status": "pending",
                    "diarised_transcript_error": None,
                    "celery_task_id": None,
                }
            )
            queued += 1
        elif row.id in failed_set:
            updates.append(
                {
                    "id": row.id,
                    "row_index": row.row_index,
                    "diarised_transcript_status": "failed",
                    "diarised_transcript_error": _REDIS_PARAMS_STORE_ERROR,
                }
            )

    if updates:
        from app.db_sharding.row_ops import update_call_import_rows_on_shards

        update_call_import_rows_on_shards(db, call_import.id, updates)

    if queued > 0:
        schedule_fair_diarization_dispatch(max_workspace_turns=999)

    return BulkDiarizationResult(
        queued=queued,
        skipped_rows=sum(skip_counts.values()),
        skipped_reason_counts=skip_counts,
    )


def count_completed_source_rows(db: Session, call_import_id: UUID) -> int:
    from app.db_sharding.scatter_gather import count_completed_call_import_rows

    return count_completed_call_import_rows(db, call_import_id)


def _completed_source_row_ids(db: Session, call_import_id: UUID) -> List[UUID]:
    from app.db_sharding.scatter_gather import list_completed_source_row_ids_ordered

    return list_completed_source_row_ids_ordered(db, call_import_id)


def count_all_source_rows(db: Session, call_import_id: UUID) -> int:
    from app.db_sharding.scatter_gather import count_call_import_rows

    if is_sharding_enabled():
        return count_call_import_rows(db, call_import_id)
    from sqlalchemy import func

    return int(
        db.query(func.count(CallImportRow.id))
        .filter(CallImportRow.call_import_id == call_import_id)
        .scalar()
        or 0
    )


def _all_source_row_ids(db: Session, call_import_id: UUID) -> List[UUID]:
    from app.db_sharding.scatter_gather import list_source_row_ids_ordered

    if is_sharding_enabled():
        return list_source_row_ids_ordered(db, call_import_id)
    return [
        row_id
        for (row_id,) in (
            db.query(CallImportRow.id)
            .filter(CallImportRow.call_import_id == call_import_id)
            .order_by(CallImportRow.row_index.asc())
            .all()
        )
    ]


def bulk_insert_evaluation_rows(
    db: Session,
    call_import_id: UUID,
    evaluation_id: UUID,
    source_row_ids: List[UUID],
    *,
    workspace_id: UUID,
) -> None:
    """Insert eval-row stubs in chunks without per-row ORM overhead."""
    if not source_row_ids:
        return

    if is_sharding_enabled():
        from app.db_sharding.row_ops import bulk_insert_evaluation_rows_on_shards
        from app.db_sharding.scatter_gather import source_row_index_map

        index_by_id = source_row_index_map(db, call_import_id)
        bulk_insert_evaluation_rows_on_shards(
            db,
            call_import_id,
            evaluation_id,
            source_row_ids,
            workspace_id=workspace_id,
            index_by_source_id=index_by_id,
        )
        return

    for start in range(0, len(source_row_ids), _BULK_INSERT_CHUNK):
        chunk = source_row_ids[start : start + _BULK_INSERT_CHUNK]
        mappings = [
            {
                "id": uuid4(),
                "evaluation_id": evaluation_id,
                "call_import_row_id": source_row_id,
                "workspace_id": workspace_id,
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
    """Create eval-row records for every import row and start dispatch."""
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

    source_row_ids = _all_source_row_ids(db, evaluation.call_import_id)
    evaluation.total_rows = len(source_row_ids)

    if not source_row_ids:
        evaluation.status = "completed"
        db.commit()
        return

    bulk_insert_evaluation_rows(
        db,
        evaluation.call_import_id,
        evaluation_id,
        source_row_ids,
        workspace_id=evaluation.workspace_id,
    )
    db.commit()

    try:
        _enqueue_eval_rows_with_optional_transcribe(
            db,
            evaluation,
            [],
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

    from app.db_sharding.row_ops import delete_call_import_rows_on_shards
    from app.db_sharding.scatter_gather import load_call_import_rows_for_delete

    rows = load_call_import_rows_for_delete(db, call_import.id, row_ids)
    if not rows:
        return 0

    _revoke_pending_tasks(rows)
    _delete_s3_objects(organization_id, call_import.id, rows)

    deleted = delete_call_import_rows_on_shards(db, call_import.id, rows)

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
                    "workspace_id": call_import.workspace_id,
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
        from app.db_sharding.row_ops import bulk_insert_mappings_on_shards

        bulk_insert_mappings_on_shards(
            db,
            call_import.id,
            mappings,
        )
    db.flush()
    return len(parsed_rows)


def execute_call_import_materialization(
    db: Session,
    call_import_id: UUID,
    organization_id: UUID,
    workspace_id: UUID,
    *,
    schedule_import_dispatch: bool = False,
) -> dict:
    """Download staged source, parse, bulk-insert rows.

    When ``schedule_import_dispatch`` is true, legacy standalone import
    fair-dispatch is scheduled. New batches use the unified eval pipeline
    only (``schedule_import_dispatch=False``).
    """
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
        if not is_sharding_enabled()
        else None
    )
    if existing_rows is not None or (
        is_sharding_enabled() and int(call_import.total_rows or 0) > 0
    ):
        logger.info(
            "execute_call_import_materialization: import {} already has rows",
            call_import_id,
        )
        if schedule_import_dispatch:
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
        from app.db_sharding.row_ops import register_shard_slices

        register_shard_slices(db, call_import.id, row_count)
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
    if schedule_import_dispatch:
        _enqueue_row_tasks(db, call_import, [])

    logger.info(
        "Materialized {} call_import_rows for import {} (org={})",
        row_count,
        call_import.id,
        organization_id,
    )
    return {"total_rows": row_count, "status": "processing"}


def _aggregate_import_row_status_counts(
    db: Session,
    call_import_id: UUID,
) -> tuple[int, int, int, int, int]:
    """Return total, completed, failed, pending, processing via SQL aggregate."""
    if is_sharding_enabled():
        from app.db_sharding.pool_manager import db_pool_manager
        from app.db_sharding.scatter_gather import shard_ids_for_import

        total = completed = failed = pending = processing = 0
        for shard_id in shard_ids_for_import(db, call_import_id):
            factory = db_pool_manager.shard_session_factory(shard_id)
            shard_db = factory()
            try:
                row = (
                    shard_db.query(
                        func.count(CallImportRow.id),
                        func.count().filter(
                            CallImportRow.status == CallImportRowStatus.COMPLETED
                        ),
                        func.count().filter(
                            CallImportRow.status == CallImportRowStatus.FAILED
                        ),
                        func.count().filter(
                            CallImportRow.status == CallImportRowStatus.PENDING
                        ),
                        func.count().filter(
                            CallImportRow.status == CallImportRowStatus.PROCESSING
                        ),
                    )
                    .filter(CallImportRow.call_import_id == call_import_id)
                    .one()
                )
                total += int(row[0] or 0)
                completed += int(row[1] or 0)
                failed += int(row[2] or 0)
                pending += int(row[3] or 0)
                processing += int(row[4] or 0)
            finally:
                shard_db.close()
        if total == 0:
            row = (
                db.query(
                    func.count(CallImportRow.id),
                    func.count().filter(
                        CallImportRow.status == CallImportRowStatus.COMPLETED
                    ),
                    func.count().filter(
                        CallImportRow.status == CallImportRowStatus.FAILED
                    ),
                    func.count().filter(
                        CallImportRow.status == CallImportRowStatus.PENDING
                    ),
                    func.count().filter(
                        CallImportRow.status == CallImportRowStatus.PROCESSING
                    ),
                )
                .filter(CallImportRow.call_import_id == call_import_id)
                .one()
            )
            total = int(row[0] or 0)
            if total > 0:
                return (
                    total,
                    int(row[1] or 0),
                    int(row[2] or 0),
                    int(row[3] or 0),
                    int(row[4] or 0),
                )
        return total, completed, failed, pending, processing

    row = (
        db.query(
            func.count(CallImportRow.id),
            func.count().filter(
                CallImportRow.status == CallImportRowStatus.COMPLETED
            ),
            func.count().filter(CallImportRow.status == CallImportRowStatus.FAILED),
            func.count().filter(CallImportRow.status == CallImportRowStatus.PENDING),
            func.count().filter(
                CallImportRow.status == CallImportRowStatus.PROCESSING
            ),
        )
        .filter(CallImportRow.call_import_id == call_import_id)
        .one()
    )
    return (
        int(row[0] or 0),
        int(row[1] or 0),
        int(row[2] or 0),
        int(row[3] or 0),
        int(row[4] or 0),
    )


def rollup_call_import_batch_status(db: Session, call_import: CallImport) -> None:
    """Recompute batch counters and terminal status on the parent import.

    Eval-primary batches (materialized via Run Evaluation) can leave thousands
    of ``pending`` import rows when an evaluation is cancelled early. Those
    rows were never enqueued on the legacy import worker and must not keep the
    parent stuck in ``processing`` once every evaluation run is terminal.
    """

    total, completed, failed, pending, processing = _aggregate_import_row_status_counts(
        db, call_import.id
    )
    pending_or_processing = pending + processing

    call_import.total_rows = total
    call_import.completed_rows = completed
    call_import.failed_rows = failed

    if call_import.status == CallImportStatus.DELETING:
        return

    active_eval = (
        db.query(CallImportEvaluation.id)
        .filter(
            CallImportEvaluation.call_import_id == call_import.id,
            CallImportEvaluation.status.in_(("pending", "running")),
        )
        .first()
    )

    import_pipeline_active = processing > 0 or (
        pending > 0 and active_eval is not None
    )
    if import_pipeline_active:
        call_import.status = CallImportStatus.PROCESSING
        return

    if pending_or_processing > 0:
        has_evaluations = (
            db.query(CallImportEvaluation.id)
            .filter(CallImportEvaluation.call_import_id == call_import.id)
            .first()
            is not None
        )
        if has_evaluations:
            if failed == 0 and completed == 0:
                call_import.status = CallImportStatus.FAILED
            else:
                call_import.status = CallImportStatus.PARTIAL
        else:
            call_import.status = CallImportStatus.PROCESSING
        return

    if total == 0:
        return
    if failed == 0:
        call_import.status = CallImportStatus.COMPLETED
    elif completed == 0:
        call_import.status = CallImportStatus.FAILED
    else:
        call_import.status = CallImportStatus.PARTIAL

    from app.services.call_imports.progress_counters import clear_import_progress_redis

    clear_import_progress_redis(call_import.id)


_EVAL_CANCEL_COLUMNS = (
    CallImportEvaluationRow.id,
    CallImportEvaluationRow.status,
    CallImportEvaluationRow.celery_task_id,
)


def count_evaluation_cancel_targets(
    db: Session,
    evaluation_id: UUID,
    *,
    mode: Literal["abort", "force_fail_pending"],
) -> int:
    """Count rows eligible for bulk cancel without loading full ORM objects."""
    if is_sharding_enabled():
        from app.db_sharding.scatter_gather import count_evaluation_cancel_targets_sharded

        return count_evaluation_cancel_targets_sharded(
            db,
            evaluation_id,
            pending_only=(mode == "force_fail_pending"),
            in_progress_only=(mode == "abort"),
        )
    from sqlalchemy import func

    query = db.query(func.count(CallImportEvaluationRow.id)).filter(
        CallImportEvaluationRow.evaluation_id == evaluation_id
    )
    if mode == "abort":
        query = query.filter(
            CallImportEvaluationRow.status.in_(("pending", "running"))
        )
    else:
        query = query.filter(CallImportEvaluationRow.status == "pending")
    return int(query.scalar() or 0)


def _batch_revoke_celery_task_ids(
    task_ids: List[str],
    *,
    terminate: bool,
) -> int:
    """Revoke Celery tasks in batches; best-effort on control-plane errors."""
    cleaned = [tid for tid in task_ids if (tid or "").strip()]
    if not cleaned:
        return 0
    try:
        from app.workers.celery_app import celery_app

        revoked = 0
        for start in range(0, len(cleaned), _REVOKE_TASK_BATCH):
            chunk = cleaned[start : start + _REVOKE_TASK_BATCH]
            if terminate:
                celery_app.control.revoke(
                    chunk, terminate=True, signal="SIGTERM"
                )
            else:
                celery_app.control.revoke(chunk, terminate=False)
            revoked += len(chunk)
        return revoked
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to batch-revoke {} Celery tasks: {}", len(cleaned), exc)
        return 0


def execute_evaluation_cancel(
    db: Session,
    evaluation_id: UUID,
    *,
    mode: Literal["abort", "force_fail_pending"],
) -> dict:
    """Cancel eval rows in chunks off the API thread."""
    from app.api.v1.routes.call_import_evaluations import _rollup_evaluation_status

    evaluation = (
        db.query(CallImportEvaluation)
        .filter(CallImportEvaluation.id == evaluation_id)
        .first()
    )
    if evaluation is None:
        logger.warning(
            "execute_evaluation_cancel: evaluation {} not found",
            evaluation_id,
        )
        return {"evaluation_id": str(evaluation_id), "cancelled": 0, "mode": mode}

    try:
        cancelled_total = 0
        if is_sharding_enabled():
            cancelled_total = _cancel_evaluation_rows_all_shards(
                evaluation_id,
                mode=mode,
            )
        else:
            cancelled_total = _cancel_evaluation_rows_on_session(
                db,
                evaluation_id,
                mode=mode,
            )

        db.refresh(evaluation)
        _rollup_evaluation_status(evaluation, db)
        db.commit()

        return {
            "evaluation_id": str(evaluation_id),
            "cancelled": cancelled_total,
            "mode": mode,
        }
    finally:
        from app.services.call_imports.evaluation_bulk_op import (
            clear_evaluation_bulk_operation,
        )

        clear_evaluation_bulk_operation(evaluation_id)


def _cancel_evaluation_rows_on_session(
    db: Session,
    evaluation_id: UUID,
    *,
    mode: Literal["abort", "force_fail_pending"],
) -> int:
    from app.api.v1.routes.call_import_evaluations import EVAL_CANCELLED_BY_USER_ERROR

    cancelled_total = 0
    while True:
        query = (
            db.query(CallImportEvaluationRow)
            .options(load_only(*_EVAL_CANCEL_COLUMNS))
            .filter(CallImportEvaluationRow.evaluation_id == evaluation_id)
        )
        if mode == "abort":
            query = query.filter(
                CallImportEvaluationRow.status.in_(("pending", "running"))
            )
        else:
            query = query.filter(CallImportEvaluationRow.status == "pending")

        rows = (
            query.order_by(CallImportEvaluationRow.id.asc())
            .limit(_BULK_INSERT_CHUNK)
            .all()
        )
        if not rows:
            break

        task_ids: List[str] = []
        now = datetime.now(timezone.utc)
        for row in rows:
            task_id = (row.celery_task_id or "").strip()
            if task_id:
                task_ids.append(task_id)
            row.status = "failed"
            row.error_message = EVAL_CANCELLED_BY_USER_ERROR
            row.finished_at = now
            row.celery_task_id = None
            cancelled_total += 1

        _batch_revoke_celery_task_ids(task_ids, terminate=True)
        db.commit()
    return cancelled_total


def _cancel_evaluation_rows_all_shards(
    evaluation_id: UUID,
    *,
    mode: Literal["abort", "force_fail_pending"],
) -> int:
    from app.db_sharding.pool_manager import db_pool_manager

    router = db_pool_manager.router
    assert router is not None
    total = 0
    for shard_id in router.shard_ids:
        factory = db_pool_manager.shard_session_factory(shard_id)
        shard_db = factory()
        try:
            total += _cancel_evaluation_rows_on_session(
                shard_db,
                evaluation_id,
                mode=mode,
            )
        finally:
            shard_db.close()
    return total


def _persist_evaluation_retry_targets(
    catalog_db: Session,
    evaluation: CallImportEvaluation,
    targets: List[Tuple[CallImportEvaluationRow, CallImportRow]],
    *,
    metric_ids: Optional[List[UUID]] = None,
    transcribe_overwrite: bool = False,
) -> None:
    """Apply retry resets on the correct DB session (per shard when sharding)."""
    from collections import defaultdict

    from sqlalchemy.orm.attributes import flag_modified

    from app.api.v1.routes.call_import_evaluations import (
        _prepare_source_row_for_retry,
        _reset_eval_row_for_retry,
    )
    from app.db_sharding.pool_manager import db_pool_manager
    from app.db_sharding.row_ops import shard_id_for_row

    task_ids: List[str] = []
    for eval_row, _source_row in targets:
        if eval_row.celery_task_id and eval_row.status in {"pending", "running"}:
            task_id = (eval_row.celery_task_id or "").strip()
            if task_id:
                task_ids.append(task_id)
    _batch_revoke_celery_task_ids(task_ids, terminate=False)

    if not is_sharding_enabled():
        for eval_row, source_row in targets:
            _prepare_source_row_for_retry(
                source_row,
                transcribe_overwrite=transcribe_overwrite,
            )
            _reset_eval_row_for_retry(
                eval_row,
                metric_ids=metric_ids,
                skip_revoke=True,
            )
        catalog_db.commit()
        return

    by_shard: dict[str, List[Tuple[UUID, UUID]]] = defaultdict(list)
    for eval_row, source_row in targets:
        shard_id = shard_id_for_row(
            catalog_db,
            evaluation.call_import_id,
            int(source_row.row_index or 0),
        )
        by_shard[shard_id].append((eval_row.id, source_row.id))

    router = db_pool_manager.router
    assert router is not None
    for shard_id, id_pairs in by_shard.items():
        factory = db_pool_manager.shard_session_factory(shard_id)
        shard_db = factory()
        try:
            eval_row_ids = [pair[0] for pair in id_pairs]
            source_row_ids = [pair[1] for pair in id_pairs]
            eval_by_id = {
                row.id: row
                for row in shard_db.query(CallImportEvaluationRow)
                .filter(CallImportEvaluationRow.id.in_(eval_row_ids))
                .all()
            }
            source_by_id = {
                row.id: row
                for row in shard_db.query(CallImportRow)
                .filter(CallImportRow.id.in_(source_row_ids))
                .all()
            }
            for eval_row_id, source_row_id in id_pairs:
                bound_eval = eval_by_id.get(eval_row_id)
                bound_source = source_by_id.get(source_row_id)
                if bound_eval is None or bound_source is None:
                    continue
                _prepare_source_row_for_retry(
                    bound_source,
                    transcribe_overwrite=transcribe_overwrite,
                )
                _reset_eval_row_for_retry(
                    bound_eval,
                    metric_ids=metric_ids,
                    skip_revoke=True,
                )
                if metric_ids:
                    flag_modified(bound_eval, "metric_scores")
            shard_db.commit()
        except Exception:
            shard_db.rollback()
            raise
        finally:
            shard_db.close()


def execute_evaluation_retry(
    db: Session,
    evaluation_id: UUID,
    *,
    eval_row_ids: Optional[List[UUID]] = None,
    metric_ids: Optional[List[UUID]] = None,
    include_completed: bool = False,
    transcribe_overwrite: bool = False,
) -> dict:
    """Reset failed eval rows in chunks and start throttled dispatch."""
    from app.api.v1.routes.call_import_evaluations import (
        _enqueue_eval_rows_with_optional_transcribe,
        _gather_retry_targets,
        _prepare_source_row_for_retry,
        _reset_eval_row_for_retry,
        _rollup_evaluation_status,
    )

    evaluation = (
        db.query(CallImportEvaluation)
        .filter(CallImportEvaluation.id == evaluation_id)
        .first()
    )
    if evaluation is None:
        logger.warning(
            "execute_evaluation_retry: evaluation {} not found",
            evaluation_id,
        )
        return {"evaluation_id": str(evaluation_id), "requeued": 0}

    try:
        targets, skipped = _gather_retry_targets(
            db,
            evaluation,
            eval_row_ids,
            include_completed=include_completed,
        )
        if not targets:
            return {
                "evaluation_id": str(evaluation_id),
                "requeued": 0,
                "skipped": len(skipped),
            }

        for start in range(0, len(targets), _BULK_INSERT_CHUNK):
            chunk = targets[start : start + _BULK_INSERT_CHUNK]
            _persist_evaluation_retry_targets(
                db,
                evaluation,
                chunk,
                metric_ids=metric_ids,
                transcribe_overwrite=transcribe_overwrite,
            )

        try:
            evaluate_only, transcribe_chain = (
                _enqueue_eval_rows_with_optional_transcribe(
                    db,
                    evaluation,
                    targets,
                    transcribe_overwrite=transcribe_overwrite,
                    restricted_metric_ids=metric_ids,
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "Failed to re-enqueue evaluation {} after retry reset",
                evaluation_id,
            )
            err_msg = f"Failed to re-enqueue retry: {exc}"
            target_ids = {eval_row.id for eval_row, _ in targets}
            if is_sharding_enabled():
                from app.db_sharding.eval_rows import foreach_evaluation_row_mutating

                def _mark_failed(row: CallImportEvaluationRow) -> bool:
                    if row.id not in target_ids:
                        return False
                    row.status = "failed"
                    row.error_message = err_msg
                    return True

                foreach_evaluation_row_mutating(db, evaluation_id, _mark_failed)
            else:
                for eval_row, _ in targets:
                    if eval_row.id in target_ids:
                        eval_row.status = "failed"
                        eval_row.error_message = err_msg
                db.commit()
            _rollup_evaluation_status(evaluation, db)
            db.commit()
            return {
                "evaluation_id": str(evaluation_id),
                "requeued": 0,
                "error": str(exc),
            }

        evaluation.error_message = None
        evaluation.finished_at = None
        _rollup_evaluation_status(evaluation, db)
        db.commit()
        return {
            "evaluation_id": str(evaluation_id),
            "requeued": evaluate_only + transcribe_chain,
            "transcribe_requeued": transcribe_chain,
            "skipped": len(skipped),
        }
    finally:
        from app.services.call_imports.evaluation_bulk_op import (
            clear_evaluation_bulk_operation,
        )

        clear_evaluation_bulk_operation(evaluation_id)
