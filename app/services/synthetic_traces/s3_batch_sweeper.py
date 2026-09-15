"""Re-enqueue orphaned S3 OTLP batch WAL objects."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from loguru import logger

from app.config import settings
from app.services.clickhouse.client import clickhouse_enabled
from app.services.storage.blob_storage_service import blob_storage_service
from app.services.storage.blob_paths import normalize_prefix
from app.services.synthetic_traces.clickhouse_store import (
    get_batch_meta,
    is_batch_processed,
)


def sweep_orphan_s3_batches() -> int:
    if not clickhouse_enabled() or not settings.S3_ENABLED:
        return 0

    prefix = f"{normalize_prefix(settings.TRACES_S3_PREFIX)}organizations/"
    cutoff_minutes = max(5, int(settings.TRACES_S3_BATCH_ORPHAN_MINUTES))
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=cutoff_minutes)
    requeued = 0

    try:
        keys = blob_storage_service.list_objects_with_prefix(
            prefix, contains="/batches/", max_keys=2000
        )
    except Exception as exc:
        logger.warning("Orphan S3 batch sweep list failed: {}", exc)
        return 0

    from app.services.synthetic_traces.ingest_pipeline import schedule_s3_batch_process
    from uuid import UUID

    for key, last_modified in keys:
        if is_batch_processed(key):
            continue
        if last_modified and last_modified > cutoff:
            continue
        parts = key.split("/")
        try:
            org_idx = parts.index("organizations") + 1
            ws_idx = parts.index("workspaces") + 1
            trace_idx = parts.index("traces") + 1
            batch_idx = parts.index("batches") + 1
            organization_id = UUID(parts[org_idx])
            workspace_id = UUID(parts[ws_idx])
            trace_uuid = UUID(parts[trace_idx])
            seq = int(parts[batch_idx].replace(".json", ""))
        except (ValueError, IndexError):
            continue

        meta = get_batch_meta(key)
        content_type = meta.get("content_type") or "application/json"
        schedule_s3_batch_process(
            s3_key=key,
            organization_id=organization_id,
            workspace_id=workspace_id,
            trace_uuid=trace_uuid,
            seq=seq,
            content_type=content_type,
        )
        requeued += 1

    return requeued
