"""Discovery orchestration for platform historical call imports."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID, uuid5

from loguru import logger
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.models.database import (
    CallImport,
    CallImportDiscoverySlice,
    CallImportRow,
    Integration,
    PlatformConversationLedger,
)
from app.models.enums import CallImportRowStatus, CallImportStatus
from app.services.voice_providers.historical.base import (
    HistoricalListItem,
    SkipReason,
    TimeSlice,
    build_canonical_recording_url,
    get_historical_adapter,
)

NAMESPACE_PLATFORM_ROW = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")


def platform_row_id(call_import_id: UUID, conversation_id: str) -> UUID:
    return uuid5(NAMESPACE_PLATFORM_ROW, f"{call_import_id}:{conversation_id}")


def _filters(call_import: CallImport) -> Dict[str, Any]:
    raw = call_import.platform_filters
    return dict(raw) if isinstance(raw, dict) else {}


def plan_time_slices(
    window_start: datetime,
    window_end: datetime,
    agent_ids: Optional[List[str]],
) -> List[Tuple[datetime, datetime, Optional[str]]]:
    slices: List[Tuple[datetime, datetime, Optional[str]]] = []
    agents = agent_ids or [None]
    cursor = window_start
    slice_id = 0
    while cursor < window_end:
        slice_end = min(cursor + timedelta(days=1), window_end)
        for agent_id in agents:
            slices.append((cursor, slice_end, agent_id))
            slice_id += 1
        cursor = slice_end
    return slices


def create_discovery_slices(
    db: Session,
    call_import: CallImport,
    agent_ids: Optional[List[str]],
) -> int:
    if call_import.window_start is None or call_import.window_end is None:
        return 0
    planned = plan_time_slices(
        call_import.window_start,
        call_import.window_end,
        agent_ids,
    )
    for idx, (start, end, agent_id) in enumerate(planned):
        cursor_val = f"agent:{agent_id}" if agent_id else ""
        db.add(
            CallImportDiscoverySlice(
                call_import_id=call_import.id,
                slice_id=idx,
                slice_start=start,
                slice_end=end,
                status="pending",
                cursor=cursor_val or None,
            )
        )
    return len(planned)


def _should_skip_item(
    item: HistoricalListItem,
    filters: Dict[str, Any],
) -> Optional[SkipReason]:
    min_duration = float(filters.get("min_duration_seconds") or 5)
    if item.duration_seconds is not None and item.duration_seconds < min_duration:
        return SkipReason.TOO_SHORT
    status = (item.status or "").strip().lower()
    allowed = filters.get("call_statuses")
    if allowed:
        allowed_set = {str(s).lower() for s in allowed}
        if status and status not in allowed_set:
            return SkipReason.FILTERED_STATUS
    else:
        if status in {"initiated", "in-progress", "processing", "queued", "ringing"}:
            return SkipReason.IN_PROGRESS
        if status and status not in {
            "done",
            "ended",
            "completed",
            "error",
            "failed",
        }:
            return SkipReason.FILTERED_STATUS
    if not item.has_audio:
        return SkipReason.NO_AUDIO
    return None


def _increment_skip(call_import: CallImport, reason: SkipReason, sample: Dict[str, Any]) -> None:
    counts = dict(call_import.skip_counts or {})
    key = reason.value
    counts[key] = int(counts.get(key) or 0) + 1
    call_import.skip_counts = counts
    samples = list(call_import.skip_samples or [])
    if len(samples) < 100:
        samples.append(sample)
        call_import.skip_samples = samples


def rematerialize_reserved_rows(db: Session, call_import_id: UUID) -> int:
    from app.db_sharding.row_ops import bulk_insert_mappings_on_shards, register_shard_slices
    from app.db_sharding.sessions import is_sharding_enabled

    reserved = (
        db.query(PlatformConversationLedger)
        .filter(
            PlatformConversationLedger.call_import_id == call_import_id,
            PlatformConversationLedger.state == "reserved",
        )
        .order_by(PlatformConversationLedger.row_index.asc())
        .all()
    )
    if not reserved:
        return 0
    call_import = db.query(CallImport).filter(CallImport.id == call_import_id).first()
    if call_import is None:
        return 0
    mappings = []
    for entry in reserved:
        mappings.append(
            {
                "id": entry.row_id,
                "call_import_id": call_import.id,
                "organization_id": call_import.organization_id,
                "workspace_id": call_import.workspace_id,
                "row_index": entry.row_index,
                "conversation_id": entry.conversation_id,
                "recording_url": build_canonical_recording_url(
                    call_import.provider or "",
                    entry.conversation_id,
                ),
                "status": CallImportRowStatus.PENDING.value,
            }
        )
    if is_sharding_enabled():
        bulk_insert_mappings_on_shards(db, call_import.id, mappings)
        register_shard_slices(db, call_import.id, call_import.total_rows or 0)
    else:
        for mapping in mappings:
            db.merge(CallImportRow(**mapping))
    for entry in reserved:
        entry.state = "materialized"
    db.flush()
    return len(reserved)


def discover_platform_slice_chunk(
    db: Session,
    call_import_id: UUID,
    slice_id: int,
    *,
    page_budget: int,
) -> bool:
    """Process up to page_budget list pages for one slice. Returns True if more work remains."""
    call_import = db.query(CallImport).filter(CallImport.id == call_import_id).first()
    if call_import is None or call_import.status == CallImportStatus.DELETING:
        return False
    if call_import.paused_at is not None:
        return False

    integration = (
        db.query(Integration)
        .filter(Integration.id == call_import.voice_integration_id)
        .first()
    )
    if integration is None:
        call_import.discovery_status = "failed"
        call_import.error_message = "Voice integration not found"
        db.commit()
        return False

    slice_row = (
        db.query(CallImportDiscoverySlice)
        .filter(
            CallImportDiscoverySlice.call_import_id == call_import_id,
            CallImportDiscoverySlice.slice_id == slice_id,
        )
        .first()
    )
    if slice_row is None or slice_row.status in {"completed", "failed"}:
        return False

    rematerialize_reserved_rows(db, call_import_id)

    adapter = get_historical_adapter(integration)
    filters = _filters(call_import)
    speed = filters.get("speed")
    include_reimport = bool(filters.get("include_previously_imported"))

    from app.workers.concurrency.platform_import_limits import (
        consume_platform_api_token,
        credential_import_paused,
    )

    if credential_import_paused(integration.id):
        call_import.paused_at = datetime.now(timezone.utc)
        call_import.pause_reason = "credential_rejected"
        db.commit()
        return False

    slice_row.status = "running"
    slice_row.attempts = int(slice_row.attempts or 0) + 1
    call_import.discovery_status = "running"
    call_import.status = CallImportStatus.PROCESSING
    db.commit()

    agent_id: Optional[str] = None
    list_cursor: Optional[str] = None
    raw_cursor = (slice_row.cursor or "").strip()
    if raw_cursor.startswith("agent:"):
        agent_id = raw_cursor[6:] or None
    elif raw_cursor:
        list_cursor = raw_cursor

    time_slice = TimeSlice(
        slice_id=slice_id,
        slice_start=slice_row.slice_start,
        slice_end=slice_row.slice_end,
        agent_id=agent_id,
    )

    pages = 0
    more = True
    while pages < page_budget and more:
        token = consume_platform_api_token(integration.id, speed)
        if not token.allowed:
            db.commit()
            return True

        try:
            items, next_cursor = adapter.list_page(time_slice, list_cursor)
        except Exception as exc:
            logger.exception(
                "platform discovery list failed import={} slice={}",
                call_import_id,
                slice_id,
            )
            slice_row.error = str(exc)
            if slice_row.attempts >= 5:
                slice_row.status = "failed"
            db.commit()
            return slice_row.status != "completed"

        slice_row.listed = int(slice_row.listed or 0) + len(items)
        accepted_batch: List[HistoricalListItem] = []
        for item in items:
            skip = _should_skip_item(item, filters)
            if skip is not None:
                _increment_skip(
                    call_import,
                    skip,
                    {"conversation_id": item.conversation_id, "reason": skip.value},
                )
                continue
            if (call_import.total_rows or 0) >= (call_import.max_calls or settings.PLATFORM_IMPORT_MAX_CALLS_DEFAULT):
                call_import.discovery_status = "capped"
                more = False
                break
            accepted_batch.append(item)

        if accepted_batch:
            _reserve_and_insert_rows(
                db,
                call_import,
                integration,
                accepted_batch,
                include_reimport=include_reimport,
            )

        pages += 1
        list_cursor = next_cursor
        if next_cursor:
            slice_row.cursor = next_cursor
        elif agent_id:
            slice_row.cursor = f"agent:{agent_id}"
        else:
            slice_row.cursor = ""
        more = bool(next_cursor)

    if not more:
        slice_row.status = "completed"
    db.commit()

    if _all_slices_terminal(db, call_import_id):
        if call_import.discovery_status != "capped":
            call_import.discovery_status = "completed"
        from app.services.billing.flexprice_service import record_call_import_batch_created

        record_call_import_batch_created(
            call_import.organization_id,
            call_import.id,
            workspace_id=call_import.workspace_id,
            total_rows=call_import.total_rows,
            source="platform",
            provider=call_import.provider,
        )
        db.commit()
        from app.workers.concurrency.fair_platform_import_dispatch import (
            schedule_fair_platform_import_dispatch,
        )

        schedule_fair_platform_import_dispatch()

    return more or slice_row.status == "running"


def _all_slices_terminal(db: Session, call_import_id: UUID) -> bool:
    pending = (
        db.query(CallImportDiscoverySlice)
        .filter(
            CallImportDiscoverySlice.call_import_id == call_import_id,
            CallImportDiscoverySlice.status.in_(("pending", "running")),
        )
        .count()
    )
    return pending == 0


def _reserve_and_insert_rows(
    db: Session,
    call_import: CallImport,
    integration: Integration,
    items: List[HistoricalListItem],
    *,
    include_reimport: bool,
) -> None:
    from app.db_sharding.row_ops import bulk_insert_mappings_on_shards, register_shard_slices
    from app.db_sharding.sessions import is_sharding_enabled

    provider = (call_import.provider or integration.platform or "").lower()
    n = len(items)
    start_index = int(call_import.next_row_index or 0)
    call_import.next_row_index = start_index + n

    mappings = []
    for offset, item in enumerate(items):
        row_id = platform_row_id(call_import.id, item.conversation_id)
        ledger = PlatformConversationLedger(
            workspace_id=call_import.workspace_id,
            provider=provider,
            conversation_id=item.conversation_id,
            call_import_id=call_import.id,
            row_id=row_id,
            row_index=start_index + offset,
            state="reserved",
        )
        try:
            with db.begin_nested():
                db.add(ledger)
                db.flush()
        except IntegrityError:
            if not include_reimport:
                _increment_skip(
                    call_import,
                    SkipReason.DUPLICATE,
                    {"conversation_id": item.conversation_id},
                )
            continue

        recording_date = None
        if item.started_at is not None:
            recording_date = item.started_at.date()

        mappings.append(
            {
                "id": row_id,
                "call_import_id": call_import.id,
                "organization_id": call_import.organization_id,
                "workspace_id": call_import.workspace_id,
                "row_index": start_index + offset,
                "conversation_id": item.conversation_id,
                "recording_url": build_canonical_recording_url(provider, item.conversation_id),
                "recording_date": recording_date,
                "raw_columns": {
                    "agent_id": item.agent_id,
                    "started_at": item.started_at.isoformat() if item.started_at else None,
                    "duration_seconds": item.duration_seconds,
                    "status": item.status,
                },
                "status": CallImportRowStatus.PENDING.value,
            }
        )

    if not mappings:
        return

    if is_sharding_enabled():
        bulk_insert_mappings_on_shards(db, call_import.id, mappings)
        register_shard_slices(db, call_import.id, call_import.next_row_index)
    else:
        for mapping in mappings:
            db.merge(CallImportRow(**mapping))

    row_ids = [m["id"] for m in mappings]
    db.query(PlatformConversationLedger).filter(
        PlatformConversationLedger.row_id.in_(row_ids)
    ).update({"state": "materialized"}, synchronize_session=False)

    call_import.total_rows = int(call_import.total_rows or 0) + len(mappings)
    db.flush()
