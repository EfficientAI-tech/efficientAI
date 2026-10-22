"""Load shard slice registry from catalog DB for router overrides."""

from __future__ import annotations

import threading
import uuid
from typing import Dict, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

SliceRegistry = Dict[Tuple[str, int], str]

_registry_lock = threading.Lock()
_registry_cache: Dict[str, SliceRegistry] = {}
_registry_generation: Dict[str, int] = {}


def invalidate_slice_registry(call_import_id: uuid.UUID | str) -> None:
    """Drop the cached slice map after slices are written or rebalanced."""
    key = str(call_import_id)
    with _registry_lock:
        _registry_cache.pop(key, None)
        _registry_generation[key] = _registry_generation.get(key, 0) + 1


def clear_slice_registry_cache() -> None:
    """Drop every cached slice map. Tests use this between cases."""
    with _registry_lock:
        _registry_cache.clear()
        _registry_generation.clear()


def load_slice_registry_for_import(
    db: Session,
    call_import_id: uuid.UUID | str,
) -> SliceRegistry:
    """
    Returns mapping (call_import_id str, slice_id) -> shard_id from
    ``call_import_shard_slices``. Empty when table missing or no rows.

    The map is cached for the process, including an empty result. Writers
    must call :func:`invalidate_slice_registry` after they change slices.
    """
    from app.models.database import CallImportShardSlice

    cid = call_import_id if isinstance(call_import_id, uuid.UUID) else uuid.UUID(str(call_import_id))
    key = str(cid)
    with _registry_lock:
        cached = _registry_cache.get(key)
        if cached is not None:
            return dict(cached)
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
        if _registry_generation.get(key, 0) != generation:
            return dict(mapping)
        _registry_cache[key] = mapping
        return dict(mapping)
