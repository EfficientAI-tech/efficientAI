"""Finalize platform discovery when import rows are idle (stale slice recovery)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

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


def sync_platform_discovery_when_import_rows_idle(
    db: Session,
    call_import: CallImport,
) -> None:
    """Reclaim stale slices once row hydrate is idle.

    Unfinished slices stay eligible. Listing can still be waiting on a rate
    limit or a later time window after the rows discovered so far have
    finished. Stale ``queued``/``running`` slices are returned to ``pending``
    from their heartbeat, and discovery is finalized only when every slice
    is already terminal.
    """
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

    from app.services.call_imports.platform_discovery import (
        finalize_platform_discovery_if_complete,
    )

    finalize_platform_discovery_if_complete(db, call_import.id)
    db.refresh(call_import)
