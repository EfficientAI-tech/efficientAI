"""Tests for Loguru setup and secret redaction."""

from __future__ import annotations

import asyncio
import sys
from io import StringIO
from typing import List

import pytest
from loguru import logger

from app.core import logging as logging_mod
from app.core.logging import redact_log_secrets
from efficientai.utils.log_redaction import (
    REDACTED,
    log_exception_safely,
    redact_secrets,
    redacting_sink,
)

GOOGLE_KEY = "AIzaSyBadBadBadBadBadBadBadBadBadBa"

# Mirrors a LiteLLM / requests error message that carries several providers' credentials.
MULTI_PROVIDER_MESSAGE = (
    "litellm.APIError: request headers={'Authorization': 'Bearer sk-proj-abc123def456', "
    "'xi-api-key': 'el_secret_999', 'x-goog-api-key': '" + GOOGLE_KEY + "'} "
    "kwargs api_key='sk-ant-api03-SECRETSECRET' token=dg_SECRET_TOKEN"
)
MULTI_PROVIDER_SECRETS = [
    "sk-proj-abc123def456",
    "el_secret_999",
    GOOGLE_KEY,
    "sk-ant-api03-SECRETSECRET",
    "dg_SECRET_TOKEN",
    "x-goog-api-key",
]


class _FakeStderr(StringIO):
    def isatty(self) -> bool:
        return False


@pytest.fixture
def configured_stderr(monkeypatch: pytest.MonkeyPatch) -> _FakeStderr:
    """Run configure_logging() against a captured stderr."""
    logging_mod.reset_logging_configuration_for_tests()
    fake = _FakeStderr()
    monkeypatch.setattr(sys, "stderr", fake)
    logging_mod.configure_logging()
    yield fake
    logging_mod.reset_logging_configuration_for_tests()


@pytest.fixture
def raw_records() -> List[str]:
    """Capture formatted records with a sink that does NOT redact."""
    records: List[str] = []
    handler_id = logger.add(records.append, format="{message}", diagnose=False, backtrace=False)
    yield records
    logger.remove(handler_id)


def _assert_no_secrets(text: str, secrets: List[str] = MULTI_PROVIDER_SECRETS) -> None:
    for secret in secrets:
        assert secret not in text, f"{secret!r} leaked into: {text!r}"


# --- redact_secrets ---------------------------------------------------------


def test_redact_log_secrets_is_shared_implementation() -> None:
    assert redact_log_secrets is redact_secrets


def test_redact_log_secrets_google_and_header() -> None:
    raw = (
        f"headers {{'x-goog-api-key': '{GOOGLE_KEY}', "
        "'Authorization': 'Bearer sk-secret-token', "
        "'api_key': 'secret123'}"
    )
    out = redact_log_secrets(raw)
    assert "AIzaSy" not in out
    assert "sk-secret-token" not in out
    assert "secret123" not in out
    assert "x-goog-api-key" not in out
    assert "REDACTED" in out


@pytest.mark.parametrize(
    ("raw", "secret"),
    [
        (f"key is {GOOGLE_KEY} here", GOOGLE_KEY),
        ("using sk-abcdefghijklmnopqrstuvwx for openai", "sk-abcdefghijklmnopqrstuvwx"),
        ("using sk-proj-AbC123xyz789", "sk-proj-AbC123xyz789"),
        ("anthropic sk-ant-api03-AbCdEf123", "sk-ant-api03-AbCdEf123"),
        ("xai xai-abcdefghijklmnopqrstuvwxyz", "xai-abcdefghijklmnopqrstuvwxyz"),
        ("groq gsk_abcdefghijklmnopqrstuvwxyz", "gsk_abcdefghijklmnopqrstuvwxyz"),
        ("aws AKIAABCDEFGHIJKLMNOP", "AKIAABCDEFGHIJKLMNOP"),
        ("{'xi-api-key': 'el_secret_999'}", "el_secret_999"),
        ('{"x-api-key": "anthropic-raw-value"}', "anthropic-raw-value"),
        ("call(api_key='plainsecretvalue')", "plainsecretvalue"),
        ("api-key: plainsecretvalue", "plainsecretvalue"),
        ("Authorization: Token 0123456789abcdef0123", "0123456789abcdef0123"),
        ("Authorization: Basic dXNlcjpwYXNzd29yZDEyMw==", "dXNlcjpwYXNzd29yZDEyMw=="),
        ("authorization=Bearer abc.def.ghi-jkl", "abc.def.ghi-jkl"),
        ("token=dg_SECRET_TOKEN", "dg_SECRET_TOKEN"),
        ("client_secret='cs-value-123'", "cs-value-123"),
        ('{"password": "hunter2hunter2"}', "hunter2hunter2"),
        ("GET https://host/v1/models?key=rawquerykey&alt=json", "rawquerykey"),
        ("GET https://x/y?X-Goog-Signature=abcdef0123&x=1", "abcdef0123"),
        ("postgresql://admin:dbpass123@db.internal:5432/app", "dbpass123"),
        ("https://AC123:authtoken456@api.exotel.com/v1/", "authtoken456"),
    ],
)
def test_redact_secrets_patterns(raw: str, secret: str) -> None:
    out = redact_secrets(raw)
    assert secret not in out
    assert REDACTED in out


@pytest.mark.parametrize(
    "text",
    [
        "token count 512",
        "prompt_tokens=120 completion_tokens=40 max_tokens=1024",
        "skip-this step",
        "task-force meeting",
        "row 3f2a9c1e-8b4d-4c2a-9f1e-1234567890ab failed",
        "Basic configuration loaded",
        "Token validation failed for user",
        "https://api.example.com/v1/chat?alt=json",
        "secret santa is fun",
        "",
    ],
)
def test_redact_secrets_leaves_ordinary_text_alone(text: str) -> None:
    assert redact_secrets(text) == text


def test_redact_secrets_handles_none_and_non_str() -> None:
    assert redact_secrets(None) == ""
    assert redact_secrets(ValueError("api_key='abcdefgh'")) == "api_key='[REDACTED]'"


# --- configure_logging (layer 1: sink redaction) ------------------------------


def test_configure_logging_exception_no_header_dump(configured_stderr: _FakeStderr) -> None:
    """With diagnose=False, traceback must not inline locals (e.g. Gemini headers)."""

    def _boom() -> None:
        _headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": GOOGLE_KEY,
        }
        raise RuntimeError("upstream failed")

    try:
        _boom()
    except RuntimeError:
        logger.exception("caught")

    text = configured_stderr.getvalue()
    assert "AIzaSy" not in text
    assert "x-goog-api-key" not in text
    assert "_headers" not in text
    assert "upstream failed" in text


def test_configure_logging_redacts_exception_message(configured_stderr: _FakeStderr) -> None:
    try:
        raise Exception(MULTI_PROVIDER_MESSAGE)
    except Exception:
        logger.exception("provider call failed")

    text = configured_stderr.getvalue()
    _assert_no_secrets(text)
    assert "provider call failed" in text
    assert REDACTED in text


def test_configure_logging_redacts_chained_cause(configured_stderr: _FakeStderr) -> None:
    try:
        try:
            raise Exception(MULTI_PROVIDER_MESSAGE)
        except Exception as inner:
            raise RuntimeError("LLM generation failed") from inner
    except RuntimeError:
        logger.exception("wrapped failure")

    text = configured_stderr.getvalue()
    _assert_no_secrets(text)
    assert "LLM generation failed" in text


def test_configure_logging_redacts_interpolated_exception(configured_stderr: _FakeStderr) -> None:
    exc = Exception(MULTI_PROVIDER_MESSAGE)
    logger.error(f"request failed: {exc}")
    _assert_no_secrets(configured_stderr.getvalue())


# --- redacting_sink -------------------------------------------------------------


def test_redacting_sink_sync_callable() -> None:
    collected: List[str] = []
    handler_id = logger.add(redacting_sink(collected.append), format="{message}")
    try:
        logger.info(MULTI_PROVIDER_MESSAGE)
    finally:
        logger.remove(handler_id)
    _assert_no_secrets("".join(collected))


def test_redacting_sink_file_like() -> None:
    stream = StringIO()
    handler_id = logger.add(redacting_sink(stream), format="{message}")
    try:
        logger.info(MULTI_PROVIDER_MESSAGE)
    finally:
        logger.remove(handler_id)
    _assert_no_secrets(stream.getvalue())
    assert REDACTED in stream.getvalue()


def test_redacting_sink_async_callable() -> None:
    """Covers the RTVI system-log sink, which forwards logs to clients."""
    collected: List[str] = []

    async def _client_sink(message: str) -> None:
        collected.append(message)

    async def _run() -> None:
        handler_id = logger.add(
            redacting_sink(_client_sink), format="{message}", diagnose=False, backtrace=False
        )
        try:
            logger.info(MULTI_PROVIDER_MESSAGE)
            await logger.complete()
        finally:
            logger.remove(handler_id)

    asyncio.run(_run())
    assert collected
    _assert_no_secrets("".join(collected))


def test_redacting_sink_rejects_unsupported_type() -> None:
    with pytest.raises(TypeError):
        redacting_sink(42)


# --- log_exception_safely (layer 2: boundary redaction) -----------------------


def _raise_provider_error() -> None:
    raise ValueError(MULTI_PROVIDER_MESSAGE)


def test_log_exception_safely_redacts_without_sink_help(raw_records: List[str]) -> None:
    try:
        _raise_provider_error()
    except ValueError as exc:
        log_exception_safely("provider failed model={}", "gemini-2.5", exc=exc)
        original_text = str(exc)

    text = "".join(raw_records)
    _assert_no_secrets(text)
    assert "provider failed model=gemini-2.5" in text
    assert "builtins.ValueError" in text
    assert "_raise_provider_error" in text  # stack frames preserved
    # The original exception is untouched for callers that re-raise it.
    assert original_text == MULTI_PROVIDER_MESSAGE


def test_log_exception_safely_defaults_to_current_exception(raw_records: List[str]) -> None:
    try:
        _raise_provider_error()
    except ValueError:
        log_exception_safely("implicit exc")

    text = "".join(raw_records)
    _assert_no_secrets(text)
    assert "implicit exc" in text
    assert "builtins.ValueError" in text


def test_log_exception_safely_summarises_chained_causes(raw_records: List[str]) -> None:
    try:
        try:
            _raise_provider_error()
        except ValueError as inner:
            raise RuntimeError("wrapper") from inner
    except RuntimeError as exc:
        log_exception_safely("chained", exc=exc)

    text = "".join(raw_records)
    _assert_no_secrets(text)
    assert "builtins.RuntimeError: wrapper" in text
    assert "caused by builtins.ValueError" in text


def test_log_exception_safely_reports_caller_location() -> None:
    records = []
    handler_id = logger.add(lambda m: records.append(m.record), format="{message}")
    try:
        try:
            _raise_provider_error()
        except ValueError as exc:
            log_exception_safely("where", exc=exc)
    finally:
        logger.remove(handler_id)

    assert records
    assert records[0]["function"] == "test_log_exception_safely_reports_caller_location"


def test_log_exception_safely_without_exception(raw_records: List[str]) -> None:
    log_exception_safely("no active exception")
    assert "no active exception" in "".join(raw_records)
