"""Async OTLP ingest: correlate, persist batch rows, schedule derive."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

import redis
from loguru import logger
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.models.database import (
    EvaluatorResult,
    SyntheticCallTrace,
    SyntheticTraceIngestStaging,
    SyntheticTraceSpanBatch,
)
from app.models.synthetic_trace_schemas import VALID_TRACE_TRANSPORTS
from app.services.synthetic_traces.otlp_ingest import parse_otlp_body
from app.services.synthetic_traces.otlp_mapper import extract_correlation_ids, group_spans_by_call_short_id
from app.services.synthetic_traces.span_storage import SPANS_STORAGE_BATCHES, SPANS_STORAGE_S3
from app.services.synthetic_traces.trace_service import (
    get_trace_by_call_short_id,
    get_trace_for_result,
    ingest_otlp_spans,
    open_trace,
    open_trace_session,
)

STAGING_STATUS_PENDING = "pending"
STAGING_STATUS_PROCESSING = "processing"
STAGING_STATUS_PROCESSED = "processed"
STAGING_STATUS_FAILED = "failed"

_redis_client: Optional[redis.Redis] = None


def _get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis_client


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _next_batch_seq(db: Session, trace_id: UUID) -> int:
    current = (
        db.query(func.max(SyntheticTraceSpanBatch.seq))
        .filter(SyntheticTraceSpanBatch.synthetic_call_trace_id == trace_id)
        .scalar()
    )
    return int(current or 0) + 1


def correlate_batch(
    db: Session,
    *,
    organization_id: UUID,
    spans: List[Dict[str, Any]],
    header_evaluator_result_id: Optional[str] = None,
    header_agent_id: Optional[str] = None,
    header_call_short_id: Optional[str] = None,
    workspace_id: Optional[UUID] = None,
) -> Tuple[Optional[SyntheticCallTrace], bool]:
    if not spans:
        return None, False

    correlation = extract_correlation_ids(spans)
    evaluator_result_id = header_evaluator_result_id or correlation.get("evaluator_result_id")
    call_short_id = correlation.get("call_short_id") or header_call_short_id
    _ = header_agent_id or correlation.get("agent_id")

    trace: Optional[SyntheticCallTrace] = None
    correlated = False

    if evaluator_result_id:
        try:
            result_uuid = UUID(str(evaluator_result_id))
            trace = get_trace_for_result(
                db,
                organization_id=organization_id,
                evaluator_result_id=result_uuid,
                workspace_id=workspace_id,
                auto_close=False,
            )
            if not trace:
                result = (
                    db.query(EvaluatorResult)
                    .filter(
                        EvaluatorResult.id == result_uuid,
                        EvaluatorResult.organization_id == organization_id,
                    )
                    .first()
                )
                if result and workspace_id is not None and result.workspace_id != workspace_id:
                    result = None
                if result:
                    trace = open_trace(
                        db,
                        organization_id=organization_id,
                        workspace_id=result.workspace_id,
                        evaluator_result_id=result.id,
                        agent_id=result.agent_id,
                        persona_id=result.persona_id,
                        scenario_id=result.scenario_id,
                        evaluator_id=result.evaluator_id,
                        call_short_id=call_short_id,
                        transport="phone",
                        tier="component",
                    )
            correlated = trace is not None
        except ValueError:
            trace = None

    if not trace and call_short_id:
        trace = get_trace_by_call_short_id(
            db,
            organization_id=organization_id,
            call_short_id=call_short_id,
            workspace_id=workspace_id,
            auto_close=False,
        )
        correlated = trace is not None

    if not trace and call_short_id and workspace_id:
        transport = correlation.get("transport") or "custom"
        if transport not in VALID_TRACE_TRANSPORTS:
            transport = "custom"
        try:
            trace = open_trace_session(
                db,
                organization_id=organization_id,
                workspace_id=workspace_id,
                call_short_id=call_short_id,
                transport=transport,
            )
            correlated = True
        except ValueError:
            trace = None

    if not trace:
        return None, False

    if trace.status in ("closed", "finalized") and trace.spans_storage != SPANS_STORAGE_S3:
        trace.status = "open"
        trace.ended_at = None

    transport = correlation.get("transport")
    if transport in VALID_TRACE_TRANSPORTS:
        trace.transport = transport

    return trace, correlated


def persist_span_batch(
    db: Session,
    trace: SyntheticCallTrace,
    spans: List[Dict[str, Any]],
) -> SyntheticTraceSpanBatch:
    if trace.spans_storage not in (SPANS_STORAGE_BATCHES, SPANS_STORAGE_S3, "legacy_jsonb"):
        trace.spans_storage = SPANS_STORAGE_BATCHES
    elif trace.spans_storage == "legacy_jsonb":
        trace.spans_storage = SPANS_STORAGE_BATCHES

    batch = SyntheticTraceSpanBatch(
        synthetic_call_trace_id=trace.id,
        workspace_id=trace.workspace_id,
        seq=_next_batch_seq(db, trace.id),
        span_count=len(spans),
        spans=spans,
        received_at=_utcnow(),
    )
    db.add(batch)
    trace.span_count = int(trace.span_count or 0) + len(spans)
    trace.last_span_at = _utcnow()
    trace.derive_pending = True
    db.commit()
    db.refresh(trace)
    db.refresh(batch)
    return batch


def schedule_derive(trace_id: UUID) -> None:
    debounce = max(1, int(settings.TRACES_DERIVE_DEBOUNCE_SECONDS))
    lock_key = f"trace:derive:{trace_id}"
    try:
        acquired = _get_redis().set(lock_key, "1", nx=True, ex=debounce)
    except redis.RedisError as exc:
        logger.warning("Trace derive debounce Redis error: {}", exc)
        acquired = True
    if not acquired:
        return

    if not settings.TRACES_ASYNC_INGEST_ENABLED:
        from app.database import SessionLocal
        from app.services.synthetic_traces.trace_service import derive_trace_turns

        db = SessionLocal()
        try:
            derive_trace_turns(db, trace_id=trace_id)
        finally:
            db.close()
        return

    try:
        from app.workers.tasks.trace_tasks import derive_trace_turns_task

        derive_trace_turns_task.apply_async(args=[str(trace_id)], countdown=debounce)
    except Exception as exc:
        logger.debug("Celery unavailable for derive; running inline: {}", exc)
        from app.database import SessionLocal
        from app.services.synthetic_traces.trace_service import derive_trace_turns

        db = SessionLocal()
        try:
            derive_trace_turns(db, trace_id=trace_id)
        finally:
            db.close()


def ingest_otlp_batch_async(
    db: Session,
    *,
    organization_id: UUID,
    spans: List[Dict[str, Any]],
    header_evaluator_result_id: Optional[str] = None,
    header_agent_id: Optional[str] = None,
    header_call_short_id: Optional[str] = None,
    workspace_id: Optional[UUID] = None,
) -> Tuple[Optional[SyntheticCallTrace], int, bool]:
    if not spans:
        return None, 0, False

    groups = group_spans_by_call_short_id(spans, header_call_short_id=header_call_short_id)
    last_trace: Optional[SyntheticCallTrace] = None
    total_accepted = 0
    any_correlated = False

    for group_call_short_id, group_spans in groups.items():
        trace, correlated = correlate_batch(
            db,
            organization_id=organization_id,
            spans=group_spans,
            header_evaluator_result_id=header_evaluator_result_id,
            header_agent_id=header_agent_id,
            header_call_short_id=group_call_short_id or header_call_short_id,
            workspace_id=workspace_id,
        )
        if not trace:
            total_accepted += len(group_spans)
            continue
        persist_span_batch(db, trace, group_spans)
        schedule_derive(trace.id)
        total_accepted += len(group_spans)
        any_correlated = any_correlated or correlated
        last_trace = trace

    return last_trace, total_accepted, any_correlated


def header_correlation_hint(
    *,
    header_evaluator_result_id: Optional[str] = None,
    header_call_short_id: Optional[str] = None,
) -> bool:
    return bool(header_evaluator_result_id or header_call_short_id)


def stage_otlp_ingest(
    db: Session,
    *,
    organization_id: UUID,
    workspace_id: UUID,
    body: bytes,
    content_type: str,
    header_evaluator_result_id: Optional[str] = None,
    header_agent_id: Optional[str] = None,
    header_call_short_id: Optional[str] = None,
) -> SyntheticTraceIngestStaging:
    row = SyntheticTraceIngestStaging(
        organization_id=organization_id,
        workspace_id=workspace_id,
        content_type=content_type or "",
        body=body,
        body_bytes=len(body),
        header_evaluator_result_id=header_evaluator_result_id,
        header_agent_id=header_agent_id,
        header_call_short_id=header_call_short_id,
        status=STAGING_STATUS_PENDING,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    schedule_staged_process(row.id)
    return row


def schedule_staged_process(staging_id: UUID) -> None:
    if not settings.TRACES_ASYNC_INGEST_ENABLED:
        process_staged_otlp(staging_id=staging_id)
        return

    try:
        from app.workers.tasks.trace_tasks import process_staged_otlp_task

        process_staged_otlp_task.apply_async(args=[str(staging_id)])
    except Exception as exc:
        logger.debug("Celery unavailable for staged ingest; running inline: {}", exc)
        process_staged_otlp(staging_id=staging_id)


def _mark_staging_failed(
    db: Session,
    row: SyntheticTraceIngestStaging,
    message: str,
) -> SyntheticTraceIngestStaging:
    row.status = STAGING_STATUS_FAILED
    row.error_message = message[:2000]
    row.processed_at = _utcnow()
    db.commit()
    db.refresh(row)
    return row


def process_staged_otlp(
    *,
    staging_id: UUID,
    db: Optional[Session] = None,
) -> Optional[SyntheticTraceIngestStaging]:
    from app.database import SessionLocal

    owns_session = db is None
    session = db or SessionLocal()
    try:
        row = (
            session.query(SyntheticTraceIngestStaging)
            .filter(SyntheticTraceIngestStaging.id == staging_id)
            .with_for_update(skip_locked=True)
            .first()
        )
        if not row:
            return None
        if row.status == STAGING_STATUS_PROCESSED:
            return row
        if row.status == STAGING_STATUS_FAILED:
            return row

        row.status = STAGING_STATUS_PROCESSING
        row.attempt_count = int(row.attempt_count or 0) + 1
        session.commit()

        try:
            spans, _fmt = parse_otlp_body(bytes(row.body), row.content_type)
        except Exception as exc:
            logger.warning("Staged OTLP parse failed for {}: {}", staging_id, exc)
            return _mark_staging_failed(session, row, f"Failed to parse OTLP payload: {exc}")

        try:
            if settings.TRACES_ASYNC_INGEST_ENABLED:
                trace, accepted, correlated = ingest_otlp_batch_async(
                    session,
                    organization_id=row.organization_id,
                    spans=spans,
                    header_evaluator_result_id=row.header_evaluator_result_id,
                    header_agent_id=row.header_agent_id,
                    header_call_short_id=row.header_call_short_id,
                    workspace_id=row.workspace_id,
                )
            else:
                trace, accepted, correlated = ingest_otlp_spans(
                    session,
                    organization_id=row.organization_id,
                    spans=spans,
                    header_evaluator_result_id=row.header_evaluator_result_id,
                    header_agent_id=row.header_agent_id,
                    header_call_short_id=row.header_call_short_id,
                    workspace_id=row.workspace_id,
                )
        except Exception:
            row = (
                session.query(SyntheticTraceIngestStaging)
                .filter(SyntheticTraceIngestStaging.id == staging_id)
                .first()
            )
            if row and row.status == STAGING_STATUS_PROCESSING:
                row.status = STAGING_STATUS_PENDING
                session.commit()
            raise

        row.status = STAGING_STATUS_PROCESSED
        row.accepted_spans = accepted
        row.synthetic_call_trace_id = trace.id if trace else None
        row.correlated = correlated
        row.error_message = None
        row.processed_at = _utcnow()
        session.commit()
        session.refresh(row)
        return row
    finally:
        if owns_session:
            session.close()


def get_staging_status(
    db: Session,
    *,
    staging_id: UUID,
    organization_id: UUID,
    workspace_id: UUID,
) -> Optional[SyntheticTraceIngestStaging]:
    return (
        db.query(SyntheticTraceIngestStaging)
        .filter(
            SyntheticTraceIngestStaging.id == staging_id,
            SyntheticTraceIngestStaging.organization_id == organization_id,
            SyntheticTraceIngestStaging.workspace_id == workspace_id,
        )
        .first()
    )


def sweep_staging_ingest(db: Session) -> int:
    retention_hours = max(1, int(settings.TRACES_STAGING_RETENTION_HOURS))
    cutoff = _utcnow() - timedelta(hours=retention_hours)
    deleted = (
        db.query(SyntheticTraceIngestStaging)
        .filter(
            SyntheticTraceIngestStaging.status.in_(
                (STAGING_STATUS_PROCESSED, STAGING_STATUS_FAILED)
            ),
            SyntheticTraceIngestStaging.processed_at.isnot(None),
            SyntheticTraceIngestStaging.processed_at < cutoff,
        )
        .delete(synchronize_session=False)
    )
    db.commit()
    return int(deleted or 0)
