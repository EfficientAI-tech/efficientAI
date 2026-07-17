"""Evaluation row lookups and fan-out helpers for sharded data plane."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Callable, List, Optional, Sequence, Tuple, TypeVar
from uuid import UUID

from sqlalchemy.orm import Query, Session

from app.db_sharding.pool_manager import db_pool_manager
from app.db_sharding.row_ops import (
    close_row_sessions,
    locate_call_import_evaluation_row,
)
from app.db_sharding.scatter_gather import load_evaluation_row_pairs
from app.db_sharding.sessions import is_sharding_enabled
from app.models.database import CallImportEvaluation, CallImportEvaluationRow, CallImportRow

T = TypeVar("T")


def scatter_gather_eval_query(
    catalog_db: Session,
    build_query: Callable[[Session], Query],
) -> List[T]:
    """Run the same ORM query on each row shard and concatenate results."""
    if not is_sharding_enabled():
        return list(build_query(catalog_db).all())

    merged: List[T] = []
    router = db_pool_manager.router
    assert router is not None
    for shard_id in router.shard_ids:
        factory = db_pool_manager.shard_session_factory(shard_id)
        shard_db = factory()
        try:
            merged.extend(build_query(shard_db).all())
        finally:
            shard_db.close()
    return merged


def scatter_gather_eval_query_count(
    catalog_db: Session,
    build_query: Callable[[Session], Query],
) -> int:
    if not is_sharding_enabled():
        return int(build_query(catalog_db).count())
    total = 0
    router = db_pool_manager.router
    assert router is not None
    for shard_id in router.shard_ids:
        factory = db_pool_manager.shard_session_factory(shard_id)
        shard_db = factory()
        try:
            total += int(build_query(shard_db).count())
        finally:
            shard_db.close()
    return total


def paginate_pairs(
    pairs: Sequence[Tuple[CallImportEvaluationRow, CallImportRow]],
    *,
    page: int,
    page_size: int,
) -> Tuple[int, List[Tuple[CallImportEvaluationRow, CallImportRow]]]:
    ordered = sorted(pairs, key=lambda pair: int(pair[1].row_index or 0))
    total = len(ordered)
    start = max(0, (page - 1) * page_size)
    end = start + page_size
    return total, list(ordered[start:end])


def gather_retry_targets_sharded(
    catalog_db: Session,
    evaluation: CallImportEvaluation,
    requested_ids: Optional[List[UUID]],
    *,
    include_completed: bool,
) -> Tuple[List[Tuple[CallImportEvaluationRow, CallImportRow]], List]:
    """Return (targets, skipped_as_dict_list) for bulk retry when sharding is on."""
    from app.models.schemas import CallImportEvaluationRetrySkippedItem

    pairs = load_evaluation_row_pairs(catalog_db, evaluation.id)
    eval_by_id = {er.id: (er, sr) for er, sr in pairs}

    targets: List[Tuple[CallImportEvaluationRow, CallImportRow]] = []
    skipped: List[CallImportEvaluationRetrySkippedItem] = []

    if requested_ids is None:
        if include_completed:
            candidate_ids = [
                er.id
                for er, _ in pairs
                if er.status in ("failed", "completed")
            ]
        else:
            candidate_ids = [er.id for er, _ in pairs if er.status == "failed"]
    else:
        requested_set = set(requested_ids)
        candidate_ids = [eid for eid in requested_set if eid in eval_by_id]
        for missing in requested_set - set(candidate_ids):
            skipped.append(
                CallImportEvaluationRetrySkippedItem(
                    eval_row_id=missing,
                    reason="unknown",
                )
            )

    for eid in candidate_ids:
        eval_row, source_row = eval_by_id[eid]
        if eval_row.status in {"pending", "running"}:
            skipped.append(
                CallImportEvaluationRetrySkippedItem(
                    eval_row_id=eval_row.id,
                    reason="in_progress",
                )
            )
            continue
        if eval_row.status == "completed" and not include_completed:
            skipped.append(
                CallImportEvaluationRetrySkippedItem(
                    eval_row_id=eval_row.id,
                    reason="completed",
                )
            )
            continue
        targets.append((eval_row, source_row))

    return targets, skipped


@contextmanager
def evaluation_row_session(eval_row_id: UUID | str):
    """Yield (row_db, catalog_db, eval_row, source_row, shard_id)."""
    row_db, catalog_db, eval_row, source_row, shard_id = (
        locate_call_import_evaluation_row(eval_row_id)
    )
    try:
        yield row_db, catalog_db, eval_row, source_row, shard_id
    finally:
        close_row_sessions(row_db, catalog_db)


def delete_evaluation_row_on_shards(
    eval_row_id: UUID,
    evaluation_id: UUID,
) -> bool:
    """Delete eval row from the shard that holds it. Returns True if deleted."""
    if not is_sharding_enabled():
        return False
    router = db_pool_manager.router
    assert router is not None
    for shard_id in router.shard_ids:
        factory = db_pool_manager.shard_session_factory(shard_id)
        shard_db = factory()
        try:
            eval_row = (
                shard_db.query(CallImportEvaluationRow)
                .filter(
                    CallImportEvaluationRow.id == eval_row_id,
                    CallImportEvaluationRow.evaluation_id == evaluation_id,
                )
                .first()
            )
            if eval_row is None:
                continue
            shard_db.delete(eval_row)
            shard_db.commit()
            return True
        except Exception:
            shard_db.rollback()
            raise
        finally:
            shard_db.close()
    return False
