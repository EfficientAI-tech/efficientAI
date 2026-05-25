"""Sarvam AI speech-to-text client.

Sarvam exposes two transcription surfaces and we use both, picked by the
audio duration:

* **REST ``/speech-to-text``** — synchronous, hard-capped at ~30 s of
  audio per request. Used for short clips (``<= _MAX_INLINE_SECONDS``).
* **Batch API** (``/speech-to-text/job/v1``) — async job that supports
  up to ~1 hour of audio. Used for everything longer. We drive it
  through the ``sarvamai`` SDK (``client.speech_to_text_job.create_job``
  → ``upload_files`` → ``start`` → ``wait_until_complete`` →
  ``download_outputs``) and read the per-file transcript JSON Sarvam
  drops in the output directory.

Why batch (not the pydub chunk-and-loop we used to do): Sarvam's docs
are explicit that the REST endpoint is for clips ``< 30 s`` and that
longer audio MUST go through the batch flow. The old chunking path
re-encoded at the source sample rate (5+ MB per 28 s WAV chunk),
swallowed Sarvam's error bodies on ``raise_for_status``, never sent
``mode`` for ``saaras:v3`` (which requires it), and turned every
transient per-chunk 4xx into a whole-row failure. Batch sidesteps
all four issues with a single SDK-mediated job.

Model-family quirks we encode here:

* ``saarika:*`` — legacy STT model. ``language_code`` is supported
  (or ``"unknown"`` for auto-detect). No ``mode`` parameter.
* ``saaras:*`` — current STT model. Accepts ``language_code`` (Sarvam
  even ships extra Indic codes for it) AND requires a ``mode`` value
  (``transcribe`` / ``translate`` / ``verbatim`` / ``transliterate``
  / ``codemix``). We unconditionally send ``mode="transcribe"`` because
  the call-import pipeline only ever wants plain text — diarisation
  runs as a separate LLM pass downstream.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)

SARVAM_STT_URL = "https://api.sarvam.ai/speech-to-text"

# Anything at or below this duration goes through the synchronous REST
# endpoint. Sarvam's documented cap is 30 s; the 2 s safety margin
# absorbs minor pydub duration-probe rounding so we never hand Sarvam
# a ~30.1 s clip and get a 400 in return.
_MAX_INLINE_SECONDS = 28

# Wall-clock budget for a batch job (upload + queue + processing).
# Picked to comfortably fit inside the worker's Celery
# ``soft_time_limit`` (currently 12 min in
# :mod:`app.workers.tasks.transcribe_call_import_row`) with headroom
# for the downstream LLM diarisation pass on the resulting transcript.
_BATCH_WAIT_SECONDS = 8 * 60

# How often we poll Sarvam for batch job status. 5 s matches the SDK
# default and is gentle on the API while still surfacing
# completed/failed states promptly for short jobs.
_BATCH_POLL_INTERVAL_SECONDS = 5


def _model_uses_saaras(model: str) -> bool:
    """Return True if ``model`` is in the ``saaras`` family.

    Used by both the REST and batch paths to decide whether to send
    the required ``mode`` parameter. We match on lowercased ``saaras``
    so any future ``saaras:v4`` / ``saaras-foo`` variants opt in
    automatically.
    """
    return "saaras" in (model or "").lower()


def _sarvam_mode_for(model: str) -> Optional[str]:
    """Return the ``mode`` value to send for ``model`` (or ``None``).

    Only ``saaras:*`` models accept (and effectively require) a mode.
    We always pick ``"transcribe"`` because every call site in this
    codebase wants plain text — translation / transliteration are
    surfaced as separate, deliberate operator workflows elsewhere.
    """
    return "transcribe" if _model_uses_saaras(model) else None


def _humanise_sarvam_http_error(exc: httpx.HTTPStatusError) -> str:
    """Build an actionable error string from a Sarvam HTTP failure.

    httpx's default ``HTTPStatusError`` only includes the status line
    and URL; Sarvam's actual JSON body (``{"error": {"code": ...,
    "message": ...}}``) is what tells us WHY the call failed
    (``invalid_request_error``, ``unprocessable_entity_error``,
    ``insufficient_quota_error``, …). We re-format with the parsed
    body when present and fall back to the raw text otherwise so
    nothing useful is dropped on the floor.
    """
    resp = exc.response
    status = resp.status_code if resp is not None else "?"
    body = ""
    code = ""
    message = ""
    if resp is not None:
        try:
            payload = resp.json()
            err = payload.get("error") if isinstance(payload, dict) else None
            if isinstance(err, dict):
                code = str(err.get("code") or "").strip()
                message = str(err.get("message") or "").strip()
            if not message:
                # Some Sarvam endpoints return ``{"detail": "..."}``
                # for FastAPI-style validation failures.
                detail = payload.get("detail") if isinstance(payload, dict) else None
                if isinstance(detail, str):
                    message = detail.strip()
            body = json.dumps(payload)[:600]
        except ValueError:
            body = (resp.text or "")[:600]

    pieces = [f"Sarvam STT HTTP {status}"]
    if code:
        pieces.append(code)
    if message:
        pieces.append(message)
    rendered = " - ".join(pieces)
    if body and not message:
        rendered = f"{rendered} (body: {body})"
    return rendered


def _sarvam_post_chunk(
    file_path: str,
    model: str,
    api_key: str,
    language: Optional[str],
) -> Dict[str, Any]:
    """POST a single short clip (``<= _MAX_INLINE_SECONDS``) and return JSON.

    Mirrors Sarvam's REST contract: ``api-subscription-key`` header,
    multipart form with ``model`` / ``file`` (and optionally
    ``language_code`` / ``mode``).
    """
    headers = {"api-subscription-key": api_key}
    data: Dict[str, Any] = {"model": model}
    if language:
        # Sarvam accepts ``language_code`` like ``hi-IN`` / ``en-IN``
        # (or ``"unknown"`` for auto-detect). Both saarika and saaras
        # accept it, so we forward unconditionally.
        data["language_code"] = language

    mode = _sarvam_mode_for(model)
    if mode is not None:
        # Required by ``saaras:v3``. Sending it for ``saarika`` would
        # be rejected, which is why this is model-gated.
        data["mode"] = mode

    with open(file_path, "rb") as f:
        files = {
            "file": (
                os.path.basename(file_path) or "audio.wav",
                f,
                "audio/wav",
            ),
        }
        with httpx.Client(timeout=120.0) as client:
            resp = client.post(
                SARVAM_STT_URL,
                headers=headers,
                data=data,
                files=files,
            )
            try:
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                # Re-raise as RuntimeError so the call-import worker
                # surfaces a meaningful ``diarised_transcript_error``
                # instead of the bare ``HTTPStatusError`` repr (which
                # buries the actual Sarvam ``error.code`` /
                # ``error.message``).
                raise RuntimeError(_humanise_sarvam_http_error(exc)) from exc
            return resp.json()


def _extract_text_from_batch_output(output_path: str) -> tuple[str, Optional[str]]:
    """Parse a Sarvam batch transcript JSON file → ``(text, language_code)``.

    The batch API writes one JSON document per input file in the same
    shape the REST endpoint returns (``transcript`` + optional
    ``language_code`` + ``diarized_transcript`` + ``timestamps``).
    We only need the plain transcript text and the detected language;
    diarisation is handled downstream by an LLM pass.

    Returns ``("", None)`` for files we can't parse so a single bad
    output doesn't abort the entire job — the caller's "no transcript
    produced" guard surfaces the right error.
    """
    try:
        with open(output_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning(
            "[sarvam] could not parse batch output %s: %s", output_path, exc
        )
        return "", None

    if not isinstance(payload, dict):
        return "", None

    # Sarvam's batch output for STT modes uses ``transcript`` like the
    # REST endpoint. ``saaras`` translation modes occasionally return
    # the text under ``translation`` instead; we accept either so a
    # future operator-driven mode switch doesn't silently drop text.
    text = (
        payload.get("transcript")
        or payload.get("translation")
        or ""
    )
    text = text.strip() if isinstance(text, str) else ""
    language_code = payload.get("language_code")
    if not isinstance(language_code, str):
        language_code = None
    return text, language_code


def _transcribe_sarvam_batch(
    audio_file_path: str,
    model: str,
    api_key: str,
    language: Optional[str],
) -> Dict[str, Any]:
    """Transcribe a long recording via Sarvam's Batch API.

    Drives ``client.speech_to_text_job.create_job`` →
    ``upload_files`` → ``start`` → ``wait_until_complete`` →
    ``download_outputs`` synchronously, then reads the resulting
    transcript JSON and returns the same dict shape as
    :func:`_sarvam_post_chunk` so callers don't have to know which
    path ran.

    Failure handling:
    * ``TimeoutError`` from ``wait_until_complete`` → ``RuntimeError``
      with the job id and budget so operators can either retry or
      pick a different STT provider for that row.
    * Job state ``Failed`` → ``RuntimeError`` with the per-file
      ``error_message`` Sarvam attaches to each task detail.
    * No successful files / empty transcripts → ``RuntimeError``
      listing what Sarvam returned, so the row's
      ``diarised_transcript_error`` is actionable.
    """
    try:
        from sarvamai import SarvamAI
    except ImportError as exc:  # pragma: no cover - guarded by pyproject
        raise RuntimeError(
            "sarvamai SDK is required for long-audio Sarvam transcription "
            "but is not installed."
        ) from exc

    client = SarvamAI(api_subscription_key=api_key)

    # ``language_code=None`` is fine for both saarika and saaras: the
    # SDK simply omits the field, which lets Sarvam auto-detect. We
    # only forward an explicit code when the caller supplied one.
    job_kwargs: Dict[str, Any] = {"model": model}
    if language:
        job_kwargs["language_code"] = language
    mode = _sarvam_mode_for(model)
    if mode is not None:
        job_kwargs["mode"] = mode

    output_dir = tempfile.mkdtemp(prefix="sarvam_batch_out_")
    job_id: Optional[str] = None
    try:
        try:
            job = client.speech_to_text_job.create_job(**job_kwargs)
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(_humanise_sarvam_http_error(exc)) from exc
        job_id = job.job_id
        logger.info(
            "[sarvam] batch job %s created (model=%s, mode=%s, language=%s)",
            job_id,
            model,
            mode,
            language,
        )

        try:
            job.upload_files(file_paths=[audio_file_path])
            job.start()
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(
                f"Sarvam batch upload/start failed for job {job_id}: "
                f"{_humanise_sarvam_http_error(exc)}"
            ) from exc

        try:
            final_status = job.wait_until_complete(
                poll_interval=_BATCH_POLL_INTERVAL_SECONDS,
                timeout=_BATCH_WAIT_SECONDS,
            )
        except TimeoutError as exc:
            raise RuntimeError(
                f"Sarvam batch job {job_id} did not complete within "
                f"{_BATCH_WAIT_SECONDS} seconds; retry or use a different "
                "STT provider for this row."
            ) from exc

        state = (final_status.job_state or "").lower()
        if state != "completed":
            # Surface per-file error messages when present — Sarvam
            # often fails the job at the file level (e.g. unsupported
            # codec, audio too long) and that detail is what tells the
            # operator how to fix the row.
            file_results = job.get_file_results()
            failed = file_results.get("failed") or []
            failure_detail = "; ".join(
                f"{f.get('file_name', '?')}: {f.get('error_message', '?')}"
                for f in failed
            )
            raise RuntimeError(
                f"Sarvam batch job {job_id} ended in state '{state}'."
                + (f" Failures: {failure_detail}" if failure_detail else "")
            )

        try:
            job.download_outputs(output_dir=output_dir)
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(
                f"Sarvam batch download failed for job {job_id}: "
                f"{_humanise_sarvam_http_error(exc)}"
            ) from exc

        # The SDK writes one ``<input_basename>.json`` per processed
        # file. We uploaded exactly one input so this is normally a
        # single file, but we walk the directory defensively in case
        # the SDK adopts a different naming convention in a future
        # release.
        transcripts: list[str] = []
        detected_lang: Optional[str] = None
        for name in sorted(os.listdir(output_dir)):
            if not name.lower().endswith(".json"):
                continue
            text, lang = _extract_text_from_batch_output(
                os.path.join(output_dir, name)
            )
            if text:
                transcripts.append(text)
            if detected_lang is None and lang:
                detected_lang = lang

        full_text = " ".join(transcripts).strip()
        if not full_text:
            raise RuntimeError(
                f"Sarvam batch job {job_id} completed but produced no "
                "transcript text."
            )

        return {
            "text": full_text,
            "language": detected_lang or language or "en",
            "segments": [],
        }
    finally:
        # Best-effort cleanup; transcript JSONs are tiny but we still
        # don't want to leak temp dirs across worker restarts.
        for name in os.listdir(output_dir) if os.path.isdir(output_dir) else []:
            try:
                os.unlink(os.path.join(output_dir, name))
            except OSError:
                pass
        try:
            os.rmdir(output_dir)
        except OSError:
            pass


def transcribe_sarvam(
    audio_file_path: str,
    model: str,
    api_key: str,
    language: Optional[str] = None,
) -> Dict[str, Any]:
    """Transcribe an audio file via Sarvam, picking REST vs batch by length.

    Routing:

    * ``duration <= _MAX_INLINE_SECONDS`` → REST ``/speech-to-text``
      (synchronous, low latency).
    * Anything longer (or when the pydub duration probe fails) →
      Batch API via the ``sarvamai`` SDK, capped at
      ``_BATCH_WAIT_SECONDS`` of wall-clock wait time.

    Returns ``{"text": str, "language": str, "segments": []}``. The
    ``segments`` list is intentionally empty — speaker segmentation is
    handled by the LLM diariser in
    :mod:`app.workers.tasks.transcribe_call_import_row`, not by
    Sarvam, regardless of which Sarvam path produced the text.
    """
    chosen_model = (model or "saarika:v2.5").strip() or "saarika:v2.5"

    # Cheaply probe duration to decide the routing. If the probe
    # fails we route to batch — batch handles short audio fine and
    # also gives us the actual Sarvam error body if something else is
    # wrong, whereas the REST path would just fail again on >30 s.
    duration_seconds: Optional[float] = None
    try:
        from pydub import AudioSegment

        duration_seconds = (
            AudioSegment.from_file(audio_file_path).duration_seconds
        )
    except Exception as e:  # noqa: BLE001 - probing only
        logger.warning(
            "[sarvam] could not probe audio duration (%s); routing to batch",
            e,
        )

    if duration_seconds is not None and duration_seconds <= _MAX_INLINE_SECONDS:
        result = _sarvam_post_chunk(
            audio_file_path, chosen_model, api_key, language
        )
        text = (result.get("transcript") or "").strip()
        return {
            "text": text,
            "language": result.get("language_code") or language or "en",
            "segments": [],
        }

    logger.info(
        "[sarvam] routing to batch API (duration=%s, model=%s)",
        duration_seconds,
        chosen_model,
    )
    return _transcribe_sarvam_batch(
        audio_file_path, chosen_model, api_key, language
    )
