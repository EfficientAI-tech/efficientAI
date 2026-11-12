"""Shared retry countdown for call-import workers (recording fetch, upload, etc.)."""

from __future__ import annotations

from app.config import settings


def import_transient_retry_countdown(
    exc: Exception | None,
    *,
    attempt: int,
    base_seconds: int | None = None,
    max_seconds: int | None = None,
) -> int:
    """Return Celery ``countdown`` for a transient import failure.

    Honors ``retry_after_seconds`` on the exception when set (429 / credential
    throttle). Otherwise uses exponential backoff from ``attempt`` (0 = first
    retry), capped at ``max_seconds``.
    """
    if exc is not None:
        retry_after = getattr(exc, "retry_after_seconds", None)
        if retry_after is not None:
            try:
                seconds = int(retry_after)
            except (TypeError, ValueError):
                seconds = 0
            if seconds > 0:
                return max(1, seconds)

    base = max(
        1,
        int(
            base_seconds
            if base_seconds is not None
            else settings.TELEPHONY_IMPORT_BACKOFF_BASE_SECONDS
        ),
    )
    cap = max(
        base,
        int(
            max_seconds
            if max_seconds is not None
            else settings.TELEPHONY_IMPORT_BACKOFF_MAX_SECONDS
        ),
    )
    level = max(0, int(attempt))
    return max(1, min(cap, base * (2**level)))


def import_dispatch_at_capacity_countdown(
    *,
    provider_wait_seconds: int = 0,
    level: int,
    base_seconds: int = 15,
    max_seconds: int = 120,
) -> int:
    """Backoff when fair import dispatch hits the global slot cap."""
    base = max(1, int(base_seconds))
    cap = max(base, int(max_seconds))
    lvl = max(1, int(level))
    exp = min(cap, base * (2 ** (lvl - 1)))
    return max(int(provider_wait_seconds or 0), exp)
