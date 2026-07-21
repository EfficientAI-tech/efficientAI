"""Short-lived in-process cache for catalog reads in bulk workers."""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, Tuple

_TTL_SECONDS = 120.0
_cache: Dict[Tuple[str, str], Tuple[float, Any]] = {}


def cached_catalog_fetch(
    namespace: str,
    key: str,
    loader: Callable[[], Any],
    *,
    ttl_seconds: float = _TTL_SECONDS,
) -> Any:
    cache_key = (namespace, key)
    now = time.monotonic()
    hit = _cache.get(cache_key)
    if hit is not None and now - hit[0] < ttl_seconds:
        return hit[1]
    value = loader()
    _cache[cache_key] = (now, value)
    return value


def clear_worker_catalog_cache() -> None:
    _cache.clear()
