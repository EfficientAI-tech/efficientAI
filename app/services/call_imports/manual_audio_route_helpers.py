"""Manual call-import audio upload helpers (used by API routes)."""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, Iterable, List, Optional, Tuple
from uuid import UUID, uuid4

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.config import settings
from app.db_sharding.sessions import is_sharding_enabled
from app.models.database import CallImport, CallImportRow
from app.models.enums import CallImportRowStatus

MAX_AUDIO_FILES_PER_REQUEST = 100
MANUAL_AUDIO_BLOB_UPLOAD_WORKERS = 10

AUDIO_CONTENT_TYPES = {
    "wav": "audio/wav",
    "mp3": "audio/mpeg",
    "flac": "audio/flac",
    "m4a": "audio/mp4",
}


def _audio_extension(filename: Optional[str]) -> Optional[str]:
    """Return the validated lower-case extension for a manual recording."""
    if not filename or "." not in filename:
        return None
    ext = filename.rsplit(".", 1)[-1].lower().strip()
    allowed = {fmt.lower().lstrip(".") for fmt in settings.ALLOWED_AUDIO_FORMATS}
    return ext if ext in allowed else None


def _audio_content_type(ext: str, upload_content_type: Optional[str]) -> str:
    """Prefer the browser-supplied audio content type, with a safe fallback."""
    supplied = (upload_content_type or "").strip()
    if supplied and supplied != "application/octet-stream":
        return supplied
    return AUDIO_CONTENT_TYPES.get(ext.lower(), "application/octet-stream")


def _audio_s3_key(
    organization_id: UUID, call_import_id: UUID, row_id: UUID, ext: str
) -> str:
    """Build the canonical S3 key for a manually uploaded recording."""
    from app.services.storage.s3_service import s3_service

    return (
        f"{s3_service.prefix}organizations/{organization_id}/call_imports/"
        f"{call_import_id}/{row_id}.{ext}"
    )


def _filename_stem(filename: Optional[str]) -> str:
    """Extract a cross-platform filename stem from an UploadFile name."""
    raw = (filename or "").strip()
    basename = re.split(r"[\\/]", raw)[-1] if raw else ""
    if "." in basename:
        basename = basename.rsplit(".", 1)[0]
    return basename.strip()


def _sanitize_conversation_id(raw: str) -> str:
    """Turn a filename stem into a stable conversation_id."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", raw.strip())
    cleaned = re.sub(r"_+", "_", cleaned).strip("._-")
    return (cleaned or "recording")[:255]


def _dedupe_conversation_id(
    base: str, counts: Dict[str, int]
) -> str:
    """Make conversation ids unique within one manual upload batch."""
    count = counts.get(base, 0) + 1
    counts[base] = count
    if count == 1:
        return base
    suffix = f"-{count}"
    return f"{base[: 255 - len(suffix)]}{suffix}"


def _conversation_id_base(conversation_id: str) -> str:
    match = re.match(r"^(.*)-(\d+)$", (conversation_id or "").strip())
    if match:
        return match.group(1)
    return (conversation_id or "").strip()


def _manual_audio_append_start_state(
    db: Session,
    call_import: CallImport,
) -> tuple[int, Dict[str, int]]:
    """Next row_index and conversation-id suffix counts for audio append."""
    from app.db_sharding.scatter_gather import (
        load_call_import_conversation_ids,
        max_call_import_row_index,
    )

    max_index = max_call_import_row_index(db, call_import.id)
    start_row_index = max_index + 1
    if start_row_index == 0 and (call_import.total_rows or 0) > 0:
        start_row_index = call_import.total_rows
    conversation_counts = _seed_conversation_counts(
        cid for cid in load_call_import_conversation_ids(db, call_import.id) if cid
    )
    return start_row_index, conversation_counts


def _seed_conversation_counts(existing_conversation_ids: Iterable[str]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for conversation_id in existing_conversation_ids:
        base = _conversation_id_base(conversation_id)
        if not base:
            continue
        counts[base] = counts.get(base, 0) + 1
    return counts


def _enforce_audio_upload_file_limit(file_count: int) -> None:
    if file_count > MAX_AUDIO_FILES_PER_REQUEST:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"At most {MAX_AUDIO_FILES_PER_REQUEST} audio files may be uploaded "
                "per request. Split large batches into multiple requests."
            ),
        )


async def _prepare_audio_upload_files(
    files: List[UploadFile],
    conversation_counts: Dict[str, int],
) -> List[Dict[str, Any]]:
    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one audio file is required.",
        )
    _enforce_audio_upload_file_limit(len(files))

    max_bytes = int(settings.MAX_FILE_SIZE_MB) * 1024 * 1024
    prepared: List[Dict[str, Any]] = []

    for idx, upload in enumerate(files):
        filename = upload.filename or f"recording-{idx + 1}"
        ext = _audio_extension(filename)
        if not ext:
            allowed = ", ".join(settings.ALLOWED_AUDIO_FORMATS)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported audio file '{filename}'. Allowed formats: {allowed}.",
            )

        contents = await upload.read()
        if not contents:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Audio file '{filename}' is empty.",
            )
        if len(contents) > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=(
                    f"Audio file '{filename}' exceeds "
                    f"{settings.MAX_FILE_SIZE_MB} MB."
                ),
            )

        base_conversation_id = _sanitize_conversation_id(_filename_stem(filename))
        conversation_id = _dedupe_conversation_id(
            base_conversation_id,
            conversation_counts,
        )
        prepared.append(
            {
                "filename": filename,
                "extension": ext,
                "content_type": _audio_content_type(ext, upload.content_type),
                "contents": contents,
                "conversation_id": conversation_id,
            }
        )
    return prepared


def _validate_audio_file_size(filename: str, size_bytes: int) -> None:
    max_bytes = int(settings.MAX_FILE_SIZE_MB) * 1024 * 1024
    if size_bytes > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"Audio file '{filename}' exceeds "
                f"{settings.MAX_FILE_SIZE_MB} MB."
            ),
        )


def _prepare_audio_presign_items(
    files: List,
    conversation_counts: Dict[str, int],
) -> List[Dict[str, Any]]:
    from app.services.call_imports import manual_audio_presign as presign_mod

    return presign_mod.prepare_manual_audio_metadata(
        files,
        conversation_counts,
        validate_extension=_audio_extension,
        validate_size=_validate_audio_file_size,
        audio_content_type=_audio_content_type,
        sanitize_conversation_id=_sanitize_conversation_id,
        dedupe_conversation_id=_dedupe_conversation_id,
        filename_stem=_filename_stem,
    )


def _upload_manual_audio_blobs_parallel(
    upload_specs: List[Tuple[str, bytes, str]],
) -> None:
    """Upload prepared manual-audio blobs concurrently (key, body, content_type)."""
    if not upload_specs:
        return

    from app.services.storage.s3_service import s3_service

    def _upload_one(spec: Tuple[str, bytes, str]) -> None:
        key, contents, content_type = spec
        s3_service.upload_file_by_key(
            contents,
            key,
            content_type=content_type,
        )

    if len(upload_specs) == 1:
        _upload_one(upload_specs[0])
        return

    workers = min(MANUAL_AUDIO_BLOB_UPLOAD_WORKERS, len(upload_specs))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_upload_one, spec) for spec in upload_specs]
        for future in as_completed(futures):
            future.result()


def _persist_prepared_audio_rows(
    db: Session,
    *,
    call_import: CallImport,
    organization_id: UUID,
    workspace_id: UUID,
    prepared: List[Dict[str, Any]],
    start_row_index: int,
) -> List[str]:
    uploaded_keys: List[str] = []
    row_mappings: List[Dict[str, Any]] = []
    upload_specs: List[Tuple[str, bytes, str]] = []

    for offset, item in enumerate(prepared):
        row_id = uuid4()
        key = _audio_s3_key(
            organization_id,
            call_import.id,
            row_id,
            item["extension"],
        )
        uploaded_keys.append(key)
        upload_specs.append((key, item["contents"], item["content_type"]))
        row_mappings.append(
            {
                "id": row_id,
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
                "recording_s3_key": key,
                "recording_content_type": item["content_type"],
                "recording_size_bytes": len(item["contents"]),
            }
        )

    _upload_manual_audio_blobs_parallel(upload_specs)

    added_size = sum(len(item["contents"]) for item in prepared)
    new_total_rows = (call_import.total_rows or 0) + len(prepared)

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
    call_import.completed_rows = (call_import.completed_rows or 0) + len(prepared)
    call_import.source_size_bytes = (call_import.source_size_bytes or 0) + added_size
    return uploaded_keys
