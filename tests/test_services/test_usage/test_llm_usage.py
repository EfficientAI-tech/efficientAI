"""Tests for Redis-buffered LLM usage counters and flush durability."""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.services.usage import llm_usage as usage_mod
from app.services.usage.context import (
    LLMUsageContext,
    LLMUsageProductSection,
    ensure_usage_context,
    get_usage_context,
    infer_product_section_from_path,
    llm_usage_context,
    reset_usage_context,
    set_usage_context,
)
from app.services.usage.normalize import UsageSnapshot


class _FakePipeline:
    def __init__(self, client: "_FakeRedis"):
        self._client = client
        self._ops: List[tuple] = []

    def hincrby(self, key: str, field: str, amount: int):
        self._ops.append(("hincrby", key, field, amount))
        return self

    def sadd(self, key: str, *members: str):
        self._ops.append(("sadd", key, members))
        return self

    def expire(self, key: str, ttl: int):
        self._ops.append(("expire", key, ttl))
        return self

    def execute(self):
        results = []
        for op in self._ops:
            kind = op[0]
            if kind == "hincrby":
                results.append(self._client.hincrby(op[1], op[2], op[3]))
            elif kind == "sadd":
                results.append(self._client.sadd(op[1], *op[2]))
            elif kind == "expire":
                results.append(self._client.expire(op[1], op[2]))
        self._ops.clear()
        return results


class _FakeRedis:
    """Minimal Redis stand-in for usage counter tests."""

    def __init__(self):
        self.hashes: Dict[str, Dict[str, int]] = {}
        self.sets: Dict[str, set] = {}
        self.kv: Dict[str, str] = {}

    def pipeline(self):
        return _FakePipeline(self)

    def hincrby(self, key: str, field: str, amount: int) -> int:
        bucket = self.hashes.setdefault(key, {})
        bucket[field] = int(bucket.get(field, 0)) + int(amount)
        return bucket[field]

    def hgetall(self, key: str) -> Dict[str, str]:
        return {k: str(v) for k, v in self.hashes.get(key, {}).items()}

    def hdel(self, key: str, *fields: str) -> int:
        bucket = self.hashes.get(key, {})
        deleted = 0
        for field in fields:
            if field in bucket:
                del bucket[field]
                deleted += 1
        if key in self.hashes and not self.hashes[key]:
            del self.hashes[key]
        return deleted

    def hlen(self, key: str) -> int:
        return len(self.hashes.get(key, {}))

    def sadd(self, key: str, *members: str) -> int:
        s = self.sets.setdefault(key, set())
        before = len(s)
        s.update(members)
        return len(s) - before

    def srem(self, key: str, *members: str) -> int:
        s = self.sets.get(key, set())
        removed = 0
        for member in members:
            if member in s:
                s.remove(member)
                removed += 1
        return removed

    def smembers(self, key: str) -> set:
        return set(self.sets.get(key, set()))

    def exists(self, key: str) -> int:
        return int(key in self.hashes or key in self.sets or key in self.kv)

    def delete(self, *keys: str) -> int:
        deleted = 0
        for key in keys:
            if key in self.hashes:
                del self.hashes[key]
                deleted += 1
            if key in self.sets:
                del self.sets[key]
                deleted += 1
            if key in self.kv:
                del self.kv[key]
                deleted += 1
        return deleted

    def expire(self, key: str, ttl: int) -> bool:
        return self.exists(key) == 1

    def set(self, key: str, value: str, nx: bool = False, ex: Optional[int] = None) -> Optional[bool]:
        if nx and key in self.kv:
            return None
        self.kv[key] = value
        return True

    def get(self, key: str) -> Optional[str]:
        return self.kv.get(key)

    def rename(self, src: str, dst: str) -> bool:
        if src not in self.hashes:
            raise KeyError(src)
        self.hashes[dst] = self.hashes.pop(src)
        return True

    def eval(self, script: str, numkeys: int, *keys_and_args: Any) -> int:
        pending, claim = keys_and_args[0], keys_and_args[1]
        if pending not in self.hashes:
            return 0
        self.rename(pending, claim)
        return 1

    def scan_iter(self, match: str = "*", count: int = 100):
        prefix = match.rstrip("*")
        for key in list(self.hashes.keys()):
            if key.startswith(prefix):
                yield key


@pytest.fixture(autouse=True)
def fake_redis(monkeypatch):
    """Always use in-memory Redis for this module — never touch real REDIS_URL."""
    client = _FakeRedis()
    usage_mod._redis = client

    def _forbid_real_redis(*_args, **_kwargs):
        raise AssertionError(
            "usage tests must not open real Redis; fake_redis fixture failed to isolate"
        )

    monkeypatch.setattr(usage_mod.redis, "from_url", _forbid_real_redis)
    yield client
    usage_mod._redis = None


@pytest.fixture
def org_ctx():
    org_id = uuid4()
    workspace_id = uuid4()
    ctx = LLMUsageContext(
        organization_id=org_id,
        workspace_id=workspace_id,
        product_section=LLMUsageProductSection.CALL_IMPORT_EVALUATIONS,
        resource_id=uuid4(),
        resource_type="call_import_evaluation",
    )
    return org_id, workspace_id, ctx


def test_record_increments_pending_and_counts_zero_token_calls(fake_redis, org_ctx):
    org_id, _workspace_id, ctx = org_ctx
    with llm_usage_context(ctx):
        usage_mod.record_llm_usage(
            "gpt-test",
            UsageSnapshot(prompt_tokens=10, completion_tokens=5),
            usage_date=date(2026, 8, 11),
        )
        usage_mod.record_llm_usage(
            "gpt-test",
            UsageSnapshot(prompt_tokens=0, completion_tokens=0),
            usage_date=date(2026, 8, 11),
        )

    pending_key = usage_mod._pending_hash_key(org_id)
    fields = fake_redis.hgetall(pending_key)
    assert str(org_id) in fake_redis.smembers("usage:pending:orgs")

    prompt = sum(int(v) for k, v in fields.items() if k.endswith("|prompt_tokens"))
    completion = sum(
        int(v) for k, v in fields.items() if k.endswith("|completion_tokens")
    )
    calls = sum(int(v) for k, v in fields.items() if k.endswith("|call_count"))
    assert prompt == 10
    assert completion == 5
    assert calls == 2


def test_record_skipped_without_context(fake_redis):
    usage_mod.record_llm_usage(
        "gpt-test",
        UsageSnapshot(prompt_tokens=10, completion_tokens=5),
    )
    assert fake_redis.hashes == {}
    assert fake_redis.sets == {}


def test_flush_commits_and_acks_claim(fake_redis, org_ctx):
    org_id, _workspace_id, ctx = org_ctx
    with llm_usage_context(ctx):
        usage_mod.record_llm_usage(
            "gpt-test",
            UsageSnapshot(prompt_tokens=4, completion_tokens=2),
            usage_date=date(2026, 8, 11),
        )

    db = MagicMock()
    db.execute.return_value = MagicMock(rowcount=1)

    flushed = usage_mod.flush_usage_to_catalog(db, org_id)
    assert flushed == 1
    db.commit.assert_called_once()
    assert usage_mod._pending_hash_key(org_id) not in fake_redis.hashes
    assert not any(k.startswith("usage:flushing:") for k in fake_redis.hashes)
    assert str(org_id) not in fake_redis.smembers("usage:pending:orgs")
    assert fake_redis.get(usage_mod._flush_lock_key(org_id)) is None


def test_flush_restores_redis_when_db_fails(fake_redis, org_ctx):
    org_id, _workspace_id, ctx = org_ctx
    with llm_usage_context(ctx):
        usage_mod.record_llm_usage(
            "gpt-test",
            UsageSnapshot(prompt_tokens=7, completion_tokens=3),
            usage_date=date(2026, 8, 11),
        )

    db = MagicMock()
    db.execute.side_effect = RuntimeError("db down")

    flushed = usage_mod.flush_usage_to_catalog(db, org_id)
    assert flushed == 0
    db.rollback.assert_called()
    db.commit.assert_not_called()

    pending = fake_redis.hgetall(usage_mod._pending_hash_key(org_id))
    prompt = sum(int(v) for k, v in pending.items() if k.endswith("|prompt_tokens"))
    completion = sum(
        int(v) for k, v in pending.items() if k.endswith("|completion_tokens")
    )
    assert prompt == 7
    assert completion == 3
    assert str(org_id) in fake_redis.smembers("usage:pending:orgs")
    assert not any(k.startswith("usage:flushing:") for k in fake_redis.hashes)


def test_flush_drops_pending_when_organization_missing(fake_redis, org_ctx):
    """Unknown org FK must not restore Redis (avoids infinite beat retries)."""
    from sqlalchemy.exc import IntegrityError

    org_id, _workspace_id, ctx = org_ctx
    with llm_usage_context(ctx):
        usage_mod.record_llm_usage(
            "gpt-test",
            UsageSnapshot(prompt_tokens=3, completion_tokens=1),
            usage_date=date(2026, 8, 11),
        )

    db = MagicMock()
    db.execute.side_effect = IntegrityError(
        "INSERT",
        {},
        Exception(
            'insert or update on table "llm_usage_daily" violates foreign key '
            'constraint "llm_usage_daily_organization_id_fkey"'
        ),
    )

    flushed = usage_mod.flush_usage_to_catalog(db, org_id)
    assert flushed == 0
    db.rollback.assert_called()
    assert usage_mod._pending_hash_key(org_id) not in fake_redis.hashes
    assert str(org_id) not in fake_redis.smembers("usage:pending:orgs")
    assert not any(k.startswith("usage:flushing:") for k in fake_redis.hashes)


def test_concurrent_flush_does_not_double_count(fake_redis, org_ctx):
    org_id, _workspace_id, ctx = org_ctx
    with llm_usage_context(ctx):
        usage_mod.record_llm_usage(
            "gpt-test",
            UsageSnapshot(prompt_tokens=9, completion_tokens=1),
            usage_date=date(2026, 8, 11),
        )

    db_a = MagicMock()
    db_a.execute.return_value = MagicMock(rowcount=0)  # force INSERT path
    db_b = MagicMock()
    db_b.execute.return_value = MagicMock(rowcount=1)

    first = usage_mod.flush_usage_to_catalog(db_a, org_id)
    second = usage_mod.flush_usage_to_catalog(db_b, org_id)

    assert first == 1
    assert second == 0
    assert db_a.commit.call_count == 1
    assert db_b.commit.call_count == 0
    # INSERT once for the claimed bucket; second flusher never upserts.
    assert db_a.execute.call_count == 2  # UPDATE miss + INSERT
    assert db_b.execute.call_count == 0


def test_ensure_usage_context_and_path_inference():
    assert (
        infer_product_section_from_path("/api/v1/call-imports/abc")
        == LLMUsageProductSection.CALL_IMPORTS
    )
    assert (
        infer_product_section_from_path("/api/v1/chat/completion")
        == LLMUsageProductSection.CHAT
    )
    assert (
        infer_product_section_from_path("/api/v1/unknown")
        == LLMUsageProductSection.OTHER
    )

    org_id = uuid4()
    workspace_id = uuid4()
    token = set_usage_context(None)
    try:
        assert get_usage_context() is None
        created = ensure_usage_context(
            org_id,
            product_section=LLMUsageProductSection.PLAYGROUND,
        )
        assert created is not None
        assert get_usage_context().organization_id == org_id
        assert get_usage_context().product_section == LLMUsageProductSection.PLAYGROUND

        # Enrich missing workspace / upgrade OTHER section.
        upgraded = ensure_usage_context(
            org_id,
            workspace_id=workspace_id,
            product_section=LLMUsageProductSection.CHAT,
        )
        assert upgraded is not None
        assert get_usage_context().workspace_id == workspace_id
        # Existing non-OTHER section is preserved.
        assert get_usage_context().product_section == LLMUsageProductSection.PLAYGROUND
    finally:
        reset_usage_context(token)


def test_ensure_uses_workspace_and_section_hints():
    from app.services.usage.context import reset_usage_hints, set_usage_hints

    org_id = uuid4()
    workspace_id = uuid4()
    ctx_token = set_usage_context(None)
    hint_tokens = set_usage_hints(
        workspace_id=workspace_id,
        product_section=LLMUsageProductSection.METRICS,
    )
    try:
        created = ensure_usage_context(org_id)
        assert created is not None
        assert get_usage_context().workspace_id == workspace_id
        assert get_usage_context().product_section == LLMUsageProductSection.METRICS
    finally:
        reset_usage_hints(hint_tokens)
        reset_usage_context(ctx_token)
