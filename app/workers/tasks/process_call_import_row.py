"""Celery task: fetch a single call recording from the configured voice provider
(currently Exotel) and persist it to S3, then update the parent batch counters.

Heavy imports (telephony service, S3 client) are deferred so the Celery boot
cost stays low and the task module can be imported safely at worker startup.
"""

from __future__ import annotations

import mimetypes
from uuid import UUID

from loguru import logger

from app.database import SessionLocal
from app.workers.config import celery_app


_RETRYABLE_COUNTDOWN_SECONDS = 60


def _extension_for_content_type(content_type: str) -> str:
    """Map an audio content-type to a sensible file extension."""
    mapping = {
        "audio/mpeg": "mp3",
        "audio/mp3": "mp3",
        "audio/wav": "wav",
        "audio/x-wav": "wav",
        "audio/wave": "wav",
        "audio/ogg": "ogg",
        "audio/flac": "flac",
        "audio/mp4": "m4a",
        "audio/x-m4a": "m4a",
    }
    if content_type in mapping:
        return mapping[content_type]
    guessed = mimetypes.guess_extension(content_type or "")
    if guessed:
        return guessed.lstrip(".")
    return "mp3"


def _rollup_parent_status(db, call_import) -> None:
    """Recompute completed_rows / failed_rows and finalize the batch status."""

    from app.models.database import CallImportRow
    from app.models.enums import CallImportRowStatus, CallImportStatus

    counts = (
        db.query(CallImportRow.status)
        .filter(CallImportRow.call_import_id == call_import.id)
        .all()
    )
    completed = sum(1 for (s,) in counts if s == CallImportRowStatus.COMPLETED)
    failed = sum(1 for (s,) in counts if s == CallImportRowStatus.FAILED)
    pending_or_processing = sum(
        1
        for (s,) in counts
        if s in (CallImportRowStatus.PENDING, CallImportRowStatus.PROCESSING)
    )

    call_import.completed_rows = completed
    call_import.failed_rows = failed

    if pending_or_processing > 0:
        call_import.status = CallImportStatus.PROCESSING
    elif failed == 0:
        call_import.status = CallImportStatus.COMPLETED
    elif completed == 0:
        call_import.status = CallImportStatus.FAILED
    else:
        call_import.status = CallImportStatus.PARTIAL


@celery_app.task(name="process_call_import_row", bind=True, max_retries=3)
def process_call_import_row_task(self, row_id: str):
    """Fetch one call recording from the provider and store it in S3.

    Retries on transient errors (network blips, 5xx); marks the row failed
    immediately on auth/4xx/oversize errors.
    """

    from app.models.database import CallImportRow
    from app.models.enums import CallImportRowStatus
    from app.services.storage.s3_service import s3_service
    from app.services.telephony.exotel_client import (
        ExotelAuthError,
        ExotelInvalidContentError,
        ExotelNotFoundError,
        ExotelRecordingTooLargeError,
        ExotelTransientError,
    )
    from app.services.telephony.telephony_service import telephony_service

    db = SessionLocal()
    try:
        row_uuid = UUID(row_id)
        row = db.query(CallImportRow).filter(CallImportRow.id == row_uuid).first()
        if row is None:
            logger.warning("CallImportRow {} not found, skipping", row_id)
            return {"status": "skipped", "reason": "row_not_found"}

        call_import = row.call_import

        if row.status == CallImportRowStatus.COMPLETED:
            return {"status": "already_completed", "row_id": row_id}

        row.status = CallImportRowStatus.PROCESSING
        row.attempts = (row.attempts or 0) + 1
        row.celery_task_id = self.request.id
        row.error_message = None
        db.commit()

        try:
            client = telephony_service.get_provider_client(
                row.organization_id, db, provider=call_import.provider
            )
        except Exception as exc:
            logger.exception("Failed to build provider client for row {}", row_id)
            row.status = CallImportRowStatus.FAILED
            row.error_message = f"Provider client error: {exc}"
            db.commit()
            _rollup_parent_status(db, call_import)
            db.commit()
            return {"status": "failed", "reason": "provider_client_error"}

        # If the CSV did not include a Recording URL for this row, resolve it
        # from the provider's call detail endpoint using the CallID. The
        # resolved URL is persisted onto the row so retries don't re-resolve.
        if not (row.recording_url and row.recording_url.strip()):
            try:
                resolved_url = client.get_call_recording_url(row.external_call_id)
            except (
                ExotelAuthError,
                ExotelNotFoundError,
                ExotelInvalidContentError,
            ) as exc:
                logger.warning(
                    "Non-retryable error resolving recording URL for row {}: {}",
                    row_id,
                    exc,
                )
                row.status = CallImportRowStatus.FAILED
                row.error_message = str(exc)
                db.commit()
                _rollup_parent_status(db, call_import)
                db.commit()
                return {"status": "failed", "reason": "non_retryable_provider_error"}
            except ExotelTransientError as exc:
                logger.warning(
                    "Transient error resolving recording URL for row {} (attempt {}): {}",
                    row_id,
                    row.attempts,
                    exc,
                )
                row.status = CallImportRowStatus.PENDING
                row.error_message = f"Transient: {exc}"
                db.commit()
                raise self.retry(exc=exc, countdown=_RETRYABLE_COUNTDOWN_SECONDS)
            except Exception as exc:
                logger.exception(
                    "Unexpected error resolving recording URL for row {}", row_id
                )
                row.error_message = f"Unexpected error: {exc}"
                row.status = CallImportRowStatus.PENDING
                db.commit()
                raise self.retry(exc=exc, countdown=_RETRYABLE_COUNTDOWN_SECONDS)

            row.recording_url = resolved_url
            db.commit()

        try:
            audio_bytes, content_type = client.download_recording(row.recording_url)
        except (
            ExotelAuthError,
            ExotelNotFoundError,
            ExotelInvalidContentError,
            ExotelRecordingTooLargeError,
        ) as exc:
            logger.warning(
                "Non-retryable error fetching recording for row {}: {}", row_id, exc
            )
            row.status = CallImportRowStatus.FAILED
            row.error_message = str(exc)
            db.commit()
            _rollup_parent_status(db, call_import)
            db.commit()
            return {"status": "failed", "reason": "non_retryable_provider_error"}
        except ExotelTransientError as exc:
            logger.warning(
                "Transient error fetching recording for row {} (attempt {}): {}",
                row_id,
                row.attempts,
                exc,
            )
            row.status = CallImportRowStatus.PENDING  # let the retry pick it up
            row.error_message = f"Transient: {exc}"
            db.commit()
            raise self.retry(exc=exc, countdown=_RETRYABLE_COUNTDOWN_SECONDS)
        except Exception as exc:
            logger.exception("Unexpected error fetching recording for row {}", row_id)
            row.error_message = f"Unexpected error: {exc}"
            row.status = CallImportRowStatus.PENDING
            db.commit()
            raise self.retry(exc=exc, countdown=_RETRYABLE_COUNTDOWN_SECONDS)

        if not s3_service.is_enabled():
            err = (
                s3_service.get_status_message()
                or "S3 is not enabled or not configured"
            )
            logger.error("S3 unavailable for row {}: {}", row_id, err)
            row.status = CallImportRowStatus.FAILED
            row.error_message = f"S3 unavailable: {err}"
            db.commit()
            _rollup_parent_status(db, call_import)
            db.commit()
            return {"status": "failed", "reason": "s3_unavailable"}

        ext = _extension_for_content_type(content_type)
        prefix = s3_service.prefix
        key = (
            f"{prefix}organizations/{row.organization_id}/call_imports/"
            f"{call_import.id}/{row.id}.{ext}"
        )

        try:
            s3_service.upload_file_by_key(audio_bytes, key, content_type=content_type)
        except Exception as exc:
            logger.exception("Failed to upload recording to S3 for row {}", row_id)
            row.error_message = f"S3 upload failed: {exc}"
            row.status = CallImportRowStatus.PENDING
            db.commit()
            raise self.retry(exc=exc, countdown=_RETRYABLE_COUNTDOWN_SECONDS)

        row.recording_s3_key = key
        row.recording_content_type = content_type
        row.recording_size_bytes = len(audio_bytes)
        row.status = CallImportRowStatus.COMPLETED
        row.error_message = None
        db.commit()

        _rollup_parent_status(db, call_import)
        db.commit()

        return {
            "status": "completed",
            "row_id": row_id,
            "s3_key": key,
            "size_bytes": len(audio_bytes),
        }
    finally:
        db.close()
