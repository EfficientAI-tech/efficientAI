"""Row placement, lookup, and bulk insert across shards."""

from __future__ import annotations

from collections import defaultdict
from contextlib import contextmanager
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple
from uuid import UUID, uuid4

from sqlalchemy.orm import Session
from sqlalchemy import text

from app.db_sharding.pool_manager import db_pool_manager, open_catalog_session
from app.db_sharding.registry import load_slice_registry_for_import
from app.db_sharding.sessions import is_sharding_enabled
from app.models.database import CallImport, CallImportRow, CallImportShardSlice
from app.models.database import CallImportEvaluationRow


def router_for_import(catalog_db: Session, call_import_id: UUID) -> Tuple[Any, Optional[dict]]:
    """Return (router, slice_registry) for routing rows of this import."""
    manager = db_pool_manager
    router = manager.router
    if router is None:
        return None, None
    registry = load_slice_registry_for_import(catalog_db, call_import_id)
    return router, registry or None


def shard_id_for_row(
    catalog_db: Session,
    call_import_id: UUID,
    row_index: int,
) -> str:
    if not is_sharding_enabled():
        return "legacy"
    router, registry = router_for_import(catalog_db, call_import_id)
    assert router is not None
    return router.shard_id_for_row(
        call_import_id,
        row_index,
        slice_registry=registry,
    )


def register_shard_slices(
    catalog_db: Session,
    call_import_id: UUID,
    total_rows: int,
) -> None:
    """Persist slice → shard assignments on the catalog for an import."""
    if not is_sharding_enabled() or total_rows <= 0:
        return
    router, _ = router_for_import(catalog_db, call_import_id)
    assert router is not None
    chunk = router.row_chunk_size
    slice_meta: Dict[int, Dict[str, Any]] = {}
    for idx in range(total_rows):
        slice_id = idx // chunk
        if slice_id not in slice_meta:
            shard_id = router.shard_id_for_row(call_import_id, idx)
            slice_meta[slice_id] = {
                "shard_id": shard_id,
                "row_index_min": idx,
                "row_index_max": idx,
            }
        else:
            slice_meta[slice_id]["row_index_max"] = idx
    for slice_id, meta in slice_meta.items():
        catalog_db.merge(
            CallImportShardSlice(
                call_import_id=call_import_id,
                slice_id=slice_id,
                shard_id=meta["shard_id"],
                row_index_min=meta["row_index_min"],
                row_index_max=meta["row_index_max"],
            )
        )
    catalog_db.flush()


def partition_mappings_by_shard(
    catalog_db: Session,
    call_import_id: UUID,
    mappings: Iterable[dict],
) -> Dict[str, List[dict]]:
    buckets: Dict[str, List[dict]] = defaultdict(list)
    if not is_sharding_enabled():
        buckets["legacy"] = list(mappings)
        return buckets
    router, registry = router_for_import(catalog_db, call_import_id)
    assert router is not None
    for mapping in mappings:
        row_index = int(mapping["row_index"])
        shard_id = router.shard_id_for_row(
            call_import_id,
            row_index,
            slice_registry=registry,
        )
        buckets[shard_id].append(mapping)
    return buckets


def _shard_db_is_postgresql(shard_db: Session) -> bool:
    bind = shard_db.get_bind()
    return bind is not None and bind.dialect.name == "postgresql"


def _shard_write_without_catalog_fks(shard_db: Session) -> None:
    """Allow row inserts on shards when parent rows live on catalog only."""
    if not _shard_db_is_postgresql(shard_db):
        return
    shard_db.execute(text("SET session_replication_role = replica"))


def _reset_shard_write_role(shard_db: Session) -> None:
    if not _shard_db_is_postgresql(shard_db):
        return
    shard_db.execute(text("SET session_replication_role = DEFAULT"))


@contextmanager
def shard_row_write_context(shard_db: Session) -> Iterator[None]:
    """Bypass catalog-only FK parents while mutating shard row tables."""
    if not is_sharding_enabled():
        yield
        return
    _shard_write_without_catalog_fks(shard_db)
    try:
        yield
    finally:
        try:
            _reset_shard_write_role(shard_db)
        except Exception:
            pass


def flush_shard_row_session(shard_db: Session) -> None:
    with shard_row_write_context(shard_db):
        shard_db.flush()


def commit_shard_row_session(shard_db: Session) -> None:
    with shard_row_write_context(shard_db):
        shard_db.commit()


def bulk_insert_mappings_on_shards(
    catalog_db: Session,
    call_import_id: UUID,
    mappings: List[dict],
    *,
    orm_class=CallImportRow,
) -> int:
    """Insert row mappings on the correct shard sessions; catalog_db unused when legacy."""
    if not mappings:
        return 0
    if not is_sharding_enabled():
        catalog_db.bulk_insert_mappings(orm_class, mappings)
        catalog_db.flush()
        return len(mappings)

    from app.models.database import CallImportRow as RowModel

    buckets = partition_mappings_by_shard(catalog_db, call_import_id, mappings)
    inserted = 0
    for shard_id, shard_mappings in buckets.items():
        factory = db_pool_manager.shard_session_factory(shard_id)
        shard_db = factory()
        try:
            _shard_write_without_catalog_fks(shard_db)
            shard_db.bulk_insert_mappings(RowModel, shard_mappings)
            shard_db.commit()
            inserted += len(shard_mappings)
        except Exception:
            shard_db.rollback()
            raise
        finally:
            try:
                _reset_shard_write_role(shard_db)
            except Exception:
                pass
            shard_db.close()
    return inserted


def partition_eval_mappings_by_shard(
    catalog_db: Session,
    call_import_id: UUID,
    mappings: Iterable[dict],
    *,
    index_by_source_id: dict[UUID, int],
) -> Dict[str, List[dict]]:
    buckets: Dict[str, List[dict]] = defaultdict(list)
    if not is_sharding_enabled():
        buckets["legacy"] = list(mappings)
        return buckets
    router, registry = router_for_import(catalog_db, call_import_id)
    assert router is not None
    for mapping in mappings:
        source_id = mapping["call_import_row_id"]
        row_index = index_by_source_id.get(source_id)
        if row_index is None:
            raise ValueError(f"unknown call_import_row_id for sharded eval insert: {source_id}")
        shard_id = router.shard_id_for_row(
            call_import_id,
            row_index,
            slice_registry=registry,
        )
        buckets[shard_id].append(mapping)
    return buckets


def bulk_insert_evaluation_rows_on_shards(
    catalog_db: Session,
    call_import_id: UUID,
    evaluation_id: UUID,
    source_row_ids: List[UUID],
    *,
    workspace_id: UUID,
    index_by_source_id: dict[UUID, int],
) -> int:
    """Insert eval-row stubs on the same shard as each source import row."""
    from app.models.database import CallImportEvaluationRow as EvalRowModel

    if not source_row_ids:
        return 0

    def _mapping(source_row_id: UUID) -> dict:
        return {
            "id": uuid4(),
            "evaluation_id": evaluation_id,
            "call_import_row_id": source_row_id,
            "workspace_id": workspace_id,
            "status": "pending",
            "metric_scores": {},
        }

    if not is_sharding_enabled():
        mappings = [_mapping(source_row_id) for source_row_id in source_row_ids]
        catalog_db.bulk_insert_mappings(EvalRowModel, mappings)
        catalog_db.flush()
        return len(mappings)

    inserted = 0
    for start in range(0, len(source_row_ids), 500):
        chunk = source_row_ids[start : start + 500]
        mappings = [_mapping(source_row_id) for source_row_id in chunk]
        buckets = partition_eval_mappings_by_shard(
            catalog_db,
            call_import_id,
            mappings,
            index_by_source_id=index_by_source_id,
        )
        for shard_id, shard_mappings in buckets.items():
            factory = db_pool_manager.shard_session_factory(shard_id)
            shard_db = factory()
            try:
                _shard_write_without_catalog_fks(shard_db)
                shard_db.bulk_insert_mappings(EvalRowModel, shard_mappings)
                shard_db.commit()
                inserted += len(shard_mappings)
            except Exception:
                shard_db.rollback()
                raise
            finally:
                try:
                    _reset_shard_write_role(shard_db)
                except Exception:
                    pass
                shard_db.close()
    return inserted


def locate_call_import_row(
    row_id: UUID | str,
) -> Tuple[Session, Optional[Session], CallImportRow, str]:
    """
    Find a call import row. Returns (row_db, catalog_db, row, shard_id).

    When sharding is off, row_db and catalog_db are the same session.
    Caller must close session(s): if catalog_db is not row_db, close both.
    """
    from app.database import SessionLocal

    rid = row_id if isinstance(row_id, UUID) else UUID(str(row_id))
    if not is_sharding_enabled():
        db = SessionLocal()
        row = db.query(CallImportRow).filter(CallImportRow.id == rid).first()
        if row is None:
            db.close()
            raise LookupError(f"call_import_row {rid} not found")
        return db, db, row, "legacy"

    router = db_pool_manager.router
    assert router is not None
    for shard_id in router.shard_ids:
        factory = db_pool_manager.shard_session_factory(shard_id)
        shard_db = factory()
        try:
            row = shard_db.query(CallImportRow).filter(CallImportRow.id == rid).first()
            if row is not None:
                catalog_db = open_catalog_session()
                return shard_db, catalog_db, row, shard_id
        except Exception:
            shard_db.close()
            raise
        shard_db.close()
    raise LookupError(f"call_import_row {rid} not found on any shard")


def locate_call_import_evaluation_row(
    eval_row_id: UUID | str,
) -> Tuple[Session, Optional[Session], CallImportEvaluationRow, CallImportRow, str]:
    """
    Find eval + source rows. Returns
    (row_db, catalog_db, eval_row, source_row, shard_id).
    """
    from app.database import SessionLocal
    from app.models.database import CallImportEvaluationRow

    eid = eval_row_id if isinstance(eval_row_id, UUID) else UUID(str(eval_row_id))
    if not is_sharding_enabled():
        db = SessionLocal()
        row = (
            db.query(CallImportEvaluationRow, CallImportRow)
            .join(
                CallImportRow,
                CallImportRow.id == CallImportEvaluationRow.call_import_row_id,
            )
            .filter(CallImportEvaluationRow.id == eid)
            .first()
        )
        if row is None:
            db.close()
            raise LookupError(f"call_import_evaluation_row {eid} not found")
        eval_row, source_row = row
        return db, db, eval_row, source_row, "legacy"

    router = db_pool_manager.router
    assert router is not None
    for shard_id in router.shard_ids:
        factory = db_pool_manager.shard_session_factory(shard_id)
        shard_db = factory()
        try:
            row = (
                shard_db.query(CallImportEvaluationRow, CallImportRow)
                .join(
                    CallImportRow,
                    CallImportRow.id == CallImportEvaluationRow.call_import_row_id,
                )
                .filter(CallImportEvaluationRow.id == eid)
                .first()
            )
            if row is not None:
                eval_row, source_row = row
                catalog_db = open_catalog_session()
                return shard_db, catalog_db, eval_row, source_row, shard_id
        except Exception:
            shard_db.close()
            raise
        shard_db.close()
    raise LookupError(f"call_import_evaluation_row {eid} not found on any shard")


def close_row_sessions(row_db: Session, catalog_db: Optional[Session]) -> None:
    row_db.close()
    if catalog_db is not None and catalog_db is not row_db:
        catalog_db.close()


def new_row_mapping(
    *,
    call_import: CallImport,
    organization_id: UUID,
    workspace_id: UUID,
    row_index: int,
    row: dict,
    transcript_source: Optional[str],
) -> dict:
    csv_transcript = row["transcript"]
    return {
        "id": uuid4(),
        "call_import_id": call_import.id,
        "organization_id": organization_id,
        "workspace_id": workspace_id,
        "row_index": row_index,
        "conversation_id": row["conversation_id"],
        "recording_date": row.get("recording_date"),
        "recording_url": row["recording_url"],
        "transcript": csv_transcript,
        "transcript_source": transcript_source,
        "raw_columns": row.get("parameter_values") or None,
        "status": row.get("status"),
    }
