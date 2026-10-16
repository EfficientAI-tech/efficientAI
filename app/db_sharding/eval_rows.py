"""Evaluation row lookups and fan-out helpers for sharded data plane."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Callable, List, Optional, Sequence, Tuple, TypeVar
from uuid import UUID

from sqlalchemy.orm import Load, Query, Session

from app.db_sharding.pool_manager import db_pool_manager
from app.db_sharding.row_ops import (
    close_row_sessions,
    locate_call_import_evaluation_row,
)
from app.db_sharding.scatter_gather import (
    SliceCount,
    defer_call_import_row_text,
    load_evaluation_row_pairs,
    plan_slice_page,
)
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


def _defer_pair_text(query: Query) -> Query:
    return query.options(*defer_call_import_row_text())


def _expunge_pairs(
    db: Session,
    pairs: Sequence[Tuple[CallImportEvaluationRow, CallImportRow]],
) -> List[Tuple[CallImportEvaluationRow, CallImportRow]]:
    kept: List[Tuple[CallImportEvaluationRow, CallImportRow]] = []
    for eval_row, source_row in pairs:
        db.expunge(eval_row)
        db.expunge(source_row)
        kept.append((eval_row, source_row))
    return kept


def _page_pairs_by_ids(
    build_query: Callable[[Session], Query],
    eval_row_ids: Sequence[UUID],
) -> List[Tuple[CallImportEvaluationRow, CallImportRow]]:
    if not eval_row_ids:
        return []
    wanted = list(eval_row_ids)
    wanted_set = set(wanted)
    found: dict[UUID, Tuple[CallImportEvaluationRow, CallImportRow]] = {}
    router = db_pool_manager.router
    assert router is not None
    for shard_id in router.shard_ids:
        if len(found) == len(wanted_set):
            break
        factory = db_pool_manager.shard_session_factory(shard_id)
        shard_db = factory()
        try:
            rows = _expunge_pairs(
                shard_db,
                _defer_pair_text(build_query(shard_db))
                .filter(CallImportEvaluationRow.id.in_(wanted))
                .all(),
            )
        finally:
            shard_db.close()
        for pair in rows:
            row_id = pair[0].id
            if row_id in wanted_set:
                found[row_id] = pair
    return [found[row_id] for row_id in wanted if row_id in found]


def _slice_counts_for_eval_query(
    build_query: Callable[[Session], Query],
) -> List[SliceCount]:
    from sqlalchemy import func

    from app.db_sharding.scatter_gather import _slice_id_expr

    slice_expr = _slice_id_expr(_row_chunk_size_for_eval())
    router = db_pool_manager.router
    assert router is not None
    counts: List[SliceCount] = []
    for shard_id in router.shard_ids:
        factory = db_pool_manager.shard_session_factory(shard_id)
        shard_db = factory()
        try:
            rows = (
                build_query(shard_db)
                .order_by(None)
                .with_entities(slice_expr, func.count(CallImportEvaluationRow.id))
                .group_by(slice_expr)
                .all()
            )
        finally:
            shard_db.close()
        for slice_id, count in rows:
            if slice_id is None or int(count or 0) <= 0:
                continue
            counts.append(SliceCount(int(slice_id), shard_id, int(count)))
    return counts


def _row_chunk_size_for_eval() -> int:
    from app.db_sharding.scatter_gather import _row_chunk_size

    return _row_chunk_size()


def _load_eval_slice_window(
    build_query: Callable[[Session], Query],
    window,
    *,
    descending: bool,
) -> List[Tuple[CallImportEvaluationRow, CallImportRow]]:
    chunk = _row_chunk_size_for_eval()
    lo = window.slice_id * chunk
    hi = lo + chunk
    factory = db_pool_manager.shard_session_factory(window.shard_id)
    shard_db = factory()
    try:
        order = (
            CallImportRow.row_index.desc()
            if descending
            else CallImportRow.row_index.asc()
        )
        return _expunge_pairs(
            shard_db,
            _defer_pair_text(build_query(shard_db))
            .filter(CallImportRow.row_index >= lo, CallImportRow.row_index < hi)
            .order_by(order)
            .offset(window.local_offset)
            .limit(window.limit)
            .all(),
        )
    finally:
        shard_db.close()


def _slim_sort_columns(include_scores: bool):
    columns = [
        CallImportEvaluationRow.id,
        CallImportEvaluationRow.evaluation_id,
        CallImportEvaluationRow.call_import_row_id,
        CallImportEvaluationRow.status,
    ]
    if include_scores:
        columns.append(CallImportEvaluationRow.metric_scores)
    return (
        Load(CallImportEvaluationRow).load_only(*columns),
        Load(CallImportRow).load_only(
            CallImportRow.id,
            CallImportRow.row_index,
            CallImportRow.conversation_id,
            CallImportRow.call_import_id,
        ),
    )


def fetch_evaluation_row_pairs_page(
    catalog_db: Session,
    build_query: Callable[[Session], Query],
    *,
    page: int,
    page_size: int,
    sort_key: PairSortKey,
    sort_desc: bool = False,
    bounded_shard_fetch: bool = True,
    row_index_desc: bool = False,
    sort_reads_scores: bool = False,
) -> Tuple[int, List[Tuple[CallImportEvaluationRow, CallImportRow]]]:
    """Return ``(total, page_slice)`` without loading every transcript.

    ``row_index`` order walks slice counts and reads only the slices on
    this page. Other sorts load slim keys, then the page's pairs.
    """
    page = max(1, page)
    page_size = max(1, page_size)
    total = scatter_gather_eval_query_count(catalog_db, build_query)
    if total == 0:
        return 0, []

    if not is_sharding_enabled():
        rows = (
            _defer_pair_text(build_query(catalog_db))
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return total, list(rows)

    offset = (page - 1) * page_size
    if bounded_shard_fetch:
        windows = plan_slice_page(
            _slice_counts_for_eval_query(build_query),
            offset=offset,
            limit=page_size,
            descending=row_index_desc,
        )
        merged: List[Tuple[CallImportEvaluationRow, CallImportRow]] = []
        for window in windows:
            merged.extend(
                _load_eval_slice_window(
                    build_query,
                    window,
                    descending=row_index_desc,
                )
            )
        merged.sort(key=sort_key, reverse=sort_desc)
        return total, merged

    slim: List[Tuple[CallImportEvaluationRow, CallImportRow]] = []
    router = db_pool_manager.router
    assert router is not None
    for shard_id in router.shard_ids:
        factory = db_pool_manager.shard_session_factory(shard_id)
        shard_db = factory()
        try:
            rows = (
                build_query(shard_db)
                .options(*_slim_sort_columns(sort_reads_scores))
                .all()
            )
            slim.extend(_expunge_pairs(shard_db, rows))
        finally:
            shard_db.close()
    slim.sort(key=sort_key, reverse=sort_desc)
    page_ids = [pair[0].id for pair in slim[offset : offset + page_size]]
    return total, _page_pairs_by_ids(build_query, page_ids)


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


_evaluation_session_bounds: dict[int, dict] = {}


def rebind_evaluation_row_session(origin_row_db, row_db, catalog_db) -> None:
    """Point the open evaluation_row_session finally-block at the new sessions."""
    bound = _evaluation_session_bounds.get(id(origin_row_db))
    if bound is None:
        return
    bound["row_db"] = row_db
    bound["catalog_db"] = catalog_db


@contextmanager
def evaluation_row_session(eval_row_id: UUID | str):
    """Yield (row_db, catalog_db, eval_row, source_row, shard_id)."""
    row_db, catalog_db, eval_row, source_row, shard_id = (
        locate_call_import_evaluation_row(eval_row_id)
    )
    token = id(row_db)
    bound = {"row_db": row_db, "catalog_db": catalog_db}
    _evaluation_session_bounds[token] = bound
    try:
        yield row_db, catalog_db, eval_row, source_row, shard_id
    finally:
        _evaluation_session_bounds.pop(token, None)
        if bound["row_db"] is not None:
            close_row_sessions(bound["row_db"], bound["catalog_db"])


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
