#!/usr/bin/env python3
"""Dry-run / execute rebalance of call-import row slices between shards."""

from __future__ import annotations

import argparse
import uuid

from app.database import SessionLocal
from app.db_sharding.registry import load_slice_registry_for_import
from app.db_sharding.sessions import is_sharding_enabled
from app.models.database import CallImport, CallImportShardSlice


def main() -> int:
    parser = argparse.ArgumentParser(description="Rebalance call-import shard slices")
    parser.add_argument("call_import_id", type=uuid.UUID)
    parser.add_argument("--target-shard", required=True, help="Destination shard id")
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--apply", action="store_true", help="Persist registry updates")
    args = parser.parse_args()

    if not is_sharding_enabled():
        print("Sharding is disabled; nothing to rebalance.")
        return 1

    db = SessionLocal()
    try:
        call_import = db.query(CallImport).filter(CallImport.id == args.call_import_id).first()
        if call_import is None:
            print("Call import not found.")
            return 1
        registry = load_slice_registry_for_import(db, args.call_import_id)
        slices = (
            db.query(CallImportShardSlice)
            .filter(CallImportShardSlice.call_import_id == args.call_import_id)
            .order_by(CallImportShardSlice.slice_id.asc())
            .all()
        )
        print(f"Import {args.call_import_id}: {len(slices)} slice(s), registry keys={len(registry)}")
        for sl in slices:
            print(
                f"  slice {sl.slice_id}: rows {sl.row_index_min}-{sl.row_index_max} "
                f"shard {sl.shard_id} -> {args.target_shard if args.apply else '(dry-run)'}"
            )
            if args.apply and not args.dry_run:
                sl.shard_id = args.target_shard
        if args.apply and not args.dry_run:
            db.commit()
            print("Registry updated. Run row data copy separately before resuming import.")
        else:
            print("Dry run only. Pass --apply without --dry-run to update registry.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
