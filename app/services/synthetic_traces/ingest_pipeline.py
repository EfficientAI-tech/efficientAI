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


def ingest_otlp_batch_ch(
    db: Session,
    *,
    organization_id: UUID,
    spans: List[Dict[str, Any]],
    header_evaluator_result_id: Optional[str] = None,
    header_agent_id: Optional[str] = None,
    header_call_short_id: Optional[str] = None,
    workspace_id: Optional[UUID] = None,
) -> Tuple[Optional[Any], int, bool]:
    from app.services.synthetic_traces import ch_trace_ops
    from app.services.synthetic_traces.clickhouse_store import mint_trace_uuid

    if not spans or workspace_id is None:
        return None, 0, False

    groups = group_spans_by_call_short_id(spans, header_call_short_id=header_call_short_id)
    last_trace: Optional[Any] = None
    total_accepted = 0
    any_correlated = False

    for group_call_short_id, group_spans in groups.items():
        trace_uuid = resolve_trace_uuid_for_s3_ingest(
            db,
            organization_id=organization_id,
            workspace_id=workspace_id,
            header_evaluator_result_id=header_evaluator_result_id,
            header_call_short_id=group_call_short_id or header_call_short_id,
        )
        trace, correlated = correlate_batch_ch(
            db,
            organization_id=organization_id,
            workspace_id=workspace_id,
            spans=group_spans,
            trace_uuid=trace_uuid or mint_trace_uuid(),
            header_evaluator_result_id=header_evaluator_result_id,
            header_agent_id=header_agent_id,
            header_call_short_id=group_call_short_id or header_call_short_id,
        )
        if not trace:
            total_accepted += len(group_spans)
            continue
        ch_trace_ops.persist_spans_ch(trace, group_spans)
        schedule_derive(trace.id)
        total_accepted += len(group_spans)
        any_correlated = any_correlated or correlated
        last_trace = trace

    return last_trace, total_accepted, any_correlated


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
    from app.services.synthetic_traces import ch_trace_ops

    if ch_trace_ops.use_ch():
        return ingest_otlp_batch_ch(
            db,
            organization_id=organization_id,
            spans=spans,
            header_evaluator_result_id=header_evaluator_result_id,
            header_agent_id=header_agent_id,
            header_call_short_id=header_call_short_id,
            workspace_id=workspace_id,
        )

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


class IngestUnavailable(Exception):
    """S3 WAL or Celery enqueue failed; API should return 503."""


def resolve_trace_uuid_for_s3_ingest(
    db: Session,
    *,
    organization_id: UUID,
    workspace_id: UUID,
    header_evaluator_result_id: Optional[str] = None,
    header_call_short_id: Optional[str] = None,
) -> UUID:
    from app.services.synthetic_traces.clickhouse_store import (
        get_trace_by_call_short_id,
        get_trace_by_evaluator_result_id,
        mint_trace_uuid,
    )

    if header_call_short_id:
        found = get_trace_by_call_short_id(
            organization_id=organization_id,
            call_short_id=header_call_short_id,
            workspace_id=workspace_id,
        )
        if found:
            return found.id

    if header_evaluator_result_id:
        try:
            er_uuid = UUID(str(header_evaluator_result_id))
            found = get_trace_by_evaluator_result_id(
                organization_id=organization_id,
                evaluator_result_id=er_uuid,
                workspace_id=workspace_id,
            )
            if found:
                return found.id
            result = (
                db.query(EvaluatorResult)
                .filter(
                    EvaluatorResult.id == er_uuid,
                    EvaluatorResult.organization_id == organization_id,
                )
                .first()
            )
            if result and result.synthetic_call_trace_id:
                return result.synthetic_call_trace_id
        except ValueError:
            pass

    return mint_trace_uuid()


def ingest_otlp_batch_to_s3(
    db: Session,
    *,
    organization_id: UUID,
    workspace_id: UUID,
    body: bytes,
    content_type: str,
    header_evaluator_result_id: Optional[str] = None,
    header_agent_id: Optional[str] = None,
    header_call_short_id: Optional[str] = None,
) -> Dict[str, Any]:
    from app.services.storage import s3_service
    from app.services.storage.blob_paths import build_trace_batch_object_key
    from app.services.synthetic_traces.clickhouse_store import next_batch_seq

    trace_uuid = resolve_trace_uuid_for_s3_ingest(
        db,
        organization_id=organization_id,
        workspace_id=workspace_id,
        header_evaluator_result_id=header_evaluator_result_id,
        header_call_short_id=header_call_short_id,
    )
    seq = next_batch_seq(trace_uuid)
    s3_key = build_trace_batch_object_key(
        prefix=settings.TRACES_S3_PREFIX,
        organization_id=str(organization_id),
        workspace_id=str(workspace_id),
        trace_id=str(trace_uuid),
        seq=seq,
    )
    try:
        s3_service.upload_file_by_key(
            body,
            s3_key,
            content_type=content_type or "application/json",
        )
    except Exception as exc:
        logger.error("S3 WAL PUT failed for {}: {}", s3_key, exc)
        raise IngestUnavailable("S3 upload failed") from exc

    try:
        schedule_s3_batch_process(
            s3_key=s3_key,
            organization_id=organization_id,
            workspace_id=workspace_id,
            trace_uuid=trace_uuid,
            seq=seq,
            content_type=content_type or "",
            header_evaluator_result_id=header_evaluator_result_id,
            header_agent_id=header_agent_id,
            header_call_short_id=header_call_short_id,
        )
    except Exception as exc:
        logger.error("Celery enqueue failed after S3 PUT {}: {}", s3_key, exc)
        raise IngestUnavailable("Failed to enqueue batch processing") from exc

    return {
        "trace_uuid": trace_uuid,
        "seq": seq,
        "s3_key": s3_key,
        "accepted_bytes": len(body),
        "correlated": header_correlation_hint(
            header_evaluator_result_id=header_evaluator_result_id,
            header_call_short_id=header_call_short_id,
        ),
    }


def schedule_s3_batch_process(
    *,
    s3_key: str,
    organization_id: UUID,
    workspace_id: UUID,
    trace_uuid: UUID,
    seq: int,
    content_type: str,
    header_evaluator_result_id: Optional[str] = None,
    header_agent_id: Optional[str] = None,
    header_call_short_id: Optional[str] = None,
) -> None:
    if not settings.TRACES_ASYNC_INGEST_ENABLED:
        process_s3_otlp_batch(
            s3_key=s3_key,
            organization_id=organization_id,
            workspace_id=workspace_id,
            trace_uuid=trace_uuid,
            seq=seq,
            content_type=content_type,
            header_evaluator_result_id=header_evaluator_result_id,
            header_agent_id=header_agent_id,
            header_call_short_id=header_call_short_id,
        )
        return

    try:
        from app.workers.tasks.trace_tasks import process_s3_otlp_batch_task

        process_s3_otlp_batch_task.apply_async(
            kwargs={
                "s3_key": s3_key,
                "organization_id": str(organization_id),
                "workspace_id": str(workspace_id),
                "trace_uuid": str(trace_uuid),
                "seq": seq,
                "content_type": content_type,
                "header_evaluator_result_id": header_evaluator_result_id,
                "header_agent_id": header_agent_id,
                "header_call_short_id": header_call_short_id,
            }
        )
    except Exception as exc:
        logger.debug("Celery unavailable for S3 batch; running inline: {}", exc)
        process_s3_otlp_batch(
            s3_key=s3_key,
            organization_id=organization_id,
            workspace_id=workspace_id,
            trace_uuid=trace_uuid,
            seq=seq,
            content_type=content_type,
            header_evaluator_result_id=header_evaluator_result_id,
            header_agent_id=header_agent_id,
            header_call_short_id=header_call_short_id,
        )


def correlate_batch_ch(
    db: Session,
    *,
    organization_id: UUID,
    workspace_id: UUID,
    spans: List[Dict[str, Any]],
    trace_uuid: UUID,
    header_evaluator_result_id: Optional[str] = None,
    header_agent_id: Optional[str] = None,
    header_call_short_id: Optional[str] = None,
) -> Tuple[Optional[Any], bool]:
    from app.services.synthetic_traces.clickhouse_store import (
        TraceRecord,
        get_trace_by_call_short_id,
        get_trace_by_uuid,
        upsert_trace_header,
    )
    from app.services.synthetic_traces.span_storage import SPANS_STORAGE_S3

    if not spans:
        return None, False

    correlation = extract_correlation_ids(spans)
    evaluator_result_id = header_evaluator_result_id or correlation.get("evaluator_result_id")
    call_short_id = correlation.get("call_short_id") or header_call_short_id
    _ = header_agent_id or correlation.get("agent_id")

    trace = get_trace_by_uuid(trace_uuid)
    correlated = trace is not None

    if not trace:
        trace = TraceRecord(
            id=trace_uuid,
            organization_id=organization_id,
            workspace_id=workspace_id,
            status="open",
            started_at=_utcnow(),
            spans_storage="clickhouse",
        )

    if not correlated and call_short_id:
        existing = get_trace_by_call_short_id(
            organization_id=organization_id,
            call_short_id=call_short_id,
            workspace_id=workspace_id,
        )
        if existing:
            trace = existing
            correlated = True

    if call_short_id:
        trace.call_short_id = call_short_id

    if evaluator_result_id:
        try:
            trace.evaluator_result_id = UUID(str(evaluator_result_id))
            result = (
                db.query(EvaluatorResult)
                .filter(EvaluatorResult.id == trace.evaluator_result_id)
                .first()
            )
            if result:
                trace.agent_id = result.agent_id
                trace.persona_id = result.persona_id
                trace.scenario_id = result.scenario_id
                trace.evaluator_id = result.evaluator_id
                result.synthetic_call_trace_id = trace.id
                db.commit()
                correlated = True
        except ValueError:
            pass

    transport = correlation.get("transport") or trace.transport
    if transport in VALID_TRACE_TRANSPORTS:
        trace.transport = transport
    elif not trace.transport:
        trace.transport = "custom"

    if trace.status in ("closed", "finalized") and trace.spans_storage != SPANS_STORAGE_S3:
        trace.status = "open"
        trace.ended_at = None

    upsert_trace_header(trace)
    return trace, correlated


def process_s3_otlp_batch(
    *,
    s3_key: str,
    organization_id: UUID,
    workspace_id: UUID,
    trace_uuid: UUID,
    seq: int,
    content_type: str,
    header_evaluator_result_id: Optional[str] = None,
    header_agent_id: Optional[str] = None,
    header_call_short_id: Optional[str] = None,
    db: Optional[Session] = None,
) -> None:
    from app.database import SessionLocal
    from app.services.storage import s3_service
    from app.services.synthetic_traces import ch_trace_ops

    owns_session = db is None
    session = db or SessionLocal()
    try:
        body = s3_service.download_file_by_key(s3_key)
        spans, _fmt = parse_otlp_body(body, content_type)
        if not spans:
            return

        groups = group_spans_by_call_short_id(spans, header_call_short_id=header_call_short_id)
        for group_call_short_id, group_spans in groups.items():
            trace, _correlated = correlate_batch_ch(
                session,
                organization_id=organization_id,
                workspace_id=workspace_id,
                spans=group_spans,
                trace_uuid=trace_uuid,
                header_evaluator_result_id=header_evaluator_result_id,
                header_agent_id=header_agent_id,
                header_call_short_id=group_call_short_id or header_call_short_id,
            )
            if not trace:
                continue
            ch_trace_ops.persist_spans_ch(trace, group_spans)
            schedule_derive(trace.id)
    finally:
        if owns_session:
            session.close()


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
