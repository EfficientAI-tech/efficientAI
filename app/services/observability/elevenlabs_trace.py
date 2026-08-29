"""Normalize ElevenLabs OTLP payloads for observability trace UI."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional


def _normalize_span_attributes(raw_attrs: Any) -> Dict[str, Any]:
    if isinstance(raw_attrs, dict):
        return dict(raw_attrs)
    if isinstance(raw_attrs, list):
        result: Dict[str, Any] = {}
        for item in raw_attrs:
            if not isinstance(item, dict):
                continue
            key = item.get("key")
            if not key:
                continue
            value = item.get("value")
            if isinstance(value, dict):
                for scalar_key in ("stringValue", "intValue", "doubleValue", "boolValue"):
                    if scalar_key in value:
                        result[key] = value[scalar_key]
                        break
                else:
                    result[key] = value
            else:
                result[key] = value
        return result
    return {}


def _to_epoch_ms(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.isdigit() or (stripped.replace(".", "", 1).isdigit() and stripped.count(".") <= 1):
            return _to_epoch_ms(float(stripped))
        try:
            return datetime.fromisoformat(stripped.replace("Z", "+00:00")).timestamp() * 1000.0
        except Exception:
            return None
    if isinstance(value, (int, float)):
        numeric = float(value)
        if numeric > 1e16:
            return numeric / 1_000_000.0
        if numeric > 1e13:
            return numeric / 1000.0
        if numeric > 1e10:
            return numeric
        if numeric > 0:
            return numeric * 1000.0
    return None


def _collect_spans(raw: Any, out: List[Dict[str, Any]]) -> None:
    if isinstance(raw, dict):
        if any(k in raw for k in ("spanId", "span_id", "id")) and any(k in raw for k in ("name", "operationName")):
            out.append(raw)
        for value in raw.values():
            _collect_spans(value, out)
    elif isinstance(raw, list):
        for item in raw:
            _collect_spans(item, out)


def extract_trace_id(otlp_payload: Dict[str, Any]) -> Optional[str]:
    spans: List[Dict[str, Any]] = []
    _collect_spans(otlp_payload, spans)
    for span in spans:
        trace_id = span.get("traceId") or span.get("trace_id")
        if trace_id:
            return str(trace_id)
    return None


def normalize_elevenlabs_otlp(
    otlp_payload: Dict[str, Any],
    *,
    conversation_id: str,
    fallback_trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    raw_spans: List[Dict[str, Any]] = []
    _collect_spans(otlp_payload, raw_spans)

    trace_id = extract_trace_id(otlp_payload) or fallback_trace_id or conversation_id
    root_span_id: Optional[str] = None
    spans: List[Dict[str, Any]] = []

    for raw in raw_spans:
        span_id = raw.get("span_id") or raw.get("spanId") or raw.get("id")
        parent_span_id = raw.get("parent_span_id") or raw.get("parentSpanId")

        start_ms = _to_epoch_ms(
            raw.get("start_time")
            or raw.get("startTime")
            or raw.get("startTimeUnixNano")
            or raw.get("start_time_unix_nano")
        )
        end_ms = _to_epoch_ms(
            raw.get("end_time")
            or raw.get("endTime")
            or raw.get("endTimeUnixNano")
            or raw.get("end_time_unix_nano")
        )

        duration_ms = raw.get("duration_ms")
        if duration_ms is None:
            duration = raw.get("duration")
            if isinstance(duration, (int, float)):
                duration_ms = duration / 1_000_000.0 if duration > 1e10 else float(duration)
            elif start_ms is not None and end_ms is not None:
                duration_ms = max(end_ms - start_ms, 0.0)

        attrs = _normalize_span_attributes(raw.get("attributes") or raw.get("tags"))
        attrs.setdefault("trace.provider", "elevenlabs")
        attrs.setdefault("elevenlabs.conversation_id", conversation_id)

        status_obj = raw.get("status")
        if isinstance(status_obj, dict):
            status_value = status_obj.get("code") or status_obj.get("status_code")
        else:
            status_value = status_obj

        spans.append({
            "span_id": span_id,
            "parent_span_id": parent_span_id,
            "name": raw.get("name") or raw.get("operationName") or "unknown",
            "start_time": start_ms,
            "end_time": end_ms,
            "duration_ms": duration_ms,
            "attributes": attrs,
            "status": str(status_value) if status_value is not None else None,
        })

        if not parent_span_id and span_id and root_span_id is None:
            root_span_id = span_id

    if root_span_id is None and spans:
        root_span_id = spans[0].get("span_id")

    return {
        "trace_id": trace_id,
        "root_span_id": root_span_id,
        "spans": spans,
        "trace_source": "elevenlabs",
    }


def enrich_with_turn_metrics(trace_payload: Dict[str, Any], transcript: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Attach synthetic elevenlabs.metric.* spans derived from conversation_turn_metrics."""
    spans = list(trace_payload.get("spans") or [])
    if not spans or not transcript:
        return trace_payload

    by_turn = [s for s in spans if isinstance(s.get("name"), str) and s.get("name", "").startswith("elevenlabs.recv.")]
    if not by_turn:
        return trace_payload

    metric_spans: List[Dict[str, Any]] = []
    for idx, entry in enumerate(transcript):
        if not isinstance(entry, dict):
            continue
        metrics = entry.get("conversation_turn_metrics")
        if not isinstance(metrics, dict):
            continue
        nested_metrics = metrics.get("metrics") if isinstance(metrics.get("metrics"), dict) else {}
        parent = by_turn[idx] if idx < len(by_turn) else None
        if not parent:
            continue
        base_start = parent.get("start_time")
        base_end = parent.get("end_time")
        if not isinstance(base_start, (int, float)):
            continue

        def _first_elapsed_ms(metric_keys: List[str]) -> Optional[float]:
            for metric_key in metric_keys:
                metric_value = nested_metrics.get(metric_key)
                if not isinstance(metric_value, dict):
                    continue
                elapsed_s = metric_value.get("elapsed_time")
                if isinstance(elapsed_s, (int, float)):
                    return float(elapsed_s) * 1000.0
            return None

        asr_ms = _first_elapsed_ms(
            [
                "convai_turn_asr_latency",
                "convai_asr_trailing_service_latency",
            ]
        )
        llm_ms = _first_elapsed_ms(
            [
                "convai_llm_service_tt_last_sentence",
                "convai_llm_service_ttf_sentence",
                "convai_llm_service_ttfb",
            ]
        )
        tts_ms = _first_elapsed_ms(
            [
                "convai_tts_service_ttfb",
            ]
        )

        entries = [
            (
                "elevenlabs.metric.asr",
                asr_ms,
                {
                    "convai_asr_provider": metrics.get("convai_asr_provider"),
                    "convai_metric_key": (
                        "convai_turn_asr_latency"
                        if "convai_turn_asr_latency" in nested_metrics
                        else "convai_asr_trailing_service_latency"
                    ),
                },
            ),
            (
                "elevenlabs.metric.llm",
                llm_ms,
                {
                    "llm_usage": entry.get("llm_usage"),
                    "convai_metric_key": (
                        "convai_llm_service_tt_last_sentence"
                        if "convai_llm_service_tt_last_sentence" in nested_metrics
                        else "convai_llm_service_ttf_sentence"
                        if "convai_llm_service_ttf_sentence" in nested_metrics
                        else "convai_llm_service_ttfb"
                    ),
                },
            ),
            (
                "elevenlabs.metric.tts",
                tts_ms,
                {
                    "convai_tts_model": metrics.get("convai_tts_model"),
                    "convai_tts_cascade": metrics.get("convai_tts_cascade"),
                    "convai_metric_key": "convai_tts_service_ttfb",
                },
            ),
        ]
        for metric_name, elapsed_ms, extra in entries:
            if elapsed_ms is None:
                continue
            end_time = base_start + elapsed_ms
            if isinstance(base_end, (int, float)):
                end_time = min(end_time, base_end)
            attrs = {"trace.provider": "elevenlabs", **{k: v for k, v in extra.items() if v is not None}}
            metric_spans.append({
                "span_id": f"{parent.get('span_id')}-{metric_name}",
                "parent_span_id": parent.get("span_id"),
                "name": metric_name,
                "start_time": base_start,
                "end_time": end_time,
                "duration_ms": elapsed_ms,
                "attributes": attrs,
                "status": "1",
            })

    if metric_spans:
        trace_payload = dict(trace_payload)
        trace_payload["spans"] = spans + metric_spans
    return trace_payload
