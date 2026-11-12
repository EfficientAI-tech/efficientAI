"""Evaluation row lookups and fan-out helpers for sharded data plane."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Callable, List, Optional, Sequence, Tuple, TypeVar
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Load, Query, Session, load_only

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
    retry_source_row_options,
)
from app.db_sharding.sessions import is_sharding_enabled
from app.models.database import CallImportEvaluation, CallImportEvaluationRow, CallImportRow

T = TypeVar("T")

RETRY_ROW_PAGE_SIZE = 1000


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
    """Count eval rows by status. Does not load row bodies."""

    def _count(session: Session) -> int:
        query = session.query(func.count(CallImportEvaluationRow.id)).filter(
            CallImportEvaluationRow.evaluation_id == evaluation_id
        )
        if statuses:
            query = query.filter(CallImportEvaluationRow.status.in_(list(statuses)))
        return int(query.scalar() or 0)

    if not is_sharding_enabled():
        return _count(catalog_db)

    router = db_pool_manager.router
    if router is None:
        return _count(catalog_db)
    total = 0
    for shard_id in router.shard_ids:
        factory = db_pool_manager.shard_session_factory(shard_id)
        shard_db = factory()
        try:
            total += _count(shard_db)
        finally:
            shard_db.close()
    if total == 0:
        return _count(catalog_db)
    return total


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


def retry_eval_row_columns(*, include_metric_scores: bool) -> tuple:
    columns = [
        CallImportEvaluationRow.id,
        CallImportEvaluationRow.evaluation_id,
        CallImportEvaluationRow.call_import_row_id,
        CallImportEvaluationRow.status,
        CallImportEvaluationRow.celery_task_id,
    ]
    if include_metric_scores:
        columns.append(CallImportEvaluationRow.metric_scores)
    return tuple(columns)


def retry_eval_ids_query(
    session: Session,
    evaluation_id: UUID,
    row_ids: Sequence[UUID],
) -> Query:
    """Explicit retry ids. Slim columns, no status filter, no transcript bodies."""
    return (
        session.query(CallImportEvaluationRow)
        .options(load_only(*retry_eval_row_columns(include_metric_scores=False)))
        .filter(
            CallImportEvaluationRow.evaluation_id == evaluation_id,
            CallImportEvaluationRow.id.in_(list(row_ids)),
        )
    )


def retry_eval_page_query(
    session: Session,
    evaluation_id: UUID,
    *,
    status: str,
    after_id: Optional[UUID] = None,
    row_ids: Optional[Sequence[UUID]] = None,
    exclude_ids: Optional[Sequence[UUID]] = None,
    include_metric_scores: bool = False,
    ordered: bool = False,
    search_term: str = "",
) -> Query:
    """One status range on (evaluation_id, status). No transcript columns.

    The worker leaves ``ordered`` off so Postgres can stop after LIMIT on
    ``ix_eval_rows_eval_status``. A read-only gather passes ``ordered`` and
    walks ids, because it does not change status and must not spin.
    """
    query = (
        session.query(CallImportEvaluationRow)
        .options(
            load_only(
                *retry_eval_row_columns(include_metric_scores=include_metric_scores)
            )
        )
        .filter(
            CallImportEvaluationRow.evaluation_id == evaluation_id,
            CallImportEvaluationRow.status == status,
        )
    )
    from app.services.call_imports.row_text_search import apply_conversation_id_search

    needle = (search_term or "").strip()
    if needle:
        query = query.join(
            CallImportRow,
            CallImportEvaluationRow.call_import_row_id == CallImportRow.id,
        )
        query = apply_conversation_id_search(query, needle)
    if after_id is not None:
        query = query.filter(CallImportEvaluationRow.id > after_id)
    if row_ids:
        query = query.filter(CallImportEvaluationRow.id.in_(list(row_ids)))
    if exclude_ids:
        query = query.filter(CallImportEvaluationRow.id.notin_(list(exclude_ids)))
    if ordered:
        query = query.order_by(CallImportEvaluationRow.id.asc())
    return query


def retry_source_page_query(session: Session, source_ids: Sequence[UUID]) -> Query:
    """Source columns for one retry page. Transcript bodies stay out of the SELECT."""
    return (
        session.query(CallImportRow)
        .options(*retry_source_row_options())
        .filter(CallImportRow.id.in_(list(source_ids)))
    )


def load_retry_target_page(
    session: Session,
    evaluation_id: UUID,
    *,
    status: str,
    after_id: Optional[UUID] = None,
    row_ids: Optional[Sequence[UUID]] = None,
    exclude_ids: Optional[Sequence[UUID]] = None,
    include_metric_scores: bool = False,
    ordered: bool = False,
    limit: int = RETRY_ROW_PAGE_SIZE,
    search_term: str = "",
) -> List[Tuple[CallImportEvaluationRow, Optional[CallImportRow]]]:
    eval_rows = (
        retry_eval_page_query(
            session,
            evaluation_id,
            status=status,
            after_id=after_id,
            row_ids=row_ids,
            exclude_ids=exclude_ids,
            include_metric_scores=include_metric_scores,
            ordered=ordered,
            search_term=search_term,
        )
        .limit(limit)
        .all()
    )
    if not eval_rows:
        return []
    sources = {
        row.id: row
        for row in retry_source_page_query(
            session,
            [row.call_import_row_id for row in eval_rows],
        ).all()
    }
    return [(row, sources.get(row.call_import_row_id)) for row in eval_rows]


def count_evaluation_retry_targets(
    catalog_db: Session,
    evaluation_id: UUID,
    *,
    statuses: Sequence[str],
    search_term: str = "",
) -> int:
    from app.services.call_imports.row_text_search import apply_conversation_id_search

    needle = (search_term or "").strip()

    def _count(session: Session) -> int:
        total = 0
        for status in statuses:
            query = session.query(func.count(CallImportEvaluationRow.id)).filter(
                CallImportEvaluationRow.evaluation_id == evaluation_id,
                CallImportEvaluationRow.status == status,
            )
            if needle:
                query = query.join(
                    CallImportRow,
                    CallImportEvaluationRow.call_import_row_id == CallImportRow.id,
                )
                query = apply_conversation_id_search(query, needle)
            total += int(query.scalar() or 0)
        return total

    if not is_sharding_enabled():
        return _count(catalog_db)

    router = db_pool_manager.router
    if router is None:
        return _count(catalog_db)
    total = 0
    for shard_id in router.shard_ids:
        factory = db_pool_manager.shard_session_factory(shard_id)
        shard_db = factory()
        try:
            total += _count(shard_db)
        finally:
            shard_db.close()
    if total == 0:
        return _count(catalog_db)
    return total


def iter_evaluation_row_sessions(catalog_db: Session, call_import_id: UUID):
    """Yield (session, shard_id) for row writes. shard_id is None on the catalog."""
    if not is_sharding_enabled():
        yield catalog_db, None
        return
    router = db_pool_manager.router
    if router is None:
        yield catalog_db, None
        return
    from app.db_sharding.scatter_gather import shard_ids_for_import

    for shard_id in shard_ids_for_import(catalog_db, call_import_id):
        factory = db_pool_manager.shard_session_factory(shard_id)
        session = factory()
        try:
            yield session, shard_id
        finally:
            session.close()


def _retry_statuses(*, include_completed: bool) -> List[str]:
    if include_completed:
        return ["failed", "completed"]
    return ["failed"]


def _collect_retry_targets_on_session(
    session: Session,
    evaluation: CallImportEvaluation,
    requested_ids: Optional[List[UUID]],
    *,
    include_completed: bool,
) -> Tuple[List[Tuple[CallImportEvaluationRow, CallImportRow]], List, set]:
    from app.models.schemas import CallImportEvaluationRetrySkippedItem

    targets: List[Tuple[CallImportEvaluationRow, CallImportRow]] = []
    skipped: List[CallImportEvaluationRetrySkippedItem] = []
    found: set = set()

    def _take(page: List[Tuple[CallImportEvaluationRow, Optional[CallImportRow]]]) -> None:
        for eval_row, source_row in page:
            found.add(eval_row.id)
            if requested_ids is not None and eval_row.status in {"pending", "running"}:
                skipped.append(
                    CallImportEvaluationRetrySkippedItem(
                        eval_row_id=eval_row.id,
                        reason="in_progress",
                    )
                )
                continue
            if (
                requested_ids is not None
                and eval_row.status == "completed"
                and not include_completed
            ):
                skipped.append(
                    CallImportEvaluationRetrySkippedItem(
                        eval_row_id=eval_row.id,
                        reason="completed",
                    )
                )
                continue
            if source_row is None:
                skipped.append(
                    CallImportEvaluationRetrySkippedItem(
                        eval_row_id=eval_row.id,
                        reason="source_row_missing",
                    )
                )
                continue
            targets.append((eval_row, source_row))

    if requested_ids is not None:
        for start in range(0, len(requested_ids), RETRY_ROW_PAGE_SIZE):
            chunk = list(requested_ids)[start : start + RETRY_ROW_PAGE_SIZE]
            eval_rows = retry_eval_ids_query(session, evaluation.id, chunk).all()
            if not eval_rows:
                continue
            sources = {
                row.id: row
                for row in retry_source_page_query(
                    session,
                    [row.call_import_row_id for row in eval_rows],
                ).all()
            }
            _take([(row, sources.get(row.call_import_row_id)) for row in eval_rows])
        return targets, skipped, found

    for status in _retry_statuses(include_completed=include_completed):
        after_id: Optional[UUID] = None
        while True:
            page = load_retry_target_page(
                session,
                evaluation.id,
                status=status,
                after_id=after_id,
                include_metric_scores=False,
                ordered=True,
            )
            if not page:
                break
            after_id = page[-1][0].id
            _take(page)
            if len(page) < RETRY_ROW_PAGE_SIZE:
                break
    return targets, skipped, found


def gather_retry_targets_sharded(
    catalog_db: Session,
    evaluation: CallImportEvaluation,
    requested_ids: Optional[List[UUID]],
    *,
    include_completed: bool,
) -> Tuple[List[Tuple[CallImportEvaluationRow, CallImportRow]], List]:
    """Return slim retry targets. Status filter is in SQL, not after a full load."""
    from app.models.schemas import CallImportEvaluationRetrySkippedItem

    targets: List[Tuple[CallImportEvaluationRow, CallImportRow]] = []
    skipped: List = []
    found: set = set()
    for session, _shard_id in iter_evaluation_row_sessions(
        catalog_db, evaluation.call_import_id
    ):
        page_targets, page_skipped, page_found = _collect_retry_targets_on_session(
            session,
            evaluation,
            requested_ids,
            include_completed=include_completed,
        )
        targets.extend(page_targets)
        skipped.extend(page_skipped)
        found.update(page_found)
    if requested_ids is not None:
        for missing in set(requested_ids) - found:
            skipped.append(
                CallImportEvaluationRetrySkippedItem(
                    eval_row_id=missing,
                    reason="unknown",
                )
            )
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
