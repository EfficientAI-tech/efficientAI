"""Health check response helpers."""

from __future__ import annotations

from app.core.migrations import check_migrations_status


def build_health_status(*, detailed: bool) -> tuple[dict, int]:
    """Build health payload and HTTP status code."""
    is_up_to_date, pending = check_migrations_status()

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
