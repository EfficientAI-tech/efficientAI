"""Running discovered labels and metrics for an evaluation, kept in Redis.

Workers read this aggregate instead of scanning every completed row. The UI
list endpoints keep their own scan. Alias resolution stays with the caller.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional
from uuid import UUID

import redis

from app.config import settings

logger = logging.getLogger(__name__)

DISCOVERED_METRICS_KEY = "__discovered_metrics__"
_TTL_SECONDS = 7 * 24 * 60 * 60
_LOCK_SECONDS = 10

_redis_client: Optional[redis.Redis] = None


def _get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis_client


def _ready_key(evaluation_id: UUID) -> str:
    return f"eval:discovered:{evaluation_id}:ready"


def _metrics_key(evaluation_id: UUID) -> str:
    return f"eval:discovered:{evaluation_id}:metrics"


def _labels_key(evaluation_id: UUID, parent_metric_id: UUID | str) -> str:
    return f"eval:discovered:{evaluation_id}:labels:{parent_metric_id}"


def _parents_key(evaluation_id: UUID) -> str:
    return f"eval:discovered:{evaluation_id}:parents"


def _lock_key(evaluation_id: UUID) -> str:
    return f"eval:discovered:{evaluation_id}:lock"


class _RedisLock:
    def __init__(self, client: redis.Redis, evaluation_id: UUID) -> None:
        self._client = client
        self._key = _lock_key(evaluation_id)

    def __enter__(self) -> "_RedisLock":
        self._held = False
        for _ in range(50):
            if self._client.set(self._key, "1", nx=True, ex=_LOCK_SECONDS):
                self._held = True
                return self
            time.sleep(0.02)
        return self

    def __exit__(self, *exc: object) -> None:
        if self._held:
            self._client.delete(self._key)


def clear_discovered_running_cache(evaluation_id: UUID) -> None:
    """Drop the running aggregate when an evaluation is deleted."""
    try:
        client = _get_redis()
        parents = client.smembers(_parents_key(evaluation_id)) or set()
        keys = [
            _ready_key(evaluation_id),
            _metrics_key(evaluation_id),
            _parents_key(evaluation_id),
            _lock_key(evaluation_id),
        ]
        keys.extend(_labels_key(evaluation_id, parent_id) for parent_id in parents)
        client.delete(*keys)
    except redis.RedisError:
        logger.warning(
            "Failed to clear discovered-running cache for %s",
            evaluation_id,
            exc_info=True,
        )


def _has_discovery_payload(metric_scores: Any) -> bool:
    if not isinstance(metric_scores, dict):
        return False
    discovered_metrics = metric_scores.get(DISCOVERED_METRICS_KEY)
    if isinstance(discovered_metrics, list) and discovered_metrics:
        return True
    for key, entry in metric_scores.items():
        if key == DISCOVERED_METRICS_KEY or not isinstance(entry, dict):
            continue
        labels = entry.get("discovered_labels")
        if isinstance(labels, list) and labels:
            return True
    return False


def record_row_discoveries(
    evaluation_id: UUID,
    metric_scores: Any,
) -> None:
    """Merge one completed row into the aggregate once it has been seeded."""
    if not _has_discovery_payload(metric_scores):
        return
    try:
        client = _get_redis()
        with _RedisLock(client, evaluation_id) as lock:
            if not lock._held:
                return
            if client.get(_ready_key(evaluation_id)) != "1":
                return
            _merge_scores(client, evaluation_id, metric_scores)
    except redis.RedisError:
        logger.warning(
            "Failed to record discoveries for evaluation %s",
            evaluation_id,
            exc_info=True,
        )


def load_running_label_entries(
    db: Any,
    evaluation_id: UUID,
    parent_metric_id: UUID,
) -> List[Dict[str, Any]]:
    """Raw (pre-alias) label aggregate. Seeds from rows once per evaluation."""
    _ensure_seeded(db, evaluation_id)
    return _read_hash(_labels_key(evaluation_id, parent_metric_id))


def load_running_metric_entries(
    db: Any,
    evaluation_id: UUID,
) -> List[Dict[str, Any]]:
    """Raw (pre-alias) top-level metric aggregate. Seeds once per evaluation."""
    _ensure_seeded(db, evaluation_id)
    return _read_hash(_metrics_key(evaluation_id))


def project_discovered_entries(
    entries: List[Dict[str, Any]],
    *,
    resolve_key,
    promoted_slugs: set[str],
) -> List[Dict[str, Any]]:
    """Apply alias resolution and drop promoted slugs. Counts collapse on alias."""
    by_key: Dict[str, Dict[str, Any]] = {}
    for entry in entries:
        key = resolve_key(entry.get("key") or entry.get("name"))
        if not key or key in promoted_slugs:
            continue
        count = max(1, int(entry.get("count") or 1))
        existing = by_key.get(key)
        if existing is None:
            copied = dict(entry)
            copied["key"] = key
            copied["count"] = count
            by_key[key] = copied
            continue
        existing["count"] = int(existing["count"]) + count
        if not existing.get("description") and entry.get("description"):
            existing["description"] = entry["description"]
        if not existing.get("sample_rationale") and entry.get("sample_rationale"):
            existing["sample_rationale"] = entry["sample_rationale"]
        if not existing.get("suggested_type") and entry.get("suggested_type"):
            existing["suggested_type"] = entry["suggested_type"]
        examples = existing.setdefault("examples", [])
        for sample in entry.get("examples") or []:
            if len(examples) >= 3:
                break
            if sample and not any(
                str(item).strip().lower() == str(sample).strip().lower()
                for item in examples
            ):
                examples.append(sample)
    return sorted(by_key.values(), key=lambda item: (-item["count"], item["key"]))


def _ensure_seeded(db: Any, evaluation_id: UUID) -> None:
    try:
        client = _get_redis()
        if client.get(_ready_key(evaluation_id)) == "1":
            return
        with _RedisLock(client, evaluation_id) as lock:
            if not lock._held:
                return
            if client.get(_ready_key(evaluation_id)) == "1":
                return
            _rewrite_from_db(client, db, evaluation_id)
            client.set(_ready_key(evaluation_id), "1", ex=_TTL_SECONDS)
    except redis.RedisError:
        logger.warning(
            "Failed to seed discovered-running cache for %s",
            evaluation_id,
            exc_info=True,
        )


def _rewrite_from_db(client: redis.Redis, db: Any, evaluation_id: UUID) -> None:
    from app.db_sharding.eval_rows import load_evaluation_rows_for_run

    parents = client.smembers(_parents_key(evaluation_id)) or set()
    stale = [_metrics_key(evaluation_id), _parents_key(evaluation_id)]
    stale.extend(_labels_key(evaluation_id, parent_id) for parent_id in parents)
    if stale:
        client.delete(*stale)
    for row in load_evaluation_rows_for_run(db, evaluation_id):
        status = getattr(row, "status", None)
        if hasattr(status, "value"):
            status = status.value
        if (status or "") != "completed":
            continue
        _merge_scores(client, evaluation_id, getattr(row, "metric_scores", None))


def _merge_scores(
    client: redis.Redis,
    evaluation_id: UUID,
    metric_scores: Any,
) -> None:
    if not isinstance(metric_scores, dict):
        return
    discovered_metrics = metric_scores.get(DISCOVERED_METRICS_KEY)
    if isinstance(discovered_metrics, list):
        _merge_list(client, _metrics_key(evaluation_id), discovered_metrics)
    for key, entry in metric_scores.items():
        if key == DISCOVERED_METRICS_KEY or not isinstance(entry, dict):
            continue
        labels = entry.get("discovered_labels")
        if not isinstance(labels, list) or not labels:
            continue
        client.sadd(_parents_key(evaluation_id), str(key))
        client.expire(_parents_key(evaluation_id), _TTL_SECONDS)
        _merge_list(client, _labels_key(evaluation_id, key), labels)


def _merge_list(client: redis.Redis, key: str, items: List[Any]) -> None:
    current = _decode_hash(client.hgetall(key) or {})
    for item in items:
        if isinstance(item, dict):
            _merge_item(current, item)
    if not current:
        return
    client.hset(
        key,
        mapping={slug: json.dumps(payload) for slug, payload in current.items()},
    )
    client.expire(key, _TTL_SECONDS)


def _merge_item(bucket: Dict[str, Dict[str, Any]], item: Dict[str, Any]) -> None:
    raw_key = str(item.get("key") or item.get("name") or "").strip()
    if not raw_key:
        return
    sample = (item.get("rationale") or item.get("sample_rationale") or "")
    sample = sample.strip() if isinstance(sample, str) else None
    sample = sample or None
    existing = bucket.get(raw_key)
    if existing is None:
        examples = [sample] if sample else []
        bucket[raw_key] = {
            "key": raw_key,
            "name": (item.get("name") or "").strip() or raw_key,
            "description": (item.get("description") or "").strip() or None,
            "suggested_type": item.get("suggested_type"),
            "sample_rationale": sample,
            "examples": examples,
            "count": max(1, int(item.get("count") or 1)),
        }
        return
    existing["count"] = int(existing.get("count") or 0) + max(
        1, int(item.get("count") or 1)
    )
    if not existing.get("description") and item.get("description"):
        existing["description"] = (item.get("description") or "").strip() or None
    if not existing.get("sample_rationale") and sample:
        existing["sample_rationale"] = sample
    if not existing.get("suggested_type") and item.get("suggested_type"):
        existing["suggested_type"] = item.get("suggested_type")
    examples = existing.setdefault("examples", [])
    if sample and len(examples) < 3 and not any(
        str(saved).strip().lower() == sample.strip().lower() for saved in examples
    ):
        examples.append(sample)


def _read_hash(key: str) -> List[Dict[str, Any]]:
    try:
        client = _get_redis()
        return list(_decode_hash(client.hgetall(key) or {}).values())
    except redis.RedisError:
        logger.warning("Failed to read discovered-running cache %s", key, exc_info=True)
        return []


def _decode_hash(raw: Dict[str, str]) -> Dict[str, Dict[str, Any]]:
    decoded: Dict[str, Dict[str, Any]] = {}
    for slug, payload in raw.items():
        try:
            value = json.loads(payload)
        except (TypeError, ValueError):
            continue
        if isinstance(value, dict):
            decoded[slug] = value
    return decoded
