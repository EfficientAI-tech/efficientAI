"""Deferred Flexprice metering for call-import evaluation workers.

Recording minutes are summed in Redis and sent as about 50 events per
evaluation, not one event per row. Each event's ``quantity`` is the sum of
per-row billable minutes, so the meter total matches per-row billing.

A full batch is copied to a sealed Redis key in the same script that clears
the counters. The sealed payload is deleted only after it is on the Flexprice
queue, so a crash between those steps retries the same batch.
"""

from __future__ import annotations

from uuid import UUID

import redis
from loguru import logger
from sqlalchemy.orm import Session

from app.config import settings
from app.models.database import (
    CallImportEvaluation,
    CallImportEvaluationRow,
    CallImportRow,
)

# Split every evaluation into this many recording-minute events (runs smaller
# than the target still send one event per audio row).
RECORDING_MINUTES_TARGET_EVENTS = 50
_BATCH_TTL_SECONDS = 14 * 24 * 60 * 60
_ROW_BILLED_TTL_SECONDS = 90 * 24 * 60 * 60

_redis: redis.Redis | None = None

_ACCUMULATE_LUA = """
if redis.call('EXISTS', KEYS[2]) == 1 then
  return {'pending_sealed'}
end
if redis.call('SET', KEYS[3], '1', 'NX', 'EX', tonumber(ARGV[9])) == false then
  return {'duplicate'}
end
local seconds = tonumber(ARGV[1])
local minutes = tonumber(ARGV[2])
local batch_size = tonumber(ARGV[3])
local ttl = tonumber(ARGV[7])
redis.call('HSET', KEYS[1],
  'organization_id', ARGV[4],
  'workspace_id', ARGV[5],
  'call_import_id', ARGV[6],
  'total_rows', ARGV[8],
  'batch_size', ARGV[3])
redis.call('HINCRBY', KEYS[1], 'audio_seconds', seconds)
redis.call('HINCRBY', KEYS[1], 'billable_minutes', minutes)
local rows = redis.call('HINCRBY', KEYS[1], 'rows', 1)
redis.call('EXPIRE', KEYS[1], ttl)
if rows < batch_size then
  return {}
end
local audio = redis.call('HGET', KEYS[1], 'audio_seconds')
local mins = redis.call('HGET', KEYS[1], 'billable_minutes')
local counted = redis.call('HGET', KEYS[1], 'rows')
local idx = redis.call('HINCRBY', KEYS[1], 'batch_index', 1)
local org = redis.call('HGET', KEYS[1], 'organization_id')
local ws = redis.call('HGET', KEYS[1], 'workspace_id')
local imp = redis.call('HGET', KEYS[1], 'call_import_id')
local total_rows = redis.call('HGET', KEYS[1], 'total_rows') or '0'
local planned_batch = redis.call('HGET', KEYS[1], 'batch_size') or '0'
local payload = table.concat({audio, mins, counted, idx, org, ws, imp, total_rows, planned_batch}, '|')
redis.call('SET', KEYS[2], payload, 'EX', ttl)
redis.call('HSET', KEYS[1], 'audio_seconds', 0, 'billable_minutes', 0, 'rows', 0)
return {'sealed'}
"""

_FLUSH_LUA = """
if redis.call('EXISTS', KEYS[2]) == 1 then
  return {'pending_sealed'}
end
local rows = tonumber(redis.call('HGET', KEYS[1], 'rows') or '0')
if rows <= 0 then
  return {}
end
local ttl = tonumber(ARGV[1])
local audio = redis.call('HGET', KEYS[1], 'audio_seconds')
local mins = redis.call('HGET', KEYS[1], 'billable_minutes')
local counted = redis.call('HGET', KEYS[1], 'rows')
local idx = redis.call('HINCRBY', KEYS[1], 'batch_index', 1)
local org = redis.call('HGET', KEYS[1], 'organization_id')
local ws = redis.call('HGET', KEYS[1], 'workspace_id')
local imp = redis.call('HGET', KEYS[1], 'call_import_id')
local total_rows = redis.call('HGET', KEYS[1], 'total_rows') or '0'
local planned_batch = redis.call('HGET', KEYS[1], 'batch_size') or '0'
local payload = table.concat({audio, mins, counted, idx, org, ws, imp, total_rows, planned_batch}, '|')
redis.call('SET', KEYS[2], payload, 'EX', ttl)
redis.call('HSET', KEYS[1], 'audio_seconds', 0, 'billable_minutes', 0, 'rows', 0)
return {'sealed'}
"""


def recording_minutes_batch_size(
    total_rows: int,
    *,
    target_events: int = RECORDING_MINUTES_TARGET_EVENTS,
) -> int:
    """Rows of audio to fold into one Flexprice event.

    ``ceil(total_rows / target_events)`` so a run of at least ``target_events``
    rows produces about that many events (1e6 → 20k rows/event → 50 events,
    50k → 1k rows/event → 50 events). Fewer rows than the target cannot fill
    50 events, so those stay one row per event.
    """
    rows = max(0, int(total_rows or 0))
    target = max(1, int(target_events))
    if rows <= 0:
        return 1
    return max(1, (rows + target - 1) // target)


def _client() -> redis.Redis:
    global _redis
    if _redis is None:
        _redis = redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis


def _batch_key(evaluation_id: UUID) -> str:
    return f"flexprice:eval_audio_batch:{evaluation_id}"


def _sealed_key(evaluation_id: UUID) -> str:
    return f"flexprice:eval_audio_sealed:{evaluation_id}"


def _row_billed_key(eval_row_id: UUID) -> str:
    return f"flexprice:eval_audio_row:{eval_row_id}"


def _claim_row_for_billing(eval_row_id: UUID) -> bool:
    """True only the first time this evaluation row is counted."""
    try:
        claimed = _client().set(
            _row_billed_key(eval_row_id),
            "1",
            nx=True,
            ex=_ROW_BILLED_TTL_SECONDS,
        )
    except redis.RedisError:
        return False
    return bool(claimed)


def _release_row_billing_claim(eval_row_id: UUID) -> None:
    try:
        _client().delete(_row_billed_key(eval_row_id))
    except redis.RedisError:
        pass


def _fallback_row_event(
    evaluation: CallImportEvaluation,
    eval_row: CallImportEvaluationRow,
    *,
    workspace_id,
    audio_seconds: int,
    billable_minutes: int,
) -> None:
    if not _claim_row_for_billing(eval_row.id):
        return
    from app.services.billing.flexprice_service import (
        buffer_call_import_recording_minutes_billed,
    )

    accepted = buffer_call_import_recording_minutes_billed(
        evaluation.organization_id,
        eval_row.id,
        workspace_id=workspace_id,
        evaluation_id=evaluation.id,
        call_import_id=evaluation.call_import_id,
        audio_seconds=audio_seconds,
        billable_minutes=billable_minutes,
    )
    if not accepted:
        _release_row_billing_claim(eval_row.id)


def _enqueue_sealed_payload(evaluation_id: UUID, payload: str) -> bool:
    parts = str(payload).split("|")
    if len(parts) < 7:
        logger.warning(
            "Flexprice sealed batch unreadable evaluation={}",
            evaluation_id,
        )
        return True
    audio_seconds = int(parts[0] or 0)
    billable_minutes = int(parts[1] or 0)
    rows_in_batch = int(parts[2] or 0)
    batch_index = int(parts[3] or 0)
    organization_id = parts[4]
    workspace_id = parts[5]
    call_import_id = parts[6]
    total_rows = int(parts[7] or 0) if len(parts) > 7 else 0
    batch_size = int(parts[8] or 0) if len(parts) > 8 else 0
    if billable_minutes <= 0 or not organization_id or not workspace_id:
        logger.warning(
            "Flexprice sealed batch dropped evaluation={} payload={}",
            evaluation_id,
            payload[:120],
        )
        return True
    from app.services.billing.flexprice_service import (
        buffer_call_import_recording_minutes_batch,
    )

    return buffer_call_import_recording_minutes_batch(
        UUID(str(organization_id)),
        workspace_id=UUID(str(workspace_id)),
        evaluation_id=evaluation_id,
        call_import_id=UUID(str(call_import_id)) if call_import_id else evaluation_id,
        audio_seconds=audio_seconds,
        billable_minutes=billable_minutes,
        rows_in_batch=rows_in_batch,
        batch_index=batch_index,
        batch_size=batch_size,
        evaluation_total_rows=total_rows,
    )


def _publish_sealed(evaluation_id: UUID) -> bool:
    """Move a sealed batch onto the Flexprice queue, then delete the seal."""
    key = _sealed_key(evaluation_id)
    try:
        payload = _client().get(key)
    except redis.RedisError as exc:
        logger.warning(
            "Flexprice sealed batch read failed evaluation={}: {}",
            evaluation_id,
            exc,
        )
        return False
    if not payload:
        return True
    accepted = _enqueue_sealed_payload(evaluation_id, payload)
    if not accepted:
        try:
            _client().expire(key, _BATCH_TTL_SECONDS)
        except redis.RedisError:
            pass
        return False
    try:
        _client().delete(key)
    except redis.RedisError as exc:
        logger.warning(
            "Flexprice sealed batch delete failed evaluation={}: {}",
            evaluation_id,
            exc,
        )
    return True


def republish_sealed_recording_batches(*, max_keys: int = 50) -> int:
    """Queue sealed batches left behind by a crash. Safe to run on a timer."""
    published = 0
    try:
        client = _client()
        cursor = 0
        seen = 0
        while seen < max_keys:
            cursor, keys = client.scan(
                cursor=cursor,
                match="flexprice:eval_audio_sealed:*",
                count=max_keys,
            )
            for key in keys:
                if seen >= max_keys:
                    break
                seen += 1
                raw_id = str(key).rsplit(":", 1)[-1]
                try:
                    evaluation_id = UUID(raw_id)
                except ValueError:
                    continue
                if _publish_sealed(evaluation_id):
                    published += 1
            if cursor in (0, "0", b"0"):
                break
    except redis.RedisError as exc:
        logger.warning("Flexprice sealed batch scan failed: {}", exc)
    return published


def enqueue_recording_minutes_for_completed_row(
    evaluation: CallImportEvaluation,
    eval_row: CallImportEvaluationRow,
    *,
    audio_seconds: int,
    billable_minutes: int,
) -> None:
    """Add this row's minutes to the evaluation batch; emit when the batch fills."""
    if billable_minutes <= 0:
        return
    batch_size = recording_minutes_batch_size(int(evaluation.total_rows or 0))
    workspace_id = eval_row.workspace_id or evaluation.workspace_id

    def _accumulate():
        return _client().eval(
            _ACCUMULATE_LUA,
            3,
            _batch_key(evaluation.id),
            _sealed_key(evaluation.id),
            _row_billed_key(eval_row.id),
            str(max(0, int(audio_seconds or 0))),
            str(int(billable_minutes)),
            str(batch_size),
            str(evaluation.organization_id),
            str(workspace_id),
            str(evaluation.call_import_id),
            str(_BATCH_TTL_SECONDS),
            str(int(evaluation.total_rows or 0)),
            str(_ROW_BILLED_TTL_SECONDS),
        )

    if not _publish_sealed(evaluation.id):
        _fallback_row_event(
            evaluation,
            eval_row,
            workspace_id=workspace_id,
            audio_seconds=audio_seconds,
            billable_minutes=billable_minutes,
        )
        return
    try:
        raw = _accumulate()
    except redis.RedisError as exc:
        logger.warning(
            "Flexprice recording batch accumulate failed evaluation={}: {}",
            evaluation.id,
            exc,
        )
        _fallback_row_event(
            evaluation,
            eval_row,
            workspace_id=workspace_id,
            audio_seconds=audio_seconds,
            billable_minutes=billable_minutes,
        )
        return
    if not raw:
        return
    marker = str(raw[0])
    if marker == "duplicate":
        return
    if marker == "pending_sealed":
        if not _publish_sealed(evaluation.id):
            _fallback_row_event(
                evaluation,
                eval_row,
                workspace_id=workspace_id,
                audio_seconds=audio_seconds,
                billable_minutes=billable_minutes,
            )
            return
        try:
            raw = _accumulate()
        except redis.RedisError as exc:
            logger.warning(
                "Flexprice recording batch accumulate retry failed evaluation={}: {}",
                evaluation.id,
                exc,
            )
            _fallback_row_event(
                evaluation,
                eval_row,
                workspace_id=workspace_id,
                audio_seconds=audio_seconds,
                billable_minutes=billable_minutes,
            )
            return
        if not raw:
            return
        marker = str(raw[0])
        if marker == "duplicate":
            return
        if marker == "pending_sealed":
            _fallback_row_event(
                evaluation,
                eval_row,
                workspace_id=workspace_id,
                audio_seconds=audio_seconds,
                billable_minutes=billable_minutes,
            )
            return
    if marker == "sealed":
        _publish_sealed(evaluation.id)


def flush_recording_minutes_remainder(evaluation_id: UUID) -> bool:
    """Send any partial batch once the evaluation has no rows left in flight."""
    if not _publish_sealed(evaluation_id):
        return False
    try:
        raw = _client().eval(
            _FLUSH_LUA,
            2,
            _batch_key(evaluation_id),
            _sealed_key(evaluation_id),
            str(_BATCH_TTL_SECONDS),
        )
    except redis.RedisError as exc:
        logger.warning(
            "Flexprice recording batch flush failed evaluation={}: {}",
            evaluation_id,
            exc,
        )
        return False
    if not raw:
        return False
    return _publish_sealed(evaluation_id)


def maybe_enqueue_recording_minutes_for_completed_row(
    db: Session,
    evaluation: CallImportEvaluation,
    eval_row: CallImportEvaluationRow,
    *,
    source_row: CallImportRow | None = None,
    resolve_audio_seconds,
    billable_minutes_fn,
) -> None:
    if (eval_row.status or "").lower() != "completed":
        return
    if source_row is None:
        source_row = (
            db.query(CallImportRow)
            .filter(CallImportRow.id == eval_row.call_import_row_id)
            .first()
        )
    if source_row is None:
        return
    if not (source_row.recording_s3_key or "").strip():
        return

    audio_seconds = resolve_audio_seconds(db, eval_row, source_row)
    minutes = billable_minutes_fn(audio_seconds)
    enqueue_recording_minutes_for_completed_row(
        evaluation,
        eval_row,
        audio_seconds=audio_seconds,
        billable_minutes=minutes,
    )


def buffer_call_import_evaluation_pass(
    evaluation: CallImportEvaluation,
    *,
    rows_billed: int,
    completed_total: int,
) -> bool:
    if rows_billed <= 0:
        return False
    from app.services.billing.flexprice_service import (
        buffer_call_import_evaluation_completed,
    )

    metric_count = len(evaluation.selected_metric_ids or [])
    return buffer_call_import_evaluation_completed(
        evaluation.organization_id,
        evaluation.id,
        workspace_id=evaluation.workspace_id,
        call_import_id=evaluation.call_import_id,
        rows_billed=rows_billed,
        completed_total=completed_total,
        total_rows=int(evaluation.total_rows or 0),
        metric_count=metric_count,
    )
