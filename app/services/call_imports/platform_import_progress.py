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


def build_platform_import_progress(
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
    queued_rows = 0
    if row_pending > 0:
        from app.db_sharding.sessions import is_sharding_enabled

        if not is_sharding_enabled():
            queued_rows = int(
                db.query(func.count(CallImportRow.id))
                .filter(
                    CallImportRow.call_import_id == call_import.id,
                    CallImportRow.status == CallImportRowStatus.PENDING,
                    CallImportRow.celery_task_id.isnot(None),
                )
                .scalar()
                or 0
            )
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

    if paused:
        phase = "paused"
    elif discovery_status == "failed" or slices_failed > 0 and not discovery_active:
        phase = "failed"
    elif discovery_active:
        phase = "discovering"
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

    is_active = (
        batch_status == CallImportStatus.DELETING.value
        or discovery_active
        or import_active
        or (discovery_terminal and not batch_terminal and batch_status == CallImportStatus.PROCESSING.value)
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
        "discovery": {
            "slices_total": slices_total,
            "slices_completed": slices_completed,
            "slices_running": slices_running,
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
