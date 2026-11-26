"""Exception hierarchy. Catch ``EfficientAIError`` to handle everything the SDK raises."""

from __future__ import annotations

from typing import Any, Optional

import httpx


class EfficientAIError(Exception):
    """Base class for all SDK errors."""


class ConfigurationError(EfficientAIError, ValueError):
    """The client was configured incorrectly (for example, no API key).

    Also a ``ValueError``, so code written against the older trace helpers keeps working.
    """


class APIConnectionError(EfficientAIError):
    """The request never got a response (DNS, connection refused, TLS, ...)."""

    def __init__(
        self, message: str = "Connection error.", *, request: Optional[httpx.Request] = None
    ):
        super().__init__(message)
        self.request = request


class APITimeoutError(APIConnectionError):
    """The request timed out."""

    def __init__(self, *, request: Optional[httpx.Request] = None):
        super().__init__("Request timed out.", request=request)


class APIStatusError(EfficientAIError):
    """The API returned a non-success status code."""

    status_code: int

    def __init__(self, message: str, *, response: httpx.Response, body: Any):
        super().__init__(message)
        self.response = response
        self.status_code = response.status_code
        self.body = body
        self.request_id: Optional[str] = response.headers.get("x-request-id")


class BadRequestError(APIStatusError):
    """400"""


class AuthenticationError(APIStatusError):
    """401: the API key is missing, invalid or inactive."""


class PermissionDeniedError(APIStatusError):
    """403: the key is valid but cannot access this resource or workspace."""


class NotFoundError(APIStatusError):
    """404"""


class ConflictError(APIStatusError):
    """409"""


class UnprocessableEntityError(APIStatusError):
    """422: the request body failed validation."""


class RateLimitError(APIStatusError):
    """429: slow down. ``retry_after`` is the server's hint in seconds, if it sent one."""

    def __init__(self, message: str, *, response: httpx.Response, body: Any):
        super().__init__(message, response=response, body=body)
        self.retry_after: Optional[float] = parse_retry_after(response.headers.get("retry-after"))


class InternalServerError(APIStatusError):
    """5xx"""


_STATUS_ERRORS: dict[int, type[APIStatusError]] = {
    400: BadRequestError,
    401: AuthenticationError,
    403: PermissionDeniedError,
    404: NotFoundError,
    409: ConflictError,
    422: UnprocessableEntityError,
    429: RateLimitError,
}


def parse_retry_after(value: Optional[str]) -> Optional[float]:
    """Parse a Retry-After header given in seconds. HTTP-date values are ignored."""
    if not value:
        return None
    try:
        seconds = float(value.strip())
    except ValueError:
        return None
    return seconds if seconds >= 0 else None


def _error_message(response: httpx.Response, body: Any) -> str:
    detail: Any = None
    if isinstance(body, dict):
        detail = body.get("detail") or body.get("message") or body.get("error")
    elif isinstance(body, str) and body.strip():
        detail = body.strip()

    if isinstance(detail, list):  # FastAPI validation errors
        parts = []
        for item in detail:
            if isinstance(item, dict):
                loc = ".".join(str(p) for p in item.get("loc", []) if p != "body")
                msg = item.get("msg", "")
                parts.append(f"{loc}: {msg}" if loc else str(msg))
            else:
                parts.append(str(item))
        detail = "; ".join(parts)

    text = str(detail) if detail else response.reason_phrase or "Unknown error"
    if len(text) > 500:
        text = text[:500] + "..."
    return f"{response.status_code}: {text}"


def make_status_error(response: httpx.Response, body: Any) -> APIStatusError:
    cls = _STATUS_ERRORS.get(response.status_code)
    if cls is None:
        cls = InternalServerError if response.status_code >= 500 else APIStatusError
    return cls(_error_message(response, body), response=response, body=body)
