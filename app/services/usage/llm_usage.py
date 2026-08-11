"""Redis-buffered LLM usage counters with catalog rollup flush."""

from __future__ import annotations

import time
import uuid
from datetime import date, datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple
from uuid import UUID

import redis
from loguru import logger
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.services.usage.context import (
    LLMUsageContext,
    get_usage_context,
)
from app.services.usage.normalize import UsageSnapshot

_redis: redis.Redis | None = None

_NONE = "__none__"
_PENDING_TTL_SECONDS = 14 * 24 * 60 * 60
_FLUSH_LOCK_TTL_SECONDS = 45
_FLUSH_LOCK_WAIT_SECONDS = 3.0
_METRIC_FIELDS = (
    "prompt_tokens",
    "completion_tokens",
    "cache_read_tokens",
    "cache_creation_tokens",
    "reasoning_tokens",
    "call_count",
)

# Atomically move pending hash → claim key so only one flusher owns the deltas.
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
    resource_id: Optional[UUID],
    resource_type: Optional[str],
    usage_date: date,
) -> str:
    return "|".join(
        [
            _token(workspace_id),
            product_section,
            model,
            _token(resource_id),
            resource_type or _NONE,
            usage_date.isoformat(),
        ]
    )


def _parse_bucket_prefix(prefix: str) -> Optional[Dict[str, Any]]:
    parts = prefix.split("|")
    if len(parts) != 6:
        return None
    ws_token, section, model, resource_token, resource_type, day_str = parts
    try:
        usage_date = date.fromisoformat(day_str)
    except ValueError:
        return None
    workspace_id = None if ws_token == _NONE else UUID(ws_token)
    resource_id = None if resource_token == _NONE else UUID(resource_token)
    resolved_resource_type = None if resource_type == _NONE else resource_type
    return {
        "workspace_id": workspace_id,
        "product_section": section,
        "model": model,
        "resource_id": resource_id,
        "resource_type": resolved_resource_type,
        "usage_date": usage_date,
    }


def _resolve_context(ctx: Optional[LLMUsageContext]) -> LLMUsageContext:
    if ctx is not None:
        return ctx
    current = get_usage_context()
    if current is not None:
        return current
    raise ValueError("LLM usage context is not set")


def _deltas_from_usage(usage: UsageSnapshot) -> Dict[str, int]:
    return {
        "prompt_tokens": usage.prompt_tokens,
        "completion_tokens": usage.completion_tokens,
        "cache_read_tokens": usage.cache_read_tokens,
        "cache_creation_tokens": usage.cache_creation_tokens,
        "reasoning_tokens": usage.reasoning_tokens,
        "call_count": 1,
    }


def record_llm_usage(
    model: str,
    usage: UsageSnapshot,
    *,
    ctx: Optional[LLMUsageContext] = None,
    usage_date: Optional[date] = None,
) -> None:
    """Increment Redis counters for one LLM call (best-effort, never raises)."""
    if not model:
        model = "unknown"
    try:
        context = _resolve_context(ctx)
    except ValueError:
        logger.debug("llm usage record skipped: missing context")
        return

    deltas = _deltas_from_usage(usage)
    if not any(deltas.values()):
        return

    day = usage_date or datetime.now(timezone.utc).date()
    prefix = _bucket_prefix(
        workspace_id=context.workspace_id,
        product_section=context.product_section.value,
        model=model,
        resource_id=context.resource_id,
        resource_type=context.resource_type,
        usage_date=day,
    )
    hash_key = _pending_hash_key(context.organization_id)

    try:
        client = _client()
        pipe = client.pipeline()
        for metric, delta in deltas.items():
            if delta:
                pipe.hincrby(hash_key, f"{prefix}|{metric}", int(delta))
        pipe.sadd("usage:pending:orgs", str(context.organization_id))
        pipe.expire(hash_key, _PENDING_TTL_SECONDS)
        pipe.execute()
    except redis.RedisError as exc:
        logger.warning("llm usage counter skipped: {}", exc)


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
        logger.warning("llm usage redis restore failed: {}", exc)


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
    """Rename pending → claim key. Returns (claim_key, buckets) or (None, {})."""
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
    *,
    resource_type: Optional[str],
) -> None:
    params = {
        "organization_id": str(organization_id),
        "workspace_id": str(bucket["workspace_id"]) if bucket["workspace_id"] else None,
        "product_section": bucket["product_section"],
        "model": bucket["model"],
        "resource_id": str(bucket["resource_id"]) if bucket["resource_id"] else None,
        "resource_type": resource_type,
        "usage_date": bucket["usage_date"].isoformat(),
        "prompt_tokens": int(deltas.get("prompt_tokens", 0)),
        "completion_tokens": int(deltas.get("completion_tokens", 0)),
        "cache_read_tokens": int(deltas.get("cache_read_tokens", 0)),
        "cache_creation_tokens": int(deltas.get("cache_creation_tokens", 0)),
        "reasoning_tokens": int(deltas.get("reasoning_tokens", 0)),
        "call_count": int(deltas.get("call_count", 0)),
    }
    result = db.execute(
        text(
            """
            UPDATE llm_usage_daily SET
                prompt_tokens = prompt_tokens + :prompt_tokens,
                completion_tokens = completion_tokens + :completion_tokens,
                cache_read_tokens = cache_read_tokens + :cache_read_tokens,
                cache_creation_tokens = cache_creation_tokens + :cache_creation_tokens,
                reasoning_tokens = reasoning_tokens + :reasoning_tokens,
                call_count = call_count + :call_count,
                resource_type = COALESCE(resource_type, :resource_type),
                updated_at = now()
            WHERE organization_id = CAST(:organization_id AS uuid)
              AND product_section = :product_section
              AND model = :model
              AND usage_date = CAST(:usage_date AS date)
              AND workspace_id IS NOT DISTINCT FROM CAST(:workspace_id AS uuid)
              AND resource_id IS NOT DISTINCT FROM CAST(:resource_id AS uuid)
            """
        ),
        params,
    )
    if result.rowcount:
        return

    db.execute(
        text(
            """
            INSERT INTO llm_usage_daily (
                id, organization_id, workspace_id, product_section, model,
                resource_id, resource_type, usage_date,
                prompt_tokens, completion_tokens, cache_read_tokens,
                cache_creation_tokens, reasoning_tokens, call_count,
                created_at, updated_at
            ) VALUES (
                gen_random_uuid(), CAST(:organization_id AS uuid),
                CAST(:workspace_id AS uuid), :product_section, :model,
                CAST(:resource_id AS uuid), :resource_type, CAST(:usage_date AS date),
                :prompt_tokens, :completion_tokens, :cache_read_tokens,
                :cache_creation_tokens, :reasoning_tokens, :call_count,
                now(), now()
            )
            """
        ),
        params,
    )


def _is_missing_organization_fk(exc: BaseException) -> bool:
    """True when insert failed because organization_id is not in organizations."""
    text_blob = " ".join(
        str(part)
        for part in (exc, getattr(exc, "orig", None), getattr(exc, "args", None))
        if part is not None
    ).lower()
    return "llm_usage_daily_organization_id_fkey" in text_blob


def flush_usage_to_catalog(db: Session, organization_id: UUID) -> int:
    """Claim Redis deltas, commit to llm_usage_daily, then ack the claim."""
    if not _acquire_flush_lock(organization_id):
        return 0

    claim_key = None
    buckets: Dict[str, Dict[str, int]] = {}
    try:
        claim_key, buckets = _claim_pending(organization_id)
        if not claim_key or not buckets:
            return 0

        flushed = 0
        try:
            for prefix, deltas in buckets.items():
                parsed = _parse_bucket_prefix(prefix)
                if not parsed:
                    continue
                _upsert_bucket(
                    db,
                    organization_id,
                    parsed,
                    deltas,
                    resource_type=parsed.get("resource_type"),
                )
                flushed += 1
            db.commit()
        except Exception as exc:
            db.rollback()
            if _is_missing_organization_fk(exc):
                # Stale/test org ids must not be restored — that loops forever on beat.
                logger.warning(
                    "llm usage flush dropped for unknown organization {}: {}",
                    organization_id,
                    exc,
                )
                if claim_key:
                    _ack_claim(claim_key, organization_id)
                return 0
            logger.warning("llm usage catalog flush failed, restoring redis: {}", exc)
            _restore_buckets_to_pending(organization_id, buckets)
            if claim_key:
                try:
                    _client().delete(claim_key)
                except redis.RedisError:
                    pass
            return 0

        _ack_claim(claim_key, organization_id)
        return flushed
    finally:
        _release_flush_lock(organization_id)


def _recover_orphaned_claims() -> None:
    """Re-queue claim hashes left behind by a crashed flusher."""
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
            buckets = _read_hash_buckets(claim_key)
            if buckets:
                _restore_buckets_to_pending(org_id, buckets)
            client.delete(claim_key)
    except redis.RedisError as exc:
        logger.warning("llm usage orphan claim recovery failed: {}", exc)


def list_pending_organization_ids() -> List[UUID]:
    try:
        client = _client()
        raw_ids = client.smembers("usage:pending:orgs")
        result: List[UUID] = []
        stale: List[str] = []
        for value in raw_ids:
            try:
                org_id = UUID(value)
            except ValueError:
                stale.append(value)
                continue
            if client.exists(_pending_hash_key(org_id)):
                result.append(org_id)
            else:
                stale.append(value)
        if stale:
            client.srem("usage:pending:orgs", *stale)
        return result
    except (redis.RedisError, ValueError):
        return []


def flush_all_usage_to_catalog(db_factory) -> int:
    """Flush all orgs with pending usage (Celery beat)."""
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
        totals["call_count"] += int(getattr(row, "call_count", 0) or 0)
    totals["total_tokens"] = totals["prompt_tokens"] + totals["completion_tokens"]
    return totals
