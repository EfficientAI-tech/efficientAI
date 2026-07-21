"""Scatter-gather reads and fan-out writes across row shards."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple, TypeVar, TYPE_CHECKING
from uuid import UUID

from sqlalchemy import case, func
from sqlalchemy.orm import Session, load_only

from app.db_sharding.pool_manager import db_pool_manager
from app.db_sharding.sessions import is_sharding_enabled
from app.models.database import CallImportEvaluation, CallImportEvaluationRow, CallImportRow

if TYPE_CHECKING:
    from app.db_sharding.session_cache import ShardSessionCache

T = TypeVar("T")


def _open_shard_session(
    shard_id: str,
    shard_cache: Optional["ShardSessionCache"],
) -> tuple[Session, bool]:
    """Return (session, should_close). Uses cache when provided."""
    if shard_cache is not None:
        return shard_cache.session_for(shard_id), False
    factory = db_pool_manager.shard_session_factory(shard_id)
    return factory(), True


def shard_ids_for_import(catalog_db: Session, call_import_id: UUID) -> List[str]:
    """Shard ids that may hold rows for this import (from registry or all shards)."""
    if not is_sharding_enabled():
        return ["legacy"]
    from app.db_sharding.registry import load_slice_registry_for_import

    registry = load_slice_registry_for_import(catalog_db, call_import_id)
    if registry:
        return sorted({v for v in registry.values()})
    router = db_pool_manager.router
    assert router is not None
    return list(router.shard_ids)


def scatter_gather_on_shards(
    shard_ids: Sequence[str],
    fn: Callable[[Session, str], T],
    *,
    max_workers: Optional[int] = None,
) -> List[T]:
    if not is_sharding_enabled() or len(shard_ids) <= 1:
        sid = shard_ids[0] if shard_ids else "legacy"
        if sid == "legacy":
            from app.database import SessionLocal

            db = SessionLocal()
            try:
                return [fn(db, sid)]
            finally:
                db.close()
        factory = db_pool_manager.shard_session_factory(sid)
        db = factory()
        try:
            return [fn(db, sid)]
        finally:
            db.close()

    workers = max_workers or min(len(shard_ids), 6)
    results: List[T] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {}
        for shard_id in shard_ids:
            futures[pool.submit(_run_on_shard, shard_id, fn)] = shard_id
        for future in as_completed(futures):
            results.append(future.result())
    return results


def _run_on_shard(shard_id: str, fn: Callable[[Session, str], T]) -> T:
    factory = db_pool_manager.shard_session_factory(shard_id)
    db = factory()
    try:
        return fn(db, shard_id)
    finally:
        db.close()


def merge_rows_by_index(rows: Iterable[CallImportRow]) -> List[CallImportRow]:
    return sorted(rows, key=lambda r: int(r.row_index or 0))


def _apply_call_import_row_filters(
    query,
    *,
    search_term: str,
    diarised_status_filter: Optional[str],
):
    if search_term:
        query = query.filter(
            CallImportRow.conversation_id.ilike(f"%{search_term}%")
        )
    if diarised_status_filter:
        query = query.filter(
            CallImportRow.diarised_transcript_status == diarised_status_filter
        )
    return query


def _merged_call_import_rows_for_import(
    catalog_db: Session,
    call_import_id: UUID,
    *,
    search_term: str = "",
    diarised_status_filter: Optional[str] = None,
) -> List[CallImportRow]:
    """All matching rows merged by ``row_index`` (scatter-gather when sharded)."""
    if not is_sharding_enabled():
        query = catalog_db.query(CallImportRow).filter(
            CallImportRow.call_import_id == call_import_id
        )
        query = _apply_call_import_row_filters(
            query,
            search_term=search_term,
            diarised_status_filter=diarised_status_filter,
        )
        return query.order_by(CallImportRow.row_index.asc()).all()

    def load_shard(db: Session, _shard_id: str) -> List[CallImportRow]:
        query = db.query(CallImportRow).filter(
            CallImportRow.call_import_id == call_import_id
        )
        query = _apply_call_import_row_filters(
            query,
            search_term=search_term,
            diarised_status_filter=diarised_status_filter,
        )
        return query.order_by(CallImportRow.row_index.asc()).all()

    shard_ids = shard_ids_for_import(catalog_db, call_import_id)
    merged: List[CallImportRow] = []
    for part in scatter_gather_on_shards(shard_ids, load_shard):
        merged.extend(part)
    merged = merge_rows_by_index(merged)
    if merged:
        return merged

    query = catalog_db.query(CallImportRow).filter(
        CallImportRow.call_import_id == call_import_id
    )
    query = _apply_call_import_row_filters(
        query,
        search_term=search_term,
        diarised_status_filter=diarised_status_filter,
    )
    return query.order_by(CallImportRow.row_index.asc()).all()


def count_call_import_rows_filtered(
    catalog_db: Session,
    call_import_id: UUID,
    *,
    search_term: str = "",
    diarised_status_filter: Optional[str] = None,
) -> int:
    if not is_sharding_enabled():
        query = catalog_db.query(func.count(CallImportRow.id)).filter(
            CallImportRow.call_import_id == call_import_id
        )
        query = _apply_call_import_row_filters(
            query,
            search_term=search_term,
            diarised_status_filter=diarised_status_filter,
        )
        return int(query.scalar() or 0)

    total = 0
    shard_ids = shard_ids_for_import(catalog_db, call_import_id)

    def count_shard(db: Session, _shard_id: str) -> int:
        query = db.query(func.count(CallImportRow.id)).filter(
            CallImportRow.call_import_id == call_import_id
        )
        query = _apply_call_import_row_filters(
            query,
            search_term=search_term,
            diarised_status_filter=diarised_status_filter,
        )
        return int(query.scalar() or 0)

    for part in scatter_gather_on_shards(shard_ids, count_shard):
        total += int(part)
    if total == 0:
        query = catalog_db.query(func.count(CallImportRow.id)).filter(
            CallImportRow.call_import_id == call_import_id
        )
        query = _apply_call_import_row_filters(
            query,
            search_term=search_term,
            diarised_status_filter=diarised_status_filter,
        )
        total = int(query.scalar() or 0)
    return total


def fetch_call_import_rows_filtered_page(
    catalog_db: Session,
    call_import_id: UUID,
    *,
    search_term: str = "",
    diarised_status_filter: Optional[str] = None,
    offset: int,
    limit: int,
) -> List[CallImportRow]:
    merged = _merged_call_import_rows_for_import(
        catalog_db,
        call_import_id,
        search_term=search_term,
        diarised_status_filter=diarised_status_filter,
    )
    return merged[offset : offset + limit]


def list_call_import_row_ids_filtered(
    catalog_db: Session,
    call_import_id: UUID,
    *,
    search_term: str = "",
    diarised_status_filter: Optional[str] = None,
) -> List[UUID]:
    merged = _merged_call_import_rows_for_import(
        catalog_db,
        call_import_id,
        search_term=search_term,
        diarised_status_filter=diarised_status_filter,
    )
    return [row.id for row in merged if row.id is not None]


def pending_eval_workspaces(
    catalog_db: Session,
    *,
    shard_cache: Optional["ShardSessionCache"] = None,
) -> List[UUID]:
    """Workspaces with pending eval rows (catalog + shard queries when sharded)."""
    if not is_sharding_enabled():
        return _pending_eval_workspaces_mono(catalog_db)

    evaluation_ids: set[UUID] = set()

    def collect_pending(db: Session, _shard_id: str) -> List[UUID]:
        rows = (
            db.query(CallImportEvaluationRow.evaluation_id)
            .filter(
                CallImportEvaluationRow.status == "pending",
                CallImportEvaluationRow.celery_task_id.is_(None),
            )
            .distinct()
            .all()
        )
        return [row[0] for row in rows if row[0] is not None]

    router = db_pool_manager.router
    assert router is not None
    for shard_id in router.shard_ids:
        shard_db, close_shard = _open_shard_session(shard_id, shard_cache)
        try:
            for eid in collect_pending(shard_db, shard_id):
                evaluation_ids.add(eid)
        finally:
            if close_shard:
                shard_db.close()

    if not evaluation_ids:
        return []

    from app.db_sharding.rebalance import filter_evaluations_not_rebalancing

    evaluation_ids = set(filter_evaluations_not_rebalancing(catalog_db, evaluation_ids))
    if not evaluation_ids:
        return []

    rows = (
        catalog_db.query(CallImportEvaluation.workspace_id)
        .filter(
            CallImportEvaluation.id.in_(evaluation_ids),
            CallImportEvaluation.status != "cancelled",
        )
        .distinct()
        .all()
    )
    return sorted({row[0] for row in rows if row[0] is not None})


def _pending_eval_workspaces_mono(db: Session) -> List[UUID]:
    from app.models.database import CallImportEvaluation

    rows = (
        db.query(CallImportEvaluation.workspace_id)
        .join(
            CallImportEvaluationRow,
            CallImportEvaluationRow.evaluation_id == CallImportEvaluation.id,
        )
        .filter(
            CallImportEvaluation.status != "cancelled",
            CallImportEvaluationRow.status == "pending",
            CallImportEvaluationRow.celery_task_id.is_(None),
        )
        .distinct()
        .all()
    )
    return sorted({row[0] for row in rows if row[0] is not None})


def evaluations_with_pending_rows(
    catalog_db: Session,
    workspace_id: UUID,
    *,
    shard_cache: Optional["ShardSessionCache"] = None,
) -> List[UUID]:
    if not is_sharding_enabled():
        return _evaluations_with_pending_mono(catalog_db, workspace_id)

    from app.models.database import CallImportEvaluation

    eval_ids = [
        row[0]
        for row in catalog_db.query(CallImportEvaluation.id)
        .filter(
            CallImportEvaluation.workspace_id == workspace_id,
            CallImportEvaluation.status != "cancelled",
        )
        .all()
        if row[0] is not None
    ]
    if not eval_ids:
        return []

    pending: set[UUID] = set()
    router = db_pool_manager.router
    assert router is not None

    for shard_id in router.shard_ids:
        shard_db, close_shard = _open_shard_session(shard_id, shard_cache)
        try:
            rows = (
                shard_db.query(CallImportEvaluationRow.evaluation_id)
                .filter(
                    CallImportEvaluationRow.evaluation_id.in_(eval_ids),
                    CallImportEvaluationRow.status == "pending",
                    CallImportEvaluationRow.celery_task_id.is_(None),
                )
                .distinct()
                .all()
            )
            pending.update(row[0] for row in rows if row[0] is not None)
        finally:
            if close_shard:
                shard_db.close()
    from app.db_sharding.rebalance import filter_evaluations_not_rebalancing

    return sorted(filter_evaluations_not_rebalancing(catalog_db, pending))


def _evaluations_with_pending_mono(db: Session, workspace_id: UUID) -> List[UUID]:
    from app.models.database import CallImportEvaluation

    rows = (
        db.query(CallImportEvaluation.id)
        .join(
            CallImportEvaluationRow,
            CallImportEvaluationRow.evaluation_id == CallImportEvaluation.id,
        )
        .filter(
            CallImportEvaluation.workspace_id == workspace_id,
            CallImportEvaluation.status != "cancelled",
            CallImportEvaluationRow.status == "pending",
            CallImportEvaluationRow.celery_task_id.is_(None),
        )
        .distinct()
        .all()
    )
    return sorted({row[0] for row in rows if row[0] is not None})


def pending_eval_row_triples(
    catalog_db: Session,
    evaluation_id: UUID,
    *,
    limit: int,
    shard_cache: Optional["ShardSessionCache"] = None,
) -> List[tuple]:
    """Return (eval_row, source_row, evaluation) tuples up to limit."""
    from app.models.database import CallImportEvaluation

    evaluation = (
        catalog_db.query(CallImportEvaluation)
        .filter(CallImportEvaluation.id == evaluation_id)
        .first()
    )
    if evaluation is None:
        return []
    from app.db_sharding.rebalance import is_import_rebalance_locked

    if is_import_rebalance_locked(evaluation.call_import_id):
        return []

    if not is_sharding_enabled():
        return (
            catalog_db.query(CallImportEvaluationRow, CallImportRow, CallImportEvaluation)
            .join(
                CallImportRow,
                CallImportRow.id == CallImportEvaluationRow.call_import_row_id,
            )
            .join(
                CallImportEvaluation,
                CallImportEvaluation.id == CallImportEvaluationRow.evaluation_id,
            )
            .filter(
                CallImportEvaluation.id == evaluation_id,
                CallImportEvaluation.status != "cancelled",
                CallImportEvaluationRow.status == "pending",
                CallImportEvaluationRow.celery_task_id.is_(None),
            )
            .order_by(CallImportEvaluationRow.created_at.asc())
            .limit(limit)
            .all()
        )

    collected: List[tuple] = []
    router = db_pool_manager.router
    assert router is not None
    for shard_id in router.shard_ids:
        if len(collected) >= limit:
            break
        shard_db, close_shard = _open_shard_session(shard_id, shard_cache)
        try:
            batch = (
                shard_db.query(CallImportEvaluationRow, CallImportRow)
                .join(
                    CallImportRow,
                    CallImportRow.id == CallImportEvaluationRow.call_import_row_id,
                )
                .filter(
                    CallImportEvaluationRow.evaluation_id == evaluation_id,
                    CallImportEvaluationRow.status == "pending",
                    CallImportEvaluationRow.celery_task_id.is_(None),
                )
                .order_by(CallImportEvaluationRow.created_at.asc())
                .limit(max(1, limit - len(collected)))
                .all()
            )
            for eval_row, source_row in batch:
                collected.append((eval_row, source_row, evaluation))
        finally:
            if close_shard:
                shard_db.close()
    return collected


def aggregate_evaluation_row_counts(
    catalog_db: Session,
    evaluation_id: UUID,
) -> tuple[int, int, int]:
    """Return (total, completed, failed) across all shards."""
    from sqlalchemy import case, func

    if not is_sharding_enabled():
        row = (
            catalog_db.query(
                func.count(CallImportEvaluationRow.id),
                func.coalesce(
                    func.sum(
                        case(
                            (CallImportEvaluationRow.status == "completed", 1),
                            else_=0,
                        )
                    ),
                    0,
                ),
                func.coalesce(
                    func.sum(
                        case(
                            (CallImportEvaluationRow.status == "failed", 1),
                            else_=0,
                        )
                    ),
                    0,
                ),
            )
            .filter(CallImportEvaluationRow.evaluation_id == evaluation_id)
            .one()
        )
        return int(row[0] or 0), int(row[1] or 0), int(row[2] or 0)

    total = completed = failed = 0
    router = db_pool_manager.router
    assert router is not None
    for shard_id in router.shard_ids:
        factory = db_pool_manager.shard_session_factory(shard_id)
        shard_db = factory()
        try:
            row = (
                shard_db.query(
                    func.count(CallImportEvaluationRow.id),
                    func.coalesce(
                        func.sum(
                            case(
                                (CallImportEvaluationRow.status == "completed", 1),
                                else_=0,
                            )
                        ),
                        0,
                    ),
                    func.coalesce(
                        func.sum(
                            case(
                                (CallImportEvaluationRow.status == "failed", 1),
                                else_=0,
                            )
                        ),
                        0,
                    ),
                )
                .filter(CallImportEvaluationRow.evaluation_id == evaluation_id)
                .one()
            )
            total += int(row[0] or 0)
            completed += int(row[1] or 0)
            failed += int(row[2] or 0)
        finally:
            shard_db.close()
    return total, completed, failed


def count_eval_rows_in_progress(catalog_db: Session, evaluation_id: UUID) -> int:
    from sqlalchemy import func

    if not is_sharding_enabled():
        return int(
            catalog_db.query(func.count())
            .filter(
                CallImportEvaluationRow.evaluation_id == evaluation_id,
                CallImportEvaluationRow.status.in_(["pending", "running"]),
            )
            .scalar()
            or 0
        )

    total = 0
    router = db_pool_manager.router
    assert router is not None
    for shard_id in router.shard_ids:
        factory = db_pool_manager.shard_session_factory(shard_id)
        shard_db = factory()
        try:
            total += int(
                shard_db.query(func.count())
                .filter(
                    CallImportEvaluationRow.evaluation_id == evaluation_id,
                    CallImportEvaluationRow.status.in_(["pending", "running"]),
                )
                .scalar()
                or 0
            )
        finally:
            shard_db.close()
    return total


def fetch_call_import_rows_page(
    catalog_db: Session,
    call_import_id: UUID,
    *,
    offset: int,
    limit: int,
) -> List[CallImportRow]:
    """Scatter-gather row list merged by row_index."""
    if not is_sharding_enabled():
        return (
            catalog_db.query(CallImportRow)
            .filter(CallImportRow.call_import_id == call_import_id)
            .order_by(CallImportRow.row_index.asc())
            .offset(offset)
            .limit(limit)
            .all()
        )

    merged = _merged_call_import_rows_for_import(catalog_db, call_import_id)
    return merged[offset : offset + limit]


def _load_call_import_rows_scatter(
    catalog_db: Session,
    call_import_id: UUID,
    *,
    columns: tuple,
    requested_row_ids: Optional[List[UUID]] = None,
) -> List[CallImportRow]:
    """Load import rows with ``load_only`` columns (catalog or scatter-gather)."""
    if not is_sharding_enabled():
        query = (
            catalog_db.query(CallImportRow)
            .options(load_only(*columns))
            .filter(CallImportRow.call_import_id == call_import_id)
        )
        if requested_row_ids:
            query = query.filter(CallImportRow.id.in_(requested_row_ids))
        return query.order_by(CallImportRow.row_index.asc()).all()

    def load_shard(db: Session, _shard_id: str) -> List[CallImportRow]:
        query = (
            db.query(CallImportRow)
            .options(load_only(*columns))
            .filter(CallImportRow.call_import_id == call_import_id)
        )
        if requested_row_ids:
            query = query.filter(CallImportRow.id.in_(requested_row_ids))
        return query.order_by(CallImportRow.row_index.asc()).all()

    merged: List[CallImportRow] = []
    shard_ids = shard_ids_for_import(catalog_db, call_import_id)
    for part in scatter_gather_on_shards(shard_ids, load_shard):
        merged.extend(part)
    merged = merge_rows_by_index(merged)
    if not merged:
        query = (
            catalog_db.query(CallImportRow)
            .options(load_only(*columns))
            .filter(CallImportRow.call_import_id == call_import_id)
        )
        if requested_row_ids:
            query = query.filter(CallImportRow.id.in_(requested_row_ids))
        merged = query.order_by(CallImportRow.row_index.asc()).all()
    elif requested_row_ids:
        requested = set(requested_row_ids)
        merged = [row for row in merged if row.id in requested]
    return merged


def load_call_import_rows_for_transcription(
    catalog_db: Session,
    call_import_id: UUID,
    *,
    requested_row_ids: Optional[List[UUID]] = None,
) -> List[CallImportRow]:
    """Rows needed to decide diarization enqueue (shard-aware when enabled)."""
    columns = (
        CallImportRow.id,
        CallImportRow.row_index,
        CallImportRow.recording_s3_key,
        CallImportRow.diarised_transcript,
        CallImportRow.diarised_transcript_status,
        CallImportRow.diarised_transcript_error,
        CallImportRow.celery_task_id,
    )
    return _load_call_import_rows_scatter(
        catalog_db,
        call_import_id,
        columns=columns,
        requested_row_ids=requested_row_ids,
    )


def load_call_import_rows_for_delete(
    catalog_db: Session,
    call_import_id: UUID,
    row_ids: List[UUID],
) -> List[CallImportRow]:
    """Rows targeted for bulk delete (shard-aware when enabled)."""
    columns = (
        CallImportRow.id,
        CallImportRow.row_index,
        CallImportRow.recording_s3_key,
        CallImportRow.celery_task_id,
        CallImportRow.status,
    )
    return _load_call_import_rows_scatter(
        catalog_db,
        call_import_id,
        columns=columns,
        requested_row_ids=row_ids,
    )


def _legacy_catalog_rows(
    catalog_db: Session,
    call_import_id: UUID,
) -> List[CallImportRow]:
    """Pre-sharding rows still stored on the catalog DB (same DB as headers)."""
    return (
        catalog_db.query(CallImportRow)
        .filter(CallImportRow.call_import_id == call_import_id)
        .order_by(CallImportRow.row_index.asc())
        .all()
    )


def aggregate_diarised_transcript_counts(
    catalog_db: Session,
    call_import_id: UUID,
) -> Dict[str, int]:
    """Batch-wide diarisation status counts (scatter-gather when sharded)."""
    if not is_sharding_enabled():
        counts: Dict[str, int] = {}
        for status_value, count in (
            catalog_db.query(CallImportRow.diarised_transcript_status, func.count())
            .filter(CallImportRow.call_import_id == call_import_id)
            .group_by(CallImportRow.diarised_transcript_status)
            .all()
        ):
            if isinstance(status_value, str):
                counts[status_value] = int(count or 0)
        return counts

    merged: Dict[str, int] = {}
    shard_ids = shard_ids_for_import(catalog_db, call_import_id)

    def count_shard(db: Session, _shard_id: str) -> Dict[str, int]:
        part: Dict[str, int] = {}
        for status_value, count in (
            db.query(CallImportRow.diarised_transcript_status, func.count())
            .filter(CallImportRow.call_import_id == call_import_id)
            .group_by(CallImportRow.diarised_transcript_status)
            .all()
        ):
            if isinstance(status_value, str):
                part[status_value] = int(count or 0)
        return part

    for part in scatter_gather_on_shards(shard_ids, count_shard):
        for key, value in part.items():
            merged[key] = merged.get(key, 0) + int(value)
    if not merged:
        for status_value, count in (
            catalog_db.query(CallImportRow.diarised_transcript_status, func.count())
            .filter(CallImportRow.call_import_id == call_import_id)
            .group_by(CallImportRow.diarised_transcript_status)
            .all()
        ):
            if isinstance(status_value, str):
                merged[status_value] = int(count or 0)
    return merged


def count_call_import_rows(
    catalog_db: Session,
    call_import_id: UUID,
) -> int:
    """Total rows for an import (shards + optional legacy catalog copy)."""
    if not is_sharding_enabled():
        return int(
            catalog_db.query(func.count(CallImportRow.id))
            .filter(CallImportRow.call_import_id == call_import_id)
            .scalar()
            or 0
        )
    total = 0
    shard_ids = shard_ids_for_import(catalog_db, call_import_id)

    def count_shard(db: Session, _shard_id: str) -> int:
        return int(
            db.query(func.count(CallImportRow.id))
            .filter(CallImportRow.call_import_id == call_import_id)
            .scalar()
            or 0
        )

    for part in scatter_gather_on_shards(shard_ids, count_shard):
        total += int(part)
    if total == 0:
        total = int(
            catalog_db.query(func.count(CallImportRow.id))
            .filter(CallImportRow.call_import_id == call_import_id)
            .scalar()
            or 0
        )
    return total


def count_completed_call_import_rows(
    catalog_db: Session,
    call_import_id: UUID,
) -> int:
    """Completed import rows (scatter-gather when sharded)."""
    from app.models.enums import CallImportRowStatus

    if not is_sharding_enabled():
        return int(
            catalog_db.query(func.count(CallImportRow.id))
            .filter(
                CallImportRow.call_import_id == call_import_id,
                CallImportRow.status == CallImportRowStatus.COMPLETED,
            )
            .scalar()
            or 0
        )

    total = 0
    shard_ids = shard_ids_for_import(catalog_db, call_import_id)

    def count_shard(db: Session, _shard_id: str) -> int:
        return int(
            db.query(func.count(CallImportRow.id))
            .filter(
                CallImportRow.call_import_id == call_import_id,
                CallImportRow.status == CallImportRowStatus.COMPLETED,
            )
            .scalar()
            or 0
        )

    for part in scatter_gather_on_shards(shard_ids, count_shard):
        total += int(part)
    if total == 0:
        total = int(
            catalog_db.query(func.count(CallImportRow.id))
            .filter(
                CallImportRow.call_import_id == call_import_id,
                CallImportRow.status == CallImportRowStatus.COMPLETED,
            )
            .scalar()
            or 0
        )
    return total


def list_completed_source_row_ids_ordered(
    catalog_db: Session,
    call_import_id: UUID,
) -> List[UUID]:
    """Completed source row ids ordered by row_index (shard-aware)."""
    from app.models.enums import CallImportRowStatus

    if not is_sharding_enabled():
        rows = (
            catalog_db.query(CallImportRow.id)
            .filter(
                CallImportRow.call_import_id == call_import_id,
                CallImportRow.status == CallImportRowStatus.COMPLETED,
            )
            .order_by(CallImportRow.row_index.asc())
            .all()
        )
        return [row_id for (row_id,) in rows if row_id is not None]

    merged: List[CallImportRow] = []

    def load_shard(db: Session, _shard_id: str) -> List[CallImportRow]:
        return (
            db.query(CallImportRow)
            .filter(
                CallImportRow.call_import_id == call_import_id,
                CallImportRow.status == CallImportRowStatus.COMPLETED,
            )
            .order_by(CallImportRow.row_index.asc())
            .all()
        )

    shard_ids = shard_ids_for_import(catalog_db, call_import_id)
    for part in scatter_gather_on_shards(shard_ids, load_shard):
        merged.extend(part)
    merged = merge_rows_by_index(merged)
    if not merged:
        rows = (
            catalog_db.query(CallImportRow.id)
            .filter(
                CallImportRow.call_import_id == call_import_id,
                CallImportRow.status == CallImportRowStatus.COMPLETED,
            )
            .order_by(CallImportRow.row_index.asc())
            .all()
        )
        return [row_id for (row_id,) in rows if row_id is not None]
    return [row.id for row in merged if row.id is not None]


def list_source_row_ids_ordered(
    catalog_db: Session,
    call_import_id: UUID,
) -> List[UUID]:
    """All source row ids for an import, ordered by row_index."""
    if not is_sharding_enabled():
        rows = (
            catalog_db.query(CallImportRow.id)
            .filter(CallImportRow.call_import_id == call_import_id)
            .order_by(CallImportRow.row_index.asc())
            .all()
        )
        return [row[0] for row in rows if row[0] is not None]

    merged: List[Tuple[UUID, int]] = [
        (row_id, int(row_index or 0))
        for row_id, row_index in catalog_db.query(
            CallImportRow.id,
            CallImportRow.row_index,
        )
        .filter(CallImportRow.call_import_id == call_import_id)
        .all()
        if row_id is not None
    ]
    shard_ids = shard_ids_for_import(catalog_db, call_import_id)

    def load_shard(db: Session, _shard_id: str) -> List[Tuple[UUID, int]]:
        return [
            (row_id, int(row_index or 0))
            for row_id, row_index in db.query(
                CallImportRow.id,
                CallImportRow.row_index,
            )
            .filter(CallImportRow.call_import_id == call_import_id)
            .order_by(CallImportRow.row_index.asc())
            .all()
            if row_id is not None
        ]

    for part in scatter_gather_on_shards(shard_ids, load_shard):
        merged.extend(part)
    merged.sort(key=lambda pair: pair[1])
    if merged:
        return [row_id for row_id, _ in merged]

    rows = (
        catalog_db.query(CallImportRow.id)
        .filter(CallImportRow.call_import_id == call_import_id)
        .order_by(CallImportRow.row_index.asc())
        .all()
    )
    return [row[0] for row in rows if row[0] is not None]


def source_row_index_map(
    catalog_db: Session,
    call_import_id: UUID,
) -> dict[UUID, int]:
    """Map call_import_row id -> row_index (for shard routing eval rows)."""
    if not is_sharding_enabled():
        rows = (
            catalog_db.query(CallImportRow.id, CallImportRow.row_index)
            .filter(CallImportRow.call_import_id == call_import_id)
            .all()
        )
        return {row_id: int(row_index or 0) for row_id, row_index in rows}

    merged: List[Tuple[UUID, int]] = [
        (row_id, int(row_index or 0))
        for row_id, row_index in catalog_db.query(
            CallImportRow.id,
            CallImportRow.row_index,
        )
        .filter(CallImportRow.call_import_id == call_import_id)
        .all()
        if row_id is not None
    ]
    shard_ids = shard_ids_for_import(catalog_db, call_import_id)

    def load_shard(db: Session, _shard_id: str) -> List[Tuple[UUID, int]]:
        return [
            (row_id, int(row_index or 0))
            for row_id, row_index in db.query(
                CallImportRow.id,
                CallImportRow.row_index,
            )
            .filter(CallImportRow.call_import_id == call_import_id)
            .all()
            if row_id is not None
        ]

    for part in scatter_gather_on_shards(shard_ids, load_shard):
        merged.extend(part)
    merged.sort(key=lambda pair: pair[1])
    if merged:
        return {row_id: row_index for row_id, row_index in merged}

    rows = (
        catalog_db.query(CallImportRow.id, CallImportRow.row_index)
        .filter(CallImportRow.call_import_id == call_import_id)
        .all()
    )
    return {row_id: int(row_index or 0) for row_id, row_index in rows}


def count_evaluation_cancel_targets_sharded(
    catalog_db: Session,
    evaluation_id: UUID,
    *,
    pending_only: bool,
    in_progress_only: bool,
) -> int:
    """Count eval rows eligible for cancel across row shards."""
    from sqlalchemy import func

    if not is_sharding_enabled():
        query = catalog_db.query(func.count(CallImportEvaluationRow.id)).filter(
            CallImportEvaluationRow.evaluation_id == evaluation_id
        )
        if in_progress_only:
            query = query.filter(
                CallImportEvaluationRow.status.in_(("pending", "running"))
            )
        elif pending_only:
            query = query.filter(CallImportEvaluationRow.status == "pending")
        return int(query.scalar() or 0)

    total = 0
    router = db_pool_manager.router
    assert router is not None
    for shard_id in router.shard_ids:
        factory = db_pool_manager.shard_session_factory(shard_id)
        shard_db = factory()
        try:
            query = shard_db.query(func.count(CallImportEvaluationRow.id)).filter(
                CallImportEvaluationRow.evaluation_id == evaluation_id
            )
            if in_progress_only:
                query = query.filter(
                    CallImportEvaluationRow.status.in_(("pending", "running"))
                )
            elif pending_only:
                query = query.filter(CallImportEvaluationRow.status == "pending")
            total += int(query.scalar() or 0)
        finally:
            shard_db.close()
    return total


def _evaluation_row_pair_sort_key(
    pair: tuple[CallImportEvaluationRow, CallImportRow],
) -> tuple[int, str]:
    _, source_row = pair
    return (int(source_row.row_index or 0), str(pair[0].id))


def _sort_evaluation_row_pairs(
    pairs: List[tuple[CallImportEvaluationRow, CallImportRow]],
) -> List[tuple[CallImportEvaluationRow, CallImportRow]]:
    return sorted(pairs, key=_evaluation_row_pair_sort_key)


def load_evaluation_row_pairs(
    catalog_db: Session,
    evaluation_id: UUID,
) -> List[tuple[CallImportEvaluationRow, CallImportRow]]:
    """All eval/source row pairs for insights and PDF aggregation."""
    if not is_sharding_enabled():
        pairs = (
            catalog_db.query(CallImportEvaluationRow, CallImportRow)
            .join(
                CallImportRow,
                CallImportRow.id == CallImportEvaluationRow.call_import_row_id,
            )
            .filter(CallImportEvaluationRow.evaluation_id == evaluation_id)
            .all()
        )
        return _sort_evaluation_row_pairs(pairs)

    pairs: List[tuple[CallImportEvaluationRow, CallImportRow]] = []
    router = db_pool_manager.router
    assert router is not None
    for shard_id in router.shard_ids:
        factory = db_pool_manager.shard_session_factory(shard_id)
        shard_db = factory()
        try:
            pairs.extend(
                shard_db.query(CallImportEvaluationRow, CallImportRow)
                .join(
                    CallImportRow,
                    CallImportRow.id == CallImportEvaluationRow.call_import_row_id,
                )
                .filter(CallImportEvaluationRow.evaluation_id == evaluation_id)
                .all()
            )
        finally:
            shard_db.close()
    if not pairs:
        pairs = (
            catalog_db.query(CallImportEvaluationRow, CallImportRow)
            .join(
                CallImportRow,
                CallImportRow.id == CallImportEvaluationRow.call_import_row_id,
            )
            .filter(CallImportEvaluationRow.evaluation_id == evaluation_id)
            .all()
        )
    return _sort_evaluation_row_pairs(pairs)
