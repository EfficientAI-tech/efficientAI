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
from fastapi import HTTPException
from sqlalchemy.orm import Session, load_only
from sqlalchemy import func, update

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


def count_source_rows_with_production_transcript(
    db: Session, call_import_id: UUID
) -> int:
    from app.db_sharding.scatter_gather import (
        count_call_import_rows_with_production_transcript,
    )

    return count_call_import_rows_with_production_transcript(db, call_import_id)


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


def _source_row_ids_with_production_transcript(
    db: Session, call_import_id: UUID
) -> List[UUID]:
    from app.db_sharding.scatter_gather import (
        list_source_row_ids_with_production_transcript,
    )

    return list_source_row_ids_with_production_transcript(db, call_import_id)


def _source_row_ids_for_evaluation(
    db: Session, evaluation: CallImportEvaluation
) -> List[UUID]:
    """Row ids to materialize for this evaluation's transcript source."""
    source = (evaluation.transcript_source or "diarised").strip().lower()
    if source == "production":
        return _source_row_ids_with_production_transcript(
            db, evaluation.call_import_id
        )
    return _all_source_row_ids(db, evaluation.call_import_id)


def bulk_insert_evaluation_rows(
    db: Session,
    call_import_id: UUID,
    evaluation_id: UUID,
    source_row_ids: List[UUID],
    *,
    workspace_id: UUID,
    shard_sessions=None,
) -> tuple[int, List[Session]]:
    """Insert eval-row stubs in chunks without per-row ORM overhead.

    When ``shard_sessions`` is set, each chunk is committed on the reused
    shard session. Otherwise sharded inserts stay deferred until the caller
    commits the pending sessions.
    """
    if not source_row_ids:
        return 0, []

    if is_sharding_enabled():
        from app.db_sharding.row_ops import bulk_insert_evaluation_rows_on_shards
        from app.db_sharding.scatter_gather import source_row_index_map

        index_by_id = source_row_index_map(db, call_import_id)
        return bulk_insert_evaluation_rows_on_shards(
            db,
            call_import_id,
            evaluation_id,
            source_row_ids,
            workspace_id=workspace_id,
            index_by_source_id=index_by_id,
            defer_commit=shard_sessions is None,
            shard_sessions=shard_sessions,
        )

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
    return len(source_row_ids), []


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

    source_row_ids = _source_row_ids_for_evaluation(db, evaluation)

    if not source_row_ids:
        evaluation.total_rows = 0
        evaluation.status = "completed"
        db.commit()
        return

    from app.db_sharding.row_ops import ShardWriteSessions

    shard_sessions = ShardWriteSessions() if is_sharding_enabled() else None
    committed = 0
    try:
        committed, pending_shard_sessions = bulk_insert_evaluation_rows(
            db,
            evaluation.call_import_id,
            evaluation_id,
            source_row_ids,
            workspace_id=evaluation.workspace_id,
            shard_sessions=shard_sessions,
        )
        if pending_shard_sessions:
            from app.db_sharding.row_ops import commit_pending_shard_sessions

            db.commit()
            commit_pending_shard_sessions(pending_shard_sessions)
        evaluation.total_rows = committed
        db.commit()
    except Exception as exc:
        committed = getattr(exc, "committed", committed)
        if shard_sessions is not None:
            shard_sessions.rollback_open()
        db.rollback()
        evaluation.total_rows = committed
        evaluation.status = "failed"
        cause = getattr(exc, "cause", exc)
        evaluation.error_message = f"Failed to materialize evaluation rows: {cause}"
        db.commit()
        raise
    finally:
        if shard_sessions is not None:
            shard_sessions.close_all()

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


def _release_platform_import_work(db: Session, call_import: CallImport) -> None:
    from app.db_sharding.pool_manager import db_pool_manager
    from app.db_sharding.sessions import is_sharding_enabled
    from app.models.database import CallImportDiscoverySlice, CallImportRow
    from app.workers.concurrency.platform_import_limits import (
        force_release_slice_lock,
        release_platform_lease,
    )

    slices = (
        db.query(CallImportDiscoverySlice)
        .filter(CallImportDiscoverySlice.call_import_id == call_import.id)
        .all()
    )
    for slice_row in slices:
        force_release_slice_lock(call_import.id, slice_row.slice_id)

    def _release_ids(session: Session) -> None:
        task_ids = [
            task_id
            for (task_id,) in session.query(CallImportRow.celery_task_id)
            .filter(
                CallImportRow.call_import_id == call_import.id,
                CallImportRow.celery_task_id.isnot(None),
            )
            .all()
            if task_id
        ]
        for task_id in task_ids:
            release_platform_lease(task_id)

    if not is_sharding_enabled():
        _release_ids(db)
        return
    router = db_pool_manager.router
    if router is None:
        return
    for shard_id in router.shard_ids:
        factory = db_pool_manager.shard_session_factory(shard_id)
        shard_db = factory()
        try:
            _release_ids(shard_db)
        finally:
            shard_db.close()


def _delete_import_rows_everywhere(db: Session, call_import_id: UUID) -> None:
    from app.db_sharding.pool_manager import db_pool_manager
    from app.db_sharding.sessions import is_sharding_enabled
    from app.models.database import CallImportEvaluationRow, CallImportRow

    def _wipe(session: Session) -> None:
        row_ids = [
            row_id
            for (row_id,) in session.query(CallImportRow.id)
            .filter(CallImportRow.call_import_id == call_import_id)
            .all()
        ]
        if row_ids:
            session.query(CallImportEvaluationRow).filter(
                CallImportEvaluationRow.call_import_row_id.in_(row_ids)
            ).delete(synchronize_session=False)
        session.query(CallImportRow).filter(
            CallImportRow.call_import_id == call_import_id
        ).delete(synchronize_session=False)
        session.commit()

    if not is_sharding_enabled():
        _wipe(db)
        return
    router = db_pool_manager.router
    if router is None:
        return
    for shard_id in router.shard_ids:
        factory = db_pool_manager.shard_session_factory(shard_id)
        shard_db = factory()
        try:
            _wipe(shard_db)
        except Exception:
            shard_db.rollback()
            raise
        finally:
            shard_db.close()


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
    _release_platform_import_work(db, call_import)
    _delete_import_rows_everywhere(db, call_import_id)

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
    *,
    defer_shard_commit: bool = False,
    shard_sessions=None,
) -> tuple[int, List[Session]]:
    """Insert import rows in chunks without per-row ORM overhead.

    When ``shard_sessions`` is set, each chunk commits on the reused shard
    session. ``ShardChunkWriteError.committed`` is the count already saved.
    """
    from app.api.v1.routes.call_imports import _parse_recording_date_cell
    from app.db_sharding.row_ops import ShardChunkWriteError, bulk_insert_mappings_on_shards

    if not parsed_rows:
        return 0, []

    pending: List[Session] = []
    committed = 0
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
        try:
            inserted, shard_pending = bulk_insert_mappings_on_shards(
                db,
                call_import.id,
                mappings,
                defer_commit=defer_shard_commit and shard_sessions is None,
                shard_sessions=shard_sessions,
            )
        except ShardChunkWriteError as exc:
            raise ShardChunkWriteError(committed + exc.committed, exc.cause) from exc
        except Exception as exc:
            if shard_sessions is not None:
                raise ShardChunkWriteError(committed, exc) from exc
            raise
        committed += inserted
        pending.extend(shard_pending)
    db.flush()
    return committed, pending


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
        parse_skips_to_json,
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
        stored_rows = int(call_import.total_rows or 0)
        return {
            "total_rows": stored_rows if call_import.status == CallImportStatus.FAILED else 0,
            "status": call_import.status.value,
        }

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
        if call_import.status == CallImportStatus.FAILED:
            return {
                "total_rows": int(call_import.total_rows or 0),
                "status": "failed",
            }
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
        logger.info(
            "execute_call_import_materialization downloading staged source "
            "(call_import={} key={})",
            call_import_id,
            call_import.source_s3_key,
        )
        file_bytes = s3_service.download_file_by_key(call_import.source_s3_key)
        logger.info(
            "execute_call_import_materialization downloaded {} bytes "
            "(call_import={})",
            len(file_bytes),
            call_import_id,
        )
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
    try:
        parse_result = _parse_source_file(
            file_bytes,
            call_import.source_format,
            call_import.sheet_name,
            parameters,
            dict(call_import.parameter_mapping or {}),
            cleaned_skipped,
        )
    except HTTPException as exc:
        call_import.status = CallImportStatus.FAILED
        call_import.error_message = (
            exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        )
        call_import.source_row_skips = []
        db.commit()
        return {"total_rows": 0, "status": "failed"}

    call_import.source_row_skips = parse_skips_to_json(parse_result.skipped)
    skipped_count = len(parse_result.skipped)

    if not parse_result.rows:
        if parse_result.skipped:
            call_import.error_message = (
                f"No importable rows. {skipped_count} row(s) skipped due "
                "to missing or invalid conversation ID or recording URL."
            )
        else:
            call_import.error_message = "Source file did not contain any data rows."
        call_import.status = CallImportStatus.FAILED
        call_import.total_rows = 0
        db.commit()
        return {
            "total_rows": 0,
            "status": "failed",
            "source_rows_skipped": skipped_count,
        }

    call_import.completed_rows = 0
    call_import.failed_rows = 0

    row_count = len(parse_result.rows)
    committed_rows = 0
    shard_sessions = None
    try:
        if is_sharding_enabled():
            from app.db_sharding.row_ops import ShardWriteSessions, register_shard_slices

            register_shard_slices(db, call_import.id, row_count)
            db.commit()
            shard_sessions = ShardWriteSessions()
            committed_rows, _pending = bulk_materialize_call_import_rows(
                db,
                call_import,
                parse_result.rows,
                organization_id,
                shard_sessions=shard_sessions,
            )
            call_import.total_rows = committed_rows
            db.commit()
        else:
            from app.db_sharding.row_ops import register_shard_slices

            call_import.total_rows = row_count
            committed_rows, _pending = bulk_materialize_call_import_rows(
                db,
                call_import,
                parse_result.rows,
                organization_id,
            )
            register_shard_slices(db, call_import.id, row_count)
            db.commit()
    except Exception as exc:  # noqa: BLE001
        committed_rows = getattr(exc, "committed", committed_rows)
        if shard_sessions is not None:
            shard_sessions.rollback_open()
        db.rollback()
        logger.exception(
            "Failed to materialize rows for call import {}",
            call_import_id,
        )
        cause = getattr(exc, "cause", exc)
        call_import.status = CallImportStatus.FAILED
        call_import.total_rows = committed_rows
        call_import.error_message = f"Failed to materialize import rows: {cause}"
        db.commit()
        return {
            "total_rows": committed_rows,
            "status": "failed",
            "source_rows_skipped": skipped_count,
        }
    finally:
        if shard_sessions is not None:
            shard_sessions.close_all()

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
    return {
        "total_rows": committed_rows,
        "status": "processing",
        "source_rows_skipped": skipped_count,
    }


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


def _call_import_status_from_evaluation_status(eval_status: str) -> CallImportStatus:
    """Map a terminal evaluation run status onto batch status."""
    normalized = (eval_status or "").strip().lower()
    if normalized == "completed":
        return CallImportStatus.COMPLETED
    if normalized == "partial":
        return CallImportStatus.PARTIAL
    if normalized in ("failed", "cancelled"):
        return CallImportStatus.FAILED
    if normalized in ("pending", "running"):
        return CallImportStatus.PROCESSING
    return CallImportStatus.PROCESSING


def _latest_evaluation_status(db: Session, call_import_id: UUID) -> Optional[str]:
    row = (
        db.query(CallImportEvaluation.status)
        .filter(CallImportEvaluation.call_import_id == call_import_id)
        .order_by(CallImportEvaluation.created_at.desc())
        .first()
    )
    return row[0] if row else None


def _latest_evaluation_progress_for_ui(
    db: Session, call_import_id: UUID
) -> dict[str, object]:
    """Most recent evaluation counters for list/detail progress bars."""
    from sqlalchemy.orm import load_only

    from app.services.call_imports.progress_counters import merge_eval_counters_for_ui

    row = (
        db.query(CallImportEvaluation)
        .options(
            load_only(
                CallImportEvaluation.id,
                CallImportEvaluation.status,
                CallImportEvaluation.transcript_source,
                CallImportEvaluation.total_rows,
                CallImportEvaluation.completed_rows,
                CallImportEvaluation.failed_rows,
            )
        )
        .filter(CallImportEvaluation.call_import_id == call_import_id)
        .order_by(CallImportEvaluation.created_at.desc())
        .first()
    )
    if row is None:
        return {
            "latest_evaluation_status": None,
            "latest_evaluation_transcript_source": None,
            "latest_evaluation_total_rows": None,
            "latest_evaluation_completed_rows": None,
            "latest_evaluation_failed_rows": None,
        }
    ui_completed_raw, ui_failed_raw = merge_eval_counters_for_ui(row)
    total = int(row.total_rows or 0)
    ui_completed = min(ui_completed_raw, total) if total else ui_completed_raw
    ui_failed = min(ui_failed_raw, total) if total else ui_failed_raw
    status = row.status
    if hasattr(status, "value"):
        status = status.value
    transcript_source = row.transcript_source
    return {
        "latest_evaluation_status": status,
        "latest_evaluation_transcript_source": transcript_source,
        "latest_evaluation_total_rows": total,
        "latest_evaluation_completed_rows": ui_completed,
        "latest_evaluation_failed_rows": ui_failed,
    }


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
                latest_eval_status = _latest_evaluation_status(db, call_import.id)
                if latest_eval_status is not None:
                    call_import.status = _call_import_status_from_evaluation_status(
                        latest_eval_status
                    )
                else:
                    call_import.status = CallImportStatus.FAILED
            else:
                call_import.status = CallImportStatus.PARTIAL
        else:
            call_import.status = CallImportStatus.PROCESSING
        return

    from app.services.call_imports.debounced_rollup import (
        platform_discovery_blocks_terminal_status,
    )

    if platform_discovery_blocks_terminal_status(call_import):
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


def cancel_eval_page_query(session: Session, evaluation_id: UUID, *, status: str):
    """One eval status page. No sort, no source join, no transcript columns."""
    return session.query(
        CallImportEvaluationRow.id,
        CallImportEvaluationRow.celery_task_id,
        CallImportEvaluationRow.call_import_row_id,
    ).filter(
        CallImportEvaluationRow.evaluation_id == evaluation_id,
        CallImportEvaluationRow.status == status,
    )


def cancel_inflight_diarisation_query(session: Session, source_ids: List[UUID]):
    """Task ids for source rows on this page that are still in diarisation."""
    return session.query(
        CallImportRow.id,
        CallImportRow.celery_task_id,
    ).filter(
        CallImportRow.id.in_(source_ids),
        CallImportRow.diarised_transcript_status.in_(("pending", "running")),
    )


def diarisation_sweep_page_query(
    session: Session,
    evaluation_id: UUID,
    call_import_id: UUID,
    *,
    status: str,
):
    """Leftover in-flight diarisation for one status. Transcript bodies stay out."""
    return (
        session.query(CallImportRow.id, CallImportRow.celery_task_id)
        .join(
            CallImportEvaluationRow,
            CallImportEvaluationRow.call_import_row_id == CallImportRow.id,
        )
        .filter(
            CallImportRow.call_import_id == call_import_id,
            CallImportRow.diarised_transcript_status == status,
            CallImportEvaluationRow.evaluation_id == evaluation_id,
        )
    )


def _count_inflight_diarisation_on_session(
    session: Session,
    evaluation_id: UUID,
    call_import_id: UUID,
) -> int:
    query = session.query(func.count(CallImportRow.id)).join(
        CallImportEvaluationRow,
        CallImportEvaluationRow.call_import_row_id == CallImportRow.id,
    ).filter(
        CallImportRow.call_import_id == call_import_id,
        CallImportEvaluationRow.evaluation_id == evaluation_id,
        CallImportRow.diarised_transcript_status.in_(("pending", "running")),
    )
    return int(query.scalar() or 0)


def count_inflight_diarisation_for_evaluation(
    db: Session,
    evaluation_id: UUID,
    call_import_id: UUID,
) -> int:
    """Count in-flight diarisation rows for this run without loading bodies."""
    if not is_sharding_enabled():
        return _count_inflight_diarisation_on_session(
            db, evaluation_id, call_import_id
        )
    from app.db_sharding.pool_manager import db_pool_manager

    router = db_pool_manager.router
    if router is None:
        return _count_inflight_diarisation_on_session(
            db, evaluation_id, call_import_id
        )
    total = 0
    for shard_id in router.shard_ids:
        factory = db_pool_manager.shard_session_factory(shard_id)
        shard_db = factory()
        try:
            total += _count_inflight_diarisation_on_session(
                shard_db, evaluation_id, call_import_id
            )
        finally:
            shard_db.close()
    return total


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

        if mode == "abort":
            _sweep_evaluation_diarisation_cancel(
                db,
                evaluation_id,
                evaluation.call_import_id,
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


def _append_task_ids(task_ids: List[str], seen: set, rows) -> None:
    for row in rows:
        task_id = row.celery_task_id if isinstance(row.celery_task_id, str) else ""
        task_id = task_id.strip()
        if task_id and task_id not in seen:
            seen.add(task_id)
            task_ids.append(task_id)


def _write_cancel_page(
    session: Session,
    eval_ids: List[UUID],
    *,
    status: str,
    source_ids: List[UUID],
    now: datetime,
) -> int:
    """One UPDATE per table for this page. Eval rowcount, or source rowcount when the page is diarisation-only."""
    from app.api.v1.routes.call_import_evaluations import EVAL_CANCELLED_BY_USER_ERROR
    from app.api.v1.routes.call_imports import CANCELLED_BY_USER_ERROR
    from app.db_sharding.row_ops import shard_row_write_context

    if not eval_ids and not source_ids:
        return 0
    updated = 0
    with shard_row_write_context(session):
        if eval_ids:
            result = session.execute(
                update(CallImportEvaluationRow)
                .where(
                    CallImportEvaluationRow.id.in_(eval_ids),
                    CallImportEvaluationRow.status == status,
                )
                .values(
                    status="failed",
                    error_message=EVAL_CANCELLED_BY_USER_ERROR,
                    finished_at=now,
                    celery_task_id=None,
                ),
                execution_options={"synchronize_session": False},
            )
            updated = int(result.rowcount or 0)
            if updated < 0:
                updated = len(eval_ids)
        if source_ids:
            result = session.execute(
                update(CallImportRow)
                .where(
                    CallImportRow.id.in_(source_ids),
                    CallImportRow.diarised_transcript_status.in_(
                        ("pending", "running")
                    ),
                )
                .values(
                    diarised_transcript_status="failed",
                    diarised_transcript_error=CANCELLED_BY_USER_ERROR,
                    celery_task_id=None,
                ),
                execution_options={"synchronize_session": False},
            )
            if not eval_ids:
                updated = int(result.rowcount or 0)
                if updated < 0:
                    updated = len(source_ids)
        session.commit()
    return updated


def _sweep_diarisation_on_session(
    session: Session,
    evaluation_id: UUID,
    call_import_id: UUID,
) -> int:
    """Page leftover in-flight diarisation. One status at a time, one UPDATE per page."""
    cancelled_total = 0
    for status in ("pending", "running"):
        previous_ids: Optional[set] = None
        while True:
            page = (
                diarisation_sweep_page_query(
                    session,
                    evaluation_id,
                    call_import_id,
                    status=status,
                )
                .limit(_BULK_INSERT_CHUNK)
                .all()
            )
            if not page:
                break
            page_ids = [row.id for row in page]
            page_id_set = set(page_ids)
            if previous_ids is not None and page_id_set == previous_ids:
                logger.warning(
                    "Diarisation cancel page for evaluation {} status {} made no progress",
                    evaluation_id,
                    status,
                )
                break
            previous_ids = page_id_set
            task_ids: List[str] = []
            _append_task_ids(task_ids, set(), page)
            updated = _write_cancel_page(
                session,
                [],
                status=status,
                source_ids=page_ids,
                now=datetime.now(timezone.utc),
            )
            _batch_revoke_celery_task_ids(task_ids, terminate=True)
            if updated == 0:
                logger.warning(
                    "Diarisation cancel page for evaluation {} status {} updated no rows",
                    evaluation_id,
                    status,
                )
                break
            cancelled_total += updated
    return cancelled_total


def _sweep_evaluation_diarisation_cancel(
    catalog_db: Session,
    evaluation_id: UUID,
    call_import_id: UUID,
) -> int:
    """Fail any remaining in-flight diarisation for rows in this evaluation run."""
    if is_sharding_enabled():
        from app.db_sharding.pool_manager import db_pool_manager

        router = db_pool_manager.router
        assert router is not None
        cancelled_total = 0
        for shard_id in router.shard_ids:
            factory = db_pool_manager.shard_session_factory(shard_id)
            shard_db = factory()
            try:
                cancelled_total += _sweep_diarisation_on_session(
                    shard_db,
                    evaluation_id,
                    call_import_id,
                )
            finally:
                shard_db.close()
        return cancelled_total

    return _sweep_diarisation_on_session(
        catalog_db,
        evaluation_id,
        call_import_id,
    )


def _cancel_evaluation_rows_on_session(
    db: Session,
    evaluation_id: UUID,
    *,
    mode: Literal["abort", "force_fail_pending"],
) -> int:
    statuses = ("pending", "running") if mode == "abort" else ("pending",)
    cascade_diarisation = mode == "abort"
    cancelled_total = 0
    for status in statuses:
        previous_ids: Optional[set] = None
        while True:
            page = (
                cancel_eval_page_query(db, evaluation_id, status=status)
                .limit(_BULK_INSERT_CHUNK)
                .all()
            )
            if not page:
                break
            page_ids = [row.id for row in page]
            page_id_set = set(page_ids)
            if previous_ids is not None and page_id_set == previous_ids:
                logger.warning(
                    "Cancel page for evaluation {} status {} made no progress",
                    evaluation_id,
                    status,
                )
                break
            previous_ids = page_id_set
            task_ids: List[str] = []
            seen_tasks: set = set()
            _append_task_ids(task_ids, seen_tasks, page)
            source_ids: List[UUID] = []
            if cascade_diarisation:
                source_rows = cancel_inflight_diarisation_query(
                    db,
                    [row.call_import_row_id for row in page],
                ).all()
                source_ids = [row.id for row in source_rows]
                _append_task_ids(task_ids, seen_tasks, source_rows)
            updated = _write_cancel_page(
                db,
                page_ids,
                status=status,
                source_ids=source_ids,
                now=datetime.now(timezone.utc),
            )
            _batch_revoke_celery_task_ids(task_ids, terminate=True)
            if updated == 0:
                logger.warning(
                    "Cancel page for evaluation {} status {} updated no rows",
                    evaluation_id,
                    status,
                )
                break
            cancelled_total += updated
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


def _session_is_postgresql(session: Session) -> bool:
    bind = session.get_bind()
    return bind is not None and getattr(getattr(bind, "dialect", None), "name", None) == "postgresql"


def _expunge_mapped(session: Session, objects) -> None:
    """Drop mapped rows from the identity map. Unmapped test doubles are ignored."""
    for obj in objects:
        state = getattr(obj, "_sa_instance_state", None)
        if state is not None and state.session is session:
            session.expunge(obj)


def _expunge_retry_page(
    session: Session,
    page: List[Tuple[CallImportEvaluationRow, Optional[CallImportRow]]],
) -> None:
    """Drop the page from the identity map so a 400k retry does not keep every row."""
    mapped = []
    for eval_row, source_row in page:
        mapped.append(eval_row)
        if source_row is not None:
            mapped.append(source_row)
    _expunge_mapped(session, mapped)


def _apply_source_retry_updates(
    session: Session,
    sources: List[CallImportRow],
    *,
    transcribe_overwrite: bool,
) -> None:
    """One UPDATE per distinct source change. Rows that need nothing are not written."""
    from app.api.v1.routes.call_import_evaluations import source_retry_assignments

    grouped: dict[tuple, List[UUID]] = {}
    templates: dict[tuple, dict] = {}
    for source_row in sources:
        changes = source_retry_assignments(
            source_row,
            transcribe_overwrite=transcribe_overwrite,
        )
        if not changes:
            continue
        key = tuple(sorted(changes.items(), key=lambda item: item[0]))
        grouped.setdefault(key, []).append(source_row.id)
        templates[key] = changes
    for key, row_ids in grouped.items():
        session.execute(
            update(CallImportRow)
            .where(CallImportRow.id.in_(row_ids))
            .values(**templates[key]),
            execution_options={"synchronize_session": False},
        )


def _apply_metric_score_resets(
    session: Session,
    page: List[Tuple[CallImportEvaluationRow, Optional[CallImportRow]]],
    metric_ids: List[UUID],
) -> None:
    """Write trimmed score documents. Postgres does this as one UPDATE per page."""
    from sqlalchemy import bindparam, text
    from sqlalchemy.dialects.postgresql import ARRAY, JSON, UUID as PG_UUID
    from sqlalchemy.orm.attributes import flag_modified

    from app.api.v1.routes.call_import_evaluations import _metric_scores_for_retry

    payloads = [
        (
            eval_row.id,
            _metric_scores_for_retry(eval_row.metric_scores, metric_ids),
        )
        for eval_row, _source_row in page
    ]
    if _session_is_postgresql(session):
        session.execute(
            text(
                """
                UPDATE call_import_evaluation_rows AS r
                SET status = 'pending',
                    error_message = NULL,
                    started_at = NULL,
                    finished_at = NULL,
                    celery_task_id = NULL,
                    metric_scores = data.scores
                FROM unnest(:ids, :scores) AS data(id, scores)
                WHERE r.id = data.id
                """
            ).bindparams(
                bindparam("ids", type_=ARRAY(PG_UUID(as_uuid=True))),
                bindparam("scores", type_=ARRAY(JSON())),
            ),
            {
                "ids": [row_id for row_id, _scores in payloads],
                "scores": [scores for _row_id, scores in payloads],
            },
        )
        return

    by_id = {eval_row.id: eval_row for eval_row, _source_row in page}
    for row_id, scores in payloads:
        eval_row = by_id[row_id]
        eval_row.status = "pending"
        eval_row.error_message = None
        eval_row.metric_scores = scores
        eval_row.started_at = None
        eval_row.finished_at = None
        eval_row.celery_task_id = None
        flag_modified(eval_row, "metric_scores")


def _write_retry_page(
    session: Session,
    page: List[Tuple[CallImportEvaluationRow, Optional[CallImportRow]]],
    *,
    metric_ids: Optional[List[UUID]] = None,
    transcribe_overwrite: bool = False,
) -> None:
    """Reset one page with bulk updates, then drop the objects from the session."""
    from app.db_sharding.row_ops import shard_row_write_context
    from app.workers.tasks.evaluate_call_import_row_audio import clear_eval_audio_chains

    if not page:
        return
    chain_ids = [
        str(eval_row.id)
        for eval_row, _source_row in page
        if (eval_row.celery_task_id or "").strip()
    ]
    sources = [source_row for _eval_row, source_row in page if source_row is not None]
    with shard_row_write_context(session):
        if metric_ids:
            _apply_metric_score_resets(session, page, metric_ids)
        else:
            eval_ids = [eval_row.id for eval_row, _source_row in page]
            session.execute(
                update(CallImportEvaluationRow)
                .where(CallImportEvaluationRow.id.in_(eval_ids))
                .values(
                    status="pending",
                    error_message=None,
                    metric_scores={},
                    started_at=None,
                    finished_at=None,
                    celery_task_id=None,
                ),
                execution_options={"synchronize_session": False},
            )
        _apply_source_retry_updates(
            session,
            sources,
            transcribe_overwrite=transcribe_overwrite,
        )
        clear_eval_audio_chains(chain_ids)
        session.commit()
    _expunge_retry_page(session, page)


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

    from app.db_sharding.pool_manager import db_pool_manager
    from app.db_sharding.row_ops import shard_id_for_row

    task_ids: List[str] = []
    for eval_row, _source_row in targets:
        if eval_row.celery_task_id and eval_row.status in {"pending", "running"}:
            task_id = (eval_row.celery_task_id or "").strip()
            if task_id:
                task_ids.append(task_id)
    _batch_revoke_celery_task_ids(task_ids, terminate=False)

    if not targets:
        return

    if not is_sharding_enabled():
        _write_retry_page(
            catalog_db,
            targets,
            metric_ids=metric_ids,
            transcribe_overwrite=transcribe_overwrite,
        )
        return

    by_shard: dict[str, List[Tuple[CallImportEvaluationRow, CallImportRow]]] = defaultdict(list)
    for eval_row, source_row in targets:
        shard_id = shard_id_for_row(
            catalog_db,
            evaluation.call_import_id,
            int(source_row.row_index or 0),
        )
        by_shard[shard_id].append((eval_row, source_row))

    router = db_pool_manager.router
    assert router is not None
    for shard_id, page in by_shard.items():
        factory = db_pool_manager.shard_session_factory(shard_id)
        shard_db = factory()
        try:
            _write_retry_page(
                shard_db,
                page,
                metric_ids=metric_ids,
                transcribe_overwrite=transcribe_overwrite,
            )
        except Exception:
            shard_db.rollback()
            raise
        finally:
            shard_db.close()


def _tally_retry_page(
    evaluation: CallImportEvaluation,
    page: List[Tuple[CallImportEvaluationRow, CallImportRow]],
    *,
    transcribe_overwrite: bool,
) -> Tuple[int, int]:
    from app.workers.concurrency.eval_dispatch import _needs_transcribe_for_eval

    eval_only = 0
    transcribe = 0
    for _eval_row, source_row in page:
        if _needs_transcribe_for_eval(
            evaluation,
            source_row,
            transcribe_overwrite=transcribe_overwrite,
        ):
            transcribe += 1
        else:
            eval_only += 1
    return eval_only, transcribe


def _mark_eval_rows_failed(
    catalog_db: Session,
    evaluation: CallImportEvaluation,
    groups: List[Tuple[Optional[str], List[UUID]]],
    message: str,
) -> None:
    """Set only the ids this retry reset back to failed."""
    from app.db_sharding.pool_manager import db_pool_manager
    from app.db_sharding.row_ops import shard_row_write_context

    for shard_id, row_ids in groups:
        if not row_ids:
            continue
        owned = False
        if shard_id is None:
            session = catalog_db
        else:
            session = db_pool_manager.shard_session_factory(shard_id)()
            owned = True
        try:
            with shard_row_write_context(session):
                for start in range(0, len(row_ids), _BULK_INSERT_CHUNK):
                    chunk = row_ids[start : start + _BULK_INSERT_CHUNK]
                    session.execute(
                        update(CallImportEvaluationRow)
                        .where(CallImportEvaluationRow.id.in_(chunk))
                        .values(status="failed", error_message=message),
                        execution_options={"synchronize_session": False},
                    )
                session.commit()
        finally:
            if owned:
                session.close()


def execute_evaluation_retry(
    db: Session,
    evaluation_id: UUID,
    *,
    eval_row_ids: Optional[List[UUID]] = None,
    metric_ids: Optional[List[UUID]] = None,
    include_completed: bool = False,
    transcribe_overwrite: bool = False,
) -> dict:
    """Page failed rows, bulk-reset them, then start throttled dispatch."""
    from app.api.v1.routes.call_import_evaluations import _rollup_evaluation_status
    from app.db_sharding.eval_rows import (
        RETRY_ROW_PAGE_SIZE,
        iter_evaluation_row_sessions,
        load_retry_target_page,
    )
    from app.workers.concurrency.fair_dispatch import (
        schedule_fair_dispatch,
        store_evaluation_transcribe_overwrite,
        store_rows_restricted_metrics,
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

    include = include_completed or bool(metric_ids)
    statuses = ["failed", "completed"] if include else ["failed"]
    restricted = [str(mid) for mid in metric_ids] if metric_ids else None
    eval_pk = evaluation.id
    import_id = evaluation.call_import_id
    eval_only = 0
    transcribe = 0
    scheduled_early = False
    seen: set[UUID] = set()
    orphans: List[UUID] = []
    shard_reset: List[UUID] = []
    reset_groups: List[Tuple[Optional[str], List[UUID]]] = []

    def _reset_loaded_page(session: Session, raw) -> str:
        """Reset one loaded page. Returns stop, continue, or empty."""
        nonlocal eval_only, transcribe, scheduled_early
        if not raw:
            return "empty"
        fresh = []
        repeated = True
        for eval_row, source_row in raw:
            if eval_row.id in seen:
                continue
            repeated = False
            seen.add(eval_row.id)
            if source_row is None:
                orphans.append(eval_row.id)
                continue
            fresh.append((eval_row, source_row))
        if repeated:
            logger.warning(
                "Retry page for evaluation {} made no progress",
                evaluation_id,
            )
            return "stop"
        if not fresh:
            if len(raw) < RETRY_ROW_PAGE_SIZE:
                return "stop"
            return "continue"
        page_ids = [eval_row.id for eval_row, _source_row in fresh]
        if restricted:
            stored = store_rows_restricted_metrics(page_ids, restricted)
            if stored is False:
                raise RuntimeError(
                    "Metric-subset retry did not store row markers; "
                    "leaving the page unchanged"
                )
        page_eval_only, page_transcribe = _tally_retry_page(
            evaluation,
            fresh,
            transcribe_overwrite=transcribe_overwrite,
        )
        _write_retry_page(
            session,
            fresh,
            metric_ids=metric_ids,
            transcribe_overwrite=transcribe_overwrite,
        )
        eval_only += page_eval_only
        transcribe += page_transcribe
        shard_reset.extend(page_ids)
        if not scheduled_early:
            schedule_fair_dispatch(max_workspace_turns=999)
            scheduled_early = True
        if len(raw) < RETRY_ROW_PAGE_SIZE:
            return "stop"
        return "continue"

    def _drain_session(session: Session, shard_id: Optional[str]) -> int:
        nonlocal seen, orphans, shard_reset
        seen = set()
        orphans = []
        shard_reset = []
        if eval_row_ids:
            for status in statuses:
                for start in range(0, len(eval_row_ids), RETRY_ROW_PAGE_SIZE):
                    chunk = eval_row_ids[start : start + RETRY_ROW_PAGE_SIZE]
                    raw = load_retry_target_page(
                        session,
                        eval_pk,
                        status=status,
                        row_ids=chunk,
                        include_metric_scores=bool(metric_ids),
                        ordered=False,
                        limit=len(chunk),
                    )
                    _reset_loaded_page(session, raw)
        else:
            for status in statuses:
                while True:
                    raw = load_retry_target_page(
                        session,
                        eval_pk,
                        status=status,
                        exclude_ids=orphans or None,
                        include_metric_scores=bool(metric_ids),
                        ordered=False,
                        limit=RETRY_ROW_PAGE_SIZE,
                    )
                    action = _reset_loaded_page(session, raw)
                    if action in {"empty", "stop"}:
                        break
        if shard_reset:
            reset_groups.append((shard_id, shard_reset))
        return len(shard_reset)

    try:
        saw_rows = 0
        for session, shard_id in iter_evaluation_row_sessions(db, import_id):
            saw_rows += _drain_session(session, shard_id)
        if is_sharding_enabled() and saw_rows == 0:
            _drain_session(db, None)

        requeued = eval_only + transcribe
        if requeued == 0:
            return {
                "evaluation_id": str(evaluation_id),
                "requeued": 0,
                "skipped": 0,
            }

        try:
            store_evaluation_transcribe_overwrite(
                evaluation.id,
                overwrite=transcribe_overwrite,
            )
            schedule_fair_dispatch(max_workspace_turns=999)
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "Failed to re-enqueue evaluation {} after retry reset",
                evaluation_id,
            )
            err_msg = f"Failed to re-enqueue retry: {exc}"
            _mark_eval_rows_failed(db, evaluation, reset_groups, err_msg)
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
            "requeued": requeued,
            "transcribe_requeued": transcribe,
            "skipped": 0,
        }
    finally:
        from app.services.call_imports.evaluation_bulk_op import (
            clear_evaluation_bulk_operation,
        )

        clear_evaluation_bulk_operation(evaluation_id)


_IMPORT_RETRY_COLUMNS = (
    CallImportRow.id,
    CallImportRow.status,
    CallImportRow.recording_s3_key,
    CallImportRow.celery_task_id,
    CallImportRow.attempts,
    CallImportRow.error_message,
)


def _stuck_pending_import_clause():
    from sqlalchemy import or_

    from app.api.v1.routes.call_imports import _STUCK_PENDING_ERROR_MARKERS

    return or_(
        CallImportRow.attempts > 0,
        *[
            CallImportRow.error_message.ilike(f"%{marker}%")
            for marker in _STUCK_PENDING_ERROR_MARKERS
        ],
    )


def import_failed_retry_query(session: Session, call_import_id: UUID):
    """Failed import rows only. Healthy pending rows are not in this scan."""
    return (
        session.query(CallImportRow)
        .options(load_only(*_IMPORT_RETRY_COLUMNS))
        .filter(
            CallImportRow.call_import_id == call_import_id,
            CallImportRow.status == CallImportRowStatus.FAILED,
        )
    )


def import_stuck_pending_retry_query(session: Session, call_import_id: UUID):
    """Pending rows that exhausted retries or hit a credential error."""
    return (
        session.query(CallImportRow)
        .options(load_only(*_IMPORT_RETRY_COLUMNS))
        .filter(
            CallImportRow.call_import_id == call_import_id,
            CallImportRow.status == CallImportRowStatus.PENDING,
            _stuck_pending_import_clause(),
        )
    )


def _reset_import_retry_page(session: Session, rows: List[CallImportRow]) -> None:
    from app.db_sharding.row_ops import shard_row_write_context

    if not rows:
        return
    row_ids = [row.id for row in rows]
    with shard_row_write_context(session):
        session.execute(
            update(CallImportRow)
            .where(CallImportRow.id.in_(row_ids))
            .values(
                status=CallImportRowStatus.PENDING,
                error_message=None,
                celery_task_id=None,
                attempts=0,
            ),
            execution_options={"synchronize_session": False},
        )
        session.commit()
    _expunge_mapped(session, rows)


def _drain_import_retry_session(session: Session, call_import_id: UUID) -> List[UUID]:
    from app.db_sharding.eval_rows import RETRY_ROW_PAGE_SIZE

    reset_ids: List[UUID] = []
    seen: set[UUID] = set()
    queries = (
        import_failed_retry_query,
        import_stuck_pending_retry_query,
    )
    for build_query in queries:
        while True:
            page = build_query(session, call_import_id).limit(RETRY_ROW_PAGE_SIZE).all()
            if not page:
                break
            fresh = [row for row in page if row.id not in seen]
            if not fresh:
                break
            fresh_ids = [row.id for row in fresh]
            seen.update(fresh_ids)
            _reset_import_retry_page(session, fresh)
            reset_ids.extend(fresh_ids)
            if len(page) < RETRY_ROW_PAGE_SIZE:
                break
    return reset_ids


def requeue_failed_import_rows(
    catalog_db: Session,
    call_import_id: UUID,
) -> List[UUID]:
    """Page failed and stuck-pending import rows and reset each page in one UPDATE."""
    from app.db_sharding.eval_rows import iter_evaluation_row_sessions

    reset_ids: List[UUID] = []
    for session, _shard_id in iter_evaluation_row_sessions(catalog_db, call_import_id):
        reset_ids.extend(_drain_import_retry_session(session, call_import_id))
    if is_sharding_enabled() and not reset_ids:
        reset_ids.extend(_drain_import_retry_session(catalog_db, call_import_id))
    return reset_ids


def mark_import_rows_enqueue_failed(
    catalog_db: Session,
    call_import_id: UUID,
    row_ids: List[UUID],
    message: str,
) -> Tuple[int, int]:
    """Return (enqueue_failed, skipped) after marking still-pending ids failed."""
    from app.db_sharding.eval_rows import iter_evaluation_row_sessions
    from app.db_sharding.row_ops import shard_row_write_context

    if not row_ids:
        return 0, 0
    from app.db_sharding.eval_rows import RETRY_ROW_PAGE_SIZE

    remaining = list(dict.fromkeys(row_ids))
    enqueue_failed = 0
    skipped = 0
    for session, _shard_id in iter_evaluation_row_sessions(catalog_db, call_import_id):
        if not remaining:
            break
        still_remaining: List[UUID] = []
        for start in range(0, len(remaining), RETRY_ROW_PAGE_SIZE):
            chunk = remaining[start : start + RETRY_ROW_PAGE_SIZE]
            rows = (
                session.query(CallImportRow.id, CallImportRow.status)
                .filter(CallImportRow.id.in_(chunk))
                .all()
            )
            found = {row.id for row in rows}
            still_remaining.extend(row_id for row_id in chunk if row_id not in found)
            pending_ids = [
                row.id
                for row in rows
                if row.status == CallImportRowStatus.PENDING
            ]
            skipped += len(rows) - len(pending_ids)
            if not pending_ids:
                continue
            with shard_row_write_context(session):
                session.execute(
                    update(CallImportRow)
                    .where(CallImportRow.id.in_(pending_ids))
                    .values(
                        status=CallImportRowStatus.FAILED,
                        error_message=message,
                    ),
                    execution_options={"synchronize_session": False},
                )
                session.commit()
            enqueue_failed += len(pending_ids)
        remaining = still_remaining
    return enqueue_failed, skipped
