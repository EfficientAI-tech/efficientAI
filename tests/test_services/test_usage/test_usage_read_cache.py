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
    get_or_compute_cached_response,
    historical_cache_ttl_seconds,
    invalidate_org_usage_read_cache,
    read_cache_version,
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


def test_usage_read_cache_stores_empty_summary(fake_redis, monkeypatch):
    org_id = uuid4()
    access = _access()
    key = cache_key_for(access)
    empty = {
        "start": "2026-08-15",
        "end": "2026-08-15",
        "totals": {"prompt_tokens": 0, "completion_tokens": 0, "call_count": 0},
    }
    seen = []

    def _set(key_name, value, nx=False, ex=None):
        seen.append(ex)
        return fake_redis.__class__.set(fake_redis, key_name, value, nx=nx, ex=ex)

    monkeypatch.setattr(fake_redis, "set", _set)
    set_cached_response(org_id, "summary", key, empty)
    assert get_cached_response(org_id, "summary", key) == empty
    assert 60 in seen


def test_usage_read_cache_uses_longer_ttl_for_closed_history(fake_redis, monkeypatch):
    org_id = uuid4()
    access = _access()
    key = cache_key_for(access)
    payload = {
        "start": "2026-08-01",
        "end": "2026-08-07",
        "totals": {"prompt_tokens": 10, "completion_tokens": 5, "call_count": 1},
    }
    seen = []

    def _set(key_name, value, nx=False, ex=None):
        seen.append(ex)
        return fake_redis.__class__.set(fake_redis, key_name, value, nx=nx, ex=ex)

    monkeypatch.setattr(fake_redis, "set", _set)
    set_cached_response(org_id, "summary", key, payload, historical=True)
    assert historical_cache_ttl_seconds() in seen
    assert 900 in seen
    assert 1020 in seen


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


def test_usage_read_cache_discards_write_when_epoch_changes(fake_redis):
    org_id = uuid4()
    access = _access()
    key = cache_key_for(access)
    payload = {
        "start": "2026-08-01",
        "end": "2026-08-07",
        "totals": {"prompt_tokens": 10, "completion_tokens": 5, "call_count": 1},
    }
    version = read_cache_version(org_id)
    invalidate_org_usage_read_cache(org_id)
    set_cached_response(org_id, "summary", key, payload, version=version)
    assert get_cached_response(org_id, "summary", key) is None
    assert fake_redis.get(f"usage:read_stale:{org_id}:summary:{key}") is None


def test_usage_read_cache_epoch_invalidation_is_a_version_bump(fake_redis):
    org_id = uuid4()
    before = fake_redis.get(f"usage:read_ver:{org_id}")
    invalidate_org_usage_read_cache(org_id)
    after = fake_redis.get(f"usage:read_ver:{org_id}")
    assert before is None
    assert after == "1"
    invalidate_org_usage_read_cache(org_id)
    assert fake_redis.get(f"usage:read_ver:{org_id}") == "2"


def test_follower_uses_stale_payload_instead_of_recomputing(fake_redis):
    org_id = uuid4()
    access = _access()
    key = cache_key_for(access)
    stale = {"totals": {"prompt_tokens": 4, "completion_tokens": 1, "call_count": 1}}
    fake_redis.set(f"usage:read_stale:{org_id}:summary:{key}", __import__("json").dumps(stale))
    fake_redis.set(f"usage:read_lock:{org_id}:summary:{key}", "1", nx=True, ex=10)
    calls = {"n": 0}

    def compute():
        calls["n"] += 1
        return {"totals": {"prompt_tokens": 9, "completion_tokens": 1, "call_count": 1}}

    payload = get_or_compute_cached_response(org_id, "summary", key, compute)
    assert payload == stale
    assert calls["n"] == 0


def test_context_merge_preaggregates_full_bucket_keys_without_dropping_other_dates():
    from app.services.usage.rollup_maintenance import (
        backfill_usage_context_keys,
        merge_staged_usage_context,
        repair_orphaned_row_context,
    )
    import inspect

    statements = []

    class _DB:
        def execute(self, statement, params=None):
            statements.append(str(statement))
            return None

    merge_staged_usage_context(_DB())
    blob = "\n".join(statements)
    assert "GROUP BY keeper_id" in blob
    assert "src.usage_date" in blob
    assert "src.model" in blob
    assert "DELETE FROM llm_usage_daily AS src" in blob
    assert "keeper.context = patch.new_context" in blob
    assert "SET context = patch.new_context" in blob
    # Must never delete from usage_ctx_patch by new_context alone across dates/models
    assert "WHERE drop_patch.new_context = keep_patch.new_context\n              AND drop_patch.src_id > keep_patch.src_id" not in blob

    backfill_src = inspect.getsource(backfill_usage_context_keys)
    assert "call_import_rows" in backfill_src
    assert "call_import_evaluation_rows" in backfill_src

    from app.services.usage import rollup_maintenance as rollup_mod

    shard_src = inspect.getsource(repair_orphaned_row_context)
    orphan_sql = rollup_mod._IMPORT_ORPHAN_SQL + rollup_mod._EVAL_ORPHAN_SQL
    assert "CAST(:ids AS uuid[])" in shard_src
    assert "WHERE id::text = ANY" not in shard_src
    assert "range(20)" not in shard_src
    assert "import_cursor" in shard_src
    assert "ORDER BY 1" in orphan_sql
    assert ":cursor" in orphan_sql
