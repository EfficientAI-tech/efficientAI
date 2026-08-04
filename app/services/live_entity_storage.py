"""High-level live entity storage: stamp shard routing and dual-write payloads."""

from __future__ import annotations

from typing import Iterable

from sqlalchemy.orm import Session

from app.db_sharding.live_entity_ops import (
    load_call_recording_payloads,
    load_evaluator_result_payloads,
    stamp_call_recording_shard,
    stamp_evaluator_result_shard,
    upsert_call_recording_payload,
    upsert_evaluator_result_payload,
)
from app.db_sharding.sessions import is_sharding_enabled
from app.models.database import CallRecording, EvaluatorResult


def register_evaluator_result(db: Session, result: EvaluatorResult) -> None:
    """Stamp shard_id (if sharding on) and persist payload after catalog flush."""
    stamp_evaluator_result_shard(result)
    db.flush()
    upsert_evaluator_result_payload(result)


def sync_evaluator_result(db: Session, result: EvaluatorResult) -> None:
    """Dual-write heavy fields to catalog (caller) and shard payload table."""
    if not result.shard_id:
        stamp_evaluator_result_shard(result)
        db.flush()
    upsert_evaluator_result_payload(result)


def hydrate_evaluator_results(results: Iterable[EvaluatorResult]) -> None:
    """Load shard payloads onto catalog rows for API responses."""
    items = list(results)
    if not items:
        return
    load_evaluator_result_payloads(items)


def register_call_recording(db: Session, recording: CallRecording) -> None:
    stamp_call_recording_shard(recording)
    db.flush()
    upsert_call_recording_payload(recording)


def sync_call_recording(db: Session, recording: CallRecording) -> None:
    if not recording.shard_id:
        stamp_call_recording_shard(recording)
        db.flush()
    upsert_call_recording_payload(recording)


def hydrate_call_recordings(recordings: Iterable[CallRecording]) -> None:
    items = list(recordings)
    if not items:
        return
    load_call_recording_payloads(items)


def sharding_active() -> bool:
    return is_sharding_enabled()
