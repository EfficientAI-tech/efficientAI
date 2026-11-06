"""Credential redaction for log output and exception text.

This module has no dependency on the ``app`` package so that both ``app`` and
``efficientai`` (runner, RTVI) can share one implementation.

Three pieces are provided:

* :func:`redact_secrets` - scrub credential-shaped substrings from text.
* :func:`redacting_sink` - wrap any Loguru sink so every formatted record
  (message *and* traceback text) passes through :func:`redact_secrets`.
* :func:`log_exception_safely` - log an exception with its stack, but with the
  exception message (and chained causes) redacted before Loguru sees them.

Redaction is a safety net, not a guarantee: callers at provider boundaries
should still avoid logging raw request data.
"""

from __future__ import annotations

import inspect
import re
import sys
from typing import Any, Callable, Optional

from loguru import logger

REDACTED = "[REDACTED]"

# --- Provider key prefixes -------------------------------------------------
# Each entry matches a whole token that is a credential by its shape alone.
_KEY_PREFIX_PATTERNS = [
    re.compile(r"\bAIza[0-9A-Za-z_-]{10,}"),  # Google API keys
    re.compile(r"\bsk-(?:ant|proj|svcacct|or)-[A-Za-z0-9_-]{8,}"),  # Anthropic / OpenAI project / OpenRouter
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"),  # generic OpenAI-style secret keys
    re.compile(r"\bxai-[A-Za-z0-9]{20,}"),  # xAI
    re.compile(r"\bgsk_[A-Za-z0-9]{20,}"),  # Groq
    re.compile(r"\br8_[A-Za-z0-9]{20,}"),  # Replicate
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),  # AWS access key id
]

# --- Auth schemes ------------------------------------------------------------
_BEARER_PATTERN = re.compile(r"\b(Bearer)\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE)
# Basic / Token are common English words, so require case-sensitive scheme and
# a value containing at least one digit to avoid redacting prose.
_BASIC_PATTERN = re.compile(r"\b(Basic)\s+(?=[A-Za-z+/=]*[0-9])[A-Za-z0-9+/]{12,}={0,2}")
_TOKEN_SCHEME_PATTERN = re.compile(r"\b(Token)\s+(?=[A-Za-z_-]*[0-9])[A-Za-z0-9._-]{16,}")

# --- Credentials embedded in URLs -------------------------------------------
_URL_USERINFO_PATTERN = re.compile(r"(\b[a-zA-Z][a-zA-Z0-9+.-]*://[^\s:/@'\"]+:)[^\s@/'\"]+@")
_URL_QUERY_PATTERN = re.compile(
    r"([?&](?:key|api_key|apikey|api-key|token|access_token|auth|signature|sig"
    r"|x-goog-signature|x-goog-credential|x-amz-signature|x-amz-credential"
    r"|x-amz-security-token)=)[^&\s'\"#]+",
    re.IGNORECASE,
)

# --- name: value / name=value fields (headers, dict reprs, kwargs, JSON) -----
_SECRET_FIELD_NAMES = (
    r"x-goog-api-key|xi-api-key|x-api-key|api[-_]?key|authorization"
    r"|auth[-_]?token|access[-_]?token|refresh[-_]?token|id[-_]?token"
    r"|client[-_]?secret|secret[-_]?key|secret|password|passwd|token"
)
_SECRET_FIELD_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_-])"  # whole field name only (not max_tokens, prompt_token)
    rf"(?P<name>{_SECRET_FIELD_NAMES})"
    r"(?P<q>['\"]?)"  # optional closing quote of a quoted key
    r"(?P<sep>\s*[:=]\s*)"
    # Unquoted values may start with an auth scheme ("Authorization: Bearer x").
    r"(?P<val>'[^']*'|\"[^\"]*\"|(?:(?:Bearer|Basic|Token|Digest)\s+)?[^\s'\",;}&)\]]+)",
    re.IGNORECASE,
)

# Header names that are themselves a searchable marker in log stores.
_GOOGLE_HEADER_NAME = re.compile(r"x-goog-api-key", re.IGNORECASE)


def _redact_field(match: re.Match) -> str:
    val = match.group("val")
    if val[:1] in ("'", '"'):
        new_val = f"{val[0]}{REDACTED}{val[0]}"
    else:
        new_val = REDACTED
    return f"{match.group('name')}{match.group('q')}{match.group('sep')}{new_val}"


def redact_secrets(text: Any) -> str:
    """Return ``text`` with credential-like substrings replaced by ``[REDACTED]``."""
    if text is None:
        return ""
    out = str(text)
    if not out:
        return out
    out = _URL_USERINFO_PATTERN.sub(rf"\1{REDACTED}@", out)
    out = _URL_QUERY_PATTERN.sub(rf"\1{REDACTED}", out)
    out = _SECRET_FIELD_PATTERN.sub(_redact_field, out)
    out = _BEARER_PATTERN.sub(rf"\1 {REDACTED}", out)
    out = _BASIC_PATTERN.sub(rf"\1 {REDACTED}", out)
    out = _TOKEN_SCHEME_PATTERN.sub(rf"\1 {REDACTED}", out)
    for pattern in _KEY_PREFIX_PATTERNS:
        out = pattern.sub(REDACTED, out)
    # Keep logs free of the literal header name so log-store searches for it
    # only ever hit historical (pre-fix) documents.
    out = _GOOGLE_HEADER_NAME.sub("google_http_api_key", out)
    return out


def redacting_sink(sink: Any) -> Callable[..., Any]:
    """Wrap a Loguru sink so every formatted record is redacted before output.

    Supports file-like objects (anything with ``write``), plain callables and
    coroutine functions (Loguru runs async sinks on the event loop).
    """
    if hasattr(sink, "write"):
        stream = sink

        def _write(message: Any) -> None:
            stream.write(redact_secrets(message))
            flush = getattr(stream, "flush", None)
            if flush is not None:
                flush()

        return _write

    if inspect.iscoroutinefunction(sink):

        async def _async_sink(message: Any) -> Any:
            return await sink(redact_secrets(message))

        return _async_sink

    if callable(sink):

        def _sync_sink(message: Any) -> Any:
            return sink(redact_secrets(message))

        return _sync_sink

    raise TypeError(f"Unsupported sink type for redaction: {type(sink).__name__}")


class RedactedException(Exception):
    """Stand-in for a third-party exception whose message has been redacted."""


_MAX_CHAIN_DEPTH = 5


def _describe(exc: BaseException) -> str:
    cls = type(exc)
    return f"{cls.__module__}.{cls.__qualname__}: {redact_secrets(str(exc))}"


def build_redacted_exception(exc: BaseException) -> RedactedException:
    """Return a copy of ``exc`` safe to log: redacted message, same stack.

    The original exception is never modified. Chained causes are summarised
    (type + redacted message) in the copy's message instead of being attached,
    so Loguru cannot print their raw text.
    """
    lines = [_describe(exc)]
    seen = {id(exc)}
    current: Optional[BaseException] = exc
    for _ in range(_MAX_CHAIN_DEPTH):
        nxt = current.__cause__ or (None if current.__suppress_context__ else current.__context__)
        if nxt is None or id(nxt) in seen:
            break
        seen.add(id(nxt))
        lines.append(f"  caused by {_describe(nxt)}")
        current = nxt

    redacted = RedactedException("\n".join(lines))
    redacted.__cause__ = None
    redacted.__context__ = None
    redacted.__suppress_context__ = True
    return redacted.with_traceback(exc.__traceback__)


def log_exception_safely(
    message: str,
    *args: Any,
    exc: Optional[BaseException] = None,
    level: str = "ERROR",
    **kwargs: Any,
) -> None:
    """Drop-in for ``logger.exception`` at provider boundaries.

    Logs the stack trace of ``exc`` (default: the exception being handled), but
    with the exception message and chained causes passed through
    :func:`redact_secrets`. The log location is the caller's line.
    """
    if exc is None:
        exc = sys.exc_info()[1]
    if exc is None:
        logger.opt(depth=1).log(level, message, *args, **kwargs)
        return
    logger.opt(exception=build_redacted_exception(exc), depth=1).log(
        level, message, *args, **kwargs
    )
