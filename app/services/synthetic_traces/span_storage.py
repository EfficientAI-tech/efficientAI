"""Load and offload OTLP span blobs for synthetic call traces."""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any, Dict, List, Optional, Set, Tuple
from uuid import UUID

from loguru import logger
from sqlalchemy.orm import Session

from app.config import settings
from app.models.database import (
    SyntheticCallTrace,
    SyntheticTraceOtelPayload,
    SyntheticTraceSpanBatch,
)
from app.services.storage import s3_service
from app.services.storage.blob_paths import build_trace_spans_object_key

SPANS_STORAGE_LEGACY = "legacy_jsonb"
SPANS_STORAGE_BATCHES = "batches"
SPANS_STORAGE_S3 = "s3"


def dedupe_spans(spans: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: Set[Tuple[Any, Any]] = set()
    out: List[Dict[str, Any]] = []
    for span in spans:
        key = (span.get("trace_id"), span.get("span_id"))
        if key in seen:
            continue
        seen.add(key)
        out.append(span)
    return out


def collect_trace_ids(spans: List[Dict[str, Any]]) -> List[str]:
    ids = {str(s.get("trace_id")) for s in spans if s.get("trace_id")}
    return sorted(ids)


def load_batches_spans(db: Session, trace_id: UUID) -> List[Dict[str, Any]]:
    rows = (
        db.query(SyntheticTraceSpanBatch)
        .filter(SyntheticTraceSpanBatch.synthetic_call_trace_id == trace_id)
        .order_by(SyntheticTraceSpanBatch.seq.asc())
        .all()
    )
    spans: List[Dict[str, Any]] = []
    for row in rows:
        spans.extend(list(row.spans or []))
    return dedupe_spans(spans)


def load_legacy_spans(db: Session, trace_id: UUID) -> List[Dict[str, Any]]:
    otel_payload = (
        db.query(SyntheticTraceOtelPayload)
        .filter(SyntheticTraceOtelPayload.synthetic_call_trace_id == trace_id)
        .first()
    )
    return list(otel_payload.spans or []) if otel_payload else []


@lru_cache(maxsize=128)
def _cached_s3_spans(s3_key: str) -> tuple:
    data = s3_service.download_file_by_key(s3_key)
    payload = json.loads(data.decode("utf-8"))
    spans = list(payload.get("spans") or [])
    return tuple(spans)


def load_s3_spans(s3_key: str) -> List[Dict[str, Any]]:
    try:
        return list(_cached_s3_spans(s3_key))
    except Exception as exc:
        logger.warning("Failed to load trace spans from S3 key={}: {}", s3_key, exc)
        return []


def load_trace_spans(db: Session, trace: SyntheticCallTrace) -> List[Dict[str, Any]]:
    storage = trace.spans_storage or SPANS_STORAGE_LEGACY
    if storage == SPANS_STORAGE_S3 and trace.spans_s3_key:
        spans = load_s3_spans(trace.spans_s3_key)
        if spans:
            return spans
    if storage in (SPANS_STORAGE_BATCHES, SPANS_STORAGE_S3):
        batch_spans = load_batches_spans(db, trace.id)
        if batch_spans:
            return batch_spans
    legacy = load_legacy_spans(db, trace.id)
    if legacy:
        return legacy
    if trace.spans_s3_key:
        return load_s3_spans(trace.spans_s3_key)
    return []


def upload_trace_spans_to_s3(
    db: Session,
    trace: SyntheticCallTrace,
    spans: List[Dict[str, Any]],
) -> Optional[str]:
    if not settings.S3_ENABLED:
        return None
    key = build_trace_spans_object_key(
        prefix=settings.TRACES_S3_PREFIX,
        organization_id=str(trace.organization_id),
        workspace_id=str(trace.workspace_id),
        trace_id=str(trace.id),
    )
    body = json.dumps(
        {"spans": spans, "trace_ids": collect_trace_ids(spans)},
        separators=(",", ":"),
    ).encode("utf-8")
    s3_service.upload_file_by_key(body, key, content_type="application/json")
    return key


def delete_trace_batches(db: Session, trace_id: UUID) -> None:
    db.query(SyntheticTraceSpanBatch).filter(
        SyntheticTraceSpanBatch.synthetic_call_trace_id == trace_id
    ).delete(synchronize_session=False)
