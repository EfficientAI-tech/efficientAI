"""Tests for telephony credential rate limiting during call imports."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import redis

from app.workers.concurrency import telephony_credential_rate_limit as module


@pytest.fixture(autouse=True)
def _rate_limit_settings(monkeypatch):
    monkeypatch.setattr(module.settings, "TELEPHONY_IMPORT_CREDIT_LIMIT", 5, raising=False)
    monkeypatch.setattr(
        module.settings, "TELEPHONY_IMPORT_CREDIT_WINDOW_SECONDS", 60, raising=False
    )
    monkeypatch.setattr(
        module.settings, "TELEPHONY_IMPORT_BACKOFF_BASE_SECONDS", 15, raising=False
    )
    monkeypatch.setattr(
        module.settings, "TELEPHONY_IMPORT_BACKOFF_MAX_SECONDS", 60, raising=False
    )


@pytest.fixture
def redis_client(monkeypatch):
    try:
        client = redis.from_url(module.settings.REDIS_URL, decode_responses=True)
        client.ping()
    except redis.RedisError:
        pytest.skip("Redis unavailable for telephony rate-limit tests")

    prefix = "telephony:import:test:"
    original_fingerprint = module.telephony_credential_fingerprint

    def _test_fingerprint(provider: str, auth_id: str, api_endpoint: str) -> str:
        return prefix + original_fingerprint(provider, auth_id, api_endpoint)

    monkeypatch.setattr(module, "telephony_credential_fingerprint", _test_fingerprint)
    monkeypatch.setattr(module, "_redis_client", client)

    for key in client.scan_iter(match=f"{prefix}*"):
        client.delete(key)

    yield client

    for key in client.scan_iter(match=f"{prefix}*"):
        client.delete(key)
    module._redis_client = None


def test_telephony_credential_fingerprint_is_stable():
    fp_a = module.telephony_credential_fingerprint(
        "exotel", "auth-1", "https://api.exotel.com"
    )
    fp_b = module.telephony_credential_fingerprint(
        "exotel", "auth-1", "https://api.exotel.com"
    )
    fp_c = module.telephony_credential_fingerprint(
        "exotel", "auth-2", "https://api.exotel.com"
    )

    assert fp_a == fp_b
    assert fp_a != fp_c


def test_consume_decrements_until_exhausted(redis_client):
    fingerprint = module.telephony_credential_fingerprint(
        "exotel", "consume-test", "https://api.exotel.com"
    )

    for expected_remaining in (4, 3, 2, 1, 0):
        status = module.consume_telephony_import_credit(fingerprint)
        assert status.allowed is True
        assert status.remaining == expected_remaining

    blocked = module.consume_telephony_import_credit(fingerprint)
    assert blocked.allowed is False
    assert blocked.wait_seconds >= 1


def test_peek_does_not_consume_credits(redis_client):
    fingerprint = module.telephony_credential_fingerprint(
        "exotel", "peek-test", "https://api.exotel.com"
    )

    first = module.consume_telephony_import_credit(fingerprint)
    assert first.allowed is True
    assert first.remaining == 4

    peek = module.peek_telephony_import_credit(fingerprint)
    assert peek.allowed is True
    assert peek.remaining == 4

    second = module.consume_telephony_import_credit(fingerprint)
    assert second.allowed is True
    assert second.remaining == 3


def test_penalize_blocks_credential(redis_client):
    fingerprint = module.telephony_credential_fingerprint(
        "exotel", "penalize-test", "https://api.exotel.com"
    )

    wait = module.penalize_telephony_credential(fingerprint, retry_after_seconds=30)
    assert wait == 30

    status = module.peek_telephony_import_credit(fingerprint)
    assert status.allowed is False
    assert status.wait_seconds >= 1


def test_redis_failure_fails_open(monkeypatch):
    broken = MagicMock()
    broken.eval.side_effect = redis.RedisError("down")
    monkeypatch.setattr(module, "_get_redis", lambda: broken)

    fingerprint = module.telephony_credential_fingerprint(
        "exotel", "fail-open", "https://api.exotel.com"
    )
    status = module.consume_telephony_import_credit(fingerprint)
    assert status.allowed is True


def test_requires_authenticated_recording_fetch_only_for_exotel():
    credentialed = SimpleNamespace(
        telephony_integration_id="uuid",
        provider="exotel",
    )
    plivo = SimpleNamespace(
        telephony_integration_id="uuid",
        provider="plivo",
    )
    direct = SimpleNamespace(telephony_integration_id=None, provider=None)

    assert module.requires_authenticated_recording_fetch(credentialed) is True
    assert module.requires_authenticated_recording_fetch(plivo) is False
    assert module.requires_authenticated_recording_fetch(direct) is False
