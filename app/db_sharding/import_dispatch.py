"""Per-shard import and diarization dispatch helpers."""

from __future__ import annotations

from typing import List, Optional, Tuple
from uuid import UUID

from sqlalchemy.orm import Session

from app.db_sharding.pool_manager import db_pool_manager
from app.db_sharding.sessions import is_sharding_enabled
from app.models.database import CallImport, CallImportRow
from app.models.enums import CallImportRowStatus, CallImportStatus


def _import_blocked_by_rebalance(call_import_id: UUID) -> bool:
    from app.db_sharding.rebalance import is_import_rebalance_locked

    return is_import_rebalance_locked(call_import_id)


def pending_import_workspaces(catalog_db: Session) -> List[UUID]:
    if not is_sharding_enabled():
        rows = (
            catalog_db.query(CallImport.workspace_id)
            .join(CallImportRow, CallImportRow.call_import_id == CallImport.id)
            .filter(
                CallImport.status != CallImportStatus.DELETING,
                CallImportRow.status == CallImportRowStatus.PENDING,
                CallImportRow.celery_task_id.is_(None),
            )
            .distinct()
            .all()
        )
        return sorted({row[0] for row in rows if row[0] is not None})

    import_ids: set[UUID] = set()
    router = db_pool_manager.router
    assert router is not None
    for shard_id in router.shard_ids:
        factory = db_pool_manager.shard_session_factory(shard_id)
        shard_db = factory()
        try:
            rows = (
                shard_db.query(CallImportRow.call_import_id)
                .filter(
                    CallImportRow.status == CallImportRowStatus.PENDING,
                    CallImportRow.celery_task_id.is_(None),
                )
                .distinct()
                .all()
            )
            import_ids.update(row[0] for row in rows if row[0] is not None)
        finally:
            shard_db.close()
    if not import_ids:
        return []
    from app.db_sharding.rebalance import filter_unlocked_call_import_ids

    import_ids = set(filter_unlocked_call_import_ids(import_ids))
    if not import_ids:
        return []
    rows = (
        catalog_db.query(CallImport.workspace_id)
        .filter(
            CallImport.id.in_(import_ids),
            CallImport.status != CallImportStatus.DELETING,
        )
        .distinct()
        .all()
    )
    return sorted({row[0] for row in rows if row[0] is not None})


def call_imports_with_pending_rows(
    catalog_db: Session,
    workspace_id: UUID,
) -> List[UUID]:
    if not is_sharding_enabled():
        rows = (
            catalog_db.query(CallImport.id)
            .join(CallImportRow, CallImportRow.call_import_id == CallImport.id)
            .filter(
                CallImport.workspace_id == workspace_id,
                CallImport.status != CallImportStatus.DELETING,
                CallImportRow.status == CallImportRowStatus.PENDING,
                CallImportRow.celery_task_id.is_(None),
            )
            .distinct()
            .all()
        )
        return sorted({row[0] for row in rows if row[0] is not None})

    candidates = [
        row[0]
        for row in catalog_db.query(CallImport.id)
        .filter(
            CallImport.workspace_id == workspace_id,
            CallImport.status != CallImportStatus.DELETING,
        )
        .all()
        if row[0] is not None
    ]
    pending: set[UUID] = set()
    router = db_pool_manager.router
    assert router is not None
    for shard_id in router.shard_ids:
        factory = db_pool_manager.shard_session_factory(shard_id)
        shard_db = factory()
        try:
            rows = (
                shard_db.query(CallImportRow.call_import_id)
                .filter(
                    CallImportRow.call_import_id.in_(candidates),
                    CallImportRow.status == CallImportRowStatus.PENDING,
                    CallImportRow.celery_task_id.is_(None),
                )
                .distinct()
                .all()
            )
            pending.update(row[0] for row in rows if row[0] is not None)
        finally:
            shard_db.close()
    from app.db_sharding.rebalance import filter_unlocked_call_import_ids

    return sorted(filter_unlocked_call_import_ids(pending))


def pending_import_row_for_call_import(
    catalog_db: Session,
    call_import_id: UUID,
) -> Optional[Tuple[CallImportRow, CallImport]]:
    call_import = (
        catalog_db.query(CallImport)
        .filter(
            CallImport.id == call_import_id,
            CallImport.status != CallImportStatus.DELETING,
        )
        .first()
    )
    if call_import is None:
        return None
    if _import_blocked_by_rebalance(call_import_id):
        return None

    if not is_sharding_enabled():
        row = (
            catalog_db.query(CallImportRow)
            .filter(
                CallImportRow.call_import_id == call_import_id,
                CallImportRow.status == CallImportRowStatus.PENDING,
                CallImportRow.celery_task_id.is_(None),
            )
            .order_by(CallImportRow.created_at.asc())
            .first()
        )
        return (row, call_import) if row is not None else None

    router = db_pool_manager.router
    assert router is not None
    for shard_id in router.shard_ids:
        factory = db_pool_manager.shard_session_factory(shard_id)
        shard_db = factory()
        try:
            row = (
                shard_db.query(CallImportRow)
                .filter(
                    CallImportRow.call_import_id == call_import_id,
                    CallImportRow.status == CallImportRowStatus.PENDING,
                    CallImportRow.celery_task_id.is_(None),
                )
                .order_by(CallImportRow.created_at.asc())
                .first()
            )
            if row is not None:
                return row, call_import
        finally:
            shard_db.close()
    return None


def pending_diarization_workspaces(catalog_db: Session) -> List[UUID]:
    if not is_sharding_enabled():
        rows = (
            catalog_db.query(CallImport.workspace_id)
            .join(CallImportRow, CallImportRow.call_import_id == CallImport.id)
            .filter(
                CallImportRow.diarised_transcript_status == "pending",
                CallImportRow.celery_task_id.is_(None),
            )
            .distinct()
            .all()
        )
        return sorted({row[0] for row in rows if row[0] is not None})

    import_ids: set[UUID] = set()
    router = db_pool_manager.router
    assert router is not None
    for shard_id in router.shard_ids:
        factory = db_pool_manager.shard_session_factory(shard_id)
        shard_db = factory()
        try:
            rows = (
                shard_db.query(CallImportRow.call_import_id)
                .filter(
                    CallImportRow.diarised_transcript_status == "pending",
                    CallImportRow.celery_task_id.is_(None),
                )
                .distinct()
                .all()
            )
            import_ids.update(row[0] for row in rows if row[0] is not None)
        finally:
            shard_db.close()
    if not import_ids:
        return []
    from app.db_sharding.rebalance import filter_unlocked_call_import_ids

    import_ids = set(filter_unlocked_call_import_ids(import_ids))
    if not import_ids:
        return []
    rows = (
        catalog_db.query(CallImport.workspace_id)
        .filter(CallImport.id.in_(import_ids))
        .distinct()
        .all()
    )
    return sorted({row[0] for row in rows if row[0] is not None})


def call_imports_with_pending_diarization(
    catalog_db: Session,
    workspace_id: UUID,
) -> List[UUID]:
    if not is_sharding_enabled():
        rows = (
            catalog_db.query(CallImport.id)
            .join(CallImportRow, CallImportRow.call_import_id == CallImport.id)
            .filter(
                CallImport.workspace_id == workspace_id,
                CallImportRow.diarised_transcript_status == "pending",
                CallImportRow.celery_task_id.is_(None),
            )
            .distinct()
            .all()
        )
        return sorted({row[0] for row in rows if row[0] is not None})

    candidates = [
        row[0]
        for row in catalog_db.query(CallImport.id)
        .filter(CallImport.workspace_id == workspace_id)
        .all()
        if row[0] is not None
    ]
    pending: set[UUID] = set()
    router = db_pool_manager.router
    assert router is not None
    for shard_id in router.shard_ids:
        factory = db_pool_manager.shard_session_factory(shard_id)
        shard_db = factory()
        try:
            rows = (
                shard_db.query(CallImportRow.call_import_id)
                .filter(
                    CallImportRow.call_import_id.in_(candidates),
                    CallImportRow.diarised_transcript_status == "pending",
                    CallImportRow.celery_task_id.is_(None),
                )
                .distinct()
                .all()
            )
            pending.update(row[0] for row in rows if row[0] is not None)
        finally:
            shard_db.close()
    from app.db_sharding.rebalance import filter_unlocked_call_import_ids

    return sorted(filter_unlocked_call_import_ids(pending))


def pending_diarization_row_for_call_import(
    catalog_db: Session,
    call_import_id: UUID,
) -> Optional[Tuple[CallImportRow, CallImport]]:
    call_import = (
        catalog_db.query(CallImport).filter(CallImport.id == call_import_id).first()
    )
    if call_import is None:
        return None
    if _import_blocked_by_rebalance(call_import_id):
        return None
    if not is_sharding_enabled():
        row = (
            catalog_db.query(CallImportRow)
            .filter(
                CallImportRow.call_import_id == call_import_id,
                CallImportRow.diarised_transcript_status == "pending",
                CallImportRow.celery_task_id.is_(None),
            )
            .order_by(CallImportRow.created_at.asc())
            .first()
        )
        return (row, call_import) if row is not None else None

    router = db_pool_manager.router
    assert router is not None
    for shard_id in router.shard_ids:
        factory = db_pool_manager.shard_session_factory(shard_id)
        shard_db = factory()
        try:
            row = (
                shard_db.query(CallImportRow)
                .filter(
                    CallImportRow.call_import_id == call_import_id,
                    CallImportRow.diarised_transcript_status == "pending",
                    CallImportRow.celery_task_id.is_(None),
                )
                .order_by(CallImportRow.created_at.asc())
                .first()
            )
            if row is not None:
                return row, call_import
        finally:
            shard_db.close()
    return None
