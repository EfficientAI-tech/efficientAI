"""Load shard slice registry from catalog DB for router overrides."""

from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Dict, Optional, Tuple

import redis
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings

logger = logging.getLogger(__name__)

SliceRegistry = Dict[Tuple[str, int], str]
_CachedRegistry = Tuple[str, SliceRegistry]

_registry_lock = threading.Lock()
_registry_cache: Dict[str, _CachedRegistry] = {}
_registry_generation: Dict[str, int] = {}
_epoch_client: Optional[redis.Redis] = None
_epoch_client_override: Optional[object] = None
_epoch_unavailable_until = 0.0


def _epoch_key(call_import_id: str) -> str:
    return f"shard:slice-registry:epoch:{call_import_id}"


def _epoch_redis() -> object:
    """Shared epoch so every API and worker process sees a placement change."""
    global _epoch_client
    if _epoch_client_override is not None:
        return _epoch_client_override
    if _epoch_client is None:
        _epoch_client = redis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=0.2,
            socket_timeout=0.2,
        )
    return _epoch_client


def _shared_epoch(call_import_id: str) -> Optional[str]:
    """Return the placement epoch, or None when it cannot be read.

    None means this process must not trust its memory: another process may
    already have moved the slices.
    """
    global _epoch_unavailable_until
    now = time.monotonic()
    if now < _epoch_unavailable_until:
        return None
    try:
        value = _epoch_redis().get(_epoch_key(call_import_id))
    except Exception:
        logger.warning(
            "Slice registry epoch is unreadable for %s; skipping the process cache",
            call_import_id,
            exc_info=True,
        )
        _epoch_unavailable_until = time.monotonic() + 1.0
        return None
    return "0" if value is None else str(value)


def invalidate_slice_registry(call_import_id: uuid.UUID | str) -> None:
    """Drop this process's cached slice map."""
    key = str(call_import_id)
    with _registry_lock:
        _registry_cache.pop(key, None)
        _registry_generation[key] = _registry_generation.get(key, 0) + 1


def publish_slice_registry_change(call_import_id: uuid.UUID | str) -> None:
    """Tell every process that placement changed.

    Call this only after the catalogue transaction has committed, and before
    old shard copies are deleted. Readers compare this epoch on every lookup
    and reload a map that does not match.
    """
    key = str(call_import_id)
    invalidate_slice_registry(key)
    try:
        _epoch_redis().incr(_epoch_key(key))
    except Exception:
        logger.warning(
            "Failed to publish slice registry change for %s",
            key,
            exc_info=True,
        )


def clear_slice_registry_cache() -> None:
    """Drop every cached slice map. Tests use this between cases."""
    global _epoch_unavailable_until
    with _registry_lock:
        _registry_cache.clear()
        _registry_generation.clear()
    _epoch_unavailable_until = 0.0


def load_slice_registry_for_import(
    db: Session,
    call_import_id: uuid.UUID | str,
) -> SliceRegistry:
    """
    Returns mapping (call_import_id str, slice_id) -> shard_id from
    ``call_import_shard_slices``. Empty when table missing or no rows.

    The map is cached in this process until :func:`publish_slice_registry_change`
    bumps the shared epoch. An empty result is cached too. When the epoch
    cannot be read, the catalogue is queried every time.
    """
    from app.models.database import CallImportShardSlice

    cid = call_import_id if isinstance(call_import_id, uuid.UUID) else uuid.UUID(str(call_import_id))
    key = str(cid)
    epoch = _shared_epoch(key)
    with _registry_lock:
        cached = _registry_cache.get(key)
        if epoch is not None and cached is not None and cached[0] == epoch:
            return dict(cached[1])
        generation = _registry_generation.get(key, 0)

    rows = db.execute(
        select(
            CallImportShardSlice.slice_id,
            CallImportShardSlice.shard_id,
        ).where(CallImportShardSlice.call_import_id == cid)
    ).all()
    mapping: SliceRegistry = {
        (key, int(slice_id)): str(shard_id) for slice_id, shard_id in rows
    }
    with _registry_lock:
        if epoch is None or _registry_generation.get(key, 0) != generation:
            return dict(mapping)
        _registry_cache[key] = (epoch, mapping)
        return dict(mapping)
