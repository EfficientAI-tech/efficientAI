"""Celery task: fetch a single call recording from the configured voice provider
(currently Exotel) and persist it to S3, then update the parent batch counters.

Heavy imports (telephony service, S3 client) are deferred so the Celery boot
cost stays low and the task module can be imported safely at worker startup.

Recording-fetch strategy is two-tier so retries / stale CSVs both work:

    1. **Credentialed call-id lookup** (preferred). When the provider client
       supports it (Exotel today), authenticate with the batch's pinned
       credentials, resolve a fresh recording URL via the Calls API, then
       download from that URL. This is the "freshest" path and works even
       when a CSV-supplied URL has expired / isn't accepting our auth.
    2. **CSV-supplied recording URL** (fallback). Only used when (a) the
       call-id flow couldn't deliver a recording for non-retryable reasons,
       or (b) the provider client has no lookup capability (e.g. Plivo —
       Plivo CSVs must include a recording URL).

When the call-id flow fails, the CSV-supplied URL is always given a turn
(if present) — that maximizes the chance of delivering bytes on this
attempt. The final outcome is then determined by the union of failure
modes: if any tier hit a transient error and bytes still couldn't be
fetched, schedule a Celery retry; if every applicable tier failed
non-retryably, mark the row failed with a composite error message.
"""

from __future__ import annotations

import mimetypes
from typing import Optional, Tuple
from uuid import UUID

from loguru import logger

from app.database import SessionLocal
from app.workers.config import celery_app


_RETRYABLE_COUNTDOWN_SECONDS = 60


def _is_direct_url_import(call_import) -> bool:
    """True only when the batch was explicitly imported without telephony creds.

    Legacy credentialed batches may have ``provider`` set but no pinned
    ``telephony_integration_id`` (org-default credential resolution). Those
    must still run the conversation-id lookup path, not public URL download.
    """
    return (
        call_import.telephony_integration_id is None
        and not (call_import.provider or "").strip()
    )


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
    immediately on auth/4xx/oversize errors after exhausting both the
    call-id lookup path and the CSV-URL fallback.
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

    NON_RETRYABLE_ERRORS = (
        ExotelAuthError,
        ExotelNotFoundError,
        ExotelInvalidContentError,
        ExotelRecordingTooLargeError,
    )

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

        from app.services.telephony.recording_download import download_public_recording

        direct_url_mode = _is_direct_url_import(call_import)
        client = None
        if not direct_url_mode:
            try:
                # Use the credential pinned on the batch when available so the
                # uploader's choice is respected even if the org default has
                # changed since upload. Falls back to (org, provider) default
                # for legacy rows imported before the column existed.
                client = telephony_service.get_provider_client(
                    row.organization_id,
                    db,
                    provider=call_import.provider,
                    credential_id=call_import.telephony_integration_id,
                )
            except Exception as exc:
                logger.exception("Failed to build provider client for row {}", row_id)
                row.status = CallImportRowStatus.FAILED
                row.error_message = f"Provider client error: {exc}"
                db.commit()
                _rollup_parent_status(db, call_import)
                db.commit()
                return {"status": "failed", "reason": "provider_client_error"}

        original_csv_url = (row.recording_url or "").strip() or None
        provider_lookup_supported = (
            not direct_url_mode
            and bool(row.conversation_id)
            and client is not None
            and hasattr(client, "get_call_recording_url")
        )

        # ------------------------------------------------------------------
        # Direct-URL mode — download from the CSV-supplied URL only.
        # ------------------------------------------------------------------
        if direct_url_mode:
            audio_bytes: Optional[bytes] = None
            content_type: Optional[str] = None
            used_url: Optional[str] = None
            direct_failure: Optional[Exception] = None
            direct_was_transient = False

            if not original_csv_url:
                msg = (
                    "Cannot fetch recording: direct URL import requires a "
                    "recording URL on each row."
                )
                logger.warning("{} (row {})", msg, row_id)
                row.status = CallImportRowStatus.FAILED
                row.error_message = msg
                db.commit()
                _rollup_parent_status(db, call_import)
                db.commit()
                return {"status": "failed", "reason": "no_recording_source"}

            try:
                fetched = download_public_recording(original_csv_url)
                audio_bytes, content_type = fetched
                used_url = original_csv_url
            except NON_RETRYABLE_ERRORS as exc:
                direct_failure = exc
                logger.warning(
                    "Direct URL download failed (non-retryable) for row {}: {}",
                    row_id,
                    exc,
                )
            except ExotelTransientError as exc:
                direct_failure = exc
                direct_was_transient = True
                logger.warning(
                    "Direct URL download failed (transient) for row {} attempt {}: {}",
                    row_id,
                    row.attempts,
                    exc,
                )
            except Exception as exc:
                direct_failure = exc
                direct_was_transient = True
                logger.exception(
                    "Direct URL download failed (unexpected) for row {}", row_id
                )

            if audio_bytes is None:
                if direct_was_transient:
                    row.status = CallImportRowStatus.PENDING
                    row.error_message = f"Transient: {direct_failure}"
                    db.commit()
                    raise self.retry(
                        exc=direct_failure, countdown=_RETRYABLE_COUNTDOWN_SECONDS
                    )
                row.status = CallImportRowStatus.FAILED
                row.error_message = (
                    f"recording URL: {direct_failure}"
                    if direct_failure is not None
                    else "Recording fetch failed"
                )
                db.commit()
                _rollup_parent_status(db, call_import)
                db.commit()
                return {"status": "failed", "reason": "non_retryable_provider_error"}

            # Fall through to the shared S3 upload success path below.
        else:
            # ------------------------------------------------------------------
            # Tier 1 — credentialed call-id flow (preferred). On success we
            # download the recording right here so a successful lookup combined
            # with a failing download still has a chance to fall back to the
            # CSV-supplied URL on the next tier.
            # ------------------------------------------------------------------
            audio_bytes: Optional[bytes] = None
            content_type: Optional[str] = None
            used_url: Optional[str] = None
            primary_failure: Optional[Exception] = None
            primary_was_transient = False

            if provider_lookup_supported:
                try:
                    resolved_url = client.get_call_recording_url(row.conversation_id)
                    fetched: Tuple[bytes, str] = client.download_recording(resolved_url)
                    audio_bytes, content_type = fetched
                    used_url = resolved_url
                except NON_RETRYABLE_ERRORS as exc:
                    primary_failure = exc
                    logger.warning(
                        "Call-id flow failed (non-retryable) for row {}: {}",
                        row_id,
                        exc,
                    )
                except ExotelTransientError as exc:
                    primary_failure = exc
                    primary_was_transient = True
                    logger.warning(
                        "Call-id flow failed (transient) for row {} attempt {}: {}",
                        row_id,
                        row.attempts,
                        exc,
                    )
                except Exception as exc:
                    primary_failure = exc
                    primary_was_transient = True
                    logger.exception(
                        "Call-id flow failed (unexpected) for row {}", row_id
                    )

            # ------------------------------------------------------------------
            # Tier 2 — CSV-supplied recording URL (fallback). Only attempted
            # when Tier 1 didn't deliver bytes. Use credentialed download when
            # the provider client supports it (Exotel recording URLs require
            # auth); otherwise fetch the URL without auth (public/Plivo links).
            # ------------------------------------------------------------------
            fallback_failure: Optional[Exception] = None
            fallback_was_transient = False

            if audio_bytes is None and original_csv_url:
                try:
                    fetched = download_public_recording(original_csv_url)
                    audio_bytes, content_type = fetched
                    used_url = original_csv_url
                    if primary_failure is not None:
                        logger.info(
                            "Recovered row {} via CSV-supplied recording URL after "
                            "call-id flow failed ({})",
                            row_id,
                            primary_failure,
                        )
                except NON_RETRYABLE_ERRORS as exc:
                    fallback_failure = exc
                    logger.warning(
                        "CSV-URL fallback failed (non-retryable) for row {}: {}",
                        row_id,
                        exc,
                    )
                except ExotelTransientError as exc:
                    fallback_failure = exc
                    fallback_was_transient = True
                    logger.warning(
                        "CSV-URL fallback failed (transient) for row {} attempt {}: {}",
                        row_id,
                        row.attempts,
                        exc,
                    )
                except Exception as exc:
                    fallback_failure = exc
                    fallback_was_transient = True
                    logger.exception(
                        "CSV-URL fallback failed (unexpected) for row {}", row_id
                    )

            # ------------------------------------------------------------------
            # Decide: success / retry / fail
            # ------------------------------------------------------------------
            if audio_bytes is None:
                if primary_failure is None and fallback_failure is None:
                    msg = (
                        "Cannot fetch recording: row has no recording URL and the "
                        "provider does not support call-id lookup."
                    )
                    logger.warning("{} (row {})", msg, row_id)
                    row.status = CallImportRowStatus.FAILED
                    row.error_message = msg
                    db.commit()
                    _rollup_parent_status(db, call_import)
                    db.commit()
                    return {"status": "failed", "reason": "no_recording_source"}

                if primary_was_transient or fallback_was_transient:
                    exc_to_raise = (
                        fallback_failure if fallback_was_transient else primary_failure
                    )
                    row.status = CallImportRowStatus.PENDING
                    row.error_message = f"Transient: {exc_to_raise}"
                    db.commit()
                    raise self.retry(
                        exc=exc_to_raise, countdown=_RETRYABLE_COUNTDOWN_SECONDS
                    )

                parts = []
                if primary_failure is not None:
                    parts.append(f"call-id lookup: {primary_failure}")
                if fallback_failure is not None:
                    parts.append(f"recording URL: {fallback_failure}")
                err_msg = "; ".join(parts) if parts else "Recording fetch failed"
                row.status = CallImportRowStatus.FAILED
                row.error_message = err_msg
                db.commit()
                _rollup_parent_status(db, call_import)
                db.commit()
                return {"status": "failed", "reason": "non_retryable_provider_error"}

        # ------------------------------------------------------------------
        # Success path — persist the resolved URL when the CSV didn't
        # supply one (matches legacy behavior so retries / debugging
        # surface what we actually fetched). When the CSV *did* supply a
        # URL we leave it untouched so a future retry can still fall back
        # to the original uploader-supplied value if a fresh lookup
        # produces a different (and possibly broken) URL.
        # ------------------------------------------------------------------
        if not original_csv_url and used_url:
            row.recording_url = used_url
            db.commit()

        if not s3_service.is_enabled():
            err = (
                s3_service.get_status_message()
                or "Cloud blob storage is not enabled or not configured"
            )
            logger.error("Cloud blob storage unavailable for row {}: {}", row_id, err)
            row.status = CallImportRowStatus.FAILED
            row.error_message = f"Cloud blob storage unavailable: {err}"
            db.commit()
            _rollup_parent_status(db, call_import)
            db.commit()
            return {"status": "failed", "reason": "s3_unavailable"}

        ext = _extension_for_content_type(content_type or "")
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
