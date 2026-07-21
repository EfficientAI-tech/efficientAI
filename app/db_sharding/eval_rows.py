"""Evaluation row lookups and fan-out helpers for sharded data plane."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Callable, List, Optional, Sequence, Tuple, TypeVar
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


def load_evaluation_rows_for_run(
    catalog_db: Session,
    evaluation_id: UUID,
) -> List[CallImportEvaluationRow]:
    """All evaluation rows for a run (scatter-gather when sharded)."""
    return [eval_row for eval_row, _ in load_evaluation_row_pairs(catalog_db, evaluation_id)]


def find_evaluation_row_in_run(
    catalog_db: Session,
    evaluation_id: UUID,
    eval_row_id: UUID,
) -> Tuple[Optional[CallImportEvaluationRow], Optional[CallImportRow]]:
    for eval_row, source_row in load_evaluation_row_pairs(catalog_db, evaluation_id):
        if eval_row.id == eval_row_id:
            return eval_row, source_row
    return None, None


def count_evaluation_rows_for_run(
    catalog_db: Session,
    evaluation_id: UUID,
    *,
    statuses: Optional[Sequence[str]] = None,
) -> int:
    rows = load_evaluation_rows_for_run(catalog_db, evaluation_id)
    if not statuses:
        return len(rows)
    allowed = set(statuses)
    return sum(1 for row in rows if (row.status or "") in allowed)


def foreach_evaluation_row_mutating(
    catalog_db: Session,
    evaluation_id: UUID,
    mutate: Callable[[CallImportEvaluationRow], bool],
) -> int:
    """Run ``mutate(row)`` on every eval row; commit per shard when sharded."""
    from sqlalchemy.orm.attributes import flag_modified

    if not is_sharding_enabled():
        rows = (
            catalog_db.query(CallImportEvaluationRow)
            .filter(CallImportEvaluationRow.evaluation_id == evaluation_id)
            .all()
        )
        changed = 0
        for row in rows:
            if mutate(row):
                flag_modified(row, "metric_scores")
                changed += 1
        return changed

    router = db_pool_manager.router
    assert router is not None
    total = 0
    for shard_id in router.shard_ids:
        factory = db_pool_manager.shard_session_factory(shard_id)
        shard_db = factory()
        try:
            rows = (
                shard_db.query(CallImportEvaluationRow)
                .filter(CallImportEvaluationRow.evaluation_id == evaluation_id)
                .all()
            )
            shard_changed = False
            for row in rows:
                if mutate(row):
                    flag_modified(row, "metric_scores")
                    shard_changed = True
                    total += 1
            if shard_changed:
                shard_db.commit()
        except Exception:
            shard_db.rollback()
            raise
        finally:
            shard_db.close()
    return total


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


PairSortKey = Callable[[Tuple[CallImportEvaluationRow, CallImportRow]], Any]


def fetch_evaluation_row_pairs_page(
    catalog_db: Session,
    build_query: Callable[[Session], Query],
    *,
    page: int,
    page_size: int,
    sort_key: PairSortKey,
    sort_desc: bool = False,
    bounded_shard_fetch: bool = True,
) -> Tuple[int, List[Tuple[CallImportEvaluationRow, CallImportRow]]]:
    """Return ``(total, page_slice)`` without loading every eval row pair.

    When sharding is enabled and ``bounded_shard_fetch`` is true (``row_index``
    sort only), each shard returns at most ``page * page_size`` rows; results
    are merged in Python and sliced to the requested page.

    For other sort keys, every shard returns all matching rows so globally
    correct ordering is preserved across shards.
    """
    page = max(1, page)
    page_size = max(1, page_size)
    total = scatter_gather_eval_query_count(catalog_db, build_query)
    if total == 0:
        return 0, []

    if not is_sharding_enabled():
        rows = (
            build_query(catalog_db)
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return total, list(rows)

    merged: List[Tuple[CallImportEvaluationRow, CallImportRow]] = []
    router = db_pool_manager.router
    assert router is not None
    over_fetch = page * page_size
    for shard_id in router.shard_ids:
        factory = db_pool_manager.shard_session_factory(shard_id)
        shard_db = factory()
        try:
            shard_query = build_query(shard_db)
            if bounded_shard_fetch:
                merged.extend(shard_query.limit(over_fetch).all())
            else:
                merged.extend(shard_query.all())
        finally:
            shard_db.close()

    merged.sort(key=sort_key, reverse=sort_desc)
    start = (page - 1) * page_size
    return total, list(merged[start : start + page_size])


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
