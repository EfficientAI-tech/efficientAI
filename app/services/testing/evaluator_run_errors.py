"""Classify evaluator worker errors for Celery retry policy."""

from __future__ import annotations

import httpx


def evaluator_error_is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, ValueError):
        return False
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if 400 <= code < 500:
            return False
    if isinstance(exc, httpx.RequestError):
        return True
    return True
