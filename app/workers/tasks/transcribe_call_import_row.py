"""Celery task: diarise one CallImport row's audio recording.

The call-import pipeline historically relied on the uploader to provide
transcripts via a CSV column. This task lets users fill that gap (or
add a second transcript next to one already supplied by the CSV) by
running the existing :class:`TranscriptionService` over the row's S3
recording and storing the result on ``CallImportRow.diarised_transcript``
— a *separate* column from the CSV-supplied production transcript so
the two values coexist and can be evaluated / exported side by side.

Diarisation is a **two-stage LLM-augmented** pipeline:

  1. ``TranscriptionService.transcribe`` produces plain text (no
     speaker segmentation — we explicitly pass
     ``enable_speaker_diarization=False`` because pyannote is no
     longer in the loop).
  2. :func:`app.workers.tasks.helpers.llm_diarisation.diarize_transcript_with_llm`
     hands that plain text to a chat model along with a caller-supplied
     prompt and asks it to emit structured ``agent`` / ``user`` turns.

The row stores:

  * Structured turns on ``diarised_segments`` (one entry per turn
    returned by the LLM, mapped through the first-speaker-is-agent
    heuristic in :func:`_segments_to_user_agent_turns` so reviewers
    keep the existing per-row "Swap user ↔ agent" affordance).
  * A rendered ``<speaker>: <text>`` line per turn on
    ``diarised_transcript`` so the existing UI / CSV-export code that
    reads the plain-text column keeps working without changes.
  * ``diarised_llm_provider`` / ``diarised_llm_model`` / ``diarised_prompt``
    so reviewers can see exactly which model + instructions produced
    the turns.

If the LLM diariser fails (bad JSON, unknown provider, …) the worker
records a typed error on the row and surfaces it in the UI — there is
no silent fallback, because the operator explicitly opted into LLM-
based diarisation by picking the model in the modal.

Provider/model for the STT step are caller-controlled — the user picks
them from the UI. We accept anything ``TranscriptionService.transcribe``
already supports (OpenAI, Deepgram, ElevenLabs, Sarvam, Smallest, plus
local Whisper as the unconditional fallback inside that service).

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
from typing import Any, Dict, List, Optional
from uuid import UUID

from loguru import logger

from app.database import SessionLocal
from app.workers.config import celery_app


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _segments_to_user_agent_turns(
    speaker_segments: Optional[List[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    """Map pyannote-labelled segments to canonical ``agent`` / ``user`` turns.

    ``TranscriptionService.transcribe(enable_speaker_diarization=True)``
    returns ``[{ "speaker": "Speaker 1", "text": "...", "start": float,
    "end": float }, ...]`` — generic speaker labels with no semantic
    role. We pick the canonical role for each raw label using a
    deterministic, easy-to-reason-about rule: the raw speaker who
    appears **earliest in time** is the ``agent``; the other becomes
    the ``user``. Most call-import recordings are agent-initiated
    (outbound IVR / outbound dialer / inbound greeting) so the agent
    almost always speaks first; when the heuristic is wrong reviewers
    flip ``diarised_speaker_swap`` from the row detail panel without
    re-running the worker.

    For recordings with more than two speakers (rare, but legal — e.g.
    conference calls) any extras keep their raw ``speaker_N`` label so
    they're still visible in the rendered transcript without being
    silently merged into ``user``.

    Each returned entry preserves ``raw_speaker`` so the swap endpoint
    can rebuild the rendered string from this list alone, without
    needing to re-read the original ``speaker_segments`` snapshot.
    """
    if not speaker_segments:
        return []

    earliest_by_label: Dict[str, float] = {}
    for seg in speaker_segments:
        raw = (seg.get("speaker") or "").strip()
        if not raw:
            continue
        start = seg.get("start")
        try:
            start_val = float(start) if start is not None else float("inf")
        except (TypeError, ValueError):
            start_val = float("inf")
        if raw not in earliest_by_label or start_val < earliest_by_label[raw]:
            earliest_by_label[raw] = start_val

    if not earliest_by_label:
        return []

    # Sort raw labels by first-appearance time, tie-breaking on label
    # text so the mapping is deterministic across calls with the same
    # transcript. The first-appearance label becomes "agent"; the next
    # becomes "user"; anything beyond that keeps a generic numbered
    # label so we never silently lose a speaker.
    ordered_labels = sorted(
        earliest_by_label.keys(),
        key=lambda lbl: (earliest_by_label[lbl], lbl),
    )
    role_map: Dict[str, str] = {}
    for idx, raw_label in enumerate(ordered_labels):
        if idx == 0:
            role_map[raw_label] = "agent"
        elif idx == 1:
            role_map[raw_label] = "user"
        else:
            role_map[raw_label] = f"speaker_{idx + 1}"

    turns: List[Dict[str, Any]] = []
    for seg in speaker_segments:
        raw = (seg.get("speaker") or "").strip()
        text = (seg.get("text") or "").strip()
        if not raw or not text:
            continue
        try:
            start_val = float(seg.get("start") or 0.0)
        except (TypeError, ValueError):
            start_val = 0.0
        try:
            end_val = float(seg.get("end") or 0.0)
        except (TypeError, ValueError):
            end_val = 0.0
        turns.append(
            {
                "speaker": role_map.get(raw, raw.lower().replace(" ", "_")),
                "text": text,
                "start": round(start_val, 3),
                "end": round(end_val, 3),
                "raw_speaker": raw,
            }
        )
    return turns


def _render_turns_as_text(
    turns: Optional[List[Dict[str, Any]]],
    *,
    swap: bool = False,
) -> str:
    """Render structured turns as ``<speaker>: <text>`` lines.

    The frontend's ``TranscriptView`` parses this exact shape into chat
    bubbles (see ``frontend/src/pages/callImports/components/TranscriptView.tsx``).
    When ``swap`` is True, ``agent`` and ``user`` are swapped — but only
    those two labels, so ``speaker_3``+ on multi-party calls keep their
    canonical role through a swap.
    """
    if not turns:
        return ""
    out: List[str] = []
    for turn in turns:
        speaker = (turn.get("speaker") or "").strip()
        text = (turn.get("text") or "").strip()
        if not speaker or not text:
            continue
        if swap:
            if speaker == "agent":
                speaker = "user"
            elif speaker == "user":
                speaker = "agent"
        out.append(f"{speaker}: {text}")
    return "\n".join(out)


# Sentinel error message stamped on rows that the operator cancelled
# via ``POST /v1/call-imports/{id}/rows/{row_id}/cancel-diarisation``.
# Kept in sync with :data:`app.api.v1.routes.call_imports.CANCELLED_BY_USER_ERROR`
# — duplicated here so the worker doesn't have to import the route
# module (which would pull FastAPI / Pydantic into the worker boot
# path). Touching either copy means touching both.
_CANCELLED_BY_USER_ERROR: str = "Diarisation cancelled by user"


def _was_cancelled_externally(db, row) -> bool:
    """Re-read ``row`` from the DB and return True if it was cancelled.

    Used by every terminal-status write in this task so an external
    cancel (which flips the row to ``failed`` + sets
    :data:`_CANCELLED_BY_USER_ERROR`) WINS THE RACE against a worker
    that's already past its slowest operation (LLM call / S3 download)
    and is about to overwrite the row with its own terminal state.

    Why ``db.expire`` + ``refresh``: the worker's SQLAlchemy session
    cached the row when it pulled it for the run, so a parallel
    update from the FastAPI process is invisible until we explicitly
    re-read. We expire just the two columns we care about so other
    in-flight modifications on the same row aren't clobbered.
    """
    try:
        db.expire(
            row,
            [
                "diarised_transcript_status",
                "diarised_transcript_error",
            ],
        )
        db.refresh(
            row,
            attribute_names=[
                "diarised_transcript_status",
                "diarised_transcript_error",
            ],
        )
    except Exception:  # noqa: BLE001 — refresh is best-effort
        return False
    return (
        (row.diarised_transcript_status or "").lower() == "failed"
        and (row.diarised_transcript_error or "") == _CANCELLED_BY_USER_ERROR
    )


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
    stt_provider: Optional[str] = None,
    stt_model: Optional[str] = None,
    credential_id: Optional[str] = None,
    language: Optional[str] = None,
    overwrite_existing: bool = False,
    run_eval_row_id: Optional[str] = None,
    diarization_llm_provider: Optional[str] = None,
    diarization_llm_model: Optional[str] = None,
    diarization_llm_credential_id: Optional[str] = None,
    diarization_prompt: Optional[str] = None,
    mode: str = "stt_llm",
    eval_restricted_metric_ids: Optional[List[str]] = None,
):
    """Diarise a single row's recording.

    Skips rows with no S3 recording, or with an existing diarised
    transcript when ``overwrite_existing`` is False. Errors are recorded
    on the row (``diarised_transcript_status='failed'`` +
    ``diarised_transcript_error``) so the UI can surface a per-row
    diagnostic without polling Celery directly. The CSV-supplied
    production ``transcript`` is never touched by this task.

    Two pipeline shapes:

    * ``mode="stt_llm"`` (default, backward-compat) — STT produces plain
      text, then ``diarization_llm_*`` splits it into structured
      ``agent`` / ``user`` turns. ``stt_provider`` / ``stt_model`` are
      required in this mode.
    * ``mode="llm_only"`` — STT is skipped; the audio bytes are sent
      directly to a multimodal ``diarization_llm_*`` model along with
      ``diarization_prompt`` for a single-pass transcribe + diarise.
      The STT kwargs are ignored.

    The ``diarization_llm_*`` kwargs identify the chat model that
    produces the structured turns. They are required in both modes:
    the worker fails the row when either ``diarization_llm_provider``
    or ``diarization_llm_model`` is missing.
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

        existing_diarised = (row.diarised_transcript or "").strip()
        if existing_diarised and not overwrite_existing:
            row.diarised_transcript_status = "completed"
            db.commit()
            return {
                "status": "skipped",
                "reason": "transcript_present",
                "row_id": row_id,
            }

        recording_key = (row.recording_s3_key or "").strip()
        if not recording_key:
            row.diarised_transcript_status = "failed"
            row.diarised_transcript_error = (
                "No recording available for this row; cannot diarise."
            )
            db.commit()
            return {"status": "skipped", "reason": "no_recording"}

        # Validate / normalise mode up-front so an invalid value
        # surfaces a typed error on the row instead of being silently
        # treated as legacy behavior.
        normalised_mode = (mode or "stt_llm").strip().lower()
        if normalised_mode not in {"stt_llm", "llm_only"}:
            row.diarised_transcript_status = "failed"
            row.diarised_transcript_error = (
                f"Unknown diarisation mode '{mode}'. Expected "
                "'stt_llm' or 'llm_only'."
            )
            db.commit()
            return {"status": "failed", "reason": "unknown_mode"}

        # STT provider validation only matters in the two-stage path.
        # In ``llm_only`` we skip it entirely so the user doesn't even
        # need an STT credential configured.
        provider_enum: Optional[ModelProvider] = None
        if normalised_mode == "stt_llm":
            if not stt_provider or not stt_model:
                row.diarised_transcript_status = "failed"
                row.diarised_transcript_error = (
                    "STT provider/model not configured. Pick an STT "
                    "model in the Diarise modal."
                )
                db.commit()
                return {"status": "failed", "reason": "missing_stt"}
            try:
                provider_enum = ModelProvider(stt_provider.lower())
            except ValueError:
                row.diarised_transcript_status = "failed"
                row.diarised_transcript_error = (
                    f"Unknown STT provider '{stt_provider}'."
                )
                db.commit()
                return {"status": "failed", "reason": "unknown_provider"}

        # The LLM diariser is mandatory in BOTH modes: the two-stage
        # path needs it to split STT output into turns, and the
        # single-stage path uses it as the transcriber+diariser. We
        # surface a typed failure on the row when the caller forgot
        # to pick a model so the modal can show a specific banner
        # instead of a generic celery error.
        llm_provider_value = (diarization_llm_provider or "").strip()
        llm_model_value = (diarization_llm_model or "").strip()
        if not llm_provider_value or not llm_model_value:
            row.diarised_transcript_status = "failed"
            row.diarised_transcript_error = (
                "Diarisation LLM provider/model not configured. Pick "
                "a chat model in the Diarise modal."
            )
            db.commit()
            return {"status": "failed", "reason": "missing_llm_diariser"}

        row.diarised_transcript_status = "running"
        row.diarised_transcript_error = None
        # Record which provider/model the user asked for *now* (rather
        # than only on success) so the per-row error banner can show
        # "Failed on deepgram/deepgram-nova-3" without the user having
        # to remember what they picked in the modal. In ``llm_only``
        # mode there is no STT, so we stamp a sentinel value that the
        # UI can render as "LLM only" instead of pretending an STT
        # provider was used.
        if normalised_mode == "stt_llm" and provider_enum is not None:
            row.diarised_transcript_provider = provider_enum.value
            row.diarised_transcript_model = stt_model
        else:
            row.diarised_transcript_provider = "llm_only"
            row.diarised_transcript_model = llm_model_value
        row.diarised_llm_provider = llm_provider_value
        row.diarised_llm_model = llm_model_value
        try:
            llm_credential_uuid = (
                UUID(diarization_llm_credential_id)
                if diarization_llm_credential_id
                else None
            )
        except (TypeError, ValueError):
            llm_credential_uuid = None
        row.diarised_llm_credential_id = llm_credential_uuid
        row.celery_task_id = self.request.id
        db.commit()

        # The diariser helper resolves the canonical default when the
        # caller leaves ``diarization_prompt`` blank. We materialise
        # the effective string here so both the helper call AND the
        # row's audit trail use the same value.
        from app.workers.tasks.helpers.llm_diarisation import (
            DEFAULT_DIARIZATION_PROMPT,
            LLMDiarisationError,
            diarize_audio_with_llm,
            diarize_transcript_with_llm,
        )

        effective_prompt = (diarization_prompt or "").strip() or (
            DEFAULT_DIARIZATION_PROMPT
        )
        row.diarised_prompt = effective_prompt

        if normalised_mode == "stt_llm":
            # ---- Two-stage path: STT then LLM diarise ---------------
            # Lazy import — TranscriptionService transitively pulls in
            # torch / pyannote / librosa, and we don't want to pay
            # that cost at worker boot if the queue is idle.
            from app.services.ai.transcription_service import (
                transcription_service,
            )

            try:
                credential_uuid = UUID(credential_id) if credential_id else None
            except (TypeError, ValueError):
                credential_uuid = None

            try:
                assert provider_enum is not None  # narrowed above
                result = transcription_service.transcribe(
                    audio_file_key=recording_key,
                    stt_provider=provider_enum,
                    stt_model=stt_model,
                    organization_id=row.organization_id,
                    db=db,
                    language=language,
                    # We diarise via an LLM in a second pass below, so
                    # the STT call only needs to produce plain text.
                    # Skipping pyannote here avoids the HuggingFace-
                    # token / speaker-count guesswork that the old
                    # path required.
                    enable_speaker_diarization=False,
                    credential_id=credential_uuid,
                )
            except Exception as exc:  # noqa: BLE001 - want message on the row
                logger.exception(
                    "transcribe_call_import_row failed for row {}", row_id
                )
                if _was_cancelled_externally(db, row):
                    logger.info(
                        "Row {} was cancelled by the user mid-flight; "
                        "preserving cancelled state instead of writing "
                        "STT failure.",
                        row_id,
                    )
                    return {"status": "cancelled", "reason": "cancelled_by_user"}
                row.diarised_transcript_status = "failed"
                row.diarised_transcript_error = _summarize_exc(exc)
                db.commit()
                return {"status": "failed", "reason": "transcription_error"}

            plain_text = (result.get("transcript") or "").strip() or None
            if not plain_text:
                if _was_cancelled_externally(db, row):
                    return {"status": "cancelled", "reason": "cancelled_by_user"}
                row.diarised_transcript_status = "failed"
                row.diarised_transcript_error = (
                    "Transcription returned an empty result."
                )
                db.commit()
                return {"status": "failed", "reason": "empty_transcript"}

            try:
                raw_turns = diarize_transcript_with_llm(
                    plain_text,
                    llm_provider=llm_provider_value,
                    llm_model=llm_model_value,
                    organization_id=row.organization_id,
                    db=db,
                    custom_prompt=effective_prompt,
                    credential_id=llm_credential_uuid,
                )
            except LLMDiarisationError as exc:
                logger.warning(
                    "LLM diarisation failed for row {}: {}", row_id, exc
                )
                if _was_cancelled_externally(db, row):
                    return {"status": "cancelled", "reason": "cancelled_by_user"}
                row.diarised_transcript_status = "failed"
                row.diarised_transcript_error = str(exc)
                db.commit()
                return {"status": "failed", "reason": "llm_diarisation_error"}
            except Exception as exc:  # noqa: BLE001 — same surfacing as STT
                logger.exception(
                    "LLM diarisation crashed for row {}", row_id
                )
                if _was_cancelled_externally(db, row):
                    return {"status": "cancelled", "reason": "cancelled_by_user"}
                row.diarised_transcript_status = "failed"
                row.diarised_transcript_error = _summarize_exc(exc)
                db.commit()
                return {"status": "failed", "reason": "llm_diarisation_error"}
        else:
            # ---- Single-stage path: audio straight to multimodal LLM
            # Download the recording bytes once and hand them off to
            # the multimodal helper. We deliberately keep this branch
            # short — all provider-specific shaping lives in the
            # helper so adding e.g. Anthropic audio support later is
            # a one-file change.
            from app.services.storage.s3_service import s3_service

            try:
                audio_bytes = s3_service.download_file_by_key(recording_key)
            except Exception as exc:  # noqa: BLE001 — surfaced to the row
                logger.exception(
                    "Failed to fetch recording for LLM-only diarise on row {}",
                    row_id,
                )
                if _was_cancelled_externally(db, row):
                    return {"status": "cancelled", "reason": "cancelled_by_user"}
                row.diarised_transcript_status = "failed"
                row.diarised_transcript_error = (
                    "Failed to download recording from storage: "
                    f"{_summarize_exc(exc)}"
                )
                db.commit()
                return {"status": "failed", "reason": "recording_download_error"}

            try:
                raw_turns = diarize_audio_with_llm(
                    audio_bytes,
                    llm_provider=llm_provider_value,
                    llm_model=llm_model_value,
                    organization_id=row.organization_id,
                    db=db,
                    custom_prompt=effective_prompt,
                    credential_id=llm_credential_uuid,
                    audio_file_key=recording_key,
                )
            except LLMDiarisationError as exc:
                logger.warning(
                    "LLM-only diarisation failed for row {}: {}", row_id, exc
                )
                if _was_cancelled_externally(db, row):
                    return {"status": "cancelled", "reason": "cancelled_by_user"}
                row.diarised_transcript_status = "failed"
                row.diarised_transcript_error = str(exc)
                db.commit()
                return {
                    "status": "failed",
                    "reason": "llm_only_diarisation_error",
                }
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "LLM-only diarisation crashed for row {}", row_id
                )
                if _was_cancelled_externally(db, row):
                    return {"status": "cancelled", "reason": "cancelled_by_user"}
                row.diarised_transcript_status = "failed"
                row.diarised_transcript_error = _summarize_exc(exc)
                db.commit()
                return {
                    "status": "failed",
                    "reason": "llm_only_diarisation_error",
                }

        turns = _segments_to_user_agent_turns(raw_turns)

        # Guard against pseudo-diarisation: when the LLM emits a single
        # speaker for the whole call we treat it the same as the
        # legacy pyannote-unavailable fallback — store the plain text
        # without speaker prefixes so the UI doesn't show a misleading
        # ``agent: <everything>`` chat bubble.
        distinct_roles = {turn.get("speaker") for turn in turns}
        has_real_diarisation = len(distinct_roles - {None, ""}) >= 2
        rendered_turns = (
            _render_turns_as_text(turns, swap=False)
            if turns and has_real_diarisation
            else ""
        )

        transcript_to_store = rendered_turns or plain_text

        # Persist into ``diarised_transcript`` so the CSV-supplied
        # production ``transcript`` is preserved as-is. The structured
        # turns are persisted alongside on ``diarised_segments`` so the
        # swap endpoint can re-render without re-running diarisation.
        # We always reset ``diarised_speaker_swap`` to False on a fresh
        # diarisation run — the heuristic is applied at write time so
        # any prior swap flip is no longer meaningful for the new turns.
        # ``diarised_segments`` is only populated when real diarisation
        # happened — single-speaker fallback gets ``None`` so the swap
        # button stays hidden (nothing meaningful to swap).
        # Cancellation-aware finaliser: if the operator clicked "Stop
        # Diarisation" while we were inside the LLM call (the most
        # likely race window because the LLM call is by far the
        # longest synchronous step), the route handler will already
        # have flipped the row to ``failed`` + the cancellation
        # sentinel. Writing ``completed`` over the top would silently
        # swallow the user's intent, so we bail BEFORE the success
        # commit and just leave the cancelled state intact. This is
        # the only race window we actually need to guard — the error
        # branches above each do their own check before writing.
        if _was_cancelled_externally(db, row):
            logger.info(
                "Row {} was cancelled by the user mid-flight; "
                "skipping success write and preserving cancelled state.",
                row_id,
            )
            return {"status": "cancelled", "reason": "cancelled_by_user"}

        row.diarised_transcript = transcript_to_store
        row.diarised_segments = turns if has_real_diarisation else None
        row.diarised_speaker_swap = False
        # Re-stamp provider/model on success so the value matches the
        # path the row actually went through. In ``stt_llm`` mode this
        # is the STT provider/model; in ``llm_only`` mode we keep the
        # sentinel value set before the LLM call so the UI can render
        # "LLM only" without having to special-case missing fields.
        if normalised_mode == "stt_llm" and provider_enum is not None:
            row.diarised_transcript_provider = provider_enum.value
            row.diarised_transcript_model = stt_model
        row.transcribe_mode = normalised_mode
        row.diarised_transcript_status = "completed"
        row.diarised_transcript_error = None
        row.diarised_at = _now()
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

                # ``eval_restricted_metric_ids`` is set by the
                # metric-subset retry path so the chained evaluator
                # only recomputes the metrics the user selected
                # (merging into the row's existing ``metric_scores``).
                if eval_restricted_metric_ids:
                    evaluate_call_import_row_task.apply_async(
                        args=(run_eval_row_id,),
                        kwargs={
                            "restricted_metric_ids": eval_restricted_metric_ids,
                        },
                    )
                else:
                    evaluate_call_import_row_task.delay(run_eval_row_id)
            except Exception:
                logger.exception(
                    "Failed to enqueue post-transcribe eval row {}",
                    run_eval_row_id,
                )

        return {
            "status": "completed",
            "row_id": row_id,
            "mode": normalised_mode,
            "provider": provider_enum.value if provider_enum else "llm_only",
            "model": stt_model if normalised_mode == "stt_llm" else llm_model_value,
            "llm_provider": llm_provider_value,
            "llm_model": llm_model_value,
            "characters": len(transcript_to_store),
            "turn_count": len(turns) if has_real_diarisation else 0,
        }
    finally:
        db.close()
