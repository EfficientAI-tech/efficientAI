"""Celery tasks for async OTLP trace derive, idle close, and S3 offload."""

from __future__ import annotations

from uuid import UUID

from loguru import logger

from app.workers.config import TRACES_WORKER_QUEUE, celery_app


@celery_app.task(name="derive_trace_turns", queue=TRACES_WORKER_QUEUE, bind=True, max_retries=3)
def derive_trace_turns_task(self, trace_id: str) -> None:
    from app.database import SessionLocal
    from app.services.synthetic_traces.trace_service import derive_trace_turns

    db = SessionLocal()
    try:
        derive_trace_turns(db, trace_id=UUID(trace_id))
    except Exception as exc:
        logger.warning("derive_trace_turns failed for {}: {}", trace_id, exc)
        raise self.retry(exc=exc, countdown=5)
    finally:
        db.close()


@celery_app.task(name="sweep_idle_traces", queue=TRACES_WORKER_QUEUE)
def sweep_idle_traces_task() -> int:
    from app.database import SessionLocal
    from app.services.synthetic_traces.trace_service import sweep_idle_traces

    db = SessionLocal()
    try:
        return sweep_idle_traces(db)
    finally:
        db.close()


@celery_app.task(
    name="process_staged_otlp",
    queue=TRACES_WORKER_QUEUE,
    bind=True,
    max_retries=3,
)
def process_staged_otlp_task(self, staging_id: str) -> None:
    from app.database import SessionLocal
    from app.services.synthetic_traces.ingest_pipeline import (
        STAGING_STATUS_FAILED,
        process_staged_otlp,
    )

    try:
        result = process_staged_otlp(staging_id=UUID(staging_id))
        if result and result.status == STAGING_STATUS_FAILED:
            return
    except Exception as exc:
        logger.warning("process_staged_otlp failed for {}: {}", staging_id, exc)
        if self.request.retries >= self.max_retries:
            db = SessionLocal()
            try:
                from app.models.database import SyntheticTraceIngestStaging
                from app.services.synthetic_traces.ingest_pipeline import _mark_staging_failed

                row = (
                    db.query(SyntheticTraceIngestStaging)
                    .filter(SyntheticTraceIngestStaging.id == UUID(staging_id))
                    .first()
                )
                if row and row.status != STAGING_STATUS_FAILED:
                    _mark_staging_failed(db, row, str(exc))
            finally:
                db.close()
            return
        raise self.retry(exc=exc, countdown=5)


@celery_app.task(name="sweep_staging_ingest", queue=TRACES_WORKER_QUEUE)
def sweep_staging_ingest_task() -> int:
    from app.database import SessionLocal
    from app.services.synthetic_traces.ingest_pipeline import sweep_staging_ingest

    db = SessionLocal()
    try:
        return sweep_staging_ingest(db)
    finally:
        db.close()


@celery_app.task(
    name="close_and_offload_trace",
    queue=TRACES_WORKER_QUEUE,
    bind=True,
    max_retries=5,
)
def close_and_offload_trace_task(self, trace_id: str) -> None:
    from app.database import SessionLocal
    from app.services.synthetic_traces.trace_service import close_and_offload_trace

    db = SessionLocal()
    try:
        close_and_offload_trace(db, trace_id=UUID(trace_id))
    except Exception as exc:
        logger.warning("close_and_offload_trace failed for {}: {}", trace_id, exc)
        raise self.retry(exc=exc, countdown=10)
    finally:
        db.close()
