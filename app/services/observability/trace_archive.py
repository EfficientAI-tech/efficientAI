"""Persist provider traces inline and/or in S3 for durable observability."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any, Dict, Optional
from uuid import UUID

from loguru import logger

from app.services.storage.s3_service import s3_service

INLINE_TRACE_SIZE_LIMIT_BYTES = 256 * 1024


def _json_size_bytes(value: Any) -> int:
    try:
        return len(json.dumps(value, separators=(",", ":")).encode("utf-8"))
    except Exception:
        return 0


def build_observability_trace_s3_key(
    *,
    organization_id: UUID,
    call_short_id: str,
) -> str:
    return (
        f"{s3_service.prefix}organizations/{organization_id}/observability/"
        f"{call_short_id}/traces/{uuid.uuid4()}.json"
    )


def persist_provider_trace(
    *,
    call_data: Dict[str, Any],
    provider_platform: str,
    organization_id: UUID,
    call_short_id: str,
    trace_payload: Dict[str, Any],
    source: str,
    raw_payload: Optional[Dict[str, Any]] = None,
    inline_limit_bytes: int = INLINE_TRACE_SIZE_LIMIT_BYTES,
) -> Dict[str, Any]:
    """Persist provider trace metadata + normalized trace with optional S3 overflow."""
    if not isinstance(call_data, dict) or not isinstance(trace_payload, dict):
        return call_data

    updated = dict(call_data)
    trace_id = trace_payload.get("trace_id") or updated.get("trace_id")
    normalized_trace = trace_payload
    trace_source = trace_payload.get("trace_source") or source
    provider_trace: Dict[str, Any] = {
        "source": source,
        "trace_source": trace_source,
        "trace_id": trace_id,
        "ingested_at": datetime.now(UTC).isoformat(),
        "provider_platform": provider_platform,
        "storage": "inline",
        "normalized_trace": normalized_trace,
        "otlp_traces": None,
        "trace_s3_key": None,
    }

    if isinstance(raw_payload, dict):
        provider_trace["otlp_traces"] = raw_payload

    payload_size = _json_size_bytes(provider_trace)
    should_archive = payload_size > max(1, inline_limit_bytes)
    if should_archive and s3_service.is_enabled():
        s3_key = build_observability_trace_s3_key(
            organization_id=organization_id,
            call_short_id=call_short_id,
        )
        archive_payload = {
            "trace_payload": trace_payload,
            "raw_payload": raw_payload,
            "source": source,
            "trace_source": trace_source,
        }
        try:
            s3_service.upload_file_by_key(
                json.dumps(archive_payload).encode("utf-8"),
                s3_key,
                content_type="application/json",
            )
            provider_trace["storage"] = "s3"
            provider_trace["trace_s3_key"] = s3_key
            provider_trace["otlp_traces"] = None
        except Exception as exc:
            logger.warning(
                "Provider trace S3 archive failed for call_short_id={}: {}",
                call_short_id,
                exc,
            )

    updated["provider_trace"] = provider_trace
    if trace_id:
        updated["trace_id"] = trace_id
    return updated


def load_provider_trace(call_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Load normalized provider trace from call_data or S3 archive."""
    if not isinstance(call_data, dict):
        return None
    provider_trace = call_data.get("provider_trace")
    if not isinstance(provider_trace, dict):
        return None

    normalized = provider_trace.get("normalized_trace")
    if isinstance(normalized, dict) and isinstance(normalized.get("spans"), list):
        return normalized

    s3_key = provider_trace.get("trace_s3_key")
    if not isinstance(s3_key, str) or not s3_key.strip():
        return None
    if not s3_service.is_enabled():
        return None

    try:
        payload_bytes = s3_service.download_file_by_key(s3_key)
        archive_payload = json.loads(payload_bytes.decode("utf-8"))
    except Exception as exc:
        logger.warning("Failed to load archived provider trace s3_key={}: {}", s3_key, exc)
        return None

    trace_payload = archive_payload.get("trace_payload")
    if isinstance(trace_payload, dict) and isinstance(trace_payload.get("spans"), list):
        return trace_payload
    return None
