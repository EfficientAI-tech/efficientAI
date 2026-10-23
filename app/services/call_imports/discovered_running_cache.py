"""Running discovered labels and metrics for an evaluation, kept in Redis.

Workers read this aggregate instead of scanning every completed row. The UI
list endpoints keep their own scan. Alias resolution stays with the caller.

Each completed row owns one contribution. Recording that row again replaces
its previous contribution, so a rescore cannot leave stale candidates behind.
A missed write clears the ready flag and the next read rebuilds from the
database. The lock carries an owner token, is renewed while a seed is in
progress, and is released only when that token still owns the key.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from typing import Any, Dict, List, Optional
from uuid import UUID

import redis

from app.config import settings

logger = logging.getLogger(__name__)

DISCOVERED_METRICS_KEY = "__discovered_metrics__"
_TTL_SECONDS = 7 * 24 * 60 * 60
_LOCK_SECONDS = 10
_LOCK_WAIT_SECONDS = 5.0
_LOCK_POLL_SECONDS = 0.02

_RENEW_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('expire', KEYS[1], ARGV[2])
end
return 0
"""

_RELEASE_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('del', KEYS[1])
end
return 0
"""

_redis_client: Optional[redis.Redis] = None


def _get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis_client


def _ready_key(evaluation_id: UUID) -> str:
    return f"eval:discovered:{evaluation_id}:ready"


def _dirty_key(evaluation_id: UUID) -> str:
    return f"eval:discovered:{evaluation_id}:dirty"


def _metrics_key(evaluation_id: UUID) -> str:
    return f"eval:discovered:{evaluation_id}:metrics"


def _labels_key(evaluation_id: UUID, parent_metric_id: UUID | str) -> str:
    return f"eval:discovered:{evaluation_id}:labels:{parent_metric_id}"


def _parents_key(evaluation_id: UUID) -> str:
    return f"eval:discovered:{evaluation_id}:parents"


def _rows_key(evaluation_id: UUID) -> str:
    return f"eval:discovered:{evaluation_id}:rows"


def _lock_key(evaluation_id: UUID) -> str:
    return f"eval:discovered:{evaluation_id}:lock"


class _RedisLock:
    """Exclusive lock that renews itself and releases only its own token."""

    def __init__(self, client: redis.Redis, evaluation_id: UUID) -> None:
        self._client = client
        self._key = _lock_key(evaluation_id)
        self._token = uuid.uuid4().hex
        self._held = False
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def __enter__(self) -> "_RedisLock":
        deadline = time.monotonic() + _LOCK_WAIT_SECONDS
        while True:
            if self._client.set(
                self._key, self._token, nx=True, ex=_LOCK_SECONDS
            ):
                self._held = True
                self._thread = threading.Thread(
                    target=self._renew_loop,
                    name="discovered-cache-lock",
                    daemon=True,
                )
                self._thread.start()
                return self
            if time.monotonic() >= deadline:
                return self
            time.sleep(_LOCK_POLL_SECONDS)

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1)
        self._release()

    def renew(self) -> bool:
        """Extend the lock. False means this owner no longer holds it."""
        if not self._held:
            return False
        try:
            kept = self._client.eval(
                _RENEW_SCRIPT,
                1,
                self._key,
                self._token,
                str(_LOCK_SECONDS),
            )
        except redis.RedisError:
            self._held = False
            return False
        if not kept:
            self._held = False
            return False
        return True

    def _renew_loop(self) -> None:
        while not self._stop.wait(_LOCK_SECONDS / 3):
            if not self.renew():
                return

    def _release(self) -> None:
        if not self._held:
            return
        self._held = False
        try:
            self._client.eval(_RELEASE_SCRIPT, 1, self._key, self._token)
        except redis.RedisError:
            logger.warning("Failed to release discovery lock %s", self._key, exc_info=True)


def clear_discovered_running_cache(evaluation_id: UUID) -> None:
    """Drop the running aggregate when an evaluation is deleted."""
    try:
        client = _get_redis()
        parents = client.smembers(_parents_key(evaluation_id)) or set()
        keys = [
            _ready_key(evaluation_id),
            _dirty_key(evaluation_id),
            _metrics_key(evaluation_id),
            _parents_key(evaluation_id),
            _rows_key(evaluation_id),
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
    return not _contribution_is_empty(_extract_contribution(metric_scores))


def record_row_discoveries(
    evaluation_id: UUID,
    row_id: UUID | str,
    metric_scores: Any,
    *,
    force: bool = False,
) -> None:
    """Replace one row's contribution in the aggregate.

    ``force`` records an empty payload too, so a retry that cleared scores
    removes candidates that belonged to that row. Rows with nothing to
    discover skip Redis unless ``force`` is set.
    """
    if row_id is None:
        return
    if not force and not _has_discovery_payload(metric_scores):
        return
    try:
        client = _get_redis()
        with _RedisLock(client, evaluation_id) as lock:
            if not lock._held:
                _mark_incomplete(client, evaluation_id)
                return
            if not lock.renew():
                _mark_incomplete(client, evaluation_id)
                return
            if client.get(_ready_key(evaluation_id)) != "1":
                _stash_row_contribution(
                    client, evaluation_id, row_id, metric_scores
                )
                return
            _replace_row_contribution(
                client, evaluation_id, row_id, metric_scores
            )
    except redis.RedisError:
        logger.warning(
            "Failed to record discoveries for evaluation %s",
            evaluation_id,
            exc_info=True,
        )
        _mark_incomplete_quietly(evaluation_id)


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
        if client.get(_dirty_key(evaluation_id)) == "1":
            client.delete(_dirty_key(evaluation_id))
        from app.db_sharding.eval_rows import load_evaluation_rows_for_run

        rows = list(load_evaluation_rows_for_run(db, evaluation_id))
        with _RedisLock(client, evaluation_id) as lock:
            if not lock._held:
                return
            if client.get(_ready_key(evaluation_id)) == "1":
                return
            if client.get(_dirty_key(evaluation_id)) == "1":
                # A completion landed while this snapshot was being read.
                return
            _rewrite_from_rows(client, evaluation_id, rows, lock)
            if not lock.renew():
                _mark_incomplete(client, evaluation_id)
                return
            if client.get(_dirty_key(evaluation_id)) == "1":
                _mark_incomplete(client, evaluation_id)
                return
            client.set(_ready_key(evaluation_id), "1", ex=_TTL_SECONDS)
    except redis.RedisError:
        logger.warning(
            "Failed to seed discovered-running cache for %s",
            evaluation_id,
            exc_info=True,
        )
        _mark_incomplete_quietly(evaluation_id)


def _mark_incomplete(client: redis.Redis, evaluation_id: UUID) -> None:
    """Forget the aggregate so the next read rebuilds it from the database."""
    client.set(_dirty_key(evaluation_id), "1", ex=_TTL_SECONDS)
    client.delete(_ready_key(evaluation_id), _rows_key(evaluation_id))


def _mark_incomplete_quietly(evaluation_id: UUID) -> None:
    try:
        _mark_incomplete(_get_redis(), evaluation_id)
    except redis.RedisError:
        logger.warning(
            "Failed to mark discovered-running cache incomplete for %s",
            evaluation_id,
            exc_info=True,
        )


def _rewrite_from_rows(
    client: redis.Redis,
    evaluation_id: UUID,
    rows: List[Any],
    lock: _RedisLock,
) -> None:
    stashed = {
        row_id: contribution
        for row_id, contribution in (
            (key, _decode_contribution(value))
            for key, value in (client.hgetall(_rows_key(evaluation_id)) or {}).items()
        )
        if contribution is not None
    }
    parents = client.smembers(_parents_key(evaluation_id)) or set()
    stale = [
        _metrics_key(evaluation_id),
        _parents_key(evaluation_id),
        _rows_key(evaluation_id),
    ]
    stale.extend(_labels_key(evaluation_id, parent_id) for parent_id in parents)
    if stale:
        client.delete(*stale)
    seen: set[str] = set()
    for row in rows:
        if not lock.renew():
            raise redis.RedisError("discovery lock lost while seeding")
        status = getattr(row, "status", None)
        if hasattr(status, "value"):
            status = status.value
        row_id = getattr(row, "id", None)
        if row_id is None:
            continue
        seen.add(str(row_id))
        if (status or "") != "completed" and str(row_id) not in stashed:
            continue
        contribution = stashed.get(str(row_id))
        scores = getattr(row, "metric_scores", None)
        if contribution is not None:
            scores = _scores_from_contribution(contribution)
        elif (status or "") != "completed":
            continue
        _store_row_contribution(
            client,
            evaluation_id,
            row_id,
            scores,
            previous=None,
        )
    for row_id, contribution in stashed.items():
        if row_id in seen:
            continue
        if not lock.renew():
            raise redis.RedisError("discovery lock lost while seeding")
        _store_row_contribution(
            client,
            evaluation_id,
            row_id,
            _scores_from_contribution(contribution),
            previous=None,
        )


def _stash_row_contribution(
    client: redis.Redis,
    evaluation_id: UUID,
    row_id: UUID | str,
    metric_scores: Any,
) -> None:
    """Remember one row until the aggregate is seeded from the database."""
    contribution = _extract_contribution(metric_scores)
    if _contribution_is_empty(contribution):
        contribution = {"metrics": [], "labels": {}, "cleared": True}
    client.hset(
        _rows_key(evaluation_id),
        str(row_id),
        json.dumps(contribution),
    )
    client.expire(_rows_key(evaluation_id), _TTL_SECONDS)


def _scores_from_contribution(contribution: Dict[str, Any]) -> Dict[str, Any]:
    if contribution.get("cleared"):
        return {}
    scores: Dict[str, Any] = {}
    metrics = contribution.get("metrics") or []
    if metrics:
        scores[DISCOVERED_METRICS_KEY] = metrics
    for parent_id, items in (contribution.get("labels") or {}).items():
        scores[str(parent_id)] = {"discovered_labels": items}
    return scores


def _replace_row_contribution(
    client: redis.Redis,
    evaluation_id: UUID,
    row_id: UUID | str,
    metric_scores: Any,
) -> None:
    raw_previous = client.hget(_rows_key(evaluation_id), str(row_id))
    previous = _decode_contribution(raw_previous)
    _store_row_contribution(
        client,
        evaluation_id,
        row_id,
        metric_scores,
        previous=previous,
    )


def _store_row_contribution(
    client: redis.Redis,
    evaluation_id: UUID,
    row_id: UUID | str,
    metric_scores: Any,
    *,
    previous: Optional[Dict[str, Any]],
) -> None:
    contribution = _extract_contribution(metric_scores)
    if previous == contribution:
        return
    if previous and not _contribution_is_empty(previous):
        _apply_contribution(client, evaluation_id, previous, -1)
    if _contribution_is_empty(contribution):
        client.hdel(_rows_key(evaluation_id), str(row_id))
        return
    _apply_contribution(client, evaluation_id, contribution, 1)
    client.hset(
        _rows_key(evaluation_id),
        str(row_id),
        json.dumps(contribution),
    )
    client.expire(_rows_key(evaluation_id), _TTL_SECONDS)


def _extract_contribution(metric_scores: Any) -> Dict[str, Any]:
    metrics: List[Dict[str, Any]] = []
    labels: Dict[str, List[Dict[str, Any]]] = {}
    if isinstance(metric_scores, dict):
        discovered_metrics = metric_scores.get(DISCOVERED_METRICS_KEY)
        if isinstance(discovered_metrics, list):
            metrics = [item for item in discovered_metrics if isinstance(item, dict)]
        for key, entry in metric_scores.items():
            if key == DISCOVERED_METRICS_KEY or not isinstance(entry, dict):
                continue
            found = entry.get("discovered_labels")
            if isinstance(found, list) and found:
                labels[str(key)] = [item for item in found if isinstance(item, dict)]
    return {"metrics": metrics, "labels": labels}


def _contribution_is_empty(contribution: Dict[str, Any]) -> bool:
    return not contribution.get("metrics") and not contribution.get("labels")


def _decode_contribution(raw: Any) -> Optional[Dict[str, Any]]:
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(value, dict):
        return None
    return value


def _apply_contribution(
    client: redis.Redis,
    evaluation_id: UUID,
    contribution: Dict[str, Any],
    sign: int,
) -> None:
    metrics = contribution.get("metrics") or []
    if metrics:
        _apply_list(client, _metrics_key(evaluation_id), metrics, sign)
    for parent_id, items in (contribution.get("labels") or {}).items():
        if not items:
            continue
        label_key = _labels_key(evaluation_id, parent_id)
        if sign > 0:
            client.sadd(_parents_key(evaluation_id), str(parent_id))
            client.expire(_parents_key(evaluation_id), _TTL_SECONDS)
        _apply_list(client, label_key, items, sign)
        if sign < 0 and not client.hgetall(label_key):
            client.srem(_parents_key(evaluation_id), str(parent_id))


def _apply_list(
    client: redis.Redis,
    key: str,
    items: List[Any],
    sign: int,
) -> None:
    current = _decode_hash(client.hgetall(key) or {})
    for item in items:
        if not isinstance(item, dict):
            continue
        if sign > 0:
            _merge_item(current, item)
        else:
            _unmerge_item(current, item)
    if not current:
        client.delete(key)
        return
    client.hset(
        key,
        mapping={slug: json.dumps(payload) for slug, payload in current.items()},
    )
    client.expire(key, _TTL_SECONDS)


def _unmerge_item(bucket: Dict[str, Dict[str, Any]], item: Dict[str, Any]) -> None:
    raw_key = str(item.get("key") or item.get("name") or "").strip()
    if not raw_key:
        return
    existing = bucket.get(raw_key)
    if existing is None:
        return
    existing["count"] = int(existing.get("count") or 0) - max(
        1, int(item.get("count") or 1)
    )
    if existing["count"] <= 0:
        bucket.pop(raw_key, None)


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
