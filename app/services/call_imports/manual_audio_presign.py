"""Presigned PUT flow for manual call-import audio (no bytes through the API)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.db_sharding.sessions import is_sharding_enabled
from app.models.database import CallImport, CallImportRow
from app.models.enums import CallImportRowStatus, CallImportStatus
from app.models.schemas import CallImportManualAudioFilePresignItem


def prepare_manual_audio_metadata(
    files: List[CallImportManualAudioFilePresignItem],
    conversation_counts: Dict[str, int],
    *,
    validate_extension,
    validate_size,
    audio_content_type,
    sanitize_conversation_id,
    dedupe_conversation_id,
    filename_stem,
) -> List[Dict[str, Any]]:
    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one audio file is required.",
        )
    prepared: List[Dict[str, Any]] = []
    for idx, item in enumerate(files):
        filename = (item.filename or "").strip() or f"recording-{idx + 1}"
        ext = validate_extension(filename)
        if not ext:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported audio file '{filename}'.",
            )
        size_bytes = int(item.size_bytes or 0)
        validate_size(filename, size_bytes)
        base_conversation_id = sanitize_conversation_id(filename_stem(filename))
        conversation_id = dedupe_conversation_id(base_conversation_id, conversation_counts)
        content_type = audio_content_type(ext, item.content_type)
        prepared.append(
            {
                "filename": filename,
                "extension": ext,
                "content_type": content_type,
                "size_bytes": size_bytes,
                "conversation_id": conversation_id,
            }
        )
    return prepared


def build_manual_audio_presign_uploads(
    *,
    organization_id: UUID,
    call_import_id: UUID,
    prepared: List[Dict[str, Any]],
    audio_s3_key,
    generate_presigned_put_url_by_key,
    expiration: int = 3600,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    uploads: List[Dict[str, Any]] = []
    keys: List[str] = []
    for item in prepared:
        row_id = uuid4()
        key = audio_s3_key(organization_id, call_import_id, row_id, item["extension"])
        keys.append(key)
        upload_url = generate_presigned_put_url_by_key(
            key,
            content_type=item["content_type"],
            expiration=expiration,
        )
        uploads.append(
            {
                "row_id": row_id,
                "recording_s3_key": key,
                "conversation_id": item["conversation_id"],
                "upload_url": upload_url,
                "content_type": item["content_type"],
                "filename": item["filename"],
                "size_bytes": item["size_bytes"],
            }
        )
    return uploads, keys


def persist_manual_audio_row_mappings(
    db: Session,
    *,
    call_import: CallImport,
    organization_id: UUID,
    workspace_id: UUID,
    uploads: List[Dict[str, Any]],
    start_row_index: int,
) -> None:
    row_mappings: List[Dict[str, Any]] = []
    added_size = 0
    for offset, item in enumerate(uploads):
        size_bytes = int(item.get("size_bytes") or 0)
        added_size += size_bytes
        row_mappings.append(
            {
                "id": item["row_id"],
                "call_import_id": call_import.id,
                "organization_id": organization_id,
                "workspace_id": workspace_id,
                "row_index": start_row_index + offset,
                "conversation_id": item["conversation_id"],
                "recording_url": None,
                "transcript": None,
                "transcript_source": None,
                "raw_columns": {"conversation_id": item["conversation_id"]},
                "status": CallImportRowStatus.COMPLETED,
                "recording_s3_key": item["recording_s3_key"],
                "recording_content_type": item["content_type"],
                "recording_size_bytes": size_bytes,
            }
        )

    new_total_rows = (call_import.total_rows or 0) + len(uploads)
    if is_sharding_enabled():
        from app.db_sharding.row_ops import (
            bulk_insert_mappings_on_shards,
            register_shard_slices,
        )

        bulk_insert_mappings_on_shards(db, call_import.id, row_mappings)
        register_shard_slices(db, call_import.id, new_total_rows)
    else:
        for mapping in row_mappings:
            db.add(CallImportRow(**mapping))

    call_import.total_rows = new_total_rows
    call_import.completed_rows = (call_import.completed_rows or 0) + len(uploads)
    call_import.source_size_bytes = (call_import.source_size_bytes or 0) + added_size


def _load_rows_for_verify(
    db: Session,
    *,
    call_import_id: UUID,
    organization_id: UUID,
    row_ids: List[UUID],
) -> List[Tuple[Session, CallImportRow]]:
    """Return (session, row) for each id; session must be closed by caller."""
    unique_ids = list(dict.fromkeys(row_ids))
    if not is_sharding_enabled():
        rows = (
            db.query(CallImportRow)
            .filter(
                CallImportRow.call_import_id == call_import_id,
                CallImportRow.organization_id == organization_id,
                CallImportRow.id.in_(unique_ids),
            )
            .all()
        )
        if len(rows) != len(unique_ids):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="One or more row ids are invalid for this import.",
            )
        return [(db, row) for row in rows]

    from app.db_sharding.row_ops import locate_call_import_row

    loaded: List[Tuple[Session, CallImportRow]] = []
    try:
        for rid in unique_ids:
            row_db, catalog_db, row, _shard_id = locate_call_import_row(rid)
            if catalog_db is not row_db:
                catalog_db.close()
            if (
                row.call_import_id != call_import_id
                or row.organization_id != organization_id
            ):
                row_db.close()
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="One or more row ids are invalid for this import.",
                )
            loaded.append((row_db, row))
    except LookupError:
        for row_db, _row in loaded:
            row_db.close()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="One or more row ids are invalid for this import.",
        ) from None
    return loaded


def verify_manual_audio_uploads(
    db: Session,
    *,
    call_import_id: UUID,
    organization_id: UUID,
    row_ids: List[UUID],
    head_object_by_key,
) -> int:
    if not row_ids:
        return 0
    sessions_rows = _load_rows_for_verify(
        db,
        call_import_id=call_import_id,
        organization_id=organization_id,
        row_ids=row_ids,
    )
    verified = 0
    modified_sessions: set[Session] = set()
    try:
        for row_db, row in sessions_rows:
            key = (row.recording_s3_key or "").strip()
            if not key:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Row {row.id} has no recording key.",
                )
            meta = head_object_by_key(key)
            if not meta:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Recording not found in storage for row {row.id}.",
                )
            size = int(meta.get("ContentLength") or 0)
            if size > 0:
                row.recording_size_bytes = size
                modified_sessions.add(row_db)
            verified += 1
        for sess in modified_sessions:
            sess.commit()
    finally:
        for row_db, _row in sessions_rows:
            if row_db is not db:
                row_db.close()
    return verified
