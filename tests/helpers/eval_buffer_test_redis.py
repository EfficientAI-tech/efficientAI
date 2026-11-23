"""Per-xdist-worker Redis URL for eval progress buffer integration tests."""

from __future__ import annotations

import os
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse


def _redis_url_with_db(url: str, db: int) -> str:
    """Return ``url`` with the logical Redis database set to ``db`` (path + ``db`` query)."""
    parsed = urlparse(url)
    path = f"/{db}"
    if parsed.query:
        params = parse_qs(parsed.query, keep_blank_values=True)
        if "db" in params:
            params["db"] = [str(db)]
        query = urlencode(params, doseq=True)
    else:
        query = parsed.query
    return urlunparse(parsed._replace(path=path, query=query))


def eval_buffer_test_redis_url(worker_id: str) -> str:
    """Avoid shared Redis DB 15 across pytest-xdist workers (flushdb races).

    Parallel workers use logical DBs 1–15 only so autouse ``flushdb`` does not
    wipe keys on DB 0 (``REDIS_URL`` / Vobiz call sessions, Celery, etc.).
    """
    explicit = os.getenv("EVAL_BUFFER_TEST_REDIS_URL", "").strip()
    base = explicit or "redis://localhost:6379/15"
    if worker_id in ("master", "main"):
        return base
    try:
        db = 1 + (int(worker_id[2:]) % 15)
    except (ValueError, IndexError):
        return base
    return _redis_url_with_db(base, db)