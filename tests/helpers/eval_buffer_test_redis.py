"""Per-xdist-worker Redis URL for eval progress buffer integration tests."""

from __future__ import annotations

import os
import re


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
    if re.search(r"/\d+$", base):
        return re.sub(r"/\d+$", f"/{db}", base)
    return f"{base.rstrip('/')}/{db}"