"""Hydrate a platform historical import row (transcript + S3 audio)."""

from __future__ import annotations

from typing import Any, Dict, Optional
from uuid import UUID

from loguru import logger

from app.config import settings
from app.models.database import Integration
from app.models.enums import CallImportRowStatus
from app.services.voice_providers.historical.base import (
    HistoricalListItem,
    get_historical_adapter,
    parse_canonical_recording_url,
)
from app.workers.concurrency.platform_import_limits import (
    clear_platform_auth_failures,
    consume_platform_api_token,
    credential_import_paused,
    record_platform_auth_failure,
)


def _extension_for_content_type(content_type: str) -> str:
    mapping = {
        "audio/mpeg": "mp3",
        "audio/mp3": "mp3",
        "audio/wav": "wav",
        "audio/x-wav": "wav",
        "audio/ogg": "ogg",
        "audio/mp4": "m4a",
    }
    ct = (content_type or "").split(";")[0].strip().lower()
    return mapping.get(ct, "mp3")


def hydrate_platform_call_import_row(
    task,
    *,
    row,
    call_import,
    db,
    row_id: str,
    catalog_db,
    row_db,
    slot_task_id: str,
    filters: Dict[str, Any],
) -> Dict[str, Any]:
    from app.services.call_imports.debounced_rollup import maybe_record_import_row_transition
    from app.services.storage.s3_service import s3_service
    from app.workers.tasks.process_call_import_row import (
        _extension_for_content_type as ext_fn,
        _mark_row_failed_for_fetch,
        _rollup_parent_on_catalog,
        _safe_commit,
    )

    integration = (
        (catalog_db if catalog_db is not row_db else db)
        .query(Integration)
        .filter(Integration.id == call_import.voice_integration_id)
        .first()
    )
    if integration is None:
        return _mark_row_failed_for_fetch(
            row=row,
            db=db,
            row_id=row_id,
            catalog_db=catalog_db,
            row_db=row_db,
            call_import=call_import,
            message="Voice integration not found",
            context="platform_no_integration",
            reason="platform_no_integration",
        )

    if credential_import_paused(integration.id):
        row.status = CallImportRowStatus.PENDING
        row.celery_task_id = None
        _safe_commit(db, row_id=row_id, context="platform_cred_paused")
        from app.workers.tasks.process_call_import_row import (
            process_call_import_row_task,
        )

        process_call_import_row_task.apply_async(
            args=(row_id,),
            kwargs={"_eval_slot_task_id": slot_task_id, "_platform_import": True},
            countdown=60,
            queue="platform-imports",
        )
        return {"status": "rescheduled", "reason": "credential_paused"}

    speed = filters.get("speed")
    token = consume_platform_api_token(integration.id, speed)
    if not token.allowed:
        row.status = CallImportRowStatus.PENDING
        row.celery_task_id = None
        _safe_commit(db, row_id=row_id, context="platform_throttled")
        from app.workers.tasks.process_call_import_row import (
            process_call_import_row_task,
        )

        process_call_import_row_task.apply_async(
            args=(row_id,),
            kwargs={"_eval_slot_task_id": slot_task_id, "_platform_import": True},
            countdown=max(1, token.wait_seconds),
            queue="platform-imports",
        )
        return {"status": "rescheduled", "reason": "rate_limited"}

    try:
        provider_key, conversation_id = parse_canonical_recording_url(row.recording_url or "")
    except ValueError:
        return _mark_row_failed_for_fetch(
            row=row,
            db=db,
            row_id=row_id,
            catalog_db=catalog_db,
            row_db=row_db,
            call_import=call_import,
            message="Invalid platform recording reference",
            context="platform_bad_url",
            reason="platform_bad_url",
        )

    adapter = get_historical_adapter(integration)
    item = HistoricalListItem(
        conversation_id=conversation_id,
        agent_id=(row.raw_columns or {}).get("agent_id") if isinstance(row.raw_columns, dict) else None,
        raw=(row.raw_columns or {}) if isinstance(row.raw_columns, dict) else {},
    )

    try:
        normalized = adapter.hydrate(item)
        clear_platform_auth_failures(integration.id)
    except Exception as exc:
        status_code = getattr(getattr(exc, "response", None), "status_code", None)
        if status_code in (401, 403):
            record_platform_auth_failure(integration.id)
        logger.warning("platform hydrate failed row {}: {}", row_id, exc)
        return _mark_row_failed_for_fetch(
            row=row,
            db=db,
            row_id=row_id,
            catalog_db=catalog_db,
            row_db=row_db,
            call_import=call_import,
            message=f"Provider hydrate failed: {exc}",
            context="platform_hydrate_failed",
            reason="platform_hydrate_failed",
        )

    if (row.transcript_source or "") != "edited":
        row.transcript = normalized.transcript
        row.transcript_source = "provider"
    merged_raw = dict(row.raw_columns or {})
    merged_raw.update(normalized.raw_columns or {})
    row.raw_columns = merged_raw

    if not s3_service.is_enabled():
        return _mark_row_failed_for_fetch(
            row=row,
            db=db,
            row_id=row_id,
            catalog_db=catalog_db,
            row_db=row_db,
            call_import=call_import,
            message="Cloud storage unavailable",
            context="s3_unavailable",
            reason="s3_unavailable",
        )

    try:
        stream, content_type = adapter.open_audio_stream(normalized)
    except Exception as exc:
        return _mark_row_failed_for_fetch(
            row=row,
            db=db,
            row_id=row_id,
            catalog_db=catalog_db,
            row_db=row_db,
            call_import=call_import,
            message=f"Recording unavailable: {exc}",
            context="platform_audio_failed",
            reason="recording_unavailable",
        )

    ext = _extension_for_content_type(content_type)
    prefix = s3_service.prefix
    key = (
        f"{prefix}organizations/{row.organization_id}/call_imports/"
        f"{call_import.id}/{row.id}.{ext}"
    )
    max_bytes = settings.PLATFORM_IMPORT_RECORDING_MAX_BYTES
    total = 0
    chunks = []
    for chunk in stream:
        total += len(chunk)
        if total > max_bytes:
            return _mark_row_failed_for_fetch(
                row=row,
                db=db,
                row_id=row_id,
                catalog_db=catalog_db,
                row_db=row_db,
                call_import=call_import,
                message="Recording exceeds size cap",
                context="platform_oversize",
                reason="recording_too_large",
            )
        chunks.append(chunk)

    body = b"".join(chunks)
    s3_service.upload_file_by_key(body, key, content_type=content_type or "audio/mpeg")

    previous_status = row.status
    row.recording_s3_key = key
    row.recording_content_type = content_type
    row.recording_size_bytes = len(body)
    row.status = CallImportRowStatus.COMPLETED
    row.error_message = None
    if not _safe_commit(db, row_id=row_id, context="platform_completed"):
        return {"status": "skipped", "reason": "row_deleted"}

    maybe_record_import_row_transition(
        call_import.id,
        previous_status=previous_status,
        new_status=row.status,
    )
    _rollup_parent_on_catalog(catalog_db, row_db, call_import)
    _safe_commit(db, row_id=row_id, context="platform_rollup")

    from app.workers.concurrency.platform_import_limits import release_platform_import_slot
    from app.workers.concurrency.fair_platform_import_dispatch import (
        schedule_fair_platform_import_dispatch,
    )

    release_platform_import_slot(slot_task_id)
    schedule_fair_platform_import_dispatch()

    return {
        "status": "completed",
        "row_id": row_id,
        "s3_key": key,
        "size_bytes": len(body),
    }
