"""Consistent-hash routing for call-import row shards."""

from __future__ import annotations

import hashlib
import uuid
from typing import List, Sequence


def _normalize_import_id(call_import_id: uuid.UUID | str) -> str:
    if isinstance(call_import_id, uuid.UUID):
        return str(call_import_id)
    return str(call_import_id)


class ShardRouter:
    """
    Maps (call_import_id, row_index) to a configured shard id.

    slice_id = row_index // chunk_size; physical shard =
    hash(call_import_id, slice_id) mod N. With one shard configured,
    every route hits that shard (single-node enterprise mode).
    """

    def __init__(
        self,
        shard_ids: Sequence[str],
        *,
        row_chunk_size: int = 500,
    ) -> None:
        if row_chunk_size < 1:
            raise ValueError("row_chunk_size must be >= 1")
        if not shard_ids:
            raise ValueError("at least one shard id is required when sharding is enabled")
        self._shard_ids: List[str] = list(shard_ids)
        self.row_chunk_size = row_chunk_size

    @property
    def shard_ids(self) -> List[str]:
        return list(self._shard_ids)

    @property
    def shard_count(self) -> int:
        return len(self._shard_ids)

    def slice_id_for_row_index(self, row_index: int) -> int:
        if row_index < 0:
            raise ValueError("row_index must be >= 0")
        return row_index // self.row_chunk_size

    def shard_id_for_row(
        self,
        call_import_id: uuid.UUID | str,
        row_index: int,
        *,
        slice_registry: dict[tuple[str, int], str] | None = None,
    ) -> str:
        slice_id = self.slice_id_for_row_index(row_index)
        if slice_registry:
            key = (_normalize_import_id(call_import_id), slice_id)
            override = slice_registry.get(key)
            if override is not None:
                return override
        return self.shard_id_for_slice(call_import_id, slice_id)

    def shard_id_for_slice(
        self,
        call_import_id: uuid.UUID | str,
        slice_id: int,
    ) -> str:
        key = f"{_normalize_import_id(call_import_id)}:{slice_id}"
        digest = hashlib.sha256(key.encode("utf-8")).digest()
        bucket = int.from_bytes(digest[:8], "big")
        idx = bucket % len(self._shard_ids)
        return self._shard_ids[idx]
