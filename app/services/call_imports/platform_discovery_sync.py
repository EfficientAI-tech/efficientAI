"""Finalize platform discovery when import rows are idle (stale slice recovery)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from loguru import logger
from sqlalchemy.orm import Session

from app.config import settings
from app.models.database import CallImport, CallImportDiscoverySlice
from app.models.enums import CallImportStatus
from app.services.call_imports.import_batch_helpers import is_platform_call_import


def reclaim_stale_platform_discovery_slices(
    db: Session,
    *,
    limit: int = 8,
) -> int:
    """Reset ``queued``/``running`` slices with no heartbeat back to ``pending``."""
    stale_cutoff = datetime.now(timezone.utc) - timedelta(
        minutes=settings.PLATFORM_IMPORT_DISCOVERY_SLICE_STALE_MINUTES
    )
    from app.workers.concurrency.platform_import_limits import force_release_slice_lock

    stale_slices = (
        db.query(CallImportDiscoverySlice)
        .join(CallImport, CallImport.id == CallImportDiscoverySlice.call_import_id)
        .filter(
            CallImport.source_format == "platform",
            CallImport.status != CallImportStatus.DELETING,
            CallImportDiscoverySlice.status.in_(("queued", "running")),
            CallImportDiscoverySlice.updated_at < stale_cutoff,
        )
        .limit(max(1, int(limit)))
        .all()
    )
    if not stale_slices:
        return 0
    for slice_row in stale_slices:
        force_release_slice_lock(slice_row.call_import_id, slice_row.slice_id)
        slice_row.status = "pending"
    db.commit()
    return len(stale_slices)


def _close_active_discovery_slices_when_rows_idle(
    db: Session,
    call_import_id: UUID,
) -> int:
    """Mark leftover discovery slices terminal once import row work is idle."""
    from sqlalchemy import update

    result = db.execute(
        update(CallImportDiscoverySlice)
        .where(
            CallImportDiscoverySlice.call_import_id == call_import_id,
            CallImportDiscoverySlice.status.in_(("pending", "queued", "running")),
        )
        .values(
            status="failed",
            error="Import row processing finished; discovery slice closed.",
        )
    )
    closed = int(result.rowcount or 0)
    if closed:
        db.flush()
    return closed


def sync_platform_discovery_when_import_rows_idle(
    db: Session,
    call_import: CallImport,
) -> None:
    """Reclaim stale slices and finalize discovery when row hydrate is done."""
    if not is_platform_call_import(call_import):
        return
    discovery = (call_import.discovery_status or "").strip().lower()
    if discovery in {"completed", "capped", "failed", "partial"}:
        return

    from app.services.call_imports.bulk_ops import _aggregate_import_row_status_counts

    total, _completed, _failed, pending, processing = _aggregate_import_row_status_counts(
        db, call_import.id
    )
    if pending > 0 or processing > 0:
        return
    if total <= 0:
        return

    reclaimed = reclaim_stale_platform_discovery_slices(db, limit=8)
    if reclaimed:
        logger.info(
            "platform discovery reclaimed {} stale slice(s) for import {}",
            reclaimed,
            call_import.id,
        )

    closed = _close_active_discovery_slices_when_rows_idle(db, call_import.id)
    if closed:
        logger.info(
            "platform discovery closed {} active slice(s) for idle import {}",
            closed,
            call_import.id,
        )

    from app.services.call_imports.platform_discovery import (
        finalize_platform_discovery_if_complete,
    )

    finalize_platform_discovery_if_complete(db, call_import.id)
    db.refresh(call_import)
