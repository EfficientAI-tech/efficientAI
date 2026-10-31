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
    * **Plivo credentialed import**: download the CSV-supplied
      ``recording_url`` with HTTP Basic auth from the batch's pinned
      credentials.
    * **Other credentialed providers**: download the CSV-supplied
      ``recording_url`` without auth (public links).

Transient download errors schedule a Celery retry; auth/4xx/oversize
errors mark the row failed immediately.
"""

from __future__ import annotations

import mimetypes
import os
import tempfile
from typing import Optional, Tuple
from uuid import UUID

from loguru import logger
from sqlalchemy.orm.exc import StaleDataError

from app.workers.config import celery_app


_CREDENTIAL_AUTH_FAIL_ATTEMPT_THRESHOLD = 2


def _fetch_recording_to_local_file(
    recording_url: str,
    *,
    telephony_client,
    use_credentialed_download: bool,
) -> Tuple[str, str]:
    """Return (temp_path, content_type). Caller must unlink temp_path."""
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".audio")
    os.close(tmp_fd)
    try:
        if use_credentialed_download:
            audio_bytes, content_type = telephony_client.download_recording(
                recording_url
            )
            with open(tmp_path, "wb") as handle:
                handle.write(audio_bytes)
            return tmp_path, content_type or "audio/mpeg"

        from app.services.telephony.recording_download import (
            download_public_recording_to_path,
        )

        content_type = download_public_recording_to_path(recording_url, tmp_path)
        return tmp_path, content_type
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _is_credentialed_auth_rejection(exc: Exception) -> bool:
    message = str(exc).lower()
    return "rejected credentials" in message and ("401" in message or "403" in message)


def _terminal_transient_failure_message(self, row, exc: Exception) -> Optional[str]:
    max_retries = getattr(self, "max_retries", None)
    if max_retries is None:
        max_retries = 3
    retries = getattr(getattr(self, "request", None), "retries", 0)
    if _is_credentialed_auth_rejection(exc) and (
        row.attempts or 0
    ) >= _CREDENTIAL_AUTH_FAIL_ATTEMPT_THRESHOLD:
        return f"Telephony credentials rejected: {exc}"
    if retries >= max_retries:
        return f"Recording fetch failed after {max_retries + 1} attempts: {exc}"
    return None


def _mark_row_failed_for_fetch(
    *,
    row,
    db,
    row_id: str,
    catalog_db,
    row_db,
    call_import,
    message: str,
    context: str,
    reason: str = "non_retryable_provider_error",
):
    from app.models.enums import CallImportRowStatus

    previous_status = row.status
    row.status = CallImportRowStatus.FAILED
    row.error_message = message
    if not _safe_commit(db, row_id=row_id, context=context):
        return {"status": "skipped", "reason": "row_deleted"}
    _rollup_parent_on_catalog(
        catalog_db,
        row_db,
        call_import,
        terminal_row=row,
        previous_row_status=previous_status,
    )
    if not _safe_commit(db, row_id=row_id, context=f"rollup_{context}"):
        return {"status": "skipped", "reason": "row_deleted"}
    return {"status": "failed", "reason": reason}


def _retry_countdown_for_error(exc: Exception, *, attempt: int = 0) -> int:
    from app.workers.concurrency.import_retry_backoff import (
        import_transient_retry_countdown,
    )

    return import_transient_retry_countdown(exc, attempt=attempt)


def _schedule_transient_retry(
    self,
    *,
    row,
    db,
    row_id: str,
    exc: Exception,
    context: str,
    catalog_db=None,
    row_db=None,
    call_import=None,
):
    from app.models.enums import CallImportRowStatus

    terminal_message = _terminal_transient_failure_message(self, row, exc)
    if terminal_message is not None and call_import is not None:
        return _mark_row_failed_for_fetch(
            row=row,
            db=db,
            row_id=row_id,
            catalog_db=catalog_db,
            row_db=row_db,
            call_import=call_import,
            message=terminal_message,
            context=context,
        )

    row.status = CallImportRowStatus.PENDING
    row.error_message = f"Transient: {exc}"
    if not _safe_commit(db, row_id=row_id, context=context):
        return {"status": "skipped", "reason": "row_deleted"}
    attempt = int(getattr(getattr(self, "request", None), "retries", 0) or 0)
    raise self.retry(
        exc=exc, countdown=_retry_countdown_for_error(exc, attempt=attempt)
    )


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


def _persist_session_changes(db) -> None:
    """Commit in production; flush inside nested test transactions (savepoints)."""
    from app.db_sharding.row_ops import commit_shard_row_session
    from app.db_sharding.sessions import is_sharding_enabled

    trans = db.get_transaction()
    nested_test_tx = (
        trans is not None
        and trans.parent is not None
        and getattr(trans.parent, "nested", False)
    )
    if nested_test_tx:
        db.flush()
        return
    if is_sharding_enabled():
        commit_shard_row_session(db)
    else:
        db.commit()


def _safe_commit(
    db,
    *,
    row_id: Optional[str] = None,
    context: str = "update",
) -> bool:
    """Commit pending ORM changes; return False when the row/import was deleted."""
    try:
        _persist_session_changes(db)
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


_CREDENTIALED_RECORDING_IMPORT_PROVIDERS = frozenset({"exotel", "plivo"})


def _use_credentialed_recording_download(call_import, client) -> bool:
    """True when CSV recording URLs should be fetched with provider auth."""
    if client is None or not hasattr(client, "download_recording"):
        return False
    return (call_import.provider or "").lower() in _CREDENTIALED_RECORDING_IMPORT_PROVIDERS


def _release_fetch_sessions(row_db, catalog_db) -> None:
    """Return checked-out connections before a recording download or S3 upload."""
    from app.database import release_read_only_session

    release_read_only_session(row_db)
    if catalog_db is not None and catalog_db is not row_db:
        release_read_only_session(catalog_db)


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


def _rollup_parent_status(db, call_import, *, force: bool = False) -> None:
    from app.services.call_imports.debounced_rollup import schedule_debounced_import_rollup

    schedule_debounced_import_rollup(db, call_import, force=force)


def _rollup_parent_on_catalog(
    catalog_db,
    row_db,
    call_import,
    *,
    force: bool = True,
    terminal_row=None,
    previous_row_status=None,
) -> None:
    from app.db_sharding.sessions import is_sharding_enabled
    from app.services.call_imports.debounced_rollup import (
        maybe_record_import_row_transition,
    )

    target = catalog_db if is_sharding_enabled() and catalog_db is not row_db else row_db
    if terminal_row is not None and previous_row_status is not None:
        maybe_record_import_row_transition(
            call_import.id,
            previous_status=previous_row_status,
            new_status=terminal_row.status,
            db=target,
        )
    _rollup_parent_status(target, call_import, force=force)
    if target is not row_db:
        _persist_session_changes(target)


@celery_app.task(name="process_call_import_row", bind=True, max_retries=3)
def process_call_import_row_task(
    self,
    row_id: str,
    _eval_slot_task_id: Optional[str] = None,
    run_eval_row_id: Optional[str] = None,
    _platform_import: bool = False,
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
    platform_release = bool(_platform_import)
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

        if call_import is None:
            return {"status": "skipped", "reason": "import_missing"}

        if call_import.status == CallImportStatus.DELETING:
            logger.info(
                "Skipping row {} — parent import {} is deleting",
                row_id,
                call_import.id,
            )
            return {"status": "skipped", "reason": "import_deleting"}
        if _platform_import and call_import.paused_at is not None:
            logger.info(
                "Skipping row {} — parent import {} is paused",
                row_id,
                call_import.id,
            )
            return {"status": "skipped", "reason": "import_inactive"}

        if _platform_import and (row.celery_task_id or "") != str(self.request.id):
            platform_release = False
            return {"status": "superseded", "row_id": row_id}

        if row.status == CallImportRowStatus.COMPLETED:
            return {"status": "already_completed", "row_id": row_id}

        if not _platform_import:
            from app.workers.concurrency.dispatch_reconcile import (
                claim_import_row_for_task,
            )

            if not claim_import_row_for_task(db, row, self.request.id):
                logger.info(
                    "Skipping import row {} already claimed or finished",
                    row_id,
                )
                return {"status": "skipped", "reason": "already_claimed"}

        if (call_import.source_format or "").lower() == "platform":
            from app.workers.tasks.platform_call_import_hydrate import (
                hydrate_platform_call_import_row,
            )

            filters = dict(call_import.platform_filters or {})
            slot_task_id = _eval_slot_task_id or self.request.id
            try:
                result = hydrate_platform_call_import_row(
                    self,
                    row=row,
                    call_import=call_import,
                    db=db,
                    row_id=row_id,
                    catalog_db=catalog_db,
                    row_db=row_db,
                    slot_task_id=slot_task_id,
                    filters=filters,
                )
            except Exception as exc:
                logger.exception("platform hydrate crashed row {}", row_id)
                if (row.celery_task_id or "") == str(self.request.id) and not row.recording_s3_key:
                    row.status = CallImportRowStatus.PENDING
                    row.celery_task_id = None
                    row.error_message = str(exc)[:500]
                    _safe_commit(db, row_id=row_id, context="platform_hydrate_crash")
                from app.workers.concurrency.fair_platform_import_dispatch import (
                    schedule_fair_platform_import_dispatch,
                )

                schedule_fair_platform_import_dispatch()
                return {"status": "failed", "reason": "hydrate_crashed"}
            status = (result or {}).get("status")
            if status == "rescheduled":
                platform_release = False
            elif status == "completed":
                platform_release = False
            else:
                from app.workers.concurrency.fair_platform_import_dispatch import (
                    schedule_fair_platform_import_dispatch,
                )

                if status not in ("skipped", "superseded", "already_completed"):
                    schedule_fair_platform_import_dispatch()
            return result

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
                previous_status = row.status
                row.status = CallImportRowStatus.FAILED
                row.error_message = f"Provider client error: {exc}"
                if not _safe_commit(db, row_id=row_id, context="provider_client_error"):
                    return {"status": "skipped", "reason": "row_deleted"}
                _rollup_parent_on_catalog(
                    catalog_db,
                    row_db,
                    call_import,
                    terminal_row=row,
                    previous_row_status=previous_status,
                )
                if not _safe_commit(db, row_id=row_id, context="rollup_provider_client_error"):
                    return {"status": "skipped", "reason": "row_deleted"}
                return {"status": "failed", "reason": "provider_client_error"}

        original_csv_url = (row.recording_url or "").strip() or None

        requires_recording_url = bool((call_import.provider or "").strip())
        if not original_csv_url:
            if requires_recording_url:
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
                previous_status = row.status
                row.status = CallImportRowStatus.FAILED
                row.error_message = msg
                if not _safe_commit(db, row_id=row_id, context="no_recording_source"):
                    return {"status": "skipped", "reason": "row_deleted"}
                _rollup_parent_on_catalog(
                    catalog_db,
                    row_db,
                    call_import,
                    terminal_row=row,
                    previous_row_status=previous_status,
                )
                if not _safe_commit(
                    db, row_id=row_id, context="rollup_no_recording_source"
                ):
                    return {"status": "skipped", "reason": "row_deleted"}
                return {"status": "failed", "reason": "no_recording_source"}

            previous_status = row.status
            row.status = CallImportRowStatus.COMPLETED
            row.error_message = None
            if not _safe_commit(db, row_id=row_id, context="mark_completed_no_recording"):
                return {"status": "skipped", "reason": "row_deleted"}
            _rollup_parent_on_catalog(
                catalog_db,
                row_db,
                call_import,
                terminal_row=row,
                previous_row_status=previous_status,
            )
            if not _safe_commit(
                db, row_id=row_id, context="rollup_completed_no_recording"
            ):
                return {"status": "skipped", "reason": "row_deleted"}
            return {
                "status": "completed",
                "row_id": row_id,
                "s3_key": None,
            }

        fetch_org_id = row.organization_id
        fetch_import_id = call_import.id
        fetch_row_id = row.id

        # ------------------------------------------------------------------
        # Direct-URL mode — download from the CSV-supplied URL only.
        # ------------------------------------------------------------------
        if direct_url_mode:
            _release_fetch_sessions(row_db, catalog_db)
            local_recording_path: Optional[str] = None
            content_type: Optional[str] = None
            direct_failure: Optional[Exception] = None
            direct_was_transient = False

            try:
                local_recording_path, content_type = _fetch_recording_to_local_file(
                    original_csv_url,
                    telephony_client=client,
                    use_credentialed_download=False,
                )
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

            if local_recording_path is None:
                if direct_was_transient:
                    terminal_message = _terminal_transient_failure_message(
                        self, row, direct_failure
                    )
                    if terminal_message is not None:
                        return _mark_row_failed_for_fetch(
                            row=row,
                            db=db,
                            row_id=row_id,
                            catalog_db=catalog_db,
                            row_db=row_db,
                            call_import=call_import,
                            message=terminal_message,
                            context="direct_url_transient_exhausted",
                        )
                    row.status = CallImportRowStatus.PENDING
                    row.error_message = f"Transient: {direct_failure}"
                    if not _safe_commit(db, row_id=row_id, context="direct_url_transient"):
                        return {"status": "skipped", "reason": "row_deleted"}
                    attempt = int(
                        getattr(getattr(self, "request", None), "retries", 0) or 0
                    )
                    raise self.retry(
                        exc=direct_failure,
                        countdown=_retry_countdown_for_error(
                            direct_failure, attempt=attempt
                        ),
                    )
                previous_status = row.status
                row.status = CallImportRowStatus.FAILED
                row.error_message = (
                    f"recording URL: {direct_failure}"
                    if direct_failure is not None
                    else "Recording fetch failed"
                )
                if not _safe_commit(db, row_id=row_id, context="direct_url_failed"):
                    return {"status": "skipped", "reason": "row_deleted"}
                _rollup_parent_on_catalog(
                    catalog_db,
                    row_db,
                    call_import,
                    terminal_row=row,
                    previous_row_status=previous_status,
                )
                if not _safe_commit(db, row_id=row_id, context="rollup_direct_url_failed"):
                    return {"status": "skipped", "reason": "row_deleted"}
                return {"status": "failed", "reason": "non_retryable_provider_error"}

            # Fall through to the shared S3 upload success path below.
        else:
            # ------------------------------------------------------------------
            # Credentialed import — download from the CSV-supplied URL only.
            # ------------------------------------------------------------------
            local_recording_path = None
            content_type = None
            download_failure: Optional[Exception] = None
            download_was_transient = False
            use_credentialed_download = _use_credentialed_recording_download(
                call_import, client
            )

            if use_credentialed_download:
                throttle_exc = _consume_authenticated_import_credit(client)
                if throttle_exc is not None:
                    return _schedule_transient_retry(
                        self,
                        row=row,
                        db=db,
                        row_id=row_id,
                        exc=throttle_exc,
                        context="credential_throttled",
                        catalog_db=catalog_db,
                        row_db=row_db,
                        call_import=call_import,
                    )

            _release_fetch_sessions(row_db, catalog_db)
            try:
                local_recording_path, content_type = _fetch_recording_to_local_file(
                    original_csv_url,
                    telephony_client=client,
                    use_credentialed_download=use_credentialed_download,
                )
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

            if local_recording_path is None:
                if download_was_transient:
                    return _schedule_transient_retry(
                        self,
                        row=row,
                        db=db,
                        row_id=row_id,
                        exc=download_failure,
                        context="transient_retry",
                        catalog_db=catalog_db,
                        row_db=row_db,
                        call_import=call_import,
                    )
                previous_status = row.status
                row.status = CallImportRowStatus.FAILED
                row.error_message = (
                    f"recording URL: {download_failure}"
                    if download_failure is not None
                    else "Recording fetch failed"
                )
                if not _safe_commit(db, row_id=row_id, context="non_retryable_provider_error"):
                    return {"status": "skipped", "reason": "row_deleted"}
                _rollup_parent_on_catalog(
                    catalog_db,
                    row_db,
                    call_import,
                    terminal_row=row,
                    previous_row_status=previous_status,
                )
                if not _safe_commit(db, row_id=row_id, context="rollup_non_retryable_provider_error"):
                    return {"status": "skipped", "reason": "row_deleted"}
                return {"status": "failed", "reason": "non_retryable_provider_error"}

        if not s3_service.is_enabled():
            err = (
                s3_service.get_status_message()
                or "Cloud blob storage is not enabled or not configured"
            )
            logger.error("Cloud blob storage unavailable for row {}: {}", row_id, err)
            previous_status = row.status
            row.status = CallImportRowStatus.FAILED
            row.error_message = f"Cloud blob storage unavailable: {err}"
            if not _safe_commit(db, row_id=row_id, context="s3_unavailable"):
                return {"status": "skipped", "reason": "row_deleted"}
            _rollup_parent_on_catalog(
                catalog_db,
                row_db,
                call_import,
                terminal_row=row,
                previous_row_status=previous_status,
            )
            if not _safe_commit(db, row_id=row_id, context="rollup_s3_unavailable"):
                return {"status": "skipped", "reason": "row_deleted"}
            return {"status": "failed", "reason": "s3_unavailable"}

        ext = _extension_for_content_type(content_type or "")
        prefix = s3_service.prefix
        key = (
            f"{prefix}organizations/{fetch_org_id}/call_imports/"
            f"{fetch_import_id}/{fetch_row_id}.{ext}"
        )

        _release_fetch_sessions(row_db, catalog_db)
        try:
            from app.services.call_imports.recording_storage import (
                upload_local_recording_file,
            )

            try:
                size_bytes, duration_seconds = upload_local_recording_file(
                    local_recording_path,
                    key=key,
                    content_type=content_type or "audio/mpeg",
                )
            finally:
                try:
                    os.unlink(local_recording_path)
                except OSError:
                    pass
        except Exception as exc:
            logger.exception("Failed to upload recording to S3 for row {}", row_id)
            terminal_message = _terminal_transient_failure_message(self, row, exc)
            if terminal_message is not None:
                return _mark_row_failed_for_fetch(
                    row=row,
                    db=db,
                    row_id=row_id,
                    catalog_db=catalog_db,
                    row_db=row_db,
                    call_import=call_import,
                    message=f"S3 upload failed after retries: {exc}",
                    context="s3_upload_exhausted",
                    reason="s3_upload_failed",
                )
            row.error_message = f"S3 upload failed: {exc}"
            row.status = CallImportRowStatus.PENDING
            if not _safe_commit(db, row_id=row_id, context="s3_upload_retry"):
                return {"status": "skipped", "reason": "row_deleted"}
            attempt = int(getattr(getattr(self, "request", None), "retries", 0) or 0)
            raise self.retry(
                exc=exc,
                countdown=_retry_countdown_for_error(exc, attempt=attempt),
            )

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
        row.recording_size_bytes = size_bytes
        row.recording_duration_seconds = duration_seconds if duration_seconds > 0 else None
        previous_import_status = row.status
        row.status = CallImportRowStatus.COMPLETED
        row.error_message = None
        if not _safe_commit(db, row_id=row_id, context="mark_completed"):
            return {"status": "skipped", "reason": "row_deleted"}

        _rollup_parent_on_catalog(
            catalog_db,
            row_db,
            call_import,
            terminal_row=row,
            previous_row_status=previous_import_status,
        )
        if not _safe_commit(db, row_id=row_id, context="rollup_completed"):
            return {"status": "skipped", "reason": "row_deleted"}

        if run_eval_row_id:
            from app.models.database import CallImportEvaluation, CallImportEvaluationRow
            from app.workers.concurrency.eval_dispatch import (
                _needs_transcribe_for_eval,
                enqueue_eval_chain_transcribe_after_import,
            )

            eval_row = (
                db.query(CallImportEvaluationRow)
                .filter(CallImportEvaluationRow.id == UUID(run_eval_row_id))
                .first()
            )
            if eval_row is not None:
                # Evaluation headers live on the catalog when sharding is on.
                eval_header_db = (
                    catalog_db
                    if catalog_db is not None and catalog_db is not row_db
                    else db
                )
                evaluation = (
                    eval_header_db.query(CallImportEvaluation)
                    .filter(CallImportEvaluation.id == eval_row.evaluation_id)
                    .first()
                )
                if evaluation is not None and _needs_transcribe_for_eval(
                    evaluation,
                    row,
                    transcribe_overwrite=False,
                ):
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
            "size_bytes": size_bytes,
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
        if run_eval_row_id:
            if not eval_chain_chained_transcribe:
                from app.db_sharding.row_ops import (
                    close_row_sessions as close_eval_sessions,
                    locate_call_import_evaluation_row,
                )
                from app.workers.concurrency.eval_dispatch import (
                    _fail_eval_row_for_import,
                    recover_eval_row_for_eval_chain,
                    source_row_import_blocks_eval,
                )
                from app.workers.tasks.evaluate_call_import_row_core import (
                    EVAL_CANCELLED_BY_USER_ERROR,
                )

                user_cancelled = False
                try:
                    cleanup_row_db, cleanup_catalog_db, eval_row, source_row, _ = (
                        locate_call_import_evaluation_row(
                            UUID(run_eval_row_id)
                        )
                    )
                except LookupError:
                    pass
                else:
                    try:
                        user_cancelled = (
                            (eval_row.status or "").lower() == "failed"
                            and (eval_row.error_message or "")
                            == EVAL_CANCELLED_BY_USER_ERROR
                        )
                        if user_cancelled:
                            pass
                        elif source_row_import_blocks_eval(source_row):
                            if eval_row.status == "pending":
                                _fail_eval_row_for_import(
                                    cleanup_row_db, eval_row, source_row
                                )
                        else:
                            recover_eval_row_for_eval_chain(eval_row)
                            if eval_row.status == "pending":
                                from app.db_sharding.row_ops import (
                                    commit_shard_row_session,
                                )

                                eval_row.celery_task_id = None
                                source_row.celery_task_id = None
                                commit_shard_row_session(cleanup_row_db)
                    finally:
                        close_eval_sessions(
                            cleanup_row_db, cleanup_catalog_db
                        )

                from app.workers.concurrency.fair_dispatch import (
                    finish_eval_work_and_redispatch,
                )

                # Redispatch after local cleanup when import did not chain
                # transcription — the transcribe worker releases the slot and
                # schedules fair dispatch when chained transcribe was enqueued.
                if not user_cancelled:
                    finish_eval_work_and_redispatch(slot_task_id)
        else:
            if platform_release:
                from app.workers.concurrency.platform_import_limits import (
                    release_platform_lease,
                )

                release_platform_lease(slot_task_id)
            from app.workers.concurrency.limits import slot_registered_for_task

            if slot_registered_for_task(slot_task_id):
                from app.workers.concurrency.fair_import_dispatch import (
                    finish_import_work_and_redispatch,
                )

                finish_import_work_and_redispatch(slot_task_id)
