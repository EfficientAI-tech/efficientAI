"""Build synthetic traces from incremental live observability call_data."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.services.observability.vapi_trace import _first_number, _normalize_role, _to_epoch_ms


_LIVE_LAYER_KEYS = {
    "stt": ("stt_ms", "stt", "asr_ms", "asr", "transcriber_ms", "transcriber"),
    "llm": ("llm_ms", "llm", "model_ms", "model"),
    "tts": ("tts_ms", "tts", "voice_ms", "voice"),
}


def _latency_from_mapping(raw: Any) -> Dict[str, float]:
    if not isinstance(raw, dict):
        return {}
    resolved: Dict[str, float] = {}
    for layer, keys in _LIVE_LAYER_KEYS.items():
        value = _first_number(*[raw.get(key) for key in keys])
        if value is not None:
            resolved[layer] = value
    return resolved


def _extract_live_turns(call_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    live_transcript = call_data.get("live_transcript")
    if isinstance(live_transcript, list) and live_transcript:
        return [entry for entry in live_transcript if isinstance(entry, dict)]

    messages = call_data.get("messages")
    if isinstance(messages, list) and messages:
        turns: List[Dict[str, Any]] = []
        for entry in messages:
            if not isinstance(entry, dict):
                continue
            content = entry.get("content") or entry.get("text") or entry.get("message")
            if not isinstance(content, str) or not content.strip():
                continue
            turns.append(
                {
                    "role": entry.get("role"),
                    "content": content,
                    "event_ts": entry.get("timestamp") or entry.get("event_ts"),
                    "latency": entry.get("latency"),
                }
            )
        return turns
    return []


def _turn_window_ms(
    entry: Dict[str, Any],
    *,
    started_at_ms: float,
    fallback_start_ms: float,
) -> tuple[float, float]:
    event_ts = _to_epoch_ms(entry.get("event_ts") or entry.get("timestamp"))
    if event_ts is not None:
        end_ts = event_ts + 800.0
        return event_ts, end_ts

    start_offset = _first_number(entry.get("start_time"), entry.get("start"))
    if start_offset is not None:
        start_ms = start_offset if start_offset > 1e10 else started_at_ms + start_offset * 1000.0
        end_offset = _first_number(entry.get("end_time"), entry.get("end"))
        if end_offset is not None:
            end_ms = end_offset if end_offset > 1e10 else started_at_ms + end_offset * 1000.0
        else:
            end_ms = start_ms + 800.0
        return start_ms, end_ms

    return fallback_start_ms, fallback_start_ms + 800.0


def _average_layer_latencies(turns: List[Dict[str, Any]]) -> Dict[str, float]:
    buckets: Dict[str, List[float]] = {"stt": [], "llm": [], "tts": []}
    for turn in turns:
        role = _normalize_role(turn.get("role"))
        layer_latencies = _latency_from_mapping(turn.get("latency"))
        if role == "user" and "stt" in layer_latencies:
            buckets["stt"].append(layer_latencies["stt"])
        if role == "agent":
            for layer in ("llm", "tts"):
                if layer in layer_latencies:
                    buckets[layer].append(layer_latencies[layer])
    return {
        layer: sum(values) / len(values)
        for layer, values in buckets.items()
        if values
    }


def build_live_synthetic_trace(
    call_data: Dict[str, Any],
    *,
    provider_call_id: str,
    provider_platform: str = "external",
    trace_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Convert live-ingest call_data into a synthetic STT/LLM/TTS trace tree."""
    if not isinstance(call_data, dict):
        return None

    turns = _extract_live_turns(call_data)
    if not turns:
        return None

    platform = (provider_platform or call_data.get("live_state", {}).get("last_platform") or "external").strip().lower()
    started_at_ms = _to_epoch_ms(call_data.get("startedAt") or call_data.get("started_at"))
    ended_at_ms = _to_epoch_ms(call_data.get("endedAt") or call_data.get("ended_at"))

    if started_at_ms is None:
        started_at_ms = _to_epoch_ms(turns[0].get("event_ts")) or 0.0
    if ended_at_ms is None:
        last_ts = _to_epoch_ms(turns[-1].get("event_ts"))
        ended_at_ms = (last_ts + 800.0) if last_ts is not None else started_at_ms + max(1000.0, len(turns) * 1200.0)

    resolved_trace_id = trace_id or call_data.get("trace_id") or f"live-{provider_call_id}"
    root_span_id = f"live-root-{provider_call_id}"
    root_span = {
        "span_id": root_span_id,
        "parent_span_id": None,
        "name": "conversation",
        "start_time": started_at_ms,
        "end_time": ended_at_ms,
        "duration_ms": max(ended_at_ms - started_at_ms, 0.0),
        "attributes": {
            "trace.provider": platform,
            "provider.call_id": provider_call_id,
            "conversation.id": provider_call_id,
            "conversation.type": "live_synthetic",
            "call.status": call_data.get("status"),
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

        span_id = f"live-turn-{idx}"
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
                    "trace.provider": platform,
                    "turn.number": idx + 1,
                    "turn.role": role,
                    "turn.text_length": len(str(text)),
                    **({"turn.user_transcript": text} if role == "user" and isinstance(text, str) and text.strip() else {}),
                    **({"turn.agent_transcript": text} if role == "agent" and isinstance(text, str) and text.strip() else {}),
                },
                "status": "1",
            }
        )

        layer_latencies = _latency_from_mapping(entry.get("latency"))
        base_start = msg_start
        for layer, dur in layer_latencies.items():
            spans.append(
                {
                    "span_id": f"live-turn-{idx}-metric-{layer}",
                    "parent_span_id": span_id,
                    "name": layer,
                    "start_time": base_start,
                    "end_time": base_start + dur,
                    "duration_ms": dur,
                    "attributes": {
                        "trace.provider": platform,
                        "metric.layer": layer,
                        "metric.scope": "turn_reported",
                        "turn.index": idx,
                    },
                    "status": "1",
                }
            )

    call_level = _average_layer_latencies(turns)
    for layer, dur in call_level.items():
        spans.append(
            {
                "span_id": f"live-metric-{layer}",
                "parent_span_id": root_span_id,
                "name": layer,
                "start_time": started_at_ms,
                "end_time": started_at_ms + dur,
                "duration_ms": dur,
                "attributes": {
                    "trace.provider": platform,
                    "metric.layer": layer,
                    "metric.scope": "call_average",
                },
                "status": "1",
            }
        )

    return {
        "trace_id": resolved_trace_id,
        "root_span_id": root_span_id,
        "spans": spans,
        "trace_source": f"{platform}_live_synthetic",
    }
