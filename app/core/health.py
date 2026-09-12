"""Health check response helpers."""

from __future__ import annotations

from app.core.migrations import check_migrations_status
from app.services.clickhouse.client import clickhouse_enabled, ping


def build_health_status(*, detailed: bool) -> tuple[dict, int]:
    """Build health payload and HTTP status code."""
    is_up_to_date, pending = check_migrations_status()
    clickhouse_ok = True
    if clickhouse_enabled():
        clickhouse_ok = ping()

    if is_up_to_date and clickhouse_ok:
        if detailed:
            payload = {"status": "healthy", "migrations": "up_to_date"}
            if clickhouse_enabled():
                payload["clickhouse"] = "ok"
            return payload, 200
        return {"status": "healthy"}, 200

    if detailed:
        payload = {
            "status": "degraded",
        }
        if not is_up_to_date:
            payload["migrations"] = "pending"
            payload["pending_migrations"] = pending
            payload["message"] = f"{len(pending)} migration(s) pending: {', '.join(pending)}"
        if clickhouse_enabled() and not clickhouse_ok:
            payload["clickhouse"] = "unavailable"
            payload.setdefault(
                "message",
                "ClickHouse is unavailable",
            )
        return payload, 503

    return {"status": "degraded"}, 503
