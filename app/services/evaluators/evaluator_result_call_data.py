"""Normalize CallRecording.call_data before storing on EvaluatorResult."""

from __future__ import annotations

from typing import Any, Dict

# Duplicated on EvaluatorResult.transcription / speaker_segments at enqueue time.
_TRANSCRIPT_DUPLICATE_KEYS = frozenset({"live_transcript", "messages", "transcript"})


def slim_call_data_for_evaluator_result(call_data: Any) -> Dict[str, Any]:
    """
    Drop transcript blobs from call_data on evaluator results.

    Telephony runs copy full CallRecording.call_data onto EvaluatorResult for
    metadata (numbers, hangup events, recording keys). Transcript text and turns
    live on ``transcription`` and ``speaker_segments`` on the result row.
    """
    if not isinstance(call_data, dict):
        return {}

    slim: Dict[str, Any] = {
        k: v for k, v in call_data.items() if k not in _TRANSCRIPT_DUPLICATE_KEYS
    }

    generated = slim.get("generated")
    if isinstance(generated, dict):
        gen = {k: v for k, v in generated.items() if k != "call_analysis"}
        if gen:
            slim["generated"] = gen
        else:
            slim.pop("generated", None)

    return slim
