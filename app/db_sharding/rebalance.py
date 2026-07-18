"""Backfill / rebalance tooling: move call-import slice rows between shards."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Set
from uuid import UUID

import redis
from loguru import logger
from sqlalchemy import and_, inspect, or_, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db_sharding.pool_manager import db_pool_manager
from app.db_sharding.row_ops import _reset_shard_write_role, _shard_write_without_catalog_fks
from app.db_sharding.sessions import is_sharding_enabled
from app.models.database import (
    CallImport,
    CallImportEvaluation,
    CallImportEvaluationRow,
    CallImportRow,
    CallImportShardSlice,
)
from app.models.enums import CallImportRowStatus, CallImportStatus

_REBALANCE_LOCK_KEY_PREFIX = "rebalance:import:"
_REBALANCE_LOCK_TTL_SECONDS = 3600

_redis_client: redis.Redis | None = None

_IN_FLIGHT_IMPORT_ROW_STATUSES = frozenset(
    {CallImportRowStatus.PENDING.value, CallImportRowStatus.PROCESSING.value}
)
_IN_FLIGHT_EVAL_ROW_STATUSES = frozenset({"pending", "running"})


class RebalanceError(Exception):
    """Operator-facing rebalance validation or execution failure."""


@dataclass(frozen=True)
class SliceInfo:
    slice_id: int
    shard_id: str
    row_index_min: int
    row_index_max: int

    @property
    def row_count(self) -> int:
        return self.row_index_max - self.row_index_min + 1


@dataclass(frozen=True)
class RebalancePlan:
    call_import_id: UUID
    from_shard_id: str
    to_shard_id: str
    slices: tuple[SliceInfo, ...]
    import_row_count: int
    eval_row_count: int


@dataclass(frozen=True)
class RebalanceResult:
    dry_run: bool
    call_import_id: UUID
    from_shard_id: str
    to_shard_id: str
    slices_moved: int
    import_rows_moved: int
    eval_rows_moved: int


def _redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis_client


def rebalance_lock_key(call_import_id: UUID | str) -> str:
    return f"{_REBALANCE_LOCK_KEY_PREFIX}{call_import_id}"


def is_import_rebalance_locked(call_import_id: UUID | str) -> bool:
    try:
        return bool(_redis().get(rebalance_lock_key(call_import_id)))
    except redis.RedisError:
        return False


def acquire_rebalance_lock(call_import_id: UUID | str) -> bool:
    """Best-effort pause: block fair dispatch for this import while rebalancing."""
    try:
        return bool(
            _redis().set(
                rebalance_lock_key(call_import_id),
                "1",
                nx=True,
                ex=_REBALANCE_LOCK_TTL_SECONDS,
            )
        )
    except redis.RedisError as exc:
        logger.warning("Could not acquire rebalance lock for {}: {}", call_import_id, exc)
        return False


def release_rebalance_lock(call_import_id: UUID | str) -> None:
    try:
        _redis().delete(rebalance_lock_key(call_import_id))
    except redis.RedisError as exc:
        logger.warning("Could not release rebalance lock for {}: {}", call_import_id, exc)


def filter_unlocked_call_import_ids(
    call_import_ids: Iterable[UUID],
) -> List[UUID]:
    """Drop imports that are mid-rebalance (fair dispatch should skip them)."""
    return [cid for cid in call_import_ids if not is_import_rebalance_locked(cid)]


def filter_evaluations_not_rebalancing(
    catalog_db: Session,
    evaluation_ids: Iterable[UUID],
) -> List[UUID]:
    """Drop evaluations whose parent import is mid-rebalance."""
    ids = list(evaluation_ids)
    if not ids:
        return []
    rows = catalog_db.execute(
        select(CallImportEvaluation.id, CallImportEvaluation.call_import_id).where(
            CallImportEvaluation.id.in_(ids)
        )
    ).all()
    return [
        evaluation_id
        for evaluation_id, call_import_id in rows
        if not is_import_rebalance_locked(call_import_id)
    ]


def _require_sharding() -> None:
    if not is_sharding_enabled():
        raise RebalanceError(
            "database.sharding.enabled must be true (set catalog_url + shards in config)"
        )


def require_sharding_enabled() -> None:
    _require_sharding()


def _configured_shard_ids() -> Set[str]:
    router = db_pool_manager.router
    if router is None:
        return set()
    return set(router.shard_ids)


def _validate_shard_id(shard_id: str, *, label: str) -> None:
    configured = _configured_shard_ids()
    if shard_id not in configured:
        raise RebalanceError(
            f"{label} shard {shard_id!r} is not configured "
            f"(available: {sorted(configured)})"
        )


def list_shard_slices(catalog_db: Session, call_import_id: UUID) -> List[SliceInfo]:
    rows = catalog_db.execute(
        select(
            CallImportShardSlice.slice_id,
            CallImportShardSlice.shard_id,
            CallImportShardSlice.row_index_min,
            CallImportShardSlice.row_index_max,
        )
        .where(CallImportShardSlice.call_import_id == call_import_id)
        .order_by(CallImportShardSlice.slice_id.asc())
    ).all()
    return [
        SliceInfo(
            slice_id=int(slice_id),
            shard_id=str(shard_id),
            row_index_min=int(row_index_min),
            row_index_max=int(row_index_max),
        )
        for slice_id, shard_id, row_index_min, row_index_max in rows
    ]


def _row_index_filter(model, slices: Sequence[SliceInfo]):
    return or_(
        *[
            and_(
                model.row_index >= slice_info.row_index_min,
                model.row_index <= slice_info.row_index_max,
            )
            for slice_info in slices
        ]
    )


def _orm_mapping(instance) -> dict:
    return {
        column.key: getattr(instance, column.key)
        for column in inspect(instance).mapper.column_attrs
    }


def _evaluation_ids_for_import(catalog_db: Session, call_import_id: UUID) -> List[UUID]:
    rows = catalog_db.execute(
        select(CallImportEvaluation.id).where(
            CallImportEvaluation.call_import_id == call_import_id
        )
    ).all()
    return [row[0] for row in rows]


def _count_rows_on_shard(
    shard_db: Session,
    *,
    call_import_id: UUID,
    slices: Sequence[SliceInfo],
    evaluation_ids: Sequence[UUID],
) -> tuple[int, int]:
    import_count = (
        shard_db.query(CallImportRow.id)
        .filter(
            CallImportRow.call_import_id == call_import_id,
            _row_index_filter(CallImportRow, slices),
        )
        .count()
    )
    eval_count = 0
    if evaluation_ids:
        row_ids = [
            row_id
            for (row_id,) in shard_db.query(CallImportRow.id)
            .filter(
                CallImportRow.call_import_id == call_import_id,
                _row_index_filter(CallImportRow, slices),
            )
            .all()
        ]
        if row_ids:
            eval_count = (
                shard_db.query(CallImportEvaluationRow.id)
                .filter(CallImportEvaluationRow.call_import_row_id.in_(row_ids))
                .count()
            )
    return import_count, eval_count


def assert_import_rebalance_ready(
    catalog_db: Session,
    call_import_id: UUID,
    *,
    force: bool = False,
) -> None:
    call_import = (
        catalog_db.query(CallImport)
        .filter(CallImport.id == call_import_id)
        .first()
    )
    if call_import is None:
        raise RebalanceError(f"call_import {call_import_id} not found on catalog")

    if call_import.status == CallImportStatus.DELETING:
        raise RebalanceError("import is being deleted; rebalance is not allowed")

    if force:
        return

    if call_import.status in {
        CallImportStatus.PROCESSING,
        CallImportStatus.PENDING,
    }:
        raise RebalanceError(
            f"import status is {call_import.status.value!r}; "
            "wait for terminal status or pass --force after pausing workers"
        )

    evaluation_ids = _evaluation_ids_for_import(catalog_db, call_import_id)
    router = db_pool_manager.router
    assert router is not None

    in_flight_import = 0
    in_flight_eval = 0
    for shard_id in router.shard_ids:
        factory = db_pool_manager.shard_session_factory(shard_id)
        shard_db = factory()
        try:
            in_flight_import += (
                shard_db.query(CallImportRow.id)
                .filter(
                    CallImportRow.call_import_id == call_import_id,
                    CallImportRow.status.in_(_IN_FLIGHT_IMPORT_ROW_STATUSES),
                )
                .count()
            )
            if evaluation_ids:
                in_flight_eval += (
                    shard_db.query(CallImportEvaluationRow.id)
                    .filter(
                        CallImportEvaluationRow.evaluation_id.in_(evaluation_ids),
                        CallImportEvaluationRow.status.in_(_IN_FLIGHT_EVAL_ROW_STATUSES),
                    )
                    .count()
                )
        finally:
            shard_db.close()

    if in_flight_import or in_flight_eval:
        raise RebalanceError(
            "import still has in-flight rows "
            f"(import_rows={in_flight_import}, eval_rows={in_flight_eval}); "
            "pause workers or pass --force"
        )


def build_rebalance_plan(
    catalog_db: Session,
    call_import_id: UUID,
    *,
    from_shard_id: str,
    to_shard_id: str,
    slice_ids: Optional[Iterable[int]] = None,
) -> RebalancePlan:
    _require_sharding()
    _validate_shard_id(from_shard_id, label="source")
    _validate_shard_id(to_shard_id, label="target")
    if from_shard_id == to_shard_id:
        raise RebalanceError("source and target shard must differ")

    all_slices = list_shard_slices(catalog_db, call_import_id)
    if not all_slices:
        raise RebalanceError(
            f"no registry slices for call_import {call_import_id}; "
            "run materialize/register_shard_slices first"
        )

    selected = [s for s in all_slices if s.shard_id == from_shard_id]
    if slice_ids is not None:
        wanted = {int(value) for value in slice_ids}
        selected = [s for s in selected if s.slice_id in wanted]
        missing = wanted - {s.slice_id for s in selected}
        if missing:
            raise RebalanceError(
                f"slice id(s) {sorted(missing)} not registered on shard {from_shard_id!r}"
            )

    if not selected:
        raise RebalanceError(
            f"no slices on shard {from_shard_id!r} for call_import {call_import_id}"
        )

    evaluation_ids = _evaluation_ids_for_import(catalog_db, call_import_id)
    factory = db_pool_manager.shard_session_factory(from_shard_id)
    shard_db = factory()
    try:
        import_count, eval_count = _count_rows_on_shard(
            shard_db,
            call_import_id=call_import_id,
            slices=selected,
            evaluation_ids=evaluation_ids,
        )
    finally:
        shard_db.close()

    return RebalancePlan(
        call_import_id=call_import_id,
        from_shard_id=from_shard_id,
        to_shard_id=to_shard_id,
        slices=tuple(selected),
        import_row_count=import_count,
        eval_row_count=eval_count,
    )


def _copy_rows_between_shards(
    *,
    call_import_id: UUID,
    slices: Sequence[SliceInfo],
    from_shard_id: str,
    to_shard_id: str,
) -> tuple[int, int]:
    source_db = db_pool_manager.shard_session_factory(from_shard_id)()
    target_db = db_pool_manager.shard_session_factory(to_shard_id)()
    import_moved = 0
    eval_moved = 0
    try:
        import_rows = (
            source_db.query(CallImportRow)
            .filter(
                CallImportRow.call_import_id == call_import_id,
                _row_index_filter(CallImportRow, slices),
            )
            .order_by(CallImportRow.row_index.asc())
            .all()
        )
        if not import_rows:
            return 0, 0

        row_ids = [row.id for row in import_rows]
        eval_rows = (
            source_db.query(CallImportEvaluationRow)
            .filter(CallImportEvaluationRow.call_import_row_id.in_(row_ids))
            .all()
        )

        existing_import_ids = {
            row_id
            for (row_id,) in target_db.query(CallImportRow.id)
            .filter(CallImportRow.id.in_(row_ids))
            .all()
        }
        existing_eval_ids = {
            row_id
            for (row_id,) in target_db.query(CallImportEvaluationRow.id)
            .filter(CallImportEvaluationRow.id.in_([row.id for row in eval_rows]))
            .all()
        }

        import_to_insert = [
            _orm_mapping(row) for row in import_rows if row.id not in existing_import_ids
        ]
        eval_to_insert = [
            _orm_mapping(row) for row in eval_rows if row.id not in existing_eval_ids
        ]

        if import_to_insert or eval_to_insert:
            _shard_write_without_catalog_fks(target_db)
            try:
                if import_to_insert:
                    target_db.bulk_insert_mappings(CallImportRow, import_to_insert)
                if eval_to_insert:
                    target_db.bulk_insert_mappings(CallImportEvaluationRow, eval_to_insert)
                target_db.commit()
            except Exception:
                target_db.rollback()
                raise
            finally:
                try:
                    _reset_shard_write_role(target_db)
                except Exception:
                    pass

        import_moved = len(import_rows)
        eval_moved = len(eval_rows)

        if eval_rows:
            source_db.query(CallImportEvaluationRow).filter(
                CallImportEvaluationRow.id.in_([row.id for row in eval_rows])
            ).delete(synchronize_session=False)
        source_db.query(CallImportRow).filter(CallImportRow.id.in_(row_ids)).delete(
            synchronize_session=False
        )
        source_db.commit()
    except Exception:
        source_db.rollback()
        raise
    finally:
        source_db.close()
        target_db.close()

    return import_moved, eval_moved


def _update_slice_registry(
    catalog_db: Session,
    call_import_id: UUID,
    slices: Sequence[SliceInfo],
    *,
    to_shard_id: str,
) -> None:
    slice_id_set = {slice_info.slice_id for slice_info in slices}
    for slice_info in slices:
        catalog_db.merge(
            CallImportShardSlice(
                call_import_id=call_import_id,
                slice_id=slice_info.slice_id,
                shard_id=to_shard_id,
                row_index_min=slice_info.row_index_min,
                row_index_max=slice_info.row_index_max,
            )
        )
    catalog_db.flush()
    logger.info(
        "Updated registry for call_import {} slices {} -> shard {}",
        call_import_id,
        sorted(slice_id_set),
        to_shard_id,
    )


def execute_rebalance_slices(
    catalog_db: Session,
    plan: RebalancePlan,
    *,
    dry_run: bool = False,
    force: bool = False,
) -> RebalanceResult:
    _require_sharding()
    assert_import_rebalance_ready(catalog_db, plan.call_import_id, force=force)

    if dry_run:
        return RebalanceResult(
            dry_run=True,
            call_import_id=plan.call_import_id,
            from_shard_id=plan.from_shard_id,
            to_shard_id=plan.to_shard_id,
            slices_moved=len(plan.slices),
            import_rows_moved=plan.import_row_count,
            eval_rows_moved=plan.eval_row_count,
        )

    lock_acquired = acquire_rebalance_lock(plan.call_import_id)
    if not lock_acquired:
        raise RebalanceError(
            f"another rebalance lock is active for import {plan.call_import_id}"
        )

    try:
        import_moved, eval_moved = _copy_rows_between_shards(
            call_import_id=plan.call_import_id,
            slices=plan.slices,
            from_shard_id=plan.from_shard_id,
            to_shard_id=plan.to_shard_id,
        )
        if plan.import_row_count > 0 and import_moved == 0:
            raise RebalanceError(
                f"expected {plan.import_row_count} import row(s) on "
                f"{plan.from_shard_id!r} but found none; "
                "registry may not match shard data"
            )
        _update_slice_registry(
            catalog_db,
            plan.call_import_id,
            plan.slices,
            to_shard_id=plan.to_shard_id,
        )
        catalog_db.commit()
    except Exception:
        catalog_db.rollback()
        raise
    finally:
        release_rebalance_lock(plan.call_import_id)

    return RebalanceResult(
        dry_run=False,
        call_import_id=plan.call_import_id,
        from_shard_id=plan.from_shard_id,
        to_shard_id=plan.to_shard_id,
        slices_moved=len(plan.slices),
        import_rows_moved=import_moved,
        eval_rows_moved=eval_moved,
    )
