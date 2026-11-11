"""Central Loguru configuration: no variable dumps in tracebacks, secret redaction on output."""

from __future__ import annotations

import os
import sys

from loguru import logger

from efficientai.utils.log_redaction import (
    log_exception_safely,
    redact_secrets,
    redacting_sink,
)

__all__ = [
    "configure_logging",
    "log_exception_safely",
    "redact_log_secrets",
    "redacting_sink",
    "reset_logging_configuration_for_tests",
]

# Backwards-compatible name used by app code and tests.
redact_log_secrets = redact_secrets

_configured = False


def _default_level() -> str:
    return os.environ.get("LOGURU_LEVEL", "DEBUG")


def configure_logging() -> None:
    """Configure Loguru once: no diagnose/backtrace dumps, redacted stderr sink."""
    global _configured
    if _configured:
        return
    _configured = True

    logger.remove()

    # diagnose=False prevents local-variable dumps in tracebacks (e.g. API keys
    # in request headers). The redacting sink scrubs the formatted record,
    # including the exception message line of any traceback.
    logger.add(
        redacting_sink(sys.stderr),
        level=_default_level(),
        diagnose=False,
        backtrace=False,
        colorize=sys.stderr.isatty(),
    )


def reset_logging_configuration_for_tests() -> None:
    """Allow tests to call configure_logging() again (internal use only)."""
    global _configured
    _configured = False
