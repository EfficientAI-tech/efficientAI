"""Build synthetic traces from Vapi call report payloads."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Set


def _to_epoch_ms(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.isdigit() or (
            stripped.replace(".", "", 1).isdigit() and stripped.count(".") <= 1
        ):
            return _to_epoch_ms(float(stripped))
        try:
            return datetime.fromisoformat(stripped.replace("Z", "+00:00")).timestamp() * 1000.0
        except Exception:
            return None
    if isinstance(value, (int, float)):
        numeric = float(value)
        if numeric > 1e16:  # ns
            return numeric / 1_000_000.0
        if numeric > 1e13:  # us
            return numeric / 1000.0
        if numeric > 1e10:  # ms epoch
            return numeric
        if numeric > 1e3:  # likely ms offset
            return numeric
        if numeric > 0:  # likely seconds offset
            return numeric * 1000.0
    return None


def _to_float(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except Exception:
            return None
    return None


def _first_number(*values: Any) -> Optional[float]:
    for value in values:
        parsed = _to_float(value)
        if parsed is not None:
            return parsed
    return None


def _extract_messages(call_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    messages = call_data.get("messages")
    if isinstance(messages, list) and messages:
        return [m for m in messages if isinstance(m, dict)]
    artifact = call_data.get("artifact")
    if isinstance(artifact, dict) and isinstance(artifact.get("messages"), list):
        return [m for m in artifact["messages"] if isinstance(m, dict)]
    return []


def _extract_latency_stats(call_data: Dict[str, Any]) -> Dict[str, Any]:
    analysis = call_data.get("analysis")
    if isinstance(analysis, dict):
        stats = analysis.get("latency_stats") or analysis.get("latencyStats")
        if isinstance(stats, dict):
            return stats
    artifact = call_data.get("artifact")
    if isinstance(artifact, dict):
        perf = artifact.get("performanceMetrics")
        if isinstance(perf, dict):
            return perf
    return {}


def _normalize_role(raw_role: Any) -> str:
    value = str(raw_role or "").lower().strip()
    if value in {"assistant", "agent", "bot", "ai"}:
        return "agent"
    return "user"


def build_vapi_synthetic_trace(
    call_data: Dict[str, Any],
    *,
    provider_call_id: str,
) -> Optional[Dict[str, Any]]:
    """Convert Vapi call report payload into a synthetic trace tree."""
    if not isinstance(call_data, dict):
        return None

    messages = [m for m in _extract_messages(call_data) if m.get("role") != "system"]
    latency_stats = _extract_latency_stats(call_data)
    turn_latencies = latency_stats.get("turn_latencies") or latency_stats.get("turnLatencies")

    has_any_signal = bool(messages) or isinstance(latency_stats, dict) and len(latency_stats) > 0
    if not has_any_signal:
        return None

    started_at_ms = _to_epoch_ms(call_data.get("startedAt") or call_data.get("started_at"))
    ended_at_ms = _to_epoch_ms(call_data.get("endedAt") or call_data.get("ended_at"))
    duration_seconds = _to_float(call_data.get("duration_seconds"))

    if started_at_ms is None:
        started_at_ms = _to_epoch_ms(messages[0].get("time") if messages else None) or 0.0
    if ended_at_ms is None and duration_seconds is not None:
        ended_at_ms = started_at_ms + duration_seconds * 1000.0
    if ended_at_ms is None:
        ended_at_ms = started_at_ms + max(1000.0, len(messages) * 1200.0)

    trace_id = f"vapi-{provider_call_id}"
    root_span_id = f"vapi-root-{provider_call_id}"
    root_span = {
        "span_id": root_span_id,
        "parent_span_id": None,
        "name": "conversation",
        "start_time": started_at_ms,
        "end_time": ended_at_ms,
        "duration_ms": max(ended_at_ms - started_at_ms, 0.0),
        "attributes": {
            "trace.provider": "vapi",
            "provider.call_id": provider_call_id,
            "conversation.id": provider_call_id,
            "conversation.type": "provider_synthetic",
            "call.status": call_data.get("status"),
        },
        "status": "1",
    }

    spans: List[Dict[str, Any]] = [root_span]
    cursor_ms = started_at_ms
    turn_span_ids: List[str] = []

    for idx, msg in enumerate(messages):
        role = _normalize_role(msg.get("role"))
        text = msg.get("message") or msg.get("content") or ""
        msg_start = (
            _to_epoch_ms(msg.get("time"))
            or (_to_float(msg.get("secondsFromStart")) * 1000.0 + started_at_ms if _to_float(msg.get("secondsFromStart")) is not None else None)
            or cursor_ms
        )
        msg_end = _to_epoch_ms(msg.get("endTime"))
        msg_duration = _to_float(msg.get("duration"))
        if msg_end is None and msg_duration is not None:
            msg_end = msg_start + msg_duration
        if msg_end is None:
            msg_end = msg_start + 800.0
        cursor_ms = max(cursor_ms, msg_end)

        span_id = f"vapi-turn-{idx}"
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
                    "trace.provider": "vapi",
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
        "stt": _first_number(
            latency_stats.get("transcriber_latency_avg"),
            latency_stats.get("transcriberLatencyAverage"),
            latency_stats.get("transcriberLatency"),
            latency_stats.get("asr"),
            latency_stats.get("asrLatency"),
        ),
        "llm": _first_number(
            latency_stats.get("model_latency_avg"),
            latency_stats.get("modelLatencyAverage"),
            latency_stats.get("modelLatency"),
            latency_stats.get("llm"),
            latency_stats.get("llmLatency"),
        ),
        "tts": _first_number(
            latency_stats.get("voice_latency_avg"),
            latency_stats.get("voiceLatencyAverage"),
            latency_stats.get("voiceLatency"),
            latency_stats.get("tts"),
            latency_stats.get("ttsLatency"),
        ),
        "endpointing": _first_number(
            latency_stats.get("endpointing_latency_avg"),
            latency_stats.get("endpointingLatencyAverage"),
            latency_stats.get("endpointingLatency"),
        ),
    }

    # Always include call-level layer spans so trace stats/icons remain populated
    # even if turnLatencies entries are sparse or shaped differently.
    for layer, dur in layer_candidates.items():
        if dur is None:
            continue
        spans.append(
            {
                "span_id": f"vapi-metric-{layer}",
                "parent_span_id": root_span_id,
                "name": layer,
                "start_time": started_at_ms,
                "end_time": started_at_ms + dur,
                "duration_ms": dur,
                "attributes": {
                    "trace.provider": "vapi",
                    "metric.layer": layer,
                    "metric.scope": "call_average",
                },
                "status": "1",
            }
        )

    if isinstance(turn_latencies, list):
        turns_with_layer_metrics: Set[int] = set()
        for idx, entry in enumerate(turn_latencies):
            parent_span_id = turn_span_ids[idx] if idx < len(turn_span_ids) else root_span_id
            base_start = started_at_ms + idx * 1000.0
            if isinstance(entry, (int, float)):
                entries = {"llm": float(entry)}
            elif isinstance(entry, dict):
                entries = {
                    "stt": _first_number(
                        entry.get("transcriber"),
                        entry.get("asr"),
                        entry.get("transcriberLatency"),
                        entry.get("asrLatency"),
                    ),
                    "llm": _first_number(
                        entry.get("model"),
                        entry.get("llm"),
                        entry.get("modelLatency"),
                        entry.get("llmLatency"),
                    ),
                    "tts": _first_number(
                        entry.get("voice"),
                        entry.get("tts"),
                        entry.get("voiceLatency"),
                        entry.get("ttsLatency"),
                    ),
                    "endpointing": _first_number(
                        entry.get("endpointing"),
                        entry.get("endpointingLatency"),
                    ),
                }
            else:
                entries = {}
            for layer, raw_value in entries.items():
                dur = _to_float(raw_value)
                if dur is None:
                    continue
                turns_with_layer_metrics.add(idx)
                spans.append(
                    {
                        "span_id": f"vapi-turn-{idx}-metric-{layer}",
                        "parent_span_id": parent_span_id,
                        "name": layer,
                        "start_time": base_start,
                        "end_time": base_start + dur,
                        "duration_ms": dur,
                        "attributes": {
                            "trace.provider": "vapi",
                            "metric.layer": layer,
                            "metric.scope": "turn_provider",
                            "turn.index": idx,
                        },
                        "status": "1",
                    }
                )

        # Vapi often reports per-turn latencies for only a subset of turns.
        # Backfill missing turns from call-level averages so later turns remain inspectable.
        for idx in range(len(turn_span_ids)):
            if idx in turns_with_layer_metrics:
                continue
            parent_span_id = turn_span_ids[idx]
            turn_span = spans[idx + 1] if idx + 1 < len(spans) else None
            base_start = (
                float(turn_span.get("start_time")) if isinstance(turn_span, dict) and isinstance(turn_span.get("start_time"), (int, float))
                else started_at_ms + idx * 1000.0
            )
            for layer, dur in layer_candidates.items():
                if dur is None:
                    continue
                spans.append(
                    {
                        "span_id": f"vapi-turn-{idx}-metric-{layer}-estimated",
                        "parent_span_id": parent_span_id,
                        "name": layer,
                        "start_time": base_start,
                        "end_time": base_start + dur,
                        "duration_ms": dur,
                        "attributes": {
                            "trace.provider": "vapi",
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
        "trace_source": "vapi_synthetic",
    }

