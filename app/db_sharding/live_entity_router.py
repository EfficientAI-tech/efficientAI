"""Consistent-hash routing for live call / evaluator result payloads."""

from __future__ import annotations

import hashlib
import uuid


def _normalize_uuid(value: uuid.UUID | str) -> str:
    if isinstance(value, uuid.UUID):
        return str(value)
    return str(value)


def live_entity_shard_id(
    workspace_id: uuid.UUID | str,
    entity_id: uuid.UUID | str,
    *,
    shard_ids: list[str],
) -> str:
    """Map a live entity to a configured data shard id."""
    if not shard_ids:
        raise ValueError("at least one shard id is required")
    key = f"{_normalize_uuid(workspace_id)}:{_normalize_uuid(entity_id)}"
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    bucket = int.from_bytes(digest[:8], "big")
    return shard_ids[bucket % len(shard_ids)]
