"""Parse OTLP export payloads into normalized span dicts."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple

from loguru import logger


def _decode_attr_value(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    if "stringValue" in value:
        return value["stringValue"]
    if "boolValue" in value:
        return value["boolValue"]
    if "intValue" in value:
        return int(value["intValue"])
    if "doubleValue" in value:
        return float(value["doubleValue"])
    if "arrayValue" in value:
        vals = value["arrayValue"].get("values") or []
        return [_decode_attr_value(v) for v in vals]
    if "kvlistValue" in value:
        items = value["kvlistValue"].get("values") or []
        return {item["key"]: _decode_attr_value(item.get("value")) for item in items}
    return value


def _attrs_list_to_dict(attrs: List[Dict[str, Any]]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for item in attrs or []:
        key = item.get("key")
        if key is None:
            continue
        out[key] = _decode_attr_value(item.get("value"))
    return out


def _span_id_hex(raw: Any) -> str:
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    return raw.hex() if hasattr(raw, "hex") else str(raw)


def parse_otlp_json(body: bytes) -> List[Dict[str, Any]]:
    data = json.loads(body)
    spans: List[Dict[str, Any]] = []
    for resource_span in data.get("resourceSpans") or []:
        for scope_span in resource_span.get("scopeSpans") or []:
            for span in scope_span.get("spans") or []:
                spans.append(_normalize_json_span(span))
    return spans


def _normalize_json_span(span: Dict[str, Any]) -> Dict[str, Any]:
    events = []
    for event in span.get("events") or []:
        events.append(
            {
                "name": event.get("name"),
                "time_unix_nano": event.get("timeUnixNano"),
                "attributes": _attrs_list_to_dict(event.get("attributes")),
            }
        )
    return {
        "trace_id": _span_id_hex(span.get("traceId")),
        "span_id": _span_id_hex(span.get("spanId")),
        "parent_span_id": _span_id_hex(span.get("parentSpanId")) or None,
        "name": span.get("name") or "",
        "start_time_unix_nano": span.get("startTimeUnixNano"),
        "end_time_unix_nano": span.get("endTimeUnixNano"),
        "attributes": _attrs_list_to_dict(span.get("attributes")),
        "events": events,
    }


def parse_otlp_protobuf(body: bytes) -> List[Dict[str, Any]]:
    try:
        from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
            ExportTraceServiceRequest,
        )
    except ImportError as exc:
        raise RuntimeError(
            "opentelemetry-proto is required for OTLP/protobuf ingest"
        ) from exc

    request = ExportTraceServiceRequest()
    request.ParseFromString(body)
    spans: List[Dict[str, Any]] = []
    for resource_spans in request.resource_spans:
        for scope_spans in resource_spans.scope_spans:
            for span in scope_spans.spans:
                events = []
                for event in span.events:
                    events.append(
                        {
                            "name": event.name,
                            "time_unix_nano": event.time_unix_nano,
                            "attributes": {
                                kv.key: _decode_otlp_any(kv.value)
                                for kv in event.attributes
                            },
                        }
                    )
                spans.append(
                    {
                        "trace_id": span.trace_id.hex(),
                        "span_id": span.span_id.hex(),
                        "parent_span_id": span.parent_span_id.hex() or None,
                        "name": span.name,
                        "start_time_unix_nano": span.start_time_unix_nano,
                        "end_time_unix_nano": span.end_time_unix_nano,
                        "attributes": {
                            kv.key: _decode_otlp_any(kv.value) for kv in span.attributes
                        },
                        "events": events,
                    }
                )
    return spans


def _decode_otlp_any(value: Any) -> Any:
    which = value.WhichOneof("value")
    if which == "string_value":
        return value.string_value
    if which == "bool_value":
        return value.bool_value
    if which == "int_value":
        return value.int_value
    if which == "double_value":
        return value.double_value
    if which == "array_value":
        return [_decode_otlp_any(v) for v in value.array_value.values]
    if which == "kvlist_value":
        return {kv.key: _decode_otlp_any(kv.value) for kv in value.kvlist_value.values}
    return None


def parse_otlp_body(body: bytes, content_type: str | None) -> Tuple[List[Dict[str, Any]], str]:
    ct = (content_type or "").lower()
    if "json" in ct:
        return parse_otlp_json(body), "json"
    try:
        return parse_otlp_protobuf(body), "protobuf"
    except Exception as proto_err:
        if body[:1] in (b"{", b"["):
            return parse_otlp_json(body), "json"
        raise proto_err
