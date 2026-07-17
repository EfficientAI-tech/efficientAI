"""Scatter-gather reads and fan-out writes across row shards."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Iterable, List, Optional, Sequence, TypeVar
from uuid import UUID

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.db_sharding.pool_manager import db_pool_manager
from app.db_sharding.sessions import is_sharding_enabled
from app.models.database import CallImportEvaluation, CallImportEvaluationRow, CallImportRow

T = TypeVar("T")


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


def pending_eval_workspaces(catalog_db: Session) -> List[UUID]:
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
        factory = db_pool_manager.shard_session_factory(shard_id)
        shard_db = factory()
        try:
            for eid in collect_pending(shard_db, shard_id):
                evaluation_ids.add(eid)
        finally:
            shard_db.close()

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
        factory = db_pool_manager.shard_session_factory(shard_id)
        shard_db = factory()
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
            shard_db.close()
    return sorted(pending)


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
        factory = db_pool_manager.shard_session_factory(shard_id)
        shard_db = factory()
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

    merged: List[CallImportRow] = []

    def load_shard(db: Session, _shard_id: str) -> List[CallImportRow]:
        return (
            db.query(CallImportRow)
            .filter(CallImportRow.call_import_id == call_import_id)
            .order_by(CallImportRow.row_index.asc())
            .all()
        )

    shard_ids = shard_ids_for_import(catalog_db, call_import_id)
    for part in scatter_gather_on_shards(shard_ids, load_shard):
        merged.extend(part)
    merged = merge_rows_by_index(merged)
    if not merged:
        merged = _legacy_catalog_rows(catalog_db, call_import_id)
    return merged[offset : offset + limit]


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

    merged = _legacy_catalog_rows(catalog_db, call_import_id)
    shard_ids = shard_ids_for_import(catalog_db, call_import_id)

    def load_shard(db: Session, _shard_id: str) -> List[CallImportRow]:
        return (
            db.query(CallImportRow)
            .filter(CallImportRow.call_import_id == call_import_id)
            .order_by(CallImportRow.row_index.asc())
            .all()
        )

    for part in scatter_gather_on_shards(shard_ids, load_shard):
        merged.extend(part)
    merged = merge_rows_by_index(merged)
    return [row.id for row in merged if row.id is not None]


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

    merged: List[CallImportRow] = list(_legacy_catalog_rows(catalog_db, call_import_id))
    shard_ids = shard_ids_for_import(catalog_db, call_import_id)

    def load_shard(db: Session, _shard_id: str) -> List[CallImportRow]:
        return (
            db.query(CallImportRow)
            .filter(CallImportRow.call_import_id == call_import_id)
            .all()
        )

    for part in scatter_gather_on_shards(shard_ids, load_shard):
        merged.extend(part)
    merged = merge_rows_by_index(merged)
    return {row.id: int(row.row_index or 0) for row in merged if row.id is not None}


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


def load_evaluation_row_pairs(
    catalog_db: Session,
    evaluation_id: UUID,
) -> List[tuple[CallImportEvaluationRow, CallImportRow]]:
    """All eval/source row pairs for insights and PDF aggregation."""
    if not is_sharding_enabled():
        return (
            catalog_db.query(CallImportEvaluationRow, CallImportRow)
            .join(
                CallImportRow,
                CallImportRow.id == CallImportEvaluationRow.call_import_row_id,
            )
            .filter(CallImportEvaluationRow.evaluation_id == evaluation_id)
            .all()
        )

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
    return pairs
