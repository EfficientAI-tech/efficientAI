#!/usr/bin/env python3
"""
Copy call_import_rows (and related eval rows) from catalog DB into data shards.

Use when sharding was enabled but historical rows still live on the catalog
database (e.g. efficientai used as catalog_url after monolith dev).

Dry-run by default; pass --apply to insert on shards and register slices.
Does not delete catalog copies until you verify (delete manually if desired).
"""

from __future__ import annotations

import argparse
import uuid
from typing import List

from sqlalchemy.orm import Session

from app.config import load_config_from_file
from app.database import SessionLocal
from app.db_sharding.pool_manager import db_pool_manager
from app.db_sharding.registry import load_slice_registry_for_import
from app.db_sharding.row_ops import (
    partition_mappings_by_shard,
    register_shard_slices,
    _reset_shard_write_role,
    _shard_write_without_catalog_fks,
)
from app.db_sharding.sessions import is_sharding_enabled
from app.models.database import (
    CallImport,
    CallImportEvaluationRow,
    CallImportRow,
)


def _row_to_mapping(row: CallImportRow) -> dict:
    cols = {c.name for c in CallImportRow.__table__.columns}
    return {name: getattr(row, name) for name in cols}


def _eval_row_to_mapping(row: CallImportEvaluationRow) -> dict:
    cols = {c.name for c in CallImportEvaluationRow.__table__.columns}
    return {name: getattr(row, name) for name in cols}


def backfill_import(
    catalog_db: Session,
    call_import_id: uuid.UUID,
    *,
    apply: bool,
) -> dict:
    rows: List[CallImportRow] = (
        catalog_db.query(CallImportRow)
        .filter(CallImportRow.call_import_id == call_import_id)
        .order_by(CallImportRow.row_index.asc())
        .all()
    )
    if not rows:
        return {"import_id": str(call_import_id), "catalog_rows": 0, "copied": 0}

    mappings = [_row_to_mapping(r) for r in rows]
    buckets = partition_mappings_by_shard(catalog_db, call_import_id, mappings)

    eval_rows = (
        catalog_db.query(CallImportEvaluationRow)
        .join(CallImportRow, CallImportRow.id == CallImportEvaluationRow.call_import_row_id)
        .filter(CallImportRow.call_import_id == call_import_id)
        .all()
    )
    eval_by_shard: dict[str, list] = {}
    for er in eval_rows:
        source = next((r for r in rows if r.id == er.call_import_row_id), None)
        if source is None:
            continue
        for sid in partition_mappings_by_shard(
            catalog_db, call_import_id, [_row_to_mapping(source)]
        ):
            if sid == "legacy":
                continue
            eval_by_shard.setdefault(sid, []).append(_eval_row_to_mapping(er))
            break

    plan = {sid: len(ms) for sid, ms in buckets.items()}
    if not apply:
        return {
            "import_id": str(call_import_id),
            "catalog_rows": len(rows),
            "plan_by_shard": plan,
            "eval_rows": len(eval_rows),
            "dry_run": True,
        }

    router = db_pool_manager.router
    assert router is not None
    for shard_id, shard_mappings in buckets.items():
        if shard_id == "legacy":
            continue
        factory = db_pool_manager.shard_session_factory(shard_id)
        shard_db = factory()
        try:
            _shard_write_without_catalog_fks(shard_db)
            for m in shard_mappings:
                shard_db.merge(CallImportRow(**m))
            for em in eval_by_shard.get(shard_id, []):
                shard_db.merge(CallImportEvaluationRow(**em))
            shard_db.commit()
            _reset_shard_write_role(shard_db)
        except Exception:
            shard_db.rollback()
            try:
                _reset_shard_write_role(shard_db)
            except Exception:
                pass
            raise
        finally:
            shard_db.close()

    register_shard_slices(catalog_db, call_import_id, len(rows))
    catalog_db.commit()
    return {
        "import_id": str(call_import_id),
        "catalog_rows": len(rows),
        "plan_by_shard": plan,
        "copied": len(rows),
        "dry_run": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill catalog rows into data shards")
    parser.add_argument("--config", default="config.yml")
    parser.add_argument("--call-import-id", type=uuid.UUID, default=None)
    parser.add_argument("--all", action="store_true", help="Every import with catalog rows")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    load_config_from_file(args.config)
    if not is_sharding_enabled():
        print("Enable database.sharding in config first.")
        return 1

    db = SessionLocal()
    try:
        if args.call_import_id:
            ids = [args.call_import_id]
        elif args.all:
            ids = [
                row[0]
                for row in db.query(CallImportRow.call_import_id).distinct().all()
                if row[0] is not None
            ]
        else:
            print("Pass --call-import-id UUID or --all")
            return 1

        for cid in ids:
            if load_slice_registry_for_import(db, cid):
                print(f"Skip {cid}: shard_slices already registered")
                continue
            result = backfill_import(db, cid, apply=args.apply)
            print(result)
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
