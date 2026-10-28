"""Scatter-gather reads and fan-out writes across row shards."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Dict, Iterable, List, NamedTuple, Optional, Sequence, Tuple, TypeVar, TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Integer, case, cast, func, or_
from sqlalchemy.orm import Session, defer, load_only, with_expression

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


class SliceCount(NamedTuple):
    slice_id: int
    shard_id: str
    count: int


class SlicePageWindow(NamedTuple):
    shard_id: str
    slice_id: int
    local_offset: int
    limit: int


def plan_slice_page(
    slices: Sequence[SliceCount],
    *,
    offset: int,
    limit: int,
    descending: bool = False,
) -> List[SlicePageWindow]:
    """Windows that cover ``offset``/``limit`` without reading other slices.

    Counts already include holes, so a slice of 500 row-index values with
    one deleted row contributes 499. The local offset is applied inside
    that slice in row_index order.
    """
    if limit <= 0:
        return []
    ordered = sorted(
        slices,
        key=lambda item: (int(item.slice_id), item.shard_id),
        reverse=descending,
    )
    remaining_offset = max(0, int(offset))
    remaining = int(limit)
    windows: List[SlicePageWindow] = []
    for item in ordered:
        if remaining <= 0:
            break
        count = int(item.count or 0)
        if count <= 0:
            continue
        if remaining_offset >= count:
            remaining_offset -= count
            continue
        take = min(remaining, count - remaining_offset)
        windows.append(
            SlicePageWindow(
                item.shard_id,
                int(item.slice_id),
                remaining_offset,
                take,
            )
        )
        remaining -= take
        remaining_offset = 0
    return windows


_ROW_TEXT_ATTRS = (
    "transcript",
    "diarised_transcript",
    "diarised_segments",
    "diarised_prompt",
    "raw_columns",
)


def defer_call_import_row_text():
    """Keep list queries from selecting transcript bodies."""
    return tuple(defer(getattr(CallImportRow, name)) for name in _ROW_TEXT_ATTRS)


def _row_chunk_size() -> int:
    router = db_pool_manager.router
    if router is None:
        return 500
    return max(1, int(router.row_chunk_size))


def _slice_id_expr(chunk: int):
    return cast(func.floor(CallImportRow.row_index / chunk), Integer)


def _collect_import_slice_counts(
    catalog_db: Session,
    call_import_id: UUID,
    *,
    search_term: str = "",
    diarised_status_filter: Optional[str] = None,
) -> List[SliceCount]:
    chunk = _row_chunk_size()
    slice_expr = _slice_id_expr(chunk)
    shard_ids = shard_ids_for_import(catalog_db, call_import_id)

    def count_shard(db: Session, shard_id: str) -> List[SliceCount]:
        query = db.query(slice_expr, func.count(CallImportRow.id)).filter(
            CallImportRow.call_import_id == call_import_id
        )
        query = _apply_call_import_row_filters(
            query,
            search_term=search_term,
            diarised_status_filter=diarised_status_filter,
        )
        counts: List[SliceCount] = []
        for slice_id, count in query.group_by(slice_expr).all():
            if int(count or 0) <= 0 or slice_id is None:
                continue
            counts.append(SliceCount(int(slice_id), shard_id, int(count)))
        return counts

    collected: List[SliceCount] = []
    for part in scatter_gather_on_shards(shard_ids, count_shard):
        collected.extend(part)
    return collected


def _load_call_import_slice_window(
    shard_id: str,
    call_import_id: UUID,
    window: SlicePageWindow,
    *,
    search_term: str = "",
    diarised_status_filter: Optional[str] = None,
    descending: bool = False,
) -> List[CallImportRow]:
    chunk = _row_chunk_size()
    lo = window.slice_id * chunk
    hi = lo + chunk
    factory = db_pool_manager.shard_session_factory(shard_id)
    db = factory()
    try:
        query = (
            db.query(CallImportRow)
            .options(*defer_call_import_row_text())
            .filter(
                CallImportRow.call_import_id == call_import_id,
                CallImportRow.row_index >= lo,
                CallImportRow.row_index < hi,
            )
        )
        query = _apply_call_import_row_filters(
            query,
            search_term=search_term,
            diarised_status_filter=diarised_status_filter,
        )
        order = (
            CallImportRow.row_index.desc()
            if descending
            else CallImportRow.row_index.asc()
        )
        rows = (
            query.order_by(order)
            .offset(window.local_offset)
            .limit(window.limit)
            .all()
        )
        for row in rows:
            db.expunge(row)
        return rows
    finally:
        db.close()


def _legacy_call_import_rows_page(
    catalog_db: Session,
    call_import_id: UUID,
    *,
    search_term: str = "",
    diarised_status_filter: Optional[str] = None,
    offset: int,
    limit: int,
) -> List[CallImportRow]:
    query = (
        catalog_db.query(CallImportRow)
        .options(*defer_call_import_row_text())
        .filter(CallImportRow.call_import_id == call_import_id)
    )
    query = _apply_call_import_row_filters(
        query,
        search_term=search_term,
        diarised_status_filter=diarised_status_filter,
    )
    return (
        query.order_by(CallImportRow.row_index.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )


def fetch_call_import_rows_filtered_page(
    catalog_db: Session,
    call_import_id: UUID,
    *,
    search_term: str = "",
    diarised_status_filter: Optional[str] = None,
    offset: int,
    limit: int,
) -> List[CallImportRow]:
    if limit <= 0:
        return []
    if not is_sharding_enabled():
        return _legacy_call_import_rows_page(
            catalog_db,
            call_import_id,
            search_term=search_term,
            diarised_status_filter=diarised_status_filter,
            offset=offset,
            limit=limit,
        )

    slices = _collect_import_slice_counts(
        catalog_db,
        call_import_id,
        search_term=search_term,
        diarised_status_filter=diarised_status_filter,
    )
    if not slices:
        return _legacy_call_import_rows_page(
            catalog_db,
            call_import_id,
            search_term=search_term,
            diarised_status_filter=diarised_status_filter,
            offset=offset,
            limit=limit,
        )

    windows = plan_slice_page(slices, offset=offset, limit=limit)
    rows: List[CallImportRow] = []
    for window in windows:
        rows.extend(
            _load_call_import_slice_window(
                window.shard_id,
                call_import_id,
                window,
                search_term=search_term,
                diarised_status_filter=diarised_status_filter,
            )
        )
    return merge_rows_by_index(rows)


def list_call_import_row_ids_filtered(
    catalog_db: Session,
    call_import_id: UUID,
    *,
    search_term: str = "",
    diarised_status_filter: Optional[str] = None,
) -> List[UUID]:
    """Matching row ids in row_index order. Does not load transcript bodies."""

    def _ids_from(db: Session) -> List[Tuple[UUID, int]]:
        query = db.query(CallImportRow.id, CallImportRow.row_index).filter(
            CallImportRow.call_import_id == call_import_id
        )
        query = _apply_call_import_row_filters(
            query,
            search_term=search_term,
            diarised_status_filter=diarised_status_filter,
        )
        return [(row_id, int(row_index or 0)) for row_id, row_index in query.all()]

    if not is_sharding_enabled():
        pairs = _ids_from(catalog_db)
    else:
        shard_ids = shard_ids_for_import(catalog_db, call_import_id)

        def load_shard(db: Session, _shard_id: str) -> List[Tuple[UUID, int]]:
            return _ids_from(db)

        pairs = []
        for part in scatter_gather_on_shards(shard_ids, load_shard):
            pairs.extend(part)
        if not pairs:
            pairs = _ids_from(catalog_db)

    pairs.sort(key=lambda pair: pair[1])
    return [row_id for row_id, _row_index in pairs if row_id is not None]


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


def _text_char_length(column):
    return func.length(func.trim(func.coalesce(column, "")))


def dispatch_eval_row_options():
    """Columns the eval dispatcher reads or writes. Skips metric_scores."""
    return (
        load_only(
            CallImportEvaluationRow.id,
            CallImportEvaluationRow.evaluation_id,
            CallImportEvaluationRow.call_import_row_id,
            CallImportEvaluationRow.status,
            CallImportEvaluationRow.celery_task_id,
            CallImportEvaluationRow.error_message,
            CallImportEvaluationRow.finished_at,
        ),
    )


def retry_source_row_options():
    """Retry columns plus text lengths. Does not load transcript bodies."""
    return (
        load_only(
            CallImportRow.id,
            CallImportRow.call_import_id,
            CallImportRow.row_index,
            CallImportRow.status,
            CallImportRow.celery_task_id,
            CallImportRow.recording_s3_key,
            CallImportRow.recording_url,
            CallImportRow.error_message,
            CallImportRow.attempts,
            CallImportRow.diarised_transcript_status,
            CallImportRow.diarised_transcript_error,
        ),
        with_expression(
            CallImportRow.transcript_char_length,
            _text_char_length(CallImportRow.transcript),
        ),
        with_expression(
            CallImportRow.diarised_transcript_char_length,
            _text_char_length(CallImportRow.diarised_transcript),
        ),
    )


def dispatch_source_row_options():
    """Columns the eval dispatcher reads or writes, plus text lengths."""
    return (
        load_only(
            CallImportRow.id,
            CallImportRow.call_import_id,
            CallImportRow.row_index,
            CallImportRow.status,
            CallImportRow.celery_task_id,
            CallImportRow.recording_s3_key,
            CallImportRow.recording_url,
            CallImportRow.error_message,
            CallImportRow.diarised_transcript_status,
            CallImportRow.diarised_transcript_error,
        ),
        with_expression(
            CallImportRow.transcript_char_length,
            _text_char_length(CallImportRow.transcript),
        ),
        with_expression(
            CallImportRow.diarised_transcript_char_length,
            _text_char_length(CallImportRow.diarised_transcript),
        ),
    )


def row_text_present(row, column: str, length_attr: str) -> bool:
    """True when a text column is non-blank, without loading a deferred body."""
    length = getattr(row, length_attr, None)
    if isinstance(length, int) and not isinstance(length, bool):
        return length > 0
    state = getattr(row, "_sa_instance_state", None)
    if state is None:
        return bool((getattr(row, column, None) or "").strip())
    from sqlalchemy.orm.base import NEVER_SET, NO_VALUE

    loaded = state.attrs[column].loaded_value
    if loaded is NEVER_SET or loaded is NO_VALUE:
        return False
    return bool((loaded or "").strip())


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
            .options(*dispatch_eval_row_options(), *dispatch_source_row_options())
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
                .options(*dispatch_eval_row_options(), *dispatch_source_row_options())
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
    """One page of import rows, merged by row_index."""
    return fetch_call_import_rows_filtered_page(
        catalog_db,
        call_import_id,
        offset=offset,
        limit=limit,
    )


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


def _production_transcript_present():
    return (
        func.length(func.btrim(func.coalesce(CallImportRow.transcript, ""))) > 0
    )


def _diarised_transcript_present():
    return (
        func.length(
            func.btrim(func.coalesce(CallImportRow.diarised_transcript, ""))
        )
        > 0
    )


def _transcript_coverage_on_session(
    db: Session, call_import_id: UUID
) -> Tuple[int, int, Dict[str, int]]:
    """Return (total, with_transcript, source_counts) using length checks."""

    def base():
        return db.query(CallImportRow).filter(
            CallImportRow.call_import_id == call_import_id
        )

    total = int(base().with_entities(func.count(CallImportRow.id)).scalar() or 0)
    prod = _production_transcript_present()
    diar = _diarised_transcript_present()
    with_transcript = int(
        base()
        .filter(or_(prod, diar))
        .with_entities(func.count(CallImportRow.id))
        .scalar()
        or 0
    )
    source_expr = func.coalesce(
        func.nullif(CallImportRow.transcript_source, ""),
        "csv",
    )
    source_counts: Dict[str, int] = {}
    for source, count in (
        base()
        .filter(prod)
        .with_entities(source_expr, func.count(CallImportRow.id))
        .group_by(source_expr)
        .all()
    ):
        if source is None:
            continue
        source_counts[str(source)] = source_counts.get(str(source), 0) + int(count or 0)
    diarised_count = int(
        base().filter(diar).with_entities(func.count(CallImportRow.id)).scalar() or 0
    )
    if diarised_count:
        source_counts["diarised"] = (
            source_counts.get("diarised", 0) + diarised_count
        )
    return total, with_transcript, source_counts


def aggregate_transcript_coverage(
    catalog_db: Session,
    call_import_id: UUID,
) -> Tuple[int, int, int, Dict[str, int]]:
    """Batch transcript coverage without loading transcript bodies.

    Returns ``(total, with_transcript, without_transcript, source_counts)``.
    """
    if not is_sharding_enabled():
        total, with_transcript, sources = _transcript_coverage_on_session(
            catalog_db, call_import_id
        )
        return total, with_transcript, total - with_transcript, sources

    total = 0
    with_transcript = 0
    sources: Dict[str, int] = {}
    shard_ids = shard_ids_for_import(catalog_db, call_import_id)

    def cover_shard(db: Session, _shard_id: str):
        return _transcript_coverage_on_session(db, call_import_id)

    for part_total, part_with, part_sources in scatter_gather_on_shards(
        shard_ids, cover_shard
    ):
        total += int(part_total)
        with_transcript += int(part_with)
        for key, value in part_sources.items():
            sources[key] = sources.get(key, 0) + int(value)
    if total == 0:
        total, with_transcript, sources = _transcript_coverage_on_session(
            catalog_db, call_import_id
        )
    return total, with_transcript, total - with_transcript, sources


_EVAL_SCORE_COLUMNS = (
    CallImportEvaluationRow.id,
    CallImportEvaluationRow.evaluation_id,
    CallImportEvaluationRow.call_import_row_id,
    CallImportEvaluationRow.status,
    CallImportEvaluationRow.metric_scores,
    CallImportEvaluationRow.error_message,
    CallImportEvaluationRow.started_at,
    CallImportEvaluationRow.finished_at,
    CallImportEvaluationRow.created_at,
    CallImportEvaluationRow.updated_at,
)


def load_evaluation_score_rows(
    catalog_db: Session,
    evaluation_id: UUID,
) -> List[CallImportEvaluationRow]:
    """Eval rows with scores and status. Does not join source transcripts."""
    def load(db: Session) -> List[CallImportEvaluationRow]:
        rows = (
            db.query(CallImportEvaluationRow)
            .options(load_only(*_EVAL_SCORE_COLUMNS))
            .filter(CallImportEvaluationRow.evaluation_id == evaluation_id)
            .all()
        )
        for row in rows:
            db.expunge(row)
        return rows

    if not is_sharding_enabled():
        return load(catalog_db)

    merged: List[CallImportEvaluationRow] = []
    router = db_pool_manager.router
    assert router is not None
    for shard_id in router.shard_ids:
        factory = db_pool_manager.shard_session_factory(shard_id)
        shard_db = factory()
        try:
            merged.extend(load(shard_db))
        finally:
            shard_db.close()
    if not merged:
        return load(catalog_db)
    return merged


def load_evaluation_score_rows_for_aggregate(
    catalog_db: Session,
    evaluation_id: UUID,
) -> List[CallImportEvaluationRow]:
    """Score rows with a terminal status only (for chart aggregates)."""

    def load(db: Session) -> List[CallImportEvaluationRow]:
        rows = (
            db.query(CallImportEvaluationRow)
            .options(load_only(*_EVAL_SCORE_COLUMNS))
            .filter(
                CallImportEvaluationRow.evaluation_id == evaluation_id,
                CallImportEvaluationRow.status.in_(("completed", "failed")),
            )
            .all()
        )
        for row in rows:
            db.expunge(row)
        return rows

    if not is_sharding_enabled():
        return load(catalog_db)

    merged: List[CallImportEvaluationRow] = []
    router = db_pool_manager.router
    assert router is not None
    for shard_id in router.shard_ids:
        factory = db_pool_manager.shard_session_factory(shard_id)
        shard_db = factory()
        try:
            merged.extend(load(shard_db))
        finally:
            shard_db.close()
    if not merged:
        return load(catalog_db)
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


def max_call_import_row_index(
    catalog_db: Session,
    call_import_id: UUID,
) -> int:
    """Highest ``row_index`` for an import, or ``-1`` when no rows exist."""
    if not is_sharding_enabled():
        result = (
            catalog_db.query(func.max(CallImportRow.row_index))
            .filter(CallImportRow.call_import_id == call_import_id)
            .scalar()
        )
        return int(result) if result is not None else -1

    max_index = -1

    def max_on_shard(db: Session, _shard_id: str) -> int:
        result = (
            db.query(func.max(CallImportRow.row_index))
            .filter(CallImportRow.call_import_id == call_import_id)
            .scalar()
        )
        return int(result) if result is not None else -1

    for part in scatter_gather_on_shards(
        shard_ids_for_import(catalog_db, call_import_id),
        max_on_shard,
    ):
        max_index = max(max_index, part)

    if max_index < 0:
        result = (
            catalog_db.query(func.max(CallImportRow.row_index))
            .filter(CallImportRow.call_import_id == call_import_id)
            .scalar()
        )
        return int(result) if result is not None else -1
    return max_index


def load_call_import_conversation_ids(
    catalog_db: Session,
    call_import_id: UUID,
) -> List[Optional[str]]:
    """All conversation ids for an import (shard-aware)."""
    if not is_sharding_enabled():
        return [
            row[0]
            for row in catalog_db.query(CallImportRow.conversation_id)
            .filter(CallImportRow.call_import_id == call_import_id)
            .all()
        ]

    conversation_ids: List[Optional[str]] = []

    def load_shard(db: Session, _shard_id: str) -> List[Optional[str]]:
        return [
            row[0]
            for row in db.query(CallImportRow.conversation_id)
            .filter(CallImportRow.call_import_id == call_import_id)
            .all()
        ]

    for part in scatter_gather_on_shards(
        shard_ids_for_import(catalog_db, call_import_id),
        load_shard,
    ):
        conversation_ids.extend(part)

    if not conversation_ids:
        conversation_ids = [
            row[0]
            for row in catalog_db.query(CallImportRow.conversation_id)
            .filter(CallImportRow.call_import_id == call_import_id)
            .all()
        ]
    return conversation_ids


def _non_empty_production_transcript_filter():
    """Rows whose CSV ``transcript`` column has non-whitespace content."""
    return (
        CallImportRow.transcript.isnot(None),
        func.length(func.trim(CallImportRow.transcript)) > 0,
    )


def count_call_import_rows_with_production_transcript(
    catalog_db: Session,
    call_import_id: UUID,
) -> int:
    """Import rows with a non-empty production transcript (shard-aware)."""
    transcript_filters = _non_empty_production_transcript_filter()

    if not is_sharding_enabled():
        return int(
            catalog_db.query(func.count(CallImportRow.id))
            .filter(
                CallImportRow.call_import_id == call_import_id,
                *transcript_filters,
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
                *transcript_filters,
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
                *transcript_filters,
            )
            .scalar()
            or 0
        )
    return total


def list_source_row_ids_with_production_transcript(
    catalog_db: Session,
    call_import_id: UUID,
) -> List[UUID]:
    """Import row ids with a non-empty production transcript, ordered by row_index."""
    transcript_filters = _non_empty_production_transcript_filter()

    if not is_sharding_enabled():
        rows = (
            catalog_db.query(CallImportRow.id)
            .filter(
                CallImportRow.call_import_id == call_import_id,
                *transcript_filters,
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
                *transcript_filters,
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
                *transcript_filters,
            )
            .order_by(CallImportRow.row_index.asc())
            .all()
        )
        return [row_id for (row_id,) in rows if row_id is not None]
    return [row.id for row in merged if row.id is not None]


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
