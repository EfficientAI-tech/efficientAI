"""Read/write live entity payloads on catalog + data shards."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.db_sharding.live_entity_router import live_entity_shard_id
from app.db_sharding.pool_manager import db_pool_manager
from app.db_sharding.row_ops import shard_row_write_context
from app.db_sharding.sessions import is_sharding_enabled
from app.models.database import (
    CallRecording,
    CallRecordingPayload,
    EvaluatorResult,
    EvaluatorResultPayload,
)


def resolve_live_shard_id(workspace_id: UUID, entity_id: UUID) -> Optional[str]:
    if not is_sharding_enabled():
        return None
    router = db_pool_manager.router
    if router is None:
        return None
    return live_entity_shard_id(workspace_id, entity_id, shard_ids=router.shard_ids)


@contextmanager
def open_payload_shard_session(shard_id: str):
    factory = db_pool_manager.shard_session_factory(shard_id)
    shard_db = factory()
    try:
        yield shard_db
    finally:
        shard_db.close()


def _evaluator_payload_dict(result: EvaluatorResult) -> Dict[str, Any]:
    return {
        "audio_s3_key": result.audio_s3_key,
        "transcription": result.transcription,
        "speaker_segments": result.speaker_segments,
        "metric_scores": result.metric_scores,
        "call_data": result.call_data,
    }


def _call_recording_payload_dict(recording: CallRecording) -> Dict[str, Any]:
    return {"call_data": recording.call_data}


def stamp_evaluator_result_shard(result: EvaluatorResult) -> None:
    if result.shard_id or not is_sharding_enabled():
        return
    shard_id = resolve_live_shard_id(result.workspace_id, result.id)
    if shard_id:
        result.shard_id = shard_id


def stamp_call_recording_shard(recording: CallRecording) -> None:
    if recording.shard_id or not is_sharding_enabled():
        return
    shard_id = resolve_live_shard_id(recording.workspace_id, recording.id)
    if shard_id:
        recording.shard_id = shard_id


def upsert_evaluator_result_payload(
    result: EvaluatorResult,
    *,
    shard_db: Optional[Session] = None,
) -> None:
    if not is_sharding_enabled() or not result.shard_id:
        return

    payload_fields = _evaluator_payload_dict(result)
    own_session = shard_db is None
    if own_session:
        with open_payload_shard_session(result.shard_id) as shard_db:
            _upsert_evaluator_payload_on_shard(shard_db, result, payload_fields)
            shard_db.commit()
    else:
        _upsert_evaluator_payload_on_shard(shard_db, result, payload_fields)


def _upsert_evaluator_payload_on_shard(
    shard_db: Session,
    result: EvaluatorResult,
    payload_fields: Dict[str, Any],
) -> None:
    with shard_row_write_context(shard_db):
        row = (
            shard_db.query(EvaluatorResultPayload)
            .filter(EvaluatorResultPayload.evaluator_result_id == result.id)
            .first()
        )
        now = datetime.now(timezone.utc)
        if row is None:
            row = EvaluatorResultPayload(
                evaluator_result_id=result.id,
                workspace_id=result.workspace_id,
                **payload_fields,
                created_at=now,
                updated_at=now,
            )
            shard_db.add(row)
        else:
            for key, value in payload_fields.items():
                setattr(row, key, value)
            row.updated_at = now
        shard_db.flush()


def upsert_call_recording_payload(
    recording: CallRecording,
    *,
    shard_db: Optional[Session] = None,
) -> None:
    if not is_sharding_enabled() or not recording.shard_id:
        return

    payload_fields = _call_recording_payload_dict(recording)
    own_session = shard_db is None
    if own_session:
        with open_payload_shard_session(recording.shard_id) as shard_db:
            _upsert_call_recording_payload_on_shard(shard_db, recording, payload_fields)
            shard_db.commit()
    else:
        _upsert_call_recording_payload_on_shard(shard_db, recording, payload_fields)


def _upsert_call_recording_payload_on_shard(
    shard_db: Session,
    recording: CallRecording,
    payload_fields: Dict[str, Any],
) -> None:
    with shard_row_write_context(shard_db):
        row = (
            shard_db.query(CallRecordingPayload)
            .filter(CallRecordingPayload.call_recording_id == recording.id)
            .first()
        )
        now = datetime.now(timezone.utc)
        if row is None:
            row = CallRecordingPayload(
                call_recording_id=recording.id,
                workspace_id=recording.workspace_id,
                **payload_fields,
                created_at=now,
                updated_at=now,
            )
            shard_db.add(row)
        else:
            for key, value in payload_fields.items():
                setattr(row, key, value)
            row.updated_at = now
        shard_db.flush()


def load_evaluator_result_payloads(
    results: Iterable[EvaluatorResult],
) -> None:
    """Merge shard payload columns onto catalog ORM rows (in place)."""
    if not is_sharding_enabled():
        return

    by_shard: Dict[str, List[EvaluatorResult]] = {}
    for result in results:
        if not result.shard_id:
            continue
        by_shard.setdefault(result.shard_id, []).append(result)

    for shard_id, shard_results in by_shard.items():
        ids = [r.id for r in shard_results]
        with open_payload_shard_session(shard_id) as shard_db:
            rows = (
                shard_db.query(EvaluatorResultPayload)
                .filter(EvaluatorResultPayload.evaluator_result_id.in_(ids))
                .all()
            )
        payload_by_id = {row.evaluator_result_id: row for row in rows}
        for result in shard_results:
            payload = payload_by_id.get(result.id)
            if payload is None:
                continue
            result.audio_s3_key = payload.audio_s3_key
            result.transcription = payload.transcription
            result.speaker_segments = payload.speaker_segments
            result.metric_scores = payload.metric_scores
            result.call_data = payload.call_data


def load_call_recording_payloads(
    recordings: Iterable[CallRecording],
) -> None:
    if not is_sharding_enabled():
        return

    by_shard: Dict[str, List[CallRecording]] = {}
    for recording in recordings:
        if not recording.shard_id:
            continue
        by_shard.setdefault(recording.shard_id, []).append(recording)

    for shard_id, shard_recordings in by_shard.items():
        ids = [r.id for r in shard_recordings]
        with open_payload_shard_session(shard_id) as shard_db:
            rows = (
                shard_db.query(CallRecordingPayload)
                .filter(CallRecordingPayload.call_recording_id.in_(ids))
                .all()
            )
        payload_by_id = {row.call_recording_id: row for row in rows}
        for recording in shard_recordings:
            payload = payload_by_id.get(recording.id)
            if payload is None:
                continue
            recording.call_data = payload.call_data
