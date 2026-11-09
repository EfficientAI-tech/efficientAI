"""Redis-buffered evaluation progress counters.

One hash per evaluation, ``eval:ctr:{evaluation_id}``:

* ``c`` / ``f``: completed / failed deltas not yet drained (may be negative).
* ``pc`` / ``pf`` / ``pgen`` / ``pseq``: the pending slot, a drained batch that
  has not been acknowledged yet. At most one per evaluation. A failed catalog
  write leaves it in place and the next flush re-sends the same payload with
  the same ``seq``, so an ambiguous commit is never applied twice.
* ``remaining``: rows still in flight. Only used to trigger finalize; reset
  from the shard pending+running count on every recount.
* ``gen``: fence version, mirrors ``call_import_evaluations.progress_counter_gen``.
* ``seq``: last flush sequence number issued.
* ``uninit``: the hash was (re)created by a row transition, so gen/seq are not
  known. Nothing is flushed until a fenced recount seeds it from the catalog.
* ``recount_at``: unix time of the last fenced recount.

``eval:ctr:dirty`` holds evaluations with unflushed deltas or a pending slot.

Every mutation is a Lua script, so each is atomic.
"""

from __future__ import annotations

import time
import uuid as uuid_lib
from dataclasses import dataclass
from typing import Optional
from uuid import UUID

import redis
from loguru import logger

from app.config import settings

DIRTY_SET_KEY = "eval:ctr:dirty"
# Fence parks ``remaining`` at this offset until the shard count is known, so
# rows finishing during the recount never see ``remaining <= 0``.
_REMAINING_FENCE_OFFSET = 10**12
# Keys are refreshed on every write; this only reclaims abandoned evaluations.
_KEY_TTL_SECONDS = 14 * 24 * 3600
_FINALIZE_DEDUP_SECONDS = 15
_LOCK_TTL_MS = 60_000

_redis: redis.Redis | None = None


def _client() -> redis.Redis:
    """Fail fast: callers fall back (direct catalog write, catalog-only UI)
    when Redis is down, so a short timeout and a single quick retry beat
    redis-py's default multi-second backoff on every row."""
    global _redis
    if _redis is None:
        from redis.backoff import ExponentialBackoff
        from redis.retry import Retry

        _redis = redis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
            retry=Retry(ExponentialBackoff(cap=0.2, base=0.05), 1),
        )
    return _redis


def counter_key(evaluation_id: UUID | str) -> str:
    return f"eval:ctr:{evaluation_id}"


def _lock_key(evaluation_id: UUID | str) -> str:
    return f"eval:ctr:lock:{evaluation_id}"


def _finalize_key(evaluation_id: UUID | str) -> str:
    return f"eval:finalize:{evaluation_id}"


# KEYS[1]=hash KEYS[2]=dirty  ARGV: dc, df, dremaining, eval_id, ttl
_RECORD_LUA = """
local existed = redis.call('EXISTS', KEYS[1])
if existed == 0 then
  redis.call('HSET', KEYS[1], 'uninit', 1)
end
local dc = tonumber(ARGV[1])
local df = tonumber(ARGV[2])
if dc ~= 0 then redis.call('HINCRBY', KEYS[1], 'c', dc) end
if df ~= 0 then redis.call('HINCRBY', KEYS[1], 'f', df) end
local rem = redis.call('HINCRBY', KEYS[1], 'remaining', tonumber(ARGV[3]))
if dc ~= 0 or df ~= 0 or existed == 0 then
  redis.call('SADD', KEYS[2], ARGV[4])
end
redis.call('EXPIRE', KEYS[1], tonumber(ARGV[5]))
return {rem, existed}
"""

# KEYS[1]=hash KEYS[2]=dirty  ARGV: eval_id
# Returns {kind, pc, pf, pgen, pseq, remaining}; kind is
# 'missing' | 'uninit' | 'empty' | 'pending'.
_DRAIN_LUA = """
if redis.call('EXISTS', KEYS[1]) == 0 then
  redis.call('SREM', KEYS[2], ARGV[1])
  return {'missing', 0, 0, 0, 0, 0}
end
local h = redis.call('HMGET', KEYS[1], 'pc', 'pf', 'pgen', 'pseq', 'uninit', 'c', 'f', 'gen', 'remaining')
local remaining = tonumber(h[9]) or 0
if h[4] then
  return {'pending', tonumber(h[1]) or 0, tonumber(h[2]) or 0, tonumber(h[3]) or 0, tonumber(h[4]), remaining}
end
if h[5] then
  return {'uninit', 0, 0, 0, 0, remaining}
end
local c = tonumber(h[6]) or 0
local f = tonumber(h[7]) or 0
if c == 0 and f == 0 then
  redis.call('SREM', KEYS[2], ARGV[1])
  return {'empty', 0, 0, 0, 0, remaining}
end
local gen = tonumber(h[8]) or 0
local seq = redis.call('HINCRBY', KEYS[1], 'seq', 1)
redis.call('HSET', KEYS[1], 'pc', c, 'pf', f, 'pgen', gen, 'pseq', seq, 'c', 0, 'f', 0)
return {'pending', c, f, gen, seq, remaining}
"""

# KEYS[1]=hash KEYS[2]=dirty  ARGV: eval_id, pseq
_ACK_LUA = """
local pseq = redis.call('HGET', KEYS[1], 'pseq')
if pseq and pseq == ARGV[2] then
  redis.call('HDEL', KEYS[1], 'pc', 'pf', 'pgen', 'pseq')
end
local h = redis.call('HMGET', KEYS[1], 'c', 'f', 'pseq', 'uninit')
if (tonumber(h[1]) or 0) == 0 and (tonumber(h[2]) or 0) == 0 and not h[3] and not h[4] then
  redis.call('SREM', KEYS[2], ARGV[1])
end
return 1
"""

# KEYS[1]=hash KEYS[2]=dirty  ARGV: eval_id, gen, catalog_seq, now, ttl, offset
_FENCE_LUA = """
local seq = tonumber(redis.call('HGET', KEYS[1], 'seq')) or 0
local catalog_seq = tonumber(ARGV[3])
if catalog_seq > seq then seq = catalog_seq end
redis.call('HDEL', KEYS[1], 'pc', 'pf', 'pgen', 'pseq', 'uninit')
redis.call('HSET', KEYS[1], 'c', 0, 'f', 0, 'gen', ARGV[2], 'seq', seq,
  'remaining', ARGV[6], 'recount_at', ARGV[4])
redis.call('SREM', KEYS[2], ARGV[1])
redis.call('EXPIRE', KEYS[1], tonumber(ARGV[5]))
return seq
"""

# KEYS[1]=hash  ARGV: gen, in_progress, offset
# Applies the shard in-progress count on top of decrements that landed since
# the fence. A stale gen means a newer recount owns ``remaining``.
_SET_REMAINING_LUA = """
local gen = redis.call('HGET', KEYS[1], 'gen')
if not gen or gen ~= ARGV[1] then return nil end
return redis.call('HINCRBY', KEYS[1], 'remaining', tonumber(ARGV[2]) - tonumber(ARGV[3]))
"""

# KEYS[1]=hash KEYS[2]=dirty  ARGV: eval_id, gen, seq, remaining, ttl
_SEED_LUA = """
redis.call('DEL', KEYS[1])
redis.call('HSET', KEYS[1], 'c', 0, 'f', 0, 'gen', ARGV[2], 'seq', ARGV[3], 'remaining', ARGV[4])
redis.call('SREM', KEYS[2], ARGV[1])
redis.call('EXPIRE', KEYS[1], tonumber(ARGV[5]))
return 1
"""

_RELEASE_LOCK_LUA = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
"""

_scripts: dict[str, object] = {}


def _script(name: str, source: str):
    client = _client()
    cached = _scripts.get(name)
    if cached is None or getattr(cached, "registered_client", None) is not client:
        cached = client.register_script(source)
        _scripts[name] = cached
    return cached


def _as_int(value) -> int:
    if value is None:
        return 0
    if isinstance(value, bytes):
        value = value.decode()
    return int(value)


@dataclass(frozen=True)
class TransitionResult:
    remaining: int
    created: bool


@dataclass(frozen=True)
class DrainResult:
    kind: str  # missing | uninit | empty | pending
    completed_delta: int = 0
    failed_delta: int = 0
    gen: int = 0
    seq: int = 0
    remaining: int = 0


def remaining_delta_for_transition(previous_status: str | None, new_status: str) -> int:
    """-1 when a row leaves pending/running, +1 when it re-enters it."""
    active = {"pending", "running"}
    was_active = (previous_status or "").strip().lower() in active
    is_active = (new_status or "").strip().lower() in active
    if was_active and not is_active:
        return -1
    if is_active and not was_active:
        return 1
    return 0


def record_transition(
    evaluation_id: UUID | str,
    *,
    completed_delta: int,
    failed_delta: int,
    remaining_delta: int,
) -> TransitionResult:
    """Apply one row transition. Raises ``redis.RedisError`` when Redis is down."""
    rem, existed = _script("record", _RECORD_LUA)(
        keys=[counter_key(evaluation_id), DIRTY_SET_KEY],
        args=[
            int(completed_delta),
            int(failed_delta),
            int(remaining_delta),
            str(evaluation_id),
            _KEY_TTL_SECONDS,
        ],
    )
    return TransitionResult(remaining=_as_int(rem), created=not bool(_as_int(existed)))


def dirty_evaluation_ids(limit: int = 5000) -> list[str]:
    client = _client()
    members: list[str] = []
    for member in client.sscan_iter(DIRTY_SET_KEY, count=500):
        members.append(member.decode() if isinstance(member, bytes) else member)
        if len(members) >= limit:
            break
    return members


def drain(evaluation_id: UUID | str) -> DrainResult:
    kind, pc, pf, pgen, pseq, remaining = _script("drain", _DRAIN_LUA)(
        keys=[counter_key(evaluation_id), DIRTY_SET_KEY],
        args=[str(evaluation_id)],
    )
    if isinstance(kind, bytes):
        kind = kind.decode()
    return DrainResult(
        kind=str(kind),
        completed_delta=_as_int(pc),
        failed_delta=_as_int(pf),
        gen=_as_int(pgen),
        seq=_as_int(pseq),
        remaining=_as_int(remaining),
    )


def ack(evaluation_id: UUID | str, seq: int) -> None:
    _script("ack", _ACK_LUA)(
        keys=[counter_key(evaluation_id), DIRTY_SET_KEY],
        args=[str(evaluation_id), str(int(seq))],
    )


def fence(evaluation_id: UUID | str, *, gen: int, catalog_seq: int) -> None:
    """Discard buffered/pending deltas and adopt the catalog's gen.

    Must run *before* the shard count, so any batch drained afterwards carries
    the new gen and only holds transitions that landed after the fence.
    """
    _script("fence", _FENCE_LUA)(
        keys=[counter_key(evaluation_id), DIRTY_SET_KEY],
        args=[
            str(evaluation_id),
            int(gen),
            int(catalog_seq),
            int(time.time()),
            _KEY_TTL_SECONDS,
            _REMAINING_FENCE_OFFSET,
        ],
    )


def set_remaining_after_count(
    evaluation_id: UUID | str, *, gen: int, in_progress: int
) -> Optional[int]:
    result = _script("set_remaining", _SET_REMAINING_LUA)(
        keys=[counter_key(evaluation_id)],
        args=[int(gen), int(in_progress), _REMAINING_FENCE_OFFSET],
    )
    return None if result is None else _as_int(result)


def seed(evaluation_id: UUID | str, *, gen: int, seq: int, remaining: int) -> None:
    """Initialise the hash at materialize time from catalog gen/seq."""
    _script("seed", _SEED_LUA)(
        keys=[counter_key(evaluation_id), DIRTY_SET_KEY],
        args=[str(evaluation_id), int(gen), int(seq), int(remaining), _KEY_TTL_SECONDS],
    )


def seed_best_effort(evaluation_id: UUID | str, *, gen: int, seq: int, remaining: int) -> None:
    try:
        seed(evaluation_id, gen=gen, seq=seq, remaining=remaining)
    except redis.RedisError as exc:
        # Transitions will recreate the key as ``uninit`` and force a recount.
        logger.warning("eval counter seed skipped for {}: {}", evaluation_id, exc)


def delete(evaluation_id: UUID | str) -> None:
    try:
        client = _client()
        pipe = client.pipeline()
        pipe.delete(counter_key(evaluation_id))
        pipe.srem(DIRTY_SET_KEY, str(evaluation_id))
        pipe.execute()
    except redis.RedisError as exc:
        logger.debug("eval counter delete skipped for {}: {}", evaluation_id, exc)


@dataclass(frozen=True)
class BufferedCounters:
    completed_delta: int = 0
    failed_delta: int = 0
    pending_completed: int = 0
    pending_failed: int = 0
    pending_gen: Optional[int] = None
    pending_seq: Optional[int] = None
    gen: Optional[int] = None
    recount_at: Optional[int] = None


def read_buffered(evaluation_id: UUID | str) -> BufferedCounters:
    """Snapshot for readers. Returns zeros when Redis is unavailable."""
    try:
        values = _client().hmget(
            counter_key(evaluation_id),
            "c", "f", "pc", "pf", "pgen", "pseq", "gen", "recount_at",
        )
    except redis.RedisError:
        return BufferedCounters()
    c, f, pc, pf, pgen, pseq, gen, recount_at = values
    return BufferedCounters(
        completed_delta=_as_int(c),
        failed_delta=_as_int(f),
        pending_completed=_as_int(pc),
        pending_failed=_as_int(pf),
        pending_gen=None if pgen is None else _as_int(pgen),
        pending_seq=None if pseq is None else _as_int(pseq),
        gen=None if gen is None else _as_int(gen),
        recount_at=None if recount_at is None else _as_int(recount_at),
    )


def unapplied_deltas(
    buffered: BufferedCounters,
    *,
    catalog_gen: int,
    catalog_seq: int,
) -> tuple[int, int]:
    """Deltas not yet reflected in the catalog row.

    Buffered ``c/f`` count only when they belong to the catalog's gen (after
    a recount the catalog is ahead of a stale Redis view). The pending slot
    counts only while the catalog has not applied its ``seq``.
    """
    completed = failed = 0
    if buffered.gen is None or buffered.gen == catalog_gen:
        completed += buffered.completed_delta
        failed += buffered.failed_delta
    if (
        buffered.pending_seq is not None
        and buffered.pending_gen == catalog_gen
        and catalog_seq < buffered.pending_seq
    ):
        completed += buffered.pending_completed
        failed += buffered.pending_failed
    return completed, failed


# --- locks / finalize dedupe -------------------------------------------------


def acquire_lock(evaluation_id: UUID | str, *, ttl_ms: int = _LOCK_TTL_MS) -> Optional[str]:
    token = uuid_lib.uuid4().hex
    try:
        if _client().set(_lock_key(evaluation_id), token, nx=True, px=ttl_ms):
            return token
    except redis.RedisError as exc:
        logger.debug("eval counter lock skipped for {}: {}", evaluation_id, exc)
    return None


def release_lock(evaluation_id: UUID | str, token: Optional[str]) -> None:
    if not token:
        return
    try:
        _script("release_lock", _RELEASE_LOCK_LUA)(
            keys=[_lock_key(evaluation_id)], args=[token]
        )
    except redis.RedisError as exc:
        logger.debug("eval counter lock release skipped for {}: {}", evaluation_id, exc)


def claim_finalize_slot(evaluation_id: UUID | str) -> bool:
    """``SET NX`` dedupe so concurrent closers enqueue one finalize."""
    try:
        return bool(
            _client().set(
                _finalize_key(evaluation_id), "1", nx=True, ex=_FINALIZE_DEDUP_SECONDS
            )
        )
    except redis.RedisError:
        return True


def request_finalize(evaluation_id: UUID | str) -> bool:
    """Enqueue ``finalize_call_import_evaluation`` unless one was just queued."""
    if not claim_finalize_slot(evaluation_id):
        return False
    try:
        from app.workers.tasks.finalize_call_import_evaluation import (
            finalize_call_import_evaluation_task,
        )

        finalize_call_import_evaluation_task.apply_async(args=[str(evaluation_id)])
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("finalize enqueue failed for evaluation {}: {}", evaluation_id, exc)
        try:
            _client().delete(_finalize_key(evaluation_id))
        except redis.RedisError:
            pass
        return False
