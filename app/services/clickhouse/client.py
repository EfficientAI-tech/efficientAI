"""ClickHouse connection wrapper."""

from __future__ import annotations

import threading
from urllib.parse import urlparse

from app.config import settings

_thread_local = threading.local()


def clickhouse_enabled() -> bool:
    return bool(getattr(settings, "CLICKHOUSE_URL", None))


def _create_client():
    import clickhouse_connect

    url = settings.CLICKHOUSE_URL
    if not url:
        raise RuntimeError("CLICKHOUSE_URL is not configured")
    parsed = urlparse(url)
    host = parsed.hostname or "localhost"
    port = parsed.port or (443 if parsed.scheme == "https" else 8123)
    secure = parsed.scheme == "https"
    return clickhouse_connect.get_client(
        host=host,
        port=port,
        username=settings.CLICKHOUSE_USER or "default",
        password=settings.CLICKHOUSE_PASSWORD or "",
        database=settings.CLICKHOUSE_DATABASE or "efficientai",
        secure=secure,
    )


def get_client():
    client = getattr(_thread_local, "client", None)
    if client is None:
        client = _create_client()
        _thread_local.client = client
    return client


def ping() -> bool:
    if not clickhouse_enabled():
        return False
    try:
        return get_client().ping()
    except Exception:
        return False


def reset_client_cache() -> None:
    if hasattr(_thread_local, "client"):
        del _thread_local.client
