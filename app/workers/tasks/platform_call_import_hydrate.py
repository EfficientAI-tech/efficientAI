"""Hydrate a platform historical import row (transcript + S3 audio)."""

from __future__ import annotations

from datetime import datetime, timezone
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


def _apply_provider_transcript(
    row,
    call_import,
    normalized,
    *,
    enabled: bool,
) -> None:
    if not enabled:
        return
    if (row.transcript_source or "") == "edited":
        return
    text = (normalized.transcript or "").strip()
    row.transcript = normalized.transcript
    row.transcript_source = "provider"
    row.transcript_provider = (call_import.provider or "").strip().lower() or None
    row.transcript_status = "completed" if text else "idle"
    if text:
        row.transcribed_at = datetime.now(timezone.utc)


_MIN_RECORDING_BYTES = 1024


def _release_import_sessions(row_db, catalog_db) -> None:
    from app.database import release_read_only_session

    release_read_only_session(row_db)
    if catalog_db is not None and catalog_db is not row_db:
        release_read_only_session(catalog_db)


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


def _hand_off(
    *,
    row,
    db,
    row_id: str,
    slot_task_id: str,
    wait_seconds: int,
    reason: str,
) -> Dict[str, Any]:
    from celery.utils import uuid as celery_uuid

    from app.workers.concurrency.fair_platform_import_dispatch import PLATFORM_IMPORTS_QUEUE
    from app.workers.concurrency.platform_import_limits import (
        release_platform_lease,
        transfer_platform_lease,
    )
    from app.workers.tasks.process_call_import_row import (
        _safe_commit,
        process_call_import_row_task,
    )

    next_id = celery_uuid()
    if not transfer_platform_lease(slot_task_id, next_id):
        return {"status": "failed", "reason": "lease_transfer"}
    row.status = CallImportRowStatus.PENDING
    row.celery_task_id = next_id
    if not _safe_commit(db, row_id=row_id, context=f"platform_{reason}"):
        release_platform_lease(next_id)
        return {"status": "skipped", "reason": "row_deleted"}
    try:
        process_call_import_row_task.apply_async(
            args=(row_id,),
            kwargs={"_eval_slot_task_id": next_id, "_platform_import": True},
            countdown=max(1, int(wait_seconds)),
            queue=PLATFORM_IMPORTS_QUEUE,
            task_id=next_id,
        )
        from app.workers.concurrency.platform_import_limits import (
            mark_platform_task_published,
        )

        mark_platform_task_published(next_id)
    except Exception:
        logger.exception("platform import handoff publish failed row {}", row_id)
        row.celery_task_id = None
        row.status = CallImportRowStatus.PENDING
        _safe_commit(db, row_id=row_id, context=f"platform_{reason}_publish")
        release_platform_lease(next_id)
        return {"status": "failed", "reason": "publish_failed"}
    return {"status": "rescheduled", "reason": reason}


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
        return _hand_off(
            row=row,
            db=db,
            row_id=row_id,
            slot_task_id=slot_task_id,
            wait_seconds=60,
            reason="credential_paused",
        )

    speed = filters.get("speed")
    token = consume_platform_api_token(
        integration.id,
        speed,
        member=f"hydrate:{row_id}:meta",
    )
    if not token.allowed:
        return _hand_off(
            row=row,
            db=db,
            row_id=row_id,
            slot_task_id=slot_task_id,
            wait_seconds=token.wait_seconds,
            reason="rate_limited",
        )

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
    organization_id = row.organization_id
    import_id = call_import.id
    stored_row_id = row.id
    raw_columns = dict(row.raw_columns or {}) if isinstance(row.raw_columns, dict) else {}
    transcript_only = (getattr(call_import, "content_modality", None) or "").lower() == "chat" or (
        filters.get("medium") or ""
    ).strip().lower() == "chat"
    if transcript_only:
        raw_columns["medium"] = "chat"
    item = HistoricalListItem(
        conversation_id=conversation_id,
        agent_id=raw_columns.get("agent_id"),
        raw=raw_columns,
    )

    _release_import_sessions(row_db, catalog_db)
    try:
        normalized = adapter.hydrate(item)
        clear_platform_auth_failures(integration.id)
    except Exception as exc:
        from app.services.call_imports.platform_discovery import list_failure_disposition

        kind, wait_seconds = list_failure_disposition(exc)
        if kind == "auth":
            record_platform_auth_failure(integration.id)
        elif kind == "retry":
            return _hand_off(
                row=row,
                db=db,
                row_id=row_id,
                slot_task_id=slot_task_id,
                wait_seconds=wait_seconds,
                reason="provider_retry",
            )
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

    import_transcript = bool(filters.get("import_provider_transcript", True)) or transcript_only
    _apply_provider_transcript(
        row,
        call_import,
        normalized,
        enabled=import_transcript,
    )
    merged_raw = dict(row.raw_columns or {})
    merged_raw.update(normalized.raw_columns or {})
    row.raw_columns = merged_raw

    if transcript_only:
        if not (row.transcript or "").strip():
            return _mark_row_failed_for_fetch(
                row=row,
                db=db,
                row_id=row_id,
                catalog_db=catalog_db,
                row_db=row_db,
                call_import=call_import,
                message="Chat transcript is empty",
                context="platform_chat_empty",
                reason="chat_transcript_empty",
            )
        previous_status = row.status
        row.recording_s3_key = None
        row.status = CallImportRowStatus.COMPLETED
        row.error_message = None
        if not _safe_commit(db, row_id=row_id, context="platform_chat_completed"):
            return {"status": "skipped", "reason": "row_deleted"}
        maybe_record_import_row_transition(
            call_import.id,
            previous_status=previous_status,
            new_status=row.status,
        )
        call_import.last_progress_at = datetime.now(timezone.utc)
        _rollup_parent_on_catalog(catalog_db, row_db, call_import)
        _safe_commit(db, row_id=row_id, context="platform_chat_rollup")
        from app.workers.concurrency.platform_import_limits import release_platform_import_slot
        from app.workers.concurrency.fair_platform_import_dispatch import (
            schedule_fair_platform_import_dispatch,
        )

        release_platform_import_slot(slot_task_id)
        schedule_fair_platform_import_dispatch()
        return {"status": "completed", "row_id": row_id, "transcript_only": True}

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

    audio_token = consume_platform_api_token(
        integration.id,
        speed,
        member=f"hydrate:{row_id}:audio",
    )
    if not audio_token.allowed:
        return _hand_off(
            row=row,
            db=db,
            row_id=row_id,
            slot_task_id=slot_task_id,
            wait_seconds=audio_token.wait_seconds,
            reason="rate_limited",
        )

    if not _safe_commit(db, row_id=row_id, context="platform_transcript_staged"):
        return {"status": "skipped", "reason": "row_deleted"}
    _release_import_sessions(row_db, catalog_db)

    try:
        stream, content_type = adapter.open_audio_stream(normalized)
    except Exception as exc:
        from app.services.call_imports.platform_discovery import list_failure_disposition

        kind, wait_seconds = list_failure_disposition(exc)
        if kind == "retry":
            return _hand_off(
                row=row,
                db=db,
                row_id=row_id,
                slot_task_id=slot_task_id,
                wait_seconds=wait_seconds,
                reason="provider_retry",
            )
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

    import os
    import tempfile

    from app.workers.concurrency.platform_import_limits import renew_platform_lease
    from app.workers.tasks.process_call_import_row import _row_or_import_gone

    ext = _extension_for_content_type(content_type)
    prefix = s3_service.prefix
    key = (
        f"{prefix}organizations/{organization_id}/call_imports/"
        f"{import_id}/{stored_row_id}.{ext}"
    )
    row.status = CallImportRowStatus.PROCESSING
    row.attempts = (row.attempts or 0) + 1
    if hasattr(row, "download_started_at"):
        row.download_started_at = datetime.now(timezone.utc)
    if not _safe_commit(db, row_id=row_id, context="platform_download_started"):
        return {"status": "skipped", "reason": "row_deleted"}
    _release_import_sessions(row_db, catalog_db)
    max_bytes = settings.PLATFORM_IMPORT_RECORDING_MAX_BYTES
    total = 0
    tmp = tempfile.NamedTemporaryFile(delete=False)
    try:
        try:
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
                tmp.write(chunk)
                if total % (8 * 1024 * 1024) < len(chunk):
                    renew_platform_lease(slot_task_id)
        finally:
            close = getattr(stream, "close", None)
            if callable(close):
                close()
        tmp.close()
        if total < _MIN_RECORDING_BYTES:
            return _mark_row_failed_for_fetch(
                row=row,
                db=db,
                row_id=row_id,
                catalog_db=catalog_db,
                row_db=row_db,
                call_import=call_import,
                message="Recording file is empty",
                context="platform_empty_audio",
                reason="recording_empty",
            )
        from app.services.call_imports.recording_storage import upload_local_recording_file

        size_bytes, duration_seconds = upload_local_recording_file(
            tmp.name,
            key=key,
            content_type=content_type or "audio/mpeg",
            size_bytes=total,
        )
    finally:
        tmp.close()
        if os.path.exists(tmp.name):
            os.unlink(tmp.name)

    if _row_or_import_gone(db, UUID(row_id), catalog_db=catalog_db):
        try:
            s3_service.delete_keys_by_prefix(key)
        except Exception:
            logger.warning("orphan platform recording delete failed key={}", key)
        return {"status": "skipped", "reason": "row_deleted"}

    previous_status = row.status
    row.recording_s3_key = key
    row.recording_content_type = content_type
    row.recording_size_bytes = size_bytes
    row.recording_duration_seconds = duration_seconds if duration_seconds > 0 else None
    row.status = CallImportRowStatus.COMPLETED
    row.error_message = None
    if not _safe_commit(db, row_id=row_id, context="platform_completed"):
        return {"status": "skipped", "reason": "row_deleted"}

    maybe_record_import_row_transition(
        call_import.id,
        previous_status=previous_status,
        new_status=row.status,
    )
    call_import.last_progress_at = datetime.now(timezone.utc)
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
        "size_bytes": total,
    }
