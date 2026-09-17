"""Health check response helpers."""

from __future__ import annotations

import time

from app.config import settings
from app.core.migrations import check_migrations_status

_readiness_cached_at: float = 0.0
_readiness_cached_status: tuple[bool, list[str]] = (True, [])


def _migration_status_cached() -> tuple[bool, list[str]]:
    global _readiness_cached_at, _readiness_cached_status

    ttl = max(0, int(settings.HEALTH_READINESS_CACHE_SECONDS))
    now = time.monotonic()
    if ttl > 0 and (now - _readiness_cached_at) < ttl:
        return _readiness_cached_status

    status = check_migrations_status()
    _readiness_cached_at = now
    _readiness_cached_status = status
    return status


def build_liveness_status() -> tuple[dict, int]:
    """Cheap liveness probe: no DB, no deployment state."""
    return {"status": "ok"}, 200


def build_readiness_status(*, detailed: bool) -> tuple[dict, int]:
    """Readiness probe for load balancers: migrations must be current."""
    is_up_to_date, pending = _migration_status_cached()

    if is_up_to_date:
        if detailed:
            return {"status": "healthy", "migrations": "up_to_date"}, 200
        return {"status": "healthy"}, 200

    if detailed:
        return {
            "status": "degraded",
            "migrations": "pending",
            "pending_migrations": pending,
            "message": f"{len(pending)} migration(s) pending: {', '.join(pending)}",
        }, 503

    return {"status": "degraded"}, 503


def build_health_status(*, detailed: bool) -> tuple[dict, int]:
    """Backward-compatible alias for readiness checks."""
    return build_readiness_status(detailed=detailed)
