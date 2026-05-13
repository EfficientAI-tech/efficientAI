"""Celery task: transcribe one CallImport row's audio recording.

The call-import pipeline historically relied on the uploader to provide
transcripts via a CSV column. This task lets users fill that gap (or
overwrite a noisy CSV transcript) by running the existing
:class:`TranscriptionService` over the row's S3 recording and storing
the resulting plain-text transcript back on ``CallImportRow.transcript``
so every downstream piece (LLM-based metrics, exports, the UI's
``TranscriptView``) just keeps working without any code changes.

Speaker diarization (pyannote) is intentionally **disabled** here —
users only need a single transcript per row, not speaker turns. This
also avoids pulling in ``torch`` / ``pyannote.audio`` at task time and
removes the HuggingFace-token requirement.

Provider/model are caller-controlled — the user picks them from the UI.
We accept anything ``TranscriptionService.transcribe`` already supports
(OpenAI, Deepgram, ElevenLabs, Sarvam, Smallest, plus local Whisper as
the unconditional fallback inside that service).

When ``run_eval_row_id`` is set the task fires the per-row evaluation
worker in a chord-like fashion: this lets the Run Evaluation modal
auto-transcribe missing transcripts and then evaluate without an extra
round-trip from the API. We do this directly (rather than via Celery's
``chord`` primitive) so the eval row only kicks off after *its own*
transcription has finished — partial failures in one row's transcription
no longer block evaluation for siblings whose transcripts succeeded.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from loguru import logger

from app.database import SessionLocal
from app.workers.config import celery_app


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _summarize_exc(exc: BaseException, *, max_chars: int = 240) -> str:
    """Pull a human-friendly one-liner out of an STT-client exception.

    Most provider SDKs surface the actually-useful detail in the *root*
    cause's ``str(...)`` (Deepgram: ``DeepgramApiError: Project does
    not have access to the requested model. (Status: 403)``; OpenAI:
    ``BadRequestError: ...``; Sarvam: the wrapped HTTP body). We walk
    the ``__cause__`` chain, prefer the deepest message, prefix the
    exception class name so the operator knows the shape, and clamp
    the result so the transcript_error column / UI banner stay
    readable.
    """

    cur: BaseException | None = exc
    last: BaseException = exc
    while cur is not None:
        last = cur
        cur = cur.__cause__ or cur.__context__
        if cur is exc:
            break

    text = str(last) or last.__class__.__name__
    text = " ".join(text.split())
    label = last.__class__.__name__
    if label and not text.lower().startswith(label.lower()):
        text = f"{label}: {text}"
    if len(text) > max_chars:
        text = text[: max_chars - 1].rstrip() + "…"
    return text


@celery_app.task(
    name="transcribe_call_import_row",
    bind=True,
    max_retries=2,
    time_limit=15 * 60,
    soft_time_limit=12 * 60,
)
def transcribe_call_import_row_task(
    self,
    row_id: str,
    stt_provider: str,
    stt_model: str,
    credential_id: Optional[str] = None,
    language: Optional[str] = None,
    overwrite_existing: bool = False,
    run_eval_row_id: Optional[str] = None,
):
    """Transcribe a single row's recording (plain text, no diarization).

    Skips rows with no S3 recording, or with an existing transcript when
    ``overwrite_existing`` is False. Errors are recorded on the row
    (``transcript_status='failed'`` + ``transcript_error``) so the UI can
    surface a per-row diagnostic without polling Celery directly.
    """

    from app.models.database import CallImportRow
    from app.models.enums import ModelProvider

    db = SessionLocal()
    try:
        row_uuid = UUID(row_id)
        row = db.query(CallImportRow).filter(CallImportRow.id == row_uuid).first()
        if row is None:
            logger.warning(
                "transcribe_call_import_row: row {} not found, skipping",
                row_id,
            )
            return {"status": "skipped", "reason": "row_not_found"}

        existing_transcript = (row.transcript or "").strip()
        if existing_transcript and not overwrite_existing:
            row.transcript_status = "completed"
            db.commit()
            return {
                "status": "skipped",
                "reason": "transcript_present",
                "row_id": row_id,
            }

        recording_key = (row.recording_s3_key or "").strip()
        if not recording_key:
            row.transcript_status = "failed"
            row.transcript_error = (
                "No recording available for this row; cannot diarize."
            )
            db.commit()
            return {"status": "skipped", "reason": "no_recording"}

        try:
            provider_enum = ModelProvider(stt_provider.lower())
        except ValueError:
            row.transcript_status = "failed"
            row.transcript_error = f"Unknown STT provider '{stt_provider}'."
            db.commit()
            return {"status": "failed", "reason": "unknown_provider"}

        row.transcript_status = "running"
        row.transcript_error = None
        # Record which provider/model the user asked for *now* (rather
        # than only on success) so the per-row error banner can show
        # "Failed on deepgram/deepgram-nova-3" without the user having
        # to remember what they picked in the modal.
        row.transcript_provider = provider_enum.value
        row.transcript_model = stt_model
        row.celery_task_id = self.request.id
        db.commit()

        # Lazy import — TranscriptionService transitively pulls in torch
        # / pyannote / librosa, and we don't want to pay that cost at
        # worker boot if the queue is idle.
        from app.services.ai.transcription_service import transcription_service

        try:
            credential_uuid = UUID(credential_id) if credential_id else None
        except (TypeError, ValueError):
            credential_uuid = None

        try:
            result = transcription_service.transcribe(
                audio_file_key=recording_key,
                stt_provider=provider_enum,
                stt_model=stt_model,
                organization_id=row.organization_id,
                db=db,
                language=language,
                # Plain-text only — we don't run pyannote here. Users
                # asked for a single transcript per row, not speaker
                # turns, so we skip the diarization stage entirely and
                # store whatever the STT provider returns as-is.
                enable_speaker_diarization=False,
                credential_id=credential_uuid,
            )
        except Exception as exc:  # noqa: BLE001 - want the message on the row
            logger.exception(
                "transcribe_call_import_row failed for row {}", row_id
            )
            row.transcript_status = "failed"
            row.transcript_error = _summarize_exc(exc)
            db.commit()
            return {"status": "failed", "reason": "transcription_error"}

        plain_text = (result.get("transcript") or "").strip() or None
        if not plain_text:
            row.transcript_status = "failed"
            row.transcript_error = (
                "Transcription returned an empty result."
            )
            db.commit()
            return {"status": "failed", "reason": "empty_transcript"}

        row.transcript = plain_text
        row.transcript_source = "transcribed"
        row.transcript_provider = provider_enum.value
        row.transcript_model = stt_model
        row.transcript_status = "completed"
        row.transcript_error = None
        row.transcribed_at = _now()
        db.commit()

        # If this transcribe run was kicked off by the auto-transcribe
        # branch of the Run Evaluation modal, immediately enqueue the
        # corresponding eval-row task so the user doesn't have to poll
        # twice (once for diarization, once for evaluation).
        if run_eval_row_id:
            try:
                from app.workers.tasks.evaluate_call_import_row import (
                    evaluate_call_import_row_task,
                )

                evaluate_call_import_row_task.delay(run_eval_row_id)
            except Exception:
                logger.exception(
                    "Failed to enqueue post-transcribe eval row {}",
                    run_eval_row_id,
                )

        return {
            "status": "completed",
            "row_id": row_id,
            "provider": provider_enum.value,
            "model": stt_model,
            "characters": len(plain_text),
        }
    finally:
        db.close()
