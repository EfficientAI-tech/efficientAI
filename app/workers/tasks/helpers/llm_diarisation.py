"""LLM-based diarisation helper.

The call-import pipeline used to lean on pyannote (or a brittle gap
heuristic) to assign speaker turns to a transcript. Both required the
STT provider to surface segments AND a working HuggingFace token, and
the result was a generic ``Speaker 1`` / ``Speaker 2`` labelling that
the rest of the pipeline had to re-map to ``agent`` / ``user`` anyway.

This module replaces that path with an LLM call: once the STT provider
has produced a plain transcript, we hand the text + a caller-supplied
diarisation prompt to a chat model and ask it to return structured
turns. The default prompt is exposed via :data:`DEFAULT_DIARIZATION_PROMPT`
so the UI can pre-fill the modal's textarea while still letting the
operator tweak it per run.

Design notes:

* The prompt is the operator's contract with the model — we don't try
  to enforce the schema by post-processing it back into a different
  shape. We do, however, validate the *output* (JSON array of objects
  with ``speaker`` + ``text``) and surface a clean error when the model
  ignores the schema, so the worker can report a typed failure on the
  row instead of crashing. The validator is lenient about key names
  (``utterance``/``content``/``message``/etc. all map to ``text``) so a
  slightly off-spec response still routes through.
* JSON mode is requested at the LLM layer
  (``response_format={"type": "json_object"}``) so OpenAI / Gemini
  are constrained to valid JSON; providers that don't recognise the
  flag drop it silently. The user-message wrapper asks for
  ``{"turns": [...]}`` (top-level object) because OpenAI JSON mode
  rejects bare arrays; the parser handles both shapes.
* The default prompt (:data:`DEFAULT_DIARIZATION_PROMPT`) explicitly
  defers to operator instructions for any text transformation
  (translation, paraphrasing, summarisation), so an operator can
  append "translate to English" to the textarea without fighting the
  default verbatim rule.
* Synthetic monotonically increasing ``start`` / ``end`` floats are
  attached to each turn so downstream code that wants to order turns
  by time (e.g. the existing first-speaker-is-agent heuristic in
  :mod:`app.workers.tasks.transcribe_call_import_row`) keeps working
  without special-casing the LLM path.
* The helper never persists anything — callers own the row update so
  the transcribe task remains the single owner of ``CallImportRow``
  state transitions.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional
from uuid import UUID

from loguru import logger
from sqlalchemy.orm import Session

from app.models.enums import ModelProvider
from app.services.ai.llm_service import llm_service


DEFAULT_DIARIZATION_PROMPT = (
    "You are a transcript diariser. Split the following raw call "
    "transcript into chronological speaker turns.\n\n"
    "Rules:\n"
    "1. Assume there are TWO speakers: an `agent` (call-centre / "
    "support / outbound caller) and a `user` (customer / callee). "
    "The first turn is almost always the agent because outbound and "
    "inbound calls open with an agent greeting.\n"
    "2. Use ONLY the labels `agent` and `user`. Do not invent other "
    "labels, even if the call has more than two voices — collapse "
    "extra parties into whichever of `agent` / `user` they are "
    "most semantically aligned with.\n"
    "3. By default, each turn's `text` should be the speaker's "
    "original words with only whitespace normalised — no "
    "paraphrasing, translation, or summarisation. HOWEVER, if the "
    "operator's instructions appended after these rules request "
    "translation, paraphrasing, summarisation, or any other text "
    "transformation, follow THOSE instructions when producing the "
    "`text` field. Operator instructions take precedence over this "
    "default.\n"
    "4. Preserve the original turn order regardless of any text "
    "transformation requested in rule 3. When no transformation is "
    "requested, the concatenation of every turn's `text`, in order, "
    "should be a near-lossless reconstruction of the input.\n"
    "5. Use exactly the keys `speaker` and `text` in each entry. "
    "Do NOT substitute `content`, `utterance`, `message`, `role`, "
    "`dialog`, `line`, etc., even if the operator's instructions "
    "imply a different shape.\n\n"
    "Return ONLY a JSON object with a single key `turns` whose "
    "value is the array of turn objects, no prose, no markdown "
    "fence. Each entry must have exactly the keys `speaker` "
    "(\"agent\" or \"user\") and `text` (string). Example:\n"
    "{\"turns\": [{\"speaker\": \"agent\", \"text\": \"Hello, this "
    "is Acme support.\"}, {\"speaker\": \"user\", \"text\": \"Hi, "
    "I have a billing question.\"}]}"
)


# How much of the prompt + transcript we'll feed to the LLM. We don't
# enforce a hard token cap (provider-specific) but we do clip the
# transcript so a 1 MB CSV cell can't blow up the prompt window.
_MAX_TRANSCRIPT_CHARS = 60_000


# Synonym keys we accept from over-creative LLMs that don't follow the
# canonical ``{"speaker": ..., "text": ...}`` schema verbatim. Without
# this leniency a model that emits ``{"speaker": "agent", "utterance":
# "Hello"}`` (very common with OpenAI/Gemini) would have every entry
# silently dropped because the validator only looked at ``text``,
# producing a misleading "empty / unusable turn list" error across
# providers. We pick the first non-empty string value out of each
# tuple so the strict schema is still preferred when the model honours
# it. The system prompt also explicitly forbids these synonyms (rule 5
# in ``DEFAULT_DIARIZATION_PROMPT``); the leniency below is a safety
# net for operator-customised prompts and lazy models.
_TEXT_KEYS: tuple[str, ...] = (
    "text",
    "utterance",
    "content",
    "message",
    "dialog",
    "dialogue",
    "line",
    "turn",
    "transcript",
    "words",
    "speech",
)
_SPEAKER_KEYS: tuple[str, ...] = (
    "speaker",
    "role",
    "who",
    "spk",
    "participant",
    "label",
)


def _first_nonempty_str(entry: Dict[str, Any], keys: tuple[str, ...]) -> str:
    """Return the stripped value of the first key in ``keys`` whose
    value is a non-empty string. Empty / missing keys yield ``""``.
    """
    for key in keys:
        value = entry.get(key)
        if isinstance(value, str):
            stripped = value.strip()
            if stripped:
                return stripped
    return ""


class LLMDiarisationError(RuntimeError):
    """Raised when the LLM diariser cannot produce valid structured turns."""


def _extract_json_array(text: str) -> Optional[list]:
    """Best-effort extraction of a JSON array from an LLM response.

    Tries the cheap-and-cheerful paths in order:

    1. The response is already a bare JSON array → ``json.loads``.
    2. The response is wrapped in a ``` ```json fence — strip the fence
       and parse the body.
    3. The response contains a JSON array somewhere in the middle —
       walk to the first ``[`` / last ``]`` and parse the slice.

    Returns ``None`` when nothing parses; the caller treats that as
    a hard failure and surfaces the raw output for debugging.
    """
    if not text:
        return None
    candidate = text.strip()

    try:
        parsed = json.loads(candidate)
        if isinstance(parsed, list):
            return parsed
    except json.JSONDecodeError:
        pass

    fence_match = re.search(
        r"```(?:json)?\s*(\[.*?\])\s*```", candidate, flags=re.DOTALL
    )
    if fence_match:
        try:
            parsed = json.loads(fence_match.group(1))
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            pass

    first_bracket = candidate.find("[")
    last_bracket = candidate.rfind("]")
    if first_bracket != -1 and last_bracket > first_bracket:
        slice_ = candidate[first_bracket : last_bracket + 1]
        try:
            parsed = json.loads(slice_)
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            return None

    return None


def _normalise_speaker_label(raw: Any) -> str:
    """Coerce a model-emitted speaker label into a canonical raw label.

    The downstream
    :func:`app.workers.tasks.transcribe_call_import_row._segments_to_user_agent_turns`
    helper expects ``Speaker 1`` / ``Speaker 2`` style raw labels (it
    maps the earliest-appearing label to ``agent`` deterministically).
    We collapse common variants here so a model that emits ``Agent`` or
    ``customer`` or ``S1`` still routes through the same heuristic.
    """
    text = str(raw or "").strip().lower()
    if not text:
        return "Speaker 1"

    if text in {"agent", "a", "representative", "rep", "support", "operator"}:
        return "Speaker 1"
    if text in {"user", "u", "customer", "caller", "client", "callee"}:
        return "Speaker 2"

    # ``speaker 1`` / ``speaker_1`` / ``speaker-1`` / ``s1``
    match = re.match(r"^(?:speaker[\s_\-]*|s)?(\d+)$", text)
    if match:
        return f"Speaker {int(match.group(1))}"

    # Anything else: preserve verbatim — the downstream mapper will
    # assign agent / user based on first-appearance order rather than
    # the literal label, so the exact string only matters as a stable
    # group key.
    return raw if isinstance(raw, str) and raw.strip() else "Speaker 1"


def diarize_transcript_with_llm(
    transcript: str,
    *,
    llm_provider: str,
    llm_model: str,
    organization_id: UUID,
    db: Session,
    custom_prompt: Optional[str] = None,
    credential_id: Optional[UUID] = None,
    temperature: float = 0.0,
) -> List[Dict[str, Any]]:
    """Ask an LLM to split ``transcript`` into ``agent`` / ``user`` turns.

    Returns a list of dicts shaped for
    :class:`app.workers.tasks.transcribe_call_import_row._segments_to_user_agent_turns`::

        [{ "speaker": "Speaker 1", "text": "...",
           "start": 0.0, "end": 1.0 }, ...]

    The synthetic ``start`` / ``end`` floats keep the downstream
    "first speaker is agent" heuristic deterministic (it sorts by
    ``start`` then label) without requiring the LLM to invent
    timestamps it can't actually produce.

    Parameters
    ----------
    transcript:
        Raw STT output. Empty / whitespace-only input short-circuits to
        ``[]``.
    llm_provider:
        ``ModelProvider`` value (``"openai"``, ``"anthropic"``, …). The
        worker resolves the API key via the standard org-scoped
        AIProvider lookup.
    llm_model:
        Concrete model name passed straight through to LiteLLM.
    organization_id, db:
        Forwarded to :func:`llm_service.generate_response` so it can
        decrypt the right credential row.
    custom_prompt:
        Operator-supplied system prompt. When empty / None, the
        :data:`DEFAULT_DIARIZATION_PROMPT` is used.
    credential_id:
        Optional AIProvider row to pin (multi-credential orgs).
    temperature:
        Forwarded to the LLM. Defaults to ``0.0`` so the same transcript
        diarises identically across retries — diarisation is a
        structured-output task, not a creative one.
    """

    cleaned = (transcript or "").strip()
    if not cleaned:
        return []

    if len(cleaned) > _MAX_TRANSCRIPT_CHARS:
        logger.warning(
            "diarize_transcript_with_llm: transcript is {} chars; "
            "truncating to {} for the LLM prompt.",
            len(cleaned),
            _MAX_TRANSCRIPT_CHARS,
        )
        cleaned = cleaned[:_MAX_TRANSCRIPT_CHARS]

    system_prompt = (custom_prompt or "").strip() or DEFAULT_DIARIZATION_PROMPT

    try:
        provider_enum = ModelProvider(llm_provider.lower())
    except ValueError as exc:
        raise LLMDiarisationError(
            f"Unknown LLM provider '{llm_provider}' for diarisation."
        ) from exc

    # The user message intentionally re-states the output contract as
    # a JSON OBJECT wrapper (``{"turns": [...]}``) rather than a bare
    # array. Two reasons:
    #
    # * OpenAI's JSON mode (``response_format={"type": "json_object"}``)
    #   requires the model to produce a top-level JSON object — a bare
    #   array is rejected. Asking for the wrapper here means JSON mode
    #   is safe to enable unconditionally even when an operator-
    #   customised system prompt asks for a bare array.
    # * The keyword "JSON" must appear somewhere in the conversation
    #   for OpenAI's JSON mode; this user message guarantees it even
    #   for custom prompts that omit it.
    #
    # The downstream parser (``_extract_json_array``) handles both the
    # wrapped object and a bare array via its bracket-scan fallback,
    # so a model that ignores the wrapper still flows through.
    messages = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": (
                "Diarise the following transcript. Return ONLY a JSON "
                "object with a single key `turns` whose value is the "
                "array of turn objects described in the system prompt "
                "— no prose, no markdown fence. Transcript:\n\n"
                f"{cleaned}"
            ),
        },
    ]

    # ``response_format={"type": "json_object"}`` is forwarded to
    # providers that support it (OpenAI JSON mode, Gemini's
    # ``responseMimeType``) and silently dropped by the rest because
    # ``litellm.drop_params=True`` is set globally in
    # :mod:`app.services.ai.llm_service`. Setting it unconditionally
    # nudges OpenAI/Gemini toward valid JSON without harming the
    # other providers.
    config = {"response_format": {"type": "json_object"}}

    response = llm_service.generate_response(
        messages=messages,
        llm_provider=provider_enum,
        llm_model=llm_model,
        organization_id=organization_id,
        db=db,
        temperature=temperature,
        credential_id=credential_id,
        config=config,
    )

    raw_text = (response.get("text") or "").strip()
    parsed = _extract_json_array(raw_text)
    if parsed is None:
        snippet = raw_text[:400].replace("\n", " ")
        raise LLMDiarisationError(
            "LLM diariser did not return a JSON array. Got: "
            f"{snippet}{'…' if len(raw_text) > 400 else ''}"
        )

    turns: List[Dict[str, Any]] = []
    cursor: float = 0.0
    for entry in parsed:
        # Two accepted entry shapes:
        #
        # * ``{"speaker": ..., "text": ...}`` — canonical, plus any
        #   alias from ``_TEXT_KEYS`` / ``_SPEAKER_KEYS`` so a model
        #   that emits ``utterance``/``content``/``role``/etc. still
        #   routes through.
        # * ``["agent", "Hello there"]`` — a 2-element list/tuple of
        #   strings, treated as ``(speaker, text)``. Some models
        #   collapse turns into this terser shape when nudged into
        #   JSON mode.
        #
        # Anything else (scalar, 3-tuple, list of lists with >2
        # elements) is dropped silently; the post-loop guard surfaces
        # a diagnostic error if every entry is dropped.
        if isinstance(entry, dict):
            text = _first_nonempty_str(entry, _TEXT_KEYS)
            raw_speaker_value = _first_nonempty_str(entry, _SPEAKER_KEYS)
        elif (
            isinstance(entry, (list, tuple))
            and len(entry) == 2
            and all(isinstance(part, str) for part in entry)
        ):
            raw_speaker_value = entry[0].strip()
            text = entry[1].strip()
        else:
            continue
        if not text:
            continue
        raw_speaker = _normalise_speaker_label(raw_speaker_value)
        turns.append(
            {
                "speaker": raw_speaker,
                "text": text,
                "start": round(cursor, 3),
                "end": round(cursor + 1.0, 3),
            }
        )
        cursor += 1.0

    if not turns:
        # Mirror the no-array error path above: include a snippet of
        # the raw model output so the operator can see WHICH key the
        # model picked instead of ``text`` (or which non-dict shape
        # it returned). Without this the error is identical for
        # every provider even when each is failing differently.
        snippet = raw_text[:400].replace("\n", " ")
        raise LLMDiarisationError(
            "LLM diariser returned a JSON array but no usable "
            "{speaker, text} entries. Got: "
            f"{snippet}{'…' if len(raw_text) > 400 else ''}"
        )

    return turns
