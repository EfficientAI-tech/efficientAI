"""Short-lived in-process cache for catalog reads in bulk workers.

One dict per worker process, shared by every thread in it. Entries expire by
their own TTL, but expiry alone never frees memory for keys that are not read
again (old version keys, finished evaluations and imports). Thread-pool
workers (``worker-imports``) are never recycled by ``worker_max_tasks_per_child``,
so the cache bounds itself:

* **Sweep on write.** A store that comes at least ``CATALOG_CACHE_SWEEP_SECONDS``
  after the last sweep first drops every expired entry. No timer or thread:
  an idle worker adds nothing, and its first write after idling cleans up.
* **Size cap.** At most ``CATALOG_CACHE_MAX_ENTRIES`` entries; the least
  recently used is evicted first. An evicted entry is just reloaded.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Any, Callable, Tuple

from app.config import settings

_TTL_SECONDS = 120.0
_DEFAULT_MAX_ENTRIES = 2048
_DEFAULT_SWEEP_SECONDS = 30.0

# (namespace, key) -> (expires_at, value), least recently used first.
_cache: "OrderedDict[Tuple[str, str], Tuple[float, Any]]" = OrderedDict()
_lock = threading.Lock()
_last_sweep = 0.0


def _setting(name: str, default: float) -> float:
    try:
        return float(getattr(settings, name, default))
    except (TypeError, ValueError):
        return default


def _max_entries() -> int:
    return max(1, int(_setting("CATALOG_CACHE_MAX_ENTRIES", _DEFAULT_MAX_ENTRIES)))


def _sweep_seconds() -> float:
    return max(0.0, _setting("CATALOG_CACHE_SWEEP_SECONDS", _DEFAULT_SWEEP_SECONDS))


def _sweep_expired_locked(now: float) -> None:
    global _last_sweep
    expired = [key for key, (expires_at, _) in _cache.items() if expires_at <= now]
    for key in expired:
        del _cache[key]
    _last_sweep = now


def cached_catalog_fetch(
    namespace: str,
    key: str,
    loader: Callable[[], Any],
    *,
    ttl_seconds: float = _TTL_SECONDS,
) -> Any:
    cache_key = (namespace, key)
    now = time.monotonic()
    with _lock:
        hit = _cache.get(cache_key)
        if hit is not None and now < hit[0]:
            _cache.move_to_end(cache_key)
            return hit[1]
    if ttl_seconds <= 0:
        return loader()

    # Load outside the lock: it queries the catalog, and other threads must
    # not wait on it. Two threads missing at once may both load; last wins.
    value = loader()
    now = time.monotonic()
    with _lock:
        if now - _last_sweep >= _sweep_seconds():
            _sweep_expired_locked(now)
        _cache[cache_key] = (now + ttl_seconds, value)
        _cache.move_to_end(cache_key)
        limit = _max_entries()
        while len(_cache) > limit:
            _cache.popitem(last=False)
    return value


def catalog_cache_size() -> int:
    with _lock:
        return len(_cache)


def clear_worker_catalog_cache() -> None:
    global _last_sweep
    with _lock:
        _cache.clear()
        _last_sweep = 0.0
