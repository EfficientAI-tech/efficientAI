"""Classify evaluator worker errors for Celery retry policy."""

from __future__ import annotations

import httpx

from app.services.testing.evaluator_simulation_errors import (
    ProductionChatLegError,
    TestAgentLlmLegError,
)


def evaluator_error_is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, (ProductionChatLegError, TestAgentLlmLegError)):
        return False
    if isinstance(exc, TimeoutError):
        return False
    if isinstance(exc, ValueError):
        return False
    if isinstance(exc, RuntimeError):
        lowered = str(exc).lower()
        if any(
            token in lowered
            for token in (
                "badrequest",
                "invalid_request",
                "validation error",
                "reasoning_effort",
            )
        ):
            return False
    if isinstance(exc, KeyError):
        return False
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if 400 <= code < 500:
            return False
    if isinstance(exc, httpx.RequestError):
        return True
    return True
