"""Aggregate live progress for platform historical imports."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import UUID

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.models.database import CallImport, CallImportDiscoverySlice, CallImportRow
from app.models.enums import CallImportRowStatus, CallImportStatus
from app.services.call_imports.bulk_ops import _aggregate_import_row_status_counts

_DISCOVERY_ACTIVE = {"queued", "running"}
_DISCOVERY_TERMINAL = {"completed", "capped", "failed"}


def _count_queued_rows(db: Session, call_import_id: UUID) -> int:
    """Pending rows that already have a worker task id.

    With sharding those rows are not on the catalog session. Counting only
    the catalog made every saved call look "waiting" while its task sat in
    the queue.
    """
    from app.db_sharding.sessions import is_sharding_enabled

    def _count(session: Session) -> int:
        return int(
            session.query(func.count(CallImportRow.id))
            .filter(
                CallImportRow.call_import_id == call_import_id,
                CallImportRow.status == CallImportRowStatus.PENDING,
                CallImportRow.celery_task_id.isnot(None),
            )
            .scalar()
            or 0
        )

    if not is_sharding_enabled():
        return _count(db)

    from app.db_sharding.pool_manager import db_pool_manager
    from app.db_sharding.scatter_gather import shard_ids_for_import

    total = 0
    for shard_id in shard_ids_for_import(db, call_import_id):
        factory = db_pool_manager.shard_session_factory(shard_id)
        shard_db = factory()
        try:
            total += _count(shard_db)
        finally:
            shard_db.close()
    return total


def build_platform_import_progress(
    db: Session,
    call_import: CallImport,
) -> Dict[str, Any]:
    import json

    from app.workers.concurrency.platform_import_limits import _client

    cache_key = f"platform_import:progress:{call_import.id}"
    try:
        cached = _client().get(cache_key)
        if cached:
            return json.loads(cached)
    except Exception:
        cached = None
    payload = _build_platform_import_progress(db, call_import)
    try:
        _client().setex(
            cache_key,
            2,
            json.dumps(payload, default=str),
        )
    except Exception:
        pass
    return payload


def _build_platform_import_progress(
    db: Session,
    call_import: CallImport,
) -> Dict[str, Any]:
    slice_rows = (
        db.query(
            func.count(CallImportDiscoverySlice.slice_id).label("total"),
            func.sum(
                case((CallImportDiscoverySlice.status == "completed", 1), else_=0)
            ).label("completed"),
            func.sum(
                case((CallImportDiscoverySlice.status == "running", 1), else_=0)
            ).label("running"),
            func.sum(
                case((CallImportDiscoverySlice.status == "queued", 1), else_=0)
            ).label("queued"),
            func.sum(
                case((CallImportDiscoverySlice.status == "pending", 1), else_=0)
            ).label("pending"),
            func.sum(
                case((CallImportDiscoverySlice.status == "failed", 1), else_=0)
            ).label("failed"),
            func.coalesce(func.sum(CallImportDiscoverySlice.listed), 0).label("listed"),
        )
        .filter(CallImportDiscoverySlice.call_import_id == call_import.id)
        .one()
    )

    slices_total = int(slice_rows.total or 0)
    slices_completed = int(slice_rows.completed or 0)
    slices_running = int(slice_rows.running or 0)
    slices_queued = int(slice_rows.queued or 0)
    slices_pending = int(slice_rows.pending or 0)
    slices_failed = int(slice_rows.failed or 0)
    listed_total = int(slice_rows.listed or 0)

    discovery_status = (call_import.discovery_status or "").strip().lower() or None
    discovery_percent = (
        round(100.0 * slices_completed / slices_total, 1) if slices_total > 0 else 0.0
    )

    (
        row_total,
        row_completed,
        row_failed,
        row_pending,
        row_processing,
    ) = _aggregate_import_row_status_counts(db, call_import.id)
    total_rows = row_total if row_total > 0 else int(call_import.total_rows or 0)
    completed_rows = row_completed if row_total > 0 else int(call_import.completed_rows or 0)
    failed_rows = row_failed if row_total > 0 else int(call_import.failed_rows or 0)
    terminal_rows = min(completed_rows + failed_rows, total_rows) if total_rows else completed_rows + failed_rows
    processing_rows = row_processing
    pending_rows = row_pending
    queued_rows = _count_queued_rows(db, call_import.id) if row_pending > 0 else 0
    import_percent = (
        round(100.0 * terminal_rows / total_rows, 1) if total_rows > 0 else 0.0
    )

    paused = call_import.paused_at is not None
    batch_status = (
        call_import.status.value
        if isinstance(call_import.status, CallImportStatus)
        else str(call_import.status or "")
    )

    discovery_active = discovery_status in _DISCOVERY_ACTIVE
    discovery_terminal = discovery_status in _DISCOVERY_TERMINAL
    import_active = (
        total_rows > 0
        and terminal_rows < total_rows
        and batch_status not in {CallImportStatus.DELETING.value, "deleting"}
    )
    batch_terminal = batch_status in {
        CallImportStatus.COMPLETED.value,
        CallImportStatus.PARTIAL.value,
        CallImportStatus.FAILED.value,
        "completed",
        "partial",
        "failed",
    }

    from app.config import settings
    from app.workers.concurrency.platform_import_limits import platform_import_runtime_stats

    runtime = platform_import_runtime_stats()
    progress_at = getattr(call_import, "last_progress_at", None)
    stalled = False
    if progress_at is not None and (import_active or discovery_active) and not paused:
        age = datetime.now(timezone.utc) - progress_at
        stalled = age.total_seconds() >= settings.PLATFORM_IMPORT_STALL_MINUTES * 60

    if paused:
        phase = "paused"
    elif stalled:
        phase = "stalled"
    elif discovery_status == "capped" and (import_active or not batch_terminal):
        phase = "capped"
    elif discovery_status == "failed" or slices_failed > 0 and not discovery_active and total_rows == 0:
        phase = "failed"
    elif discovery_active:
        phase = "discovering"
    elif discovery_terminal and total_rows == 0 and discovery_status in {"completed", "capped"}:
        phase = "complete"
    elif import_active or (discovery_terminal and not batch_terminal):
        phase = "importing"
    else:
        phase = "complete"

    if discovery_active and total_rows == 0:
        overall_percent = discovery_percent * 0.45
    elif discovery_active:
        overall_percent = min(
            99.0,
            discovery_percent * 0.35 + import_percent * 0.65,
        )
    elif total_rows > 0:
        overall_percent = import_percent
    elif discovery_terminal:
        overall_percent = 100.0 if discovery_status in {"completed", "capped"} else 0.0
    else:
        overall_percent = discovery_percent * 0.45

    nothing_imported = (
        discovery_terminal and total_rows == 0 and discovery_status in {"completed", "capped"}
    )
    is_active = (
        not nothing_imported
        and (
            batch_status == CallImportStatus.DELETING.value
            or discovery_active
            or import_active
            or (
                discovery_terminal
                and not batch_terminal
                and batch_status == CallImportStatus.PROCESSING.value
            )
        )
    )
    if batch_status == CallImportStatus.DELETING.value:
        phase = "deleting"
        is_active = True
        overall_percent = 0.0

    return {
        "call_import_id": str(call_import.id),
        "provider": call_import.provider,
        "dataset": call_import.dataset,
        "status": batch_status,
        "discovery_status": discovery_status,
        "paused": paused,
        "pause_reason": call_import.pause_reason,
        "phase": phase,
        "overall_percent": round(overall_percent, 1),
        "is_active": is_active,
        "calls_discovered": total_rows,
        "skip_counts": dict(call_import.skip_counts or {}),
        "window_start": call_import.window_start,
        "window_end": call_import.window_end,
        "updated_at": call_import.updated_at or datetime.now(timezone.utc),
        "last_progress_at": getattr(call_import, "last_progress_at", None),
        "backlog": runtime["imports_depth"],
        "inflight": runtime["global_leases"],
        "rate_limited": False,
        "slice_errors": slices_failed,
        "discovery": {
            "slices_total": slices_total,
            "slices_completed": slices_completed,
            "slices_running": slices_running,
            "slices_queued": slices_queued,
            "slices_pending": slices_pending,
            "slices_failed": slices_failed,
            "listed_total": listed_total,
            "percent": discovery_percent,
        },
        "recordings": {
            "total": total_rows,
            "completed": completed_rows,
            "failed": failed_rows,
            "processing": processing_rows,
            "pending": pending_rows,
            "queued": queued_rows,
            "percent": import_percent,
        },
    }
