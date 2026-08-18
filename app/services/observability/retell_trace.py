"""Build synthetic traces from Retell call report payloads."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.services.observability.vapi_trace import (
    _first_number,
    _normalize_role,
    _to_epoch_ms,
    _to_float,
)


def _latency_p50(latency: Dict[str, Any], key: str) -> Optional[float]:
    bucket = latency.get(key)
    if isinstance(bucket, dict):
        return _to_float(bucket.get("p50"))
    return None


def _extract_transcript_turns(call_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    transcript_object = call_data.get("transcript_object")
    if isinstance(transcript_object, list) and transcript_object:
        return [entry for entry in transcript_object if isinstance(entry, dict)]

    messages = call_data.get("messages")
    if isinstance(messages, list) and messages:
        turns = []
        for entry in messages:
            if not isinstance(entry, dict):
                continue
            role = entry.get("role")
            content = entry.get("content") or entry.get("message") or entry.get("text")
            if not content:
                continue
            turns.append({"role": role, "content": content, **entry})
        if turns:
            return turns

    transcript_raw = call_data.get("transcript")
    if isinstance(transcript_raw, list):
        return [entry for entry in transcript_raw if isinstance(entry, dict)]

    if isinstance(transcript_raw, str) and transcript_raw.strip():
        turns: List[Dict[str, Any]] = []
        for line in transcript_raw.split("\n"):
            stripped = line.strip()
            if not stripped:
                continue
            lower = stripped.lower()
            if lower.startswith("agent:"):
                turns.append({"role": "agent", "content": stripped.split(":", 1)[1].strip()})
            elif lower.startswith("user:"):
                turns.append({"role": "user", "content": stripped.split(":", 1)[1].strip()})
        if turns:
            return turns
    return []


def _turn_window_ms(
    entry: Dict[str, Any],
    *,
    started_at_ms: float,
    fallback_start_ms: float,
) -> tuple[float, float]:
    words = entry.get("words")
    if isinstance(words, list) and words:
        first_word = words[0] if isinstance(words[0], dict) else {}
        last_word = words[-1] if isinstance(words[-1], dict) else {}
        start_sec = _to_float(first_word.get("start"))
        end_sec = _to_float(last_word.get("end"))
        if start_sec is not None:
            end_sec = end_sec if end_sec is not None else start_sec
            return started_at_ms + start_sec * 1000.0, started_at_ms + end_sec * 1000.0

    for key in ("start_time", "timestamp", "start"):
        offset = _to_float(entry.get(key))
        if offset is None:
            continue
        start_ms = offset if offset > 1e10 else started_at_ms + offset * 1000.0
        end_offset = _first_number(entry.get("end_time"), entry.get("end"))
        if end_offset is not None:
            end_ms = end_offset if end_offset > 1e10 else started_at_ms + end_offset * 1000.0
        else:
            end_ms = start_ms + 800.0
        return start_ms, end_ms

    return fallback_start_ms, fallback_start_ms + 800.0


def build_retell_synthetic_trace(
    call_data: Dict[str, Any],
    *,
    provider_call_id: str,
) -> Optional[Dict[str, Any]]:
    """Convert Retell call report payload into a synthetic trace tree."""
    if not isinstance(call_data, dict):
        return None

    turns = _extract_transcript_turns(call_data)
    latency_stats = call_data.get("latency") if isinstance(call_data.get("latency"), dict) else {}

    has_any_signal = bool(turns) or bool(latency_stats)
    if not has_any_signal:
        return None

    started_at_ms = _to_epoch_ms(
        call_data.get("start_timestamp") or call_data.get("startedAt") or call_data.get("started_at")
    )
    ended_at_ms = _to_epoch_ms(
        call_data.get("end_timestamp") or call_data.get("endedAt") or call_data.get("ended_at")
    )
    duration_ms = _to_float(call_data.get("duration_ms"))
    duration_seconds = _to_float(call_data.get("duration_seconds"))

    if started_at_ms is None:
        started_at_ms = 0.0
    if ended_at_ms is None and duration_ms is not None:
        ended_at_ms = started_at_ms + duration_ms
    elif ended_at_ms is None and duration_seconds is not None:
        ended_at_ms = started_at_ms + duration_seconds * 1000.0
    if ended_at_ms is None:
        ended_at_ms = started_at_ms + max(1000.0, len(turns) * 1200.0)

    trace_id = f"retell-{provider_call_id}"
    root_span_id = f"retell-root-{provider_call_id}"
    root_span = {
        "span_id": root_span_id,
        "parent_span_id": None,
        "name": "conversation",
        "start_time": started_at_ms,
        "end_time": ended_at_ms,
        "duration_ms": max(ended_at_ms - started_at_ms, 0.0),
        "attributes": {
            "trace.provider": "retell",
            "provider.call_id": provider_call_id,
            "conversation.id": provider_call_id,
            "conversation.type": "provider_synthetic",
            "call.status": call_data.get("call_status") or call_data.get("status"),
        },
        "status": "1",
    }

    spans: List[Dict[str, Any]] = [root_span]
    cursor_ms = started_at_ms
    turn_span_ids: List[str] = []

    for idx, entry in enumerate(turns):
        role = _normalize_role(entry.get("role"))
        text = entry.get("content") or entry.get("text") or ""
        msg_start, msg_end = _turn_window_ms(entry, started_at_ms=started_at_ms, fallback_start_ms=cursor_ms)
        cursor_ms = max(cursor_ms, msg_end)

        span_id = f"retell-turn-{idx}"
        turn_span_ids.append(span_id)
        spans.append(
            {
                "span_id": span_id,
                "parent_span_id": root_span_id,
                "name": "turn",
                "start_time": msg_start,
                "end_time": msg_end,
                "duration_ms": max(msg_end - msg_start, 0.0),
                "attributes": {
                    "trace.provider": "retell",
                    "turn.number": idx + 1,
                    "turn.role": role,
                    "turn.text_length": len(str(text)),
                    **({"turn.user_transcript": text} if role == "user" and isinstance(text, str) and text.strip() else {}),
                    **({"turn.agent_transcript": text} if role == "agent" and isinstance(text, str) and text.strip() else {}),
                },
                "status": "1",
            }
        )

    layer_candidates = {
        "stt": _latency_p50(latency_stats, "asr"),
        "llm": _latency_p50(latency_stats, "llm"),
        "tts": _latency_p50(latency_stats, "tts"),
    }

    for layer, dur in layer_candidates.items():
        if dur is None:
            continue
        spans.append(
            {
                "span_id": f"retell-metric-{layer}",
                "parent_span_id": root_span_id,
                "name": layer,
                "start_time": started_at_ms,
                "end_time": started_at_ms + dur,
                "duration_ms": dur,
                "attributes": {
                    "trace.provider": "retell",
                    "metric.layer": layer,
                    "metric.scope": "call_average",
                },
                "status": "1",
            }
        )

    for idx, parent_span_id in enumerate(turn_span_ids):
        turn_span = spans[idx + 1]
        base_start = float(turn_span.get("start_time") or started_at_ms + idx * 1000.0)
        for layer, dur in layer_candidates.items():
            if dur is None:
                continue
            spans.append(
                {
                    "span_id": f"retell-turn-{idx}-metric-{layer}-estimated",
                    "parent_span_id": parent_span_id,
                    "name": layer,
                    "start_time": base_start,
                    "end_time": base_start + dur,
                    "duration_ms": dur,
                    "attributes": {
                        "trace.provider": "retell",
                        "metric.layer": layer,
                        "metric.scope": "turn_estimated",
                        "turn.index": idx,
                        "metric.estimated": True,
                    },
                    "status": "1",
                }
            )

    return {
        "trace_id": trace_id,
        "root_span_id": root_span_id,
        "spans": spans,
        "trace_source": "retell_synthetic",
    }
