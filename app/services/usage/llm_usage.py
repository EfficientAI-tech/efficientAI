"""Redis-buffered LLM/STT usage counters with catalog rollup flush."""

from __future__ import annotations

import math
import time
import uuid
import json
from datetime import date, datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple
from uuid import UUID

import redis
from loguru import logger
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.services.usage.bucket_context import (
    build_bucket_context,
    context_bucket_token,
    legacy_resource_context,
    parse_context_bucket_token,
)
from app.services.usage.context import (
    LLMUsageContext,
    LLMUsageProductSection,
    get_usage_context,
)
from app.services.usage.normalize import UsageSnapshot

_redis: redis.Redis | None = None

_NONE = "__none__"
_PENDING_TTL_SECONDS = 14 * 24 * 60 * 60
_FLUSH_LOCK_TTL_SECONDS = 45
_FLUSH_LOCK_WAIT_SECONDS = 3.0
USAGE_KIND_LLM = "llm"
USAGE_KIND_STT = "stt"
USAGE_KIND_TTS = "tts"
_METRIC_FIELDS = (
    "prompt_tokens",
    "completion_tokens",
    "cache_read_tokens",
    "cache_creation_tokens",
    "reasoning_tokens",
    "audio_seconds",
    "tts_characters",
    "call_count",
)

_CLAIM_LUA = """
if redis.call('EXISTS', KEYS[1]) == 0 then
  return 0
end
redis.call('RENAME', KEYS[1], KEYS[2])
return 1
"""


def _client() -> redis.Redis:
    global _redis
    if _redis is None:
        _redis = redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis


def _token(value: Optional[UUID]) -> str:
    return str(value) if value else _NONE


def _pending_hash_key(organization_id: UUID) -> str:
    return f"usage:pending:{organization_id}"


def _flush_lock_key(organization_id: UUID) -> str:
    return f"usage:flush:lock:{organization_id}"


def _claim_hash_key(organization_id: UUID, claim_id: str) -> str:
    return f"usage:flushing:{organization_id}:{claim_id}"


def _bucket_prefix(
    *,
    workspace_id: Optional[UUID],
    product_section: str,
    model: str,
    context: Optional[Dict[str, Any]],
    usage_date: date,
    usage_kind: str,
) -> str:
    return "|".join(
        [
            _token(workspace_id),
            product_section,
            model,
            context_bucket_token(context),
            usage_date.isoformat(),
            usage_kind or USAGE_KIND_LLM,
        ]
    )


def _parse_bucket_prefix(prefix: str) -> Optional[Dict[str, Any]]:
    parts = prefix.split("|")
    # New: 6 parts with JSON context token + usage_kind.
    if len(parts) == 6:
        ws_token, section, model, context_token, day_str, usage_kind = parts
        context = parse_context_bucket_token(context_token)
    elif len(parts) == 7:
        # Legacy Redis keys: resource_id + resource_type before date/kind.
        (
            ws_token,
            section,
            model,
            resource_token,
            resource_type,
            day_str,
            usage_kind,
        ) = parts
        resource_id = None if resource_token == _NONE else UUID(resource_token)
        resolved_resource_type = None if resource_type == _NONE else resource_type
        context = legacy_resource_context(resource_id, resolved_resource_type)
    elif len(parts) == 5:
        ws_token, section, model, context_token, day_str = parts
        usage_kind = USAGE_KIND_LLM
        context = parse_context_bucket_token(context_token)
    else:
        return None
    try:
        usage_date = date.fromisoformat(day_str)
    except ValueError:
        return None
    workspace_id = None if ws_token == _NONE else UUID(ws_token)
    return {
        "workspace_id": workspace_id,
        "product_section": section,
        "model": model,
        "context": context,
        "usage_date": usage_date,
        "usage_kind": usage_kind or USAGE_KIND_LLM,
    }


def _bucket_from_context(
    context: LLMUsageContext,
    *,
    model: str,
    usage_date: date,
    usage_kind: str,
) -> Dict[str, Any]:
    return {
        "workspace_id": context.workspace_id,
        "product_section": context.product_section.value,
        "model": model,
        "context": build_bucket_context(
            resource_id=context.resource_id,
            resource_type=context.resource_type,
            extra=context.extra,
        ),
        "usage_date": usage_date,
        "usage_kind": usage_kind,
    }


def _resolve_context(
    *,
    organization_id: Optional[UUID] = None,
    ctx: Optional[LLMUsageContext] = None,
) -> Optional[LLMUsageContext]:
    if ctx is not None:
        return ctx
    current = get_usage_context()
    if current is not None:
        return current
    if organization_id is not None:
        from app.services.usage.context import (
            get_usage_section_hint,
            get_usage_workspace_hint,
        )

        return LLMUsageContext(
            organization_id=organization_id,
            workspace_id=get_usage_workspace_hint(),
            product_section=get_usage_section_hint(),
        )
    return None


def _deltas_from_usage(usage: UsageSnapshot) -> Dict[str, int]:
    return {
        "prompt_tokens": usage.prompt_tokens,
        "completion_tokens": usage.completion_tokens,
        "cache_read_tokens": usage.cache_read_tokens,
        "cache_creation_tokens": usage.cache_creation_tokens,
        "reasoning_tokens": usage.reasoning_tokens,
        "audio_seconds": 0,
        "tts_characters": 0,
        "call_count": 1,
    }


def _deltas_from_stt(audio_seconds: int, *, count_call: bool = True) -> Dict[str, int]:
    return {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "cache_read_tokens": 0,
        "cache_creation_tokens": 0,
        "reasoning_tokens": 0,
        "audio_seconds": max(0, int(audio_seconds)),
        "tts_characters": 0,
        "call_count": 1 if count_call else 0,
    }


def _deltas_from_tts(characters: int) -> Dict[str, int]:
    return {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "cache_read_tokens": 0,
        "cache_creation_tokens": 0,
        "reasoning_tokens": 0,
        "audio_seconds": 0,
        "tts_characters": max(0, int(characters)),
        "call_count": 1,
    }


def _buffer_to_postgres(
    organization_id: UUID,
    bucket: Dict[str, Any],
    deltas: Dict[str, int],
) -> None:
    """Durable fallback when Redis is unavailable."""
    try:
        from app.database import SessionLocal
    except Exception as exc:
        logger.warning("usage postgres fallback unavailable: {}", exc)
        return

    params = {
        "organization_id": str(organization_id),
        "workspace_id": str(bucket["workspace_id"]) if bucket.get("workspace_id") else None,
        "product_section": bucket["product_section"],
        "model": bucket["model"],
        "context": json.dumps(bucket.get("context") or {}),
        "usage_date": bucket["usage_date"].isoformat(),
        "usage_kind": bucket.get("usage_kind") or USAGE_KIND_LLM,
        "prompt_tokens": int(deltas.get("prompt_tokens", 0)),
        "completion_tokens": int(deltas.get("completion_tokens", 0)),
        "cache_read_tokens": int(deltas.get("cache_read_tokens", 0)),
        "cache_creation_tokens": int(deltas.get("cache_creation_tokens", 0)),
        "reasoning_tokens": int(deltas.get("reasoning_tokens", 0)),
        "audio_seconds": int(deltas.get("audio_seconds", 0)),
        "tts_characters": int(deltas.get("tts_characters", 0)),
        "call_count": int(deltas.get("call_count", 0)),
    }
    db = SessionLocal()
    try:
        db.execute(
            text(
                """
                INSERT INTO usage_pending_buffer (
                    id, organization_id, workspace_id, product_section, model,
                    context, usage_date, usage_kind,
                    prompt_tokens, completion_tokens, cache_read_tokens,
                    cache_creation_tokens, reasoning_tokens, audio_seconds,
                    tts_characters, call_count, created_at
                ) VALUES (
                    gen_random_uuid(), CAST(:organization_id AS uuid),
                    CAST(:workspace_id AS uuid), :product_section, :model,
                    CAST(:context AS jsonb),
                    CAST(:usage_date AS date), :usage_kind,
                    :prompt_tokens, :completion_tokens, :cache_read_tokens,
                    :cache_creation_tokens, :reasoning_tokens, :audio_seconds,
                    :tts_characters, :call_count, now()
                )
                """
            ),
            params,
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.warning("usage postgres fallback insert failed: {}", exc)
    finally:
        db.close()


def _incr_pending(
    organization_id: UUID,
    prefix: str,
    deltas: Dict[str, int],
    bucket: Dict[str, Any],
) -> None:
    hash_key = _pending_hash_key(organization_id)
    try:
        client = _client()
        pipe = client.pipeline()
        for metric, delta in deltas.items():
            if delta:
                pipe.hincrby(hash_key, f"{prefix}|{metric}", int(delta))
        pipe.sadd("usage:pending:orgs", str(organization_id))
        pipe.expire(hash_key, _PENDING_TTL_SECONDS)
        pipe.execute()
    except redis.RedisError as exc:
        logger.warning("usage redis counter failed, buffering to postgres: {}", exc)
        _buffer_to_postgres(organization_id, bucket, deltas)


def _context_for_record(
    *,
    organization_id: Optional[UUID] = None,
    ctx: Optional[LLMUsageContext] = None,
) -> Optional[LLMUsageContext]:
    context = _resolve_context(organization_id=organization_id, ctx=ctx)
    if context is None:
        return None
    from app.services.usage.call_import_context import enrich_usage_context_workspace

    return enrich_usage_context_workspace(context)


def record_llm_usage(
    model: str,
    usage: UsageSnapshot,
    *,
    organization_id: Optional[UUID] = None,
    ctx: Optional[LLMUsageContext] = None,
    usage_date: Optional[date] = None,
) -> None:
    """Increment counters for one LLM call (best-effort, never raises)."""
    if not model:
        model = "unknown"
    context = _context_for_record(organization_id=organization_id, ctx=ctx)
    if context is None:
        logger.warning("llm usage record skipped: missing organization_id")
        return

    deltas = _deltas_from_usage(usage)
    if not any(deltas.values()):
        return

    day = usage_date or datetime.now(timezone.utc).date()
    bucket = _bucket_from_context(
        context,
        model=model,
        usage_date=day,
        usage_kind=USAGE_KIND_LLM,
    )
    prefix = _bucket_prefix(**bucket)
    _incr_pending(context.organization_id, prefix, deltas, bucket)


def record_stt_usage(
    model: str,
    *,
    audio_seconds: float | int = 0,
    organization_id: Optional[UUID] = None,
    ctx: Optional[LLMUsageContext] = None,
    usage_date: Optional[date] = None,
    count_call: bool = True,
) -> None:
    """Increment counters for one STT call (audio seconds + optional call_count)."""
    if not model:
        model = "unknown"
    context = _context_for_record(organization_id=organization_id, ctx=ctx)
    if context is None:
        logger.warning("stt usage record skipped: missing organization_id")
        return

    seconds = int(max(0, math.ceil(float(audio_seconds or 0))))
    deltas = _deltas_from_stt(seconds, count_call=count_call)
    day = usage_date or datetime.now(timezone.utc).date()
    bucket = _bucket_from_context(
        context,
        model=model,
        usage_date=day,
        usage_kind=USAGE_KIND_STT,
    )
    prefix = _bucket_prefix(**bucket)
    _incr_pending(context.organization_id, prefix, deltas, bucket)


def record_call_usage(
    model: str = "voice-call",
    *,
    organization_id: Optional[UUID] = None,
    ctx: Optional[LLMUsageContext] = None,
    usage_date: Optional[date] = None,
    audio_seconds: int = 0,
) -> None:
    """Record one completed call session (call_count + optional duration).

    Best-effort, never raises. Uses the same Redis-buffered path as other
    usage counters (one pipelined HINCRBY batch per call).
    """
    if not model:
        model = "voice-call"
    context = _context_for_record(organization_id=organization_id, ctx=ctx)
    if context is None:
        logger.warning("call usage record skipped: missing organization_id")
        return

    seconds = max(0, int(audio_seconds or 0))
    deltas = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "cache_read_tokens": 0,
        "cache_creation_tokens": 0,
        "reasoning_tokens": 0,
        "audio_seconds": seconds,
        "tts_characters": 0,
        "call_count": 1,
    }
    day = usage_date or datetime.now(timezone.utc).date()
    bucket = _bucket_from_context(
        context,
        model=model,
        usage_date=day,
        usage_kind=USAGE_KIND_LLM,
    )
    prefix = _bucket_prefix(**bucket)
    _incr_pending(context.organization_id, prefix, deltas, bucket)


def record_tts_usage(
    model: str,
    *,
    characters: int = 0,
    organization_id: Optional[UUID] = None,
    ctx: Optional[LLMUsageContext] = None,
    usage_date: Optional[date] = None,
) -> None:
    """Increment counters for one TTS call (characters + call_count)."""
    if not model:
        model = "unknown"
    context = _context_for_record(organization_id=organization_id, ctx=ctx)
    if context is None:
        logger.warning("tts usage record skipped: missing organization_id")
        return

    chars = max(0, int(characters or 0))
    deltas = _deltas_from_tts(chars)
    day = usage_date or datetime.now(timezone.utc).date()
    bucket = _bucket_from_context(
        context,
        model=model,
        usage_date=day,
        usage_kind=USAGE_KIND_TTS,
    )
    prefix = _bucket_prefix(**bucket)
    _incr_pending(context.organization_id, prefix, deltas, bucket)


def probe_audio_seconds(audio_file_path: str) -> int:
    """Best-effort audio duration in whole seconds."""
    if not audio_file_path:
        return 0
    try:
        from pydub import AudioSegment

        return max(0, int(math.ceil(AudioSegment.from_file(audio_file_path).duration_seconds)))
    except Exception:
        pass
    try:
        import librosa

        return max(0, int(math.ceil(librosa.get_duration(path=audio_file_path))))
    except Exception:
        return 0


def _parse_hash_to_buckets(raw: Dict[str, str]) -> Dict[str, Dict[str, int]]:
    buckets: Dict[str, Dict[str, int]] = {}
    for field, value in raw.items():
        if "|" not in field:
            continue
        prefix, metric = field.rsplit("|", 1)
        if metric not in _METRIC_FIELDS:
            continue
        amount = int(value or 0)
        if not amount:
            continue
        bucket = buckets.setdefault(prefix, {})
        bucket[metric] = bucket.get(metric, 0) + amount
    return buckets


def _read_hash_buckets(hash_key: str) -> Dict[str, Dict[str, int]]:
    try:
        client = _client()
        raw = client.hgetall(hash_key)
    except redis.RedisError as exc:
        logger.warning("llm usage read hash failed: {}", exc)
        return {}
    return _parse_hash_to_buckets(raw)


def _restore_buckets_to_pending(
    organization_id: UUID, buckets: Dict[str, Dict[str, int]]
) -> None:
    try:
        client = _client()
        pipe = client.pipeline()
        hash_key = _pending_hash_key(organization_id)
        for prefix, metrics in buckets.items():
            for metric, amount in metrics.items():
                if amount:
                    pipe.hincrby(hash_key, f"{prefix}|{metric}", amount)
        pipe.sadd("usage:pending:orgs", str(organization_id))
        pipe.expire(hash_key, _PENDING_TTL_SECONDS)
        pipe.execute()
    except redis.RedisError as exc:
        logger.warning("llm usage redis restore failed, buffering: {}", exc)
        for prefix, metrics in buckets.items():
            parsed = _parse_bucket_prefix(prefix)
            if parsed:
                _buffer_to_postgres(organization_id, parsed, metrics)


_CLAIM_COMMITTED_TTL_SECONDS = 24 * 60 * 60
_CLAIM_COMMITTED_REDIS_RETRIES = 5


def _claim_committed_key(claim_key: str) -> str:
    return f"usage:claim_done:{claim_key}"


def _record_claim_committed_pg(
    db: Session, claim_key: str, organization_id: UUID
) -> None:
    try:
        db.execute(
            text(
                """
                INSERT INTO usage_committed_claims (claim_key, organization_id)
                VALUES (:claim_key, CAST(:organization_id AS uuid))
                ON CONFLICT (claim_key) DO NOTHING
                """
            ),
            {
                "claim_key": claim_key,
                "organization_id": str(organization_id),
            },
        )
    except Exception as exc:
        logger.debug("usage committed claim pg write skipped: {}", exc)


def _is_claim_committed_pg(claim_key: str) -> bool:
    try:
        from app.database import SessionLocal

        db = SessionLocal()
        try:
            return (
                db.execute(
                    text(
                        """
                        SELECT 1 FROM usage_committed_claims
                        WHERE claim_key = :claim_key
                        """
                    ),
                    {"claim_key": claim_key},
                ).first()
                is not None
            )
        finally:
            db.close()
    except Exception:
        return False


def _mark_claim_committed(claim_key: str) -> bool:
    for attempt in range(_CLAIM_COMMITTED_REDIS_RETRIES):
        try:
            _client().set(
                _claim_committed_key(claim_key),
                "1",
                ex=_CLAIM_COMMITTED_TTL_SECONDS,
            )
            return True
        except redis.RedisError:
            if attempt + 1 < _CLAIM_COMMITTED_REDIS_RETRIES:
                time.sleep(0.05 * (attempt + 1))
    return False


def _is_claim_committed(claim_key: str) -> bool:
    try:
        if _client().exists(_claim_committed_key(claim_key)):
            return True
    except redis.RedisError:
        pass
    return _is_claim_committed_pg(claim_key)


def _finalize_committed_claim(
    db: Session, claim_key: str, organization_id: UUID
) -> None:
    _record_claim_committed_pg(db, claim_key, organization_id)
    _mark_claim_committed(claim_key)
    _ack_claim(claim_key, organization_id)


def _has_pending_usage(organization_id: UUID) -> bool:
    try:
        client = _client()
        if client.exists(_pending_hash_key(organization_id)):
            return True
        return bool(client.sismember("usage:pending:orgs", str(organization_id)))
    except redis.RedisError:
        return False


def _acquire_flush_lock(organization_id: UUID) -> bool:
    try:
        client = _client()
        lock_key = _flush_lock_key(organization_id)
        if client.set(lock_key, "1", nx=True, ex=_FLUSH_LOCK_TTL_SECONDS):
            return True
        deadline = time.monotonic() + _FLUSH_LOCK_WAIT_SECONDS
        while time.monotonic() < deadline:
            time.sleep(0.05)
            if client.set(lock_key, "1", nx=True, ex=_FLUSH_LOCK_TTL_SECONDS):
                return True
            if client.get(lock_key) is None:
                continue
        return False
    except redis.RedisError as exc:
        logger.warning("llm usage flush lock failed: {}", exc)
        return False


def _release_flush_lock(organization_id: UUID) -> None:
    try:
        _client().delete(_flush_lock_key(organization_id))
    except redis.RedisError:
        pass


def _claim_pending(
    organization_id: UUID,
) -> Tuple[Optional[str], Dict[str, Dict[str, int]]]:
    claim_id = str(uuid.uuid4())
    pending_key = _pending_hash_key(organization_id)
    claim_key = _claim_hash_key(organization_id, claim_id)
    try:
        client = _client()
        claimed = int(client.eval(_CLAIM_LUA, 2, pending_key, claim_key) or 0)
        if not claimed:
            return None, {}
        buckets = _read_hash_buckets(claim_key)
        if not buckets:
            client.delete(claim_key)
            return None, {}
        return claim_key, buckets
    except redis.RedisError as exc:
        logger.warning("llm usage claim failed: {}", exc)
        return None, {}


def _ack_claim(claim_key: str, organization_id: UUID) -> None:
    try:
        client = _client()
        client.delete(claim_key)
        pending_key = _pending_hash_key(organization_id)
        if not client.exists(pending_key):
            client.srem("usage:pending:orgs", str(organization_id))
    except redis.RedisError:
        pass


def _upsert_bucket(
    db: Session,
    organization_id: UUID,
    bucket: Dict[str, Any],
    deltas: Dict[str, int],
) -> None:
    context = bucket.get("context") or {}
    params = {
        "organization_id": str(organization_id),
        "workspace_id": str(bucket["workspace_id"]) if bucket["workspace_id"] else None,
        "product_section": bucket["product_section"],
        "model": bucket["model"],
        "context": json.dumps(context),
        "context_resource_id": str(context.get("resource_id") or ""),
        "context_resource_type": str(context.get("resource_type") or ""),
        "usage_date": bucket["usage_date"].isoformat(),
        "usage_kind": bucket.get("usage_kind") or USAGE_KIND_LLM,
        "prompt_tokens": int(deltas.get("prompt_tokens", 0)),
        "completion_tokens": int(deltas.get("completion_tokens", 0)),
        "cache_read_tokens": int(deltas.get("cache_read_tokens", 0)),
        "cache_creation_tokens": int(deltas.get("cache_creation_tokens", 0)),
        "reasoning_tokens": int(deltas.get("reasoning_tokens", 0)),
        "audio_seconds": int(deltas.get("audio_seconds", 0)),
        "tts_characters": int(deltas.get("tts_characters", 0)),
        "call_count": int(deltas.get("call_count", 0)),
    }
    update_set = """
                prompt_tokens = prompt_tokens + :prompt_tokens,
                completion_tokens = completion_tokens + :completion_tokens,
                cache_read_tokens = cache_read_tokens + :cache_read_tokens,
                cache_creation_tokens = cache_creation_tokens + :cache_creation_tokens,
                reasoning_tokens = reasoning_tokens + :reasoning_tokens,
                audio_seconds = audio_seconds + :audio_seconds,
                tts_characters = tts_characters + :tts_characters,
                call_count = call_count + :call_count,
                context = CASE
                    WHEN context = '{}'::jsonb THEN CAST(:context AS jsonb)
                    ELSE context || CAST(:context AS jsonb)
                END,
                updated_at = now()
    """
    where_base = """
            WHERE organization_id = CAST(:organization_id AS uuid)
              AND product_section = :product_section
              AND model = :model
              AND usage_date = CAST(:usage_date AS date)
              AND usage_kind = :usage_kind
              AND workspace_id IS NOT DISTINCT FROM CAST(:workspace_id AS uuid)
    """
    exact_context_where = where_base + " AND context = CAST(:context AS jsonb)"
    legacy_context_where = (
        where_base
        + """
              AND COALESCE(context->>'resource_id', '') = :context_resource_id
              AND COALESCE(context->>'resource_type', '') = :context_resource_type
    """
    )

    result = db.execute(
        text(f"UPDATE llm_usage_daily SET {update_set} {exact_context_where}"),
        params,
    )
    if result.rowcount:
        return

    result = db.execute(
        text(f"UPDATE llm_usage_daily SET {update_set} {legacy_context_where}"),
        params,
    )
    if result.rowcount:
        return

    db.execute(text("SAVEPOINT llm_usage_bucket_insert"))
    try:
        db.execute(
            text(
                """
            INSERT INTO llm_usage_daily (
                id, organization_id, workspace_id, product_section, model,
                context, usage_date, usage_kind,
                prompt_tokens, completion_tokens, cache_read_tokens,
                cache_creation_tokens, reasoning_tokens, audio_seconds,
                tts_characters, call_count,
                created_at, updated_at
            ) VALUES (
                gen_random_uuid(), CAST(:organization_id AS uuid),
                CAST(:workspace_id AS uuid), :product_section, :model,
                CAST(:context AS jsonb), CAST(:usage_date AS date),
                :usage_kind,
                :prompt_tokens, :completion_tokens, :cache_read_tokens,
                :cache_creation_tokens, :reasoning_tokens, :audio_seconds,
                :tts_characters, :call_count,
                now(), now()
            )
            """
            ),
            params,
        )
        db.execute(text("RELEASE SAVEPOINT llm_usage_bucket_insert"))
    except IntegrityError as exc:
        if not _is_unique_violation(exc):
            db.execute(text("ROLLBACK TO SAVEPOINT llm_usage_bucket_insert"))
            db.execute(text("RELEASE SAVEPOINT llm_usage_bucket_insert"))
            raise
        db.execute(text("ROLLBACK TO SAVEPOINT llm_usage_bucket_insert"))
        result = db.execute(
            text(f"UPDATE llm_usage_daily SET {update_set} {legacy_context_where}"),
            params,
        )
        if not result.rowcount:
            result = db.execute(
                text(f"UPDATE llm_usage_daily SET {update_set} {exact_context_where}"),
                params,
            )
        db.execute(text("RELEASE SAVEPOINT llm_usage_bucket_insert"))
        if not result.rowcount:
            logger.warning(
                "llm usage upsert unique conflict but no matching bucket for org {}",
                organization_id,
            )


def _is_unique_violation(exc: BaseException) -> bool:
    text_blob = " ".join(
        str(part)
        for part in (
            exc,
            getattr(exc, "orig", None),
            getattr(getattr(exc, "orig", None), "pgcode", None),
        )
        if part is not None
    ).lower()
    return "uniqueviolation" in text_blob or "duplicate key" in text_blob


def _is_missing_organization_fk(exc: BaseException) -> bool:
    text_blob = " ".join(
        str(part)
        for part in (exc, getattr(exc, "orig", None), getattr(exc, "args", None))
        if part is not None
    ).lower()
    return "llm_usage_daily_organization_id_fkey" in text_blob


def _flush_pending_buffer(db: Session, organization_id: UUID) -> int:
    """Drain Postgres write-ahead rows into llm_usage_daily."""
    try:
        rows = db.execute(
            text(
                """
                SELECT id, workspace_id, product_section, model, context,
                       usage_date, usage_kind,
                       prompt_tokens, completion_tokens, cache_read_tokens,
                       cache_creation_tokens, reasoning_tokens, audio_seconds,
                       tts_characters, call_count
                FROM usage_pending_buffer
                WHERE organization_id = CAST(:organization_id AS uuid)
                ORDER BY created_at ASC
                LIMIT 2000
                """
            ),
            {"organization_id": str(organization_id)},
        ).mappings().all()
    except Exception as exc:
        db.rollback()
        logger.debug("usage buffer read skipped: {}", exc)
        return 0
    if not rows:
        return 0

    flushed = 0
    ids: List[str] = []
    try:
        for row in rows:
            row_context = row["context"] or {}
            if isinstance(row_context, str):
                row_context = json.loads(row_context)
            bucket = {
                "workspace_id": row["workspace_id"],
                "product_section": row["product_section"],
                "model": row["model"],
                "context": row_context,
                "usage_date": row["usage_date"],
                "usage_kind": row["usage_kind"] or USAGE_KIND_LLM,
            }
            deltas = {
                "prompt_tokens": int(row["prompt_tokens"] or 0),
                "completion_tokens": int(row["completion_tokens"] or 0),
                "cache_read_tokens": int(row["cache_read_tokens"] or 0),
                "cache_creation_tokens": int(row["cache_creation_tokens"] or 0),
                "reasoning_tokens": int(row["reasoning_tokens"] or 0),
                "audio_seconds": int(row["audio_seconds"] or 0),
                "tts_characters": int(row.get("tts_characters") or 0),
                "call_count": int(row["call_count"] or 0),
            }
            _upsert_bucket(
                db,
                organization_id,
                bucket,
                deltas,
            )
            ids.append(str(row["id"]))
            flushed += 1
        if ids:
            from sqlalchemy import bindparam

            db.execute(
                text(
                    "DELETE FROM usage_pending_buffer WHERE id IN :ids"
                ).bindparams(bindparam("ids", expanding=True)),
                {"ids": ids},
            )
        db.commit()
        return flushed
    except Exception as exc:
        db.rollback()
        if _is_missing_organization_fk(exc):
            logger.warning(
                "usage buffer dropped for unknown organization {}: {}",
                organization_id,
                exc,
            )
            if ids:
                try:
                    db.execute(
                        text(
                            """
                            DELETE FROM usage_pending_buffer
                            WHERE organization_id = CAST(:organization_id AS uuid)
                            """
                        ),
                        {"organization_id": str(organization_id)},
                    )
                    db.commit()
                except Exception:
                    db.rollback()
            return 0
        logger.warning("usage buffer flush failed: {}", exc)
        return 0


_CATALOG_FLUSH_COOLDOWN_SEC = 20


def _catalog_flush_recently(organization_id: UUID) -> bool:
    """Skip flush if another request flushed this org within the cooldown window."""
    try:
        client = _client()
        key = f"usage:catalog_flush:{organization_id}"
        return not client.set(key, "1", nx=True, ex=_CATALOG_FLUSH_COOLDOWN_SEC)
    except redis.RedisError:
        return False


def flush_usage_to_catalog(db: Session, organization_id: UUID, *, force: bool = False) -> int:
    """Claim Redis deltas + drain PG buffer into llm_usage_daily."""
    _recover_orphaned_claims()
    skip_redis_flush = not force and _catalog_flush_recently(organization_id)
    if skip_redis_flush and _has_pending_usage(organization_id):
        skip_redis_flush = False
    flushed = 0
    if not skip_redis_flush:
        redis_locked = _acquire_flush_lock(organization_id)
        claim_key = None
        buckets: Dict[str, Dict[str, int]] = {}
        try:
            if redis_locked:
                claim_key, buckets = _claim_pending(organization_id)
                if claim_key and buckets:
                    skipped: Dict[str, Dict[str, int]] = {}
                    try:
                        for prefix, deltas in buckets.items():
                            parsed = _parse_bucket_prefix(prefix)
                            if not parsed:
                                skipped[prefix] = deltas
                                logger.warning(
                                    "llm usage skipped unparseable bucket prefix for org {}",
                                    organization_id,
                                )
                                continue
                            _upsert_bucket(
                                db,
                                organization_id,
                                parsed,
                                deltas,
                            )
                            flushed += 1
                        if claim_key:
                            _record_claim_committed_pg(db, claim_key, organization_id)
                        db.commit()
                    except Exception as exc:
                        db.rollback()
                        if _is_missing_organization_fk(exc):
                            logger.warning(
                                "llm usage flush dropped for unknown organization {}: {}",
                                organization_id,
                                exc,
                            )
                            if claim_key:
                                _finalize_committed_claim(
                                    db, claim_key, organization_id
                                )
                                db.commit()
                            claim_key = None
                            buckets = {}
                        else:
                            logger.warning(
                                "llm usage catalog flush failed, restoring redis: {}", exc
                            )
                            restore_buckets = dict(buckets)
                            if skipped:
                                restore_buckets.update(skipped)
                            _restore_buckets_to_pending(organization_id, restore_buckets)
                            if claim_key:
                                try:
                                    _client().delete(claim_key)
                                except redis.RedisError:
                                    pass
                            claim_key = None
                            return flushed + _flush_pending_buffer(db, organization_id)
                    if skipped:
                        _restore_buckets_to_pending(organization_id, skipped)
                    if claim_key:
                        _mark_claim_committed(claim_key)
                        _ack_claim(claim_key, organization_id)
                        claim_key = None
        finally:
            if redis_locked:
                _release_flush_lock(organization_id)

    flushed += _flush_pending_buffer(db, organization_id)
    return flushed


def _recover_orphaned_claims() -> None:
    try:
        client = _client()
        for claim_key in client.scan_iter(match="usage:flushing:*", count=100):
            parts = claim_key.split(":")
            if len(parts) < 4:
                continue
            try:
                org_id = UUID(parts[2])
            except ValueError:
                continue
            if client.exists(_flush_lock_key(org_id)):
                continue
            if _is_claim_committed(claim_key):
                client.delete(claim_key)
                continue
            buckets = _read_hash_buckets(claim_key)
            if buckets:
                _restore_buckets_to_pending(org_id, buckets)
            client.delete(claim_key)
    except redis.RedisError as exc:
        logger.warning("llm usage orphan claim recovery failed: {}", exc)


def list_pending_organization_ids() -> List[UUID]:
    result: List[UUID] = []
    seen: set[UUID] = set()
    try:
        client = _client()
        raw_ids = client.smembers("usage:pending:orgs")
        stale: List[str] = []
        for value in raw_ids:
            try:
                org_id = UUID(value)
            except ValueError:
                stale.append(value)
                continue
            if client.exists(_pending_hash_key(org_id)):
                result.append(org_id)
                seen.add(org_id)
            else:
                stale.append(value)
        if stale:
            client.srem("usage:pending:orgs", *stale)
    except (redis.RedisError, ValueError):
        pass

    try:
        from app.database import SessionLocal

        db = SessionLocal()
        try:
            rows = db.execute(
                text(
                    """
                    SELECT DISTINCT organization_id
                    FROM usage_pending_buffer
                    LIMIT 5000
                    """
                )
            ).all()
            for row in rows:
                org_id = row[0] if not isinstance(row, dict) else row["organization_id"]
                if isinstance(org_id, str):
                    org_id = UUID(org_id)
                if org_id not in seen:
                    result.append(org_id)
                    seen.add(org_id)
        finally:
            db.close()
    except Exception as exc:
        logger.debug("usage buffer org scan skipped: {}", exc)

    return result


def flush_all_usage_to_catalog(db_factory) -> int:
    _recover_orphaned_claims()
    total = 0
    for org_id in list_pending_organization_ids():
        db = db_factory()
        try:
            total += flush_usage_to_catalog(db, org_id)
        except Exception as exc:
            db.rollback()
            logger.warning("flush_all usage failed for {}: {}", org_id, exc)
        finally:
            db.close()
    return total


def merge_usage_totals(
    rows: Iterable[Any],
) -> Dict[str, int]:
    totals = {field: 0 for field in _METRIC_FIELDS}
    for row in rows:
        totals["prompt_tokens"] += int(getattr(row, "prompt_tokens", 0) or 0)
        totals["completion_tokens"] += int(getattr(row, "completion_tokens", 0) or 0)
        totals["cache_read_tokens"] += int(getattr(row, "cache_read_tokens", 0) or 0)
        totals["cache_creation_tokens"] += int(
            getattr(row, "cache_creation_tokens", 0) or 0
        )
        totals["reasoning_tokens"] += int(getattr(row, "reasoning_tokens", 0) or 0)
        totals["audio_seconds"] += int(getattr(row, "audio_seconds", 0) or 0)
        totals["tts_characters"] += int(getattr(row, "tts_characters", 0) or 0)
        totals["call_count"] += int(getattr(row, "call_count", 0) or 0)
    totals["total_tokens"] = totals["prompt_tokens"] + totals["completion_tokens"]
    return totals
