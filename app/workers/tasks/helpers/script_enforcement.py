"""Detect non-Latin script in diariser output and surface it in logs.

Why this exists
---------------

``DEFAULT_DIARIZATION_PROMPT`` instructs the model to romanise Indic-
language speech into Latin script (Hinglish-style: "Main aap ki kya
sahayata kar sakthi hu" rather than the Devanagari original or an
English translation). Frontier multimodal models comply with that
rule the majority of the time, but Gemini 2.5 Flash / Flash Lite
specifically continue to emit Devanagari / Tamil / Telugu output on a
material fraction of Hinglish calls.

This module gives the diariser a deterministic detector so we can:

* See in logs exactly which rows violated the rule and which scripts
  leaked (Devanagari vs. Tamil vs. Telugu, …).
* Track compliance rate per provider/model over time without paying
  for any corrective LLM round-trip.

Why no automatic LLM retry
--------------------------

A previous iteration of this module fired a one-shot corrective LLM
call whenever an Indic script was detected. That doubles the LLM cost
for every offending row, and at 1000s of evaluations a day that adds
up fast — not worth the marginal compliance gain. The current
behaviour is detect-and-log only; operators who hit a row with
non-Latin transcript can manually re-run diarisation from the UI.

If retry compliance ever becomes desirable as an opt-in, the natural
extension point is to add a flag (e.g. ``ENABLE_CORRECTIVE_RETRY``)
that wraps a retry call here without changing any caller signature.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from loguru import logger


# Unicode ranges (inclusive) for the major Indic / South Asian scripts
# we want to flag as non-Latin output. Sourced from
# https://unicode.org/charts/. Keeping the list explicit (rather than
# checking ``unicodedata.script`` per-char) avoids the ``unicodedata2``
# soft-dep and stays fast even on long transcripts because the inner
# loop is a handful of integer comparisons.
#
# Notes on what we deliberately do NOT include:
#
# * ``Latin-1 Supplement`` (U+0080–U+00FF) and the various Latin
#   Extended blocks: those are diacritics on the Latin alphabet and
#   are perfectly valid in romanised Indic output (e.g. IAST).
# * ``Arabic`` (U+0600–U+06FF): Urdu calls in Nastaliq sometimes show
#   up here, but operators can write Urdu either in Arabic-derived
#   script or romanised; we intentionally don't force a script choice
#   for Urdu specifically because both are common in production. If
#   that becomes a problem the range can be added.
_INDIC_UNICODE_RANGES: Tuple[Tuple[int, int, str], ...] = (
    (0x0900, 0x097F, "Devanagari"),
    (0x0980, 0x09FF, "Bengali / Assamese"),
    (0x0A00, 0x0A7F, "Gurmukhi (Punjabi)"),
    (0x0A80, 0x0AFF, "Gujarati"),
    (0x0B00, 0x0B7F, "Oriya"),
    (0x0B80, 0x0BFF, "Tamil"),
    (0x0C00, 0x0C7F, "Telugu"),
    (0x0C80, 0x0CFF, "Kannada"),
    (0x0D00, 0x0D7F, "Malayalam"),
    (0x0D80, 0x0DFF, "Sinhala"),
    # Devanagari Extended + Vedic Extensions — rare in calls but
    # cheap to include.
    (0xA8E0, 0xA8FF, "Devanagari Extended"),
    (0x1CD0, 0x1CFF, "Vedic Extensions"),
)


def _classify_codepoint(cp: int) -> str:
    """Return the script name for a codepoint, or ``""`` if it's Latin/other."""
    for start, end, name in _INDIC_UNICODE_RANGES:
        if start <= cp <= end:
            return name
    return ""


def contains_indic_script(text: str) -> bool:
    """``True`` when ``text`` contains any character from an Indic block.

    Hot-path on the diariser: called once per turn after every LLM
    response. Bias-free toward Latin characters, ASCII, digits, and
    common punctuation — only the ranges in :data:`_INDIC_UNICODE_RANGES`
    trigger.
    """
    if not text:
        return False
    return any(_classify_codepoint(ord(ch)) for ch in text)


def script_summary(text: str) -> Dict[str, int]:
    """Return a ``{script_name: char_count}`` histogram for ``text``.

    ASCII / Latin characters are not counted — they are the desired
    output. Used both by :func:`find_violating_turns` and externally
    if a caller wants a breakdown on a single string.
    """
    counts: Dict[str, int] = {}
    for ch in text or "":
        name = _classify_codepoint(ord(ch))
        if name:
            counts[name] = counts.get(name, 0) + 1
    return counts


def find_violating_turns(
    turns: List[Dict[str, Any]],
) -> List[Tuple[int, Dict[str, int]]]:
    """List ``(index, script_counts)`` for every turn containing Indic chars.

    Returns an empty list when every turn is Latin-only.
    """
    out: List[Tuple[int, Dict[str, int]]] = []
    for idx, turn in enumerate(turns):
        text = turn.get("text") if isinstance(turn, dict) else None
        if not isinstance(text, str):
            continue
        counts = script_summary(text)
        if counts:
            out.append((idx, counts))
    return out


def log_script_violations(
    turns: List[Dict[str, Any]],
    *,
    log_label: str = "diariser",
) -> List[Dict[str, Any]]:
    """Detect Indic-script leaks and emit a structured log line.

    Returns ``turns`` unchanged. Splitting "detect" from "log" lets
    callers also build their own metric / per-row error message off
    the same data via :func:`find_violating_turns` if they want.

    Parameters
    ----------
    turns:
        Parsed turn list from the diariser.
    log_label:
        Tag included in the log line so the operator can tell text-
        path violations (``diarize_transcript_with_llm[…]``) apart
        from audio-path violations (``diarize_audio_with_llm[…]``).
    """
    violations = find_violating_turns(turns)
    if not violations:
        return turns

    distinct_scripts = sorted({s for _, c in violations for s in c})
    total_violating_chars = sum(
        count for _, counts in violations for count in counts.values()
    )
    logger.warning(
        "{}: detected non-Latin script in {} of {} turn(s) "
        "(scripts: {}, total non-Latin chars: {}); operator's "
        "SCRIPT NORMALISATION rule was not honoured by the model. "
        "Output is preserved as-is to avoid an automatic LLM retry — "
        "re-run diarisation manually if a romanised transcript is "
        "required.",
        log_label,
        len(violations),
        len(turns),
        ", ".join(distinct_scripts),
        total_violating_chars,
    )
    return turns
