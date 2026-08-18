"""Tests for usage read cache."""

from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest

from app.core.usage_entitlement import UsagePolicySnapshot
from app.services.usage import read_cache as cache_mod
from app.services.usage.access import UsageAccessResult
from app.services.usage.read_cache import (
    cache_key_for,
    get_cached_response,
    invalidate_org_usage_read_cache,
    set_cached_response,
)
from tests.test_services.test_usage.test_llm_usage import _FakeRedis


@pytest.fixture
def fake_redis(monkeypatch):
    client = _FakeRedis()
    cache_mod._redis = client
    monkeypatch.setattr(cache_mod.redis, "from_url", lambda *_args, **_kwargs: client)
    yield client
    cache_mod._redis = None


def _access() -> UsageAccessResult:
    policy = UsagePolicySnapshot(extended_history=False, max_history_days=7)
    return UsageAccessResult(
        display_start=date(2026, 8, 1),
        display_end=date(2026, 8, 7),
        filter_start=date(2026, 8, 1),
        filter_end=date(2026, 8, 8),
        enforced_filter_floor=date(2026, 8, 1),
        policy=policy,
        range_clamped=False,
    )


def test_usage_read_cache_skips_empty_summary(fake_redis, monkeypatch):
    org_id = uuid4()
    access = _access()
    key = cache_key_for(access)
    empty = {
        "start": "2026-08-15",
        "end": "2026-08-15",
        "totals": {"prompt_tokens": 0, "completion_tokens": 0, "call_count": 0},
    }
    set_cached_response(org_id, "summary", key, empty)
    assert get_cached_response(org_id, "summary", key) is None


def test_usage_read_cache_round_trip(fake_redis, monkeypatch):
    org_id = uuid4()
    access = _access()
    key = cache_key_for(access, workspace_id=None)
    payload = {
        "start": "2026-08-01",
        "end": "2026-08-07",
        "totals": {"prompt_tokens": 10, "completion_tokens": 5, "call_count": 1},
    }

    set_cached_response(org_id, "summary", key, payload)
    cached = get_cached_response(org_id, "summary", key)

    assert cached == payload


def test_usage_read_cache_invalidate_org(fake_redis, monkeypatch):
    org_id = uuid4()
    other_org = uuid4()
    access = _access()
    key = cache_key_for(access)
    payload = {
        "start": "2026-08-01",
        "end": "2026-08-07",
        "totals": {"prompt_tokens": 10, "completion_tokens": 5, "call_count": 1},
    }

    set_cached_response(org_id, "summary", key, payload)
    set_cached_response(other_org, "summary", key, payload)

    deleted = invalidate_org_usage_read_cache(org_id)

    assert deleted >= 1
    assert get_cached_response(org_id, "summary", key) is None
    assert get_cached_response(other_org, "summary", key) is not None
