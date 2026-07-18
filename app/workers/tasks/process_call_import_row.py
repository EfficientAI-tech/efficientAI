"""Celery task: fetch a single call recording from the configured voice provider
and persist it to S3, then update the parent batch counters.

Heavy imports (telephony service, S3 client) are deferred so the Celery boot
cost stays low and the task module can be imported safely at worker startup.

Recording-fetch strategy is CSV-URL-only:

    * **Direct-URL import** (no telephony credential): download the
      CSV-supplied ``recording_url`` without provider auth.
    * **Exotel credentialed import**: download the CSV-supplied
      ``recording_url`` with HTTP Basic auth from the batch's pinned
      credentials.
    * **Other credentialed providers** (e.g. Plivo): download the
      CSV-supplied ``recording_url`` without auth (public links).

Transient download errors schedule a Celery retry; auth/4xx/oversize
errors mark the row failed immediately.
"""

from __future__ import annotations

import mimetypes
from typing import Optional, Tuple
from uuid import UUID

from loguru import logger
from sqlalchemy.orm.exc import StaleDataError

from app.database import SessionLocal
from app.workers.config import celery_app


_RETRYABLE_COUNTDOWN_SECONDS = 60


def _retry_countdown_for_error(exc: Exception) -> int:
    retry_after = getattr(exc, "retry_after_seconds", None)
    if retry_after is not None:
        try:
            seconds = int(retry_after)
        except (TypeError, ValueError):
            seconds = 0
        if seconds > 0:
            return max(1, seconds)
    return _RETRYABLE_COUNTDOWN_SECONDS


def _schedule_transient_retry(self, *, row, db, row_id: str, exc: Exception, context: str):
    from app.models.enums import CallImportRowStatus

    row.status = CallImportRowStatus.PENDING
    row.error_message = f"Transient: {exc}"
    if not _safe_commit(db, row_id=row_id, context=context):
        return {"status": "skipped", "reason": "row_deleted"}
    raise self.retry(exc=exc, countdown=_retry_countdown_for_error(exc))


def _consume_authenticated_import_credit(client) -> Optional[Exception]:
    fingerprint = getattr(client, "_credential_fingerprint", None)
    if not fingerprint:
        return None

    from app.services.telephony.exotel_client import CredentialedRecordingThrottledError
    from app.workers.concurrency.telephony_credential_rate_limit import (
        consume_telephony_import_credit,
    )

    credit = consume_telephony_import_credit(fingerprint)
    if credit.allowed:
        return None
    return CredentialedRecordingThrottledError(
        f"Telephony credential throttled for {credit.wait_seconds}s",
        retry_after_seconds=max(1, credit.wait_seconds),
    )


def _safe_commit(
    db,
    *,
    row_id: Optional[str] = None,
    context: str = "update",
) -> bool:
    """Commit pending ORM changes; return False when the row/import was deleted."""
    try:
        db.commit()
        return True
    except StaleDataError:
        db.rollback()
        logger.info(
            "CallImportRow {} already deleted during {} — skipping in-flight update",
            row_id or "?",
            context,
        )
        return False


def _row_or_import_gone(
    db,
    row_id: UUID,
    *,
    catalog_db=None,
) -> Optional[str]:
    """Return a skip reason when the row or its parent import no longer exists."""
    from app.models.database import CallImport, CallImportRow
    from app.models.enums import CallImportStatus
    from app.db_sharding.sessions import is_sharding_enabled

    if is_sharding_enabled() and catalog_db is not None and catalog_db is not db:
        row_pk = (
            db.query(CallImportRow.id)
            .filter(CallImportRow.id == row_id)
            .first()
        )
        if row_pk is None:
            return "row_deleted"
        call_import_id = (
            db.query(CallImportRow.call_import_id)
            .filter(CallImportRow.id == row_id)
            .scalar()
        )
        if call_import_id is None:
            return "row_deleted"
        import_status = (
            catalog_db.query(CallImport.status)
            .filter(CallImport.id == call_import_id)
            .scalar()
        )
        if import_status is None:
            return "row_deleted"
        if import_status == CallImportStatus.DELETING:
            return "import_deleting"
        return None

    db.expire_all()
    hit = (
        db.query(CallImportRow.id, CallImport.status)
        .join(CallImport, CallImportRow.call_import_id == CallImport.id)
        .filter(CallImportRow.id == row_id)
        .first()
    )
    if hit is None:
        return "row_deleted"
    _row_pk, import_status = hit
    if import_status == CallImportStatus.DELETING:
        return "import_deleting"
    return None


def _use_credentialed_recording_download(call_import, client) -> bool:
    """True when CSV recording URLs should be fetched with provider auth."""
    if client is None or not hasattr(client, "download_recording"):
        return False
    return (call_import.provider or "").lower() == "exotel"


def _is_direct_url_import(call_import) -> bool:
    """True only when the batch was explicitly imported without telephony creds."""
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

    from app.services.call_imports.bulk_ops import rollup_call_import_batch_status

    rollup_call_import_batch_status(db, call_import)


def _rollup_parent_on_catalog(catalog_db, row_db, call_import) -> None:
    from app.db_sharding.sessions import is_sharding_enabled

    target = catalog_db if is_sharding_enabled() and catalog_db is not row_db else row_db
    _rollup_parent_status(target, call_import)
    if target is not row_db:
        target.commit()


@celery_app.task(name="process_call_import_row", bind=True, max_retries=3)
def process_call_import_row_task(
    self,
    row_id: str,
    _eval_slot_task_id: Optional[str] = None,
    run_eval_row_id: Optional[str] = None,
):
    """Fetch one call recording from the provider and store it in S3.

    Retries on transient errors (network blips, 5xx); marks the row failed
    immediately on auth/4xx/oversize errors.
    """

    from app.models.database import CallImportRow
    from app.models.enums import CallImportRowStatus
    from app.services.storage.s3_service import s3_service
    from app.services.telephony.exotel_client import (
        CredentialedRecordingThrottledError,
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

    slot_task_id = _eval_slot_task_id or self.request.id
    eval_chain_chained_transcribe = False
    row_db = catalog_db = None
    from app.db_sharding.row_ops import close_row_sessions, locate_call_import_row
    from app.models.database import CallImport

    try:
        try:
            row_db, catalog_db, row, shard_id = locate_call_import_row(row_id)
        except LookupError:
            logger.warning("CallImportRow {} not found, skipping", row_id)
            return {"status": "skipped", "reason": "row_not_found"}

        db = row_db
        row_uuid = row.id

        if catalog_db is not row_db:
            call_import = (
                catalog_db.query(CallImport)
                .filter(CallImport.id == row.call_import_id)
                .first()
            )
            logger.bind(shard_id=shard_id).debug(
                "process_call_import_row on shard {}", shard_id
            )
        else:
            call_import = row.call_import

        from app.models.enums import CallImportStatus

        if call_import.status == CallImportStatus.DELETING:
            logger.info(
                "Skipping row {} — parent import {} is being deleted",
                row_id,
                call_import.id,
            )
            return {"status": "skipped", "reason": "import_deleting"}

        if row.status == CallImportRowStatus.COMPLETED:
            return {"status": "already_completed", "row_id": row_id}

        row.status = CallImportRowStatus.PROCESSING
        row.attempts = (row.attempts or 0) + 1
        row.celery_task_id = self.request.id
        row.error_message = None
        if not _safe_commit(db, row_id=row_id, context="mark_processing"):
            return {"status": "skipped", "reason": "row_deleted"}

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
                    catalog_db if catalog_db is not row_db else db,
                    provider=call_import.provider,
                    credential_id=call_import.telephony_integration_id,
                )
            except Exception as exc:
                logger.exception("Failed to build provider client for row {}", row_id)
                row.status = CallImportRowStatus.FAILED
                row.error_message = f"Provider client error: {exc}"
                if not _safe_commit(db, row_id=row_id, context="provider_client_error"):
                    return {"status": "skipped", "reason": "row_deleted"}
                _rollup_parent_on_catalog(catalog_db, row_db, call_import)
                if not _safe_commit(db, row_id=row_id, context="rollup_provider_client_error"):
                    return {"status": "skipped", "reason": "row_deleted"}
                return {"status": "failed", "reason": "provider_client_error"}

        original_csv_url = (row.recording_url or "").strip() or None

        # ------------------------------------------------------------------
        # Direct-URL mode — download from the CSV-supplied URL only.
        # ------------------------------------------------------------------
        if direct_url_mode:
            audio_bytes: Optional[bytes] = None
            content_type: Optional[str] = None
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
                if not _safe_commit(db, row_id=row_id, context="direct_url_no_source"):
                    return {"status": "skipped", "reason": "row_deleted"}
                _rollup_parent_on_catalog(catalog_db, row_db, call_import)
                if not _safe_commit(db, row_id=row_id, context="rollup_direct_url_no_source"):
                    return {"status": "skipped", "reason": "row_deleted"}
                return {"status": "failed", "reason": "no_recording_source"}

            try:
                fetched = download_public_recording(original_csv_url)
                audio_bytes, content_type = fetched
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
                    if not _safe_commit(db, row_id=row_id, context="direct_url_transient"):
                        return {"status": "skipped", "reason": "row_deleted"}
                    raise self.retry(
                        exc=direct_failure, countdown=_RETRYABLE_COUNTDOWN_SECONDS
                    )
                row.status = CallImportRowStatus.FAILED
                row.error_message = (
                    f"recording URL: {direct_failure}"
                    if direct_failure is not None
                    else "Recording fetch failed"
                )
                if not _safe_commit(db, row_id=row_id, context="direct_url_failed"):
                    return {"status": "skipped", "reason": "row_deleted"}
                _rollup_parent_on_catalog(catalog_db, row_db, call_import)
                if not _safe_commit(db, row_id=row_id, context="rollup_direct_url_failed"):
                    return {"status": "skipped", "reason": "row_deleted"}
                return {"status": "failed", "reason": "non_retryable_provider_error"}

            # Fall through to the shared S3 upload success path below.
        else:
            # ------------------------------------------------------------------
            # Credentialed import — download from the CSV-supplied URL only.
            # Exotel URLs require HTTP Basic auth; other providers use public
            # download (e.g. Plivo presigned links).
            # ------------------------------------------------------------------
            audio_bytes: Optional[bytes] = None
            content_type: Optional[str] = None
            download_failure: Optional[Exception] = None
            download_was_transient = False

            if not original_csv_url:
                provider_key = (call_import.provider or "").lower()
                if provider_key == "exotel":
                    msg = (
                        "Cannot fetch recording: Exotel import requires a "
                        "recording URL on each row."
                    )
                else:
                    msg = (
                        "Cannot fetch recording: row has no recording URL."
                    )
                logger.warning("{} (row {})", msg, row_id)
                row.status = CallImportRowStatus.FAILED
                row.error_message = msg
                if not _safe_commit(db, row_id=row_id, context="no_recording_source"):
                    return {"status": "skipped", "reason": "row_deleted"}
                _rollup_parent_on_catalog(catalog_db, row_db, call_import)
                if not _safe_commit(db, row_id=row_id, context="rollup_no_recording_source"):
                    return {"status": "skipped", "reason": "row_deleted"}
                return {"status": "failed", "reason": "no_recording_source"}

            if _use_credentialed_recording_download(call_import, client):
                throttle_exc = _consume_authenticated_import_credit(client)
                if throttle_exc is not None:
                    return _schedule_transient_retry(
                        self,
                        row=row,
                        db=db,
                        row_id=row_id,
                        exc=throttle_exc,
                        context="credential_throttled",
                    )

            try:
                if _use_credentialed_recording_download(call_import, client):
                    fetched: Tuple[bytes, str] = client.download_recording(
                        original_csv_url
                    )
                else:
                    fetched = download_public_recording(original_csv_url)
                audio_bytes, content_type = fetched
            except NON_RETRYABLE_ERRORS as exc:
                download_failure = exc
                logger.warning(
                    "Recording download failed (non-retryable) for row {}: {}",
                    row_id,
                    exc,
                )
            except (ExotelTransientError, CredentialedRecordingThrottledError) as exc:
                download_failure = exc
                download_was_transient = True
                logger.warning(
                    "Recording download failed (transient) for row {} attempt {}: {}",
                    row_id,
                    row.attempts,
                    exc,
                )
            except Exception as exc:
                download_failure = exc
                download_was_transient = True
                logger.exception(
                    "Recording download failed (unexpected) for row {}", row_id
                )

            if audio_bytes is None:
                if download_was_transient:
                    return _schedule_transient_retry(
                        self,
                        row=row,
                        db=db,
                        row_id=row_id,
                        exc=download_failure,
                        context="transient_retry",
                    )
                row.status = CallImportRowStatus.FAILED
                row.error_message = (
                    f"recording URL: {download_failure}"
                    if download_failure is not None
                    else "Recording fetch failed"
                )
                if not _safe_commit(db, row_id=row_id, context="non_retryable_provider_error"):
                    return {"status": "skipped", "reason": "row_deleted"}
                _rollup_parent_on_catalog(catalog_db, row_db, call_import)
                if not _safe_commit(db, row_id=row_id, context="rollup_non_retryable_provider_error"):
                    return {"status": "skipped", "reason": "row_deleted"}
                return {"status": "failed", "reason": "non_retryable_provider_error"}

        if not s3_service.is_enabled():
            err = (
                s3_service.get_status_message()
                or "Cloud blob storage is not enabled or not configured"
            )
            logger.error("Cloud blob storage unavailable for row {}: {}", row_id, err)
            row.status = CallImportRowStatus.FAILED
            row.error_message = f"Cloud blob storage unavailable: {err}"
            if not _safe_commit(db, row_id=row_id, context="s3_unavailable"):
                return {"status": "skipped", "reason": "row_deleted"}
            _rollup_parent_on_catalog(catalog_db, row_db, call_import)
            if not _safe_commit(db, row_id=row_id, context="rollup_s3_unavailable"):
                return {"status": "skipped", "reason": "row_deleted"}
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
            if not _safe_commit(db, row_id=row_id, context="s3_upload_retry"):
                return {"status": "skipped", "reason": "row_deleted"}
            raise self.retry(exc=exc, countdown=_RETRYABLE_COUNTDOWN_SECONDS)

        skip_reason = _row_or_import_gone(
            db,
            row_uuid,
            catalog_db=catalog_db if catalog_db is not row_db else None,
        )
        if skip_reason:
            db.rollback()
            logger.info(
                "Skipping row {} finalize — {}",
                row_id,
                skip_reason,
            )
            return {"status": "skipped", "reason": skip_reason}

        row.recording_s3_key = key
        row.recording_content_type = content_type
        row.recording_size_bytes = len(audio_bytes)
        previous_import_status = row.status
        row.status = CallImportRowStatus.COMPLETED
        row.error_message = None
        if not _safe_commit(db, row_id=row_id, context="mark_completed"):
            return {"status": "skipped", "reason": "row_deleted"}

        _rollup_parent_on_catalog(catalog_db, row_db, call_import)
        if not _safe_commit(db, row_id=row_id, context="rollup_completed"):
            return {"status": "skipped", "reason": "row_deleted"}

        if run_eval_row_id:
            from app.models.database import CallImportEvaluation, CallImportEvaluationRow
            from app.workers.concurrency.eval_dispatch import (
                enqueue_eval_chain_transcribe_after_import,
            )

            eval_row = (
                db.query(CallImportEvaluationRow)
                .filter(CallImportEvaluationRow.id == UUID(run_eval_row_id))
                .first()
            )
            if eval_row is not None:
                evaluation = (
                    db.query(CallImportEvaluation)
                    .filter(CallImportEvaluation.id == eval_row.evaluation_id)
                    .first()
                )
                if evaluation is not None:
                    enqueue_eval_chain_transcribe_after_import(
                        db,
                        evaluation=evaluation,
                        eval_row=eval_row,
                        source_row=row,
                        slot_task_id=slot_task_id,
                    )
                    eval_chain_chained_transcribe = True

        return {
            "status": "completed",
            "row_id": row_id,
            "s3_key": key,
            "size_bytes": len(audio_bytes),
        }
    except StaleDataError:
        db.rollback()
        logger.info(
            "CallImportRow {} already deleted during processing — skipping",
            row_id,
        )
        return {"status": "skipped", "reason": "row_deleted"}
    finally:
        if row_db is not None:
            close_row_sessions(row_db, catalog_db if catalog_db is not row_db else None)
        from app.workers.concurrency.limits import slot_registered_for_task

        if slot_registered_for_task(slot_task_id):
            if run_eval_row_id:
                if not eval_chain_chained_transcribe:
                    cleanup_db = SessionLocal()
                    try:
                        from app.models.database import CallImportEvaluationRow, CallImportRow
                        from app.models.enums import CallImportRowStatus
                        from app.workers.concurrency.eval_dispatch import (
                            _fail_eval_row_for_import,
                        )

                        eval_row = (
                            cleanup_db.query(CallImportEvaluationRow)
                            .filter(CallImportEvaluationRow.id == UUID(run_eval_row_id))
                            .first()
                        )
                        source_row = (
                            cleanup_db.query(CallImportRow)
                            .filter(CallImportRow.id == UUID(row_id))
                            .first()
                        )
                        if (
                            eval_row is not None
                            and source_row is not None
                            and source_row.status != CallImportRowStatus.COMPLETED
                            and eval_row.status == "pending"
                        ):
                            _fail_eval_row_for_import(
                                cleanup_db, eval_row, source_row
                            )
                    finally:
                        cleanup_db.close()

                from app.workers.concurrency.fair_dispatch import (
                    finish_eval_work_and_redispatch,
                )

                if not eval_chain_chained_transcribe:
                    finish_eval_work_and_redispatch(slot_task_id)
            else:
                from app.workers.concurrency.fair_import_dispatch import (
                    finish_import_work_and_redispatch,
                )

                finish_import_work_and_redispatch(slot_task_id)
