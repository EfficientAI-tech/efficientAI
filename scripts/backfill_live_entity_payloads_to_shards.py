#!/usr/bin/env python3
"""
Copy live evaluator_results / call_recordings heavy columns to shard payload tables.

Stamps ``shard_id`` on catalog headers when missing. Dual-write keeps catalog
columns intact; this script backfills shard copies for historical rows.

Dry-run by default; pass --apply to write payloads on shards.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import load_config_from_file
from app.database import SessionLocal
from app.db_sharding.sessions import is_sharding_enabled
from app.models.database import CallRecording, EvaluatorResult
from app.services.live_entity_storage import (
    register_call_recording,
    register_evaluator_result,
    sync_call_recording,
    sync_evaluator_result,
)


def backfill_evaluator_results(db, *, batch_size: int, apply: bool) -> dict:
    query = db.query(EvaluatorResult).order_by(EvaluatorResult.created_at.asc())
    total = query.count()
    copied = 0
    offset = 0
    while offset < total:
        batch = query.offset(offset).limit(batch_size).all()
        if not batch:
            break
        for result in batch:
            if apply:
                if not result.shard_id:
                    register_evaluator_result(db, result)
                else:
                    sync_evaluator_result(db, result)
                db.commit()
            copied += 1
        offset += batch_size
    return {"evaluator_results": total, "processed": copied}


def backfill_call_recordings(db, *, batch_size: int, apply: bool) -> dict:
    query = db.query(CallRecording).order_by(CallRecording.created_at.asc())
    total = query.count()
    copied = 0
    offset = 0
    while offset < total:
        batch = query.offset(offset).limit(batch_size).all()
        if not batch:
            break
        for recording in batch:
            if apply:
                if not recording.shard_id:
                    register_call_recording(db, recording)
                else:
                    sync_call_recording(db, recording)
                db.commit()
            copied += 1
        offset += batch_size
    return {"call_recordings": total, "processed": copied}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", "-c", default="config.yml")
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--apply", action="store_true", help="Write to shards (default: dry-run)")
    args = parser.parse_args()

    load_config_from_file(args.config)
    if not is_sharding_enabled():
        print("Sharding is disabled; nothing to backfill.")
        return 0

    db = SessionLocal()
    try:
        eval_stats = backfill_evaluator_results(
            db, batch_size=args.batch_size, apply=args.apply
        )
        call_stats = backfill_call_recordings(
            db, batch_size=args.batch_size, apply=args.apply
        )
        mode = "APPLY" if args.apply else "DRY-RUN"
        print(f"[{mode}] evaluator_results: {eval_stats}")
        print(f"[{mode}] call_recordings: {call_stats}")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
