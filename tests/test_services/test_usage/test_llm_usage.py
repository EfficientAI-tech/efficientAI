"""Tests for Redis-buffered LLM usage counters and flush durability."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
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


def _stub_stamp_cost_params(*_args, **_kwargs) -> Dict[str, Any]:
    return {
        "input_cost_micro_usd": 0,
        "output_cost_micro_usd": 0,
        "cache_read_cost_micro_usd": 0,
        "cache_creation_cost_micro_usd": 0,
        "reasoning_cost_micro_usd": 0,
        "audio_cost_micro_usd": 0,
        "tts_cost_micro_usd": 0,
        "total_cost_micro_usd": 0,
        "pricing_rate_source": None,
        "pricing_rate_id": None,
    }


@pytest.fixture(autouse=True)
def _stub_usage_cost_stamp(monkeypatch):
    monkeypatch.setattr(usage_mod, "_stamp_cost_params", _stub_stamp_cost_params)


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

    def exists(self, key: str):
        self._ops.append(("exists", key))
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
            elif kind == "exists":
                results.append(self._client.exists(op[1]))
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

    def sismember(self, key: str, member: str) -> bool:
        return member in self.sets.get(key, set())

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

    def pipeline(self):
        return _FakePipeline(self)

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
        for key in list(self.hashes.keys()) + list(self.kv.keys()):
            if key.startswith(prefix):
                yield key


@pytest.fixture(autouse=True)
def fake_redis(monkeypatch):
    """Always use in-memory Redis for this module — never touch real REDIS_URL."""
    client = _FakeRedis()
    usage_mod._redis = client
    import app.services.usage.read_cache as read_cache_mod

    read_cache_mod._redis = client

    def _forbid_real_redis(*_args, **_kwargs):
        raise AssertionError(
            "usage tests must not open real Redis; fake_redis fixture failed to isolate"
        )

    monkeypatch.setattr(usage_mod.redis, "from_url", _forbid_real_redis)
    monkeypatch.setattr(read_cache_mod.redis, "from_url", _forbid_real_redis)
    yield client
    usage_mod._redis = None
    read_cache_mod._redis = None


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


def test_record_increments_pending_and_ignores_zero_token_calls(fake_redis, org_ctx):
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
    assert calls == 1
    assert any(k.rsplit("|", 1)[0].endswith("|llm") for k in fields)


def test_record_skipped_without_organization(fake_redis):
    usage_mod.record_llm_usage(
        "gpt-test",
        UsageSnapshot(prompt_tokens=10, completion_tokens=5),
    )
    assert fake_redis.hashes == {}
    assert fake_redis.sets == {}


def test_record_with_organization_id_without_context(fake_redis):
    org_id = uuid4()
    usage_mod.record_llm_usage(
        "gpt-test",
        UsageSnapshot(prompt_tokens=3, completion_tokens=1),
        organization_id=org_id,
        usage_date=date(2026, 8, 11),
    )
    pending_key = usage_mod._pending_hash_key(org_id)
    fields = fake_redis.hgetall(pending_key)
    assert fields
    assert sum(int(v) for k, v in fields.items() if k.endswith("|call_count")) == 1
    assert any("|other|" in k for k in fields)


def test_record_call_usage(fake_redis, org_ctx):
    org_id, _workspace_id, ctx = org_ctx
    with llm_usage_context(ctx):
        usage_mod.record_call_usage(
            "voice-agent-call",
            audio_seconds=42,
            usage_date=date(2026, 8, 11),
        )

    pending_key = usage_mod._pending_hash_key(org_id)
    fields = fake_redis.hgetall(pending_key)
    audio = sum(int(v) for k, v in fields.items() if k.endswith("|audio_seconds"))
    calls = sum(int(v) for k, v in fields.items() if k.endswith("|call_count"))
    assert audio == 42
    assert calls == 1
    assert any(k.rsplit("|", 1)[0].endswith("|llm") for k in fields)


def test_agent_usage_context_reuses_single_bucket(fake_redis):
    """Stable evaluator context avoids per-call Redis/DB bucket explosion."""
    from app.services.usage.context import usage_context_for_evaluator_result

    org_id = uuid4()
    workspace_id = uuid4()
    agent_id = uuid4()
    evaluator_id = uuid4()
    prefixes = set()
    for idx in range(3):
        result = SimpleNamespace(
            id=uuid4(),
            result_id=f"res-{idx}",
            organization_id=org_id,
            workspace_id=workspace_id,
            evaluator_id=evaluator_id,
            agent_id=agent_id,
        )
        ctx = usage_context_for_evaluator_result(result)
        with llm_usage_context(ctx):
            usage_mod.record_call_usage(
                "voice-agent-call",
                audio_seconds=10,
                usage_date=date(2026, 8, 13),
            )
        fields = fake_redis.hgetall(usage_mod._pending_hash_key(org_id))
        prefixes.update(k.rsplit("|", 1)[0] for k in fields if k.endswith("|call_count"))

    assert len(prefixes) == 1
    calls = sum(int(v) for k, v in fake_redis.hgetall(usage_mod._pending_hash_key(org_id)).items() if k.endswith("|call_count"))
    assert calls == 3


def test_record_stt_usage(fake_redis, org_ctx):
    org_id, _workspace_id, ctx = org_ctx
    with llm_usage_context(ctx):
        usage_mod.record_stt_usage(
            "nova-2",
            audio_seconds=12.2,
            usage_date=date(2026, 8, 11),
        )

    pending_key = usage_mod._pending_hash_key(org_id)
    fields = fake_redis.hgetall(pending_key)
    audio = sum(int(v) for k, v in fields.items() if k.endswith("|audio_seconds"))
    calls = sum(int(v) for k, v in fields.items() if k.endswith("|call_count"))
    assert audio == 13  # ceil
    assert calls == 1
    assert any(k.rsplit("|", 1)[0].endswith("|stt") for k in fields)


def test_record_tts_usage(fake_redis, org_ctx):
    org_id, _workspace_id, ctx = org_ctx
    with llm_usage_context(ctx):
        usage_mod.record_tts_usage(
            "eleven_flash_v2_5",
            characters=142,
            usage_date=date(2026, 8, 11),
        )

    pending_key = usage_mod._pending_hash_key(org_id)
    fields = fake_redis.hgetall(pending_key)
    chars = sum(int(v) for k, v in fields.items() if k.endswith("|tts_characters"))
    calls = sum(int(v) for k, v in fields.items() if k.endswith("|call_count"))
    assert chars == 142
    assert calls == 1
    assert any(k.rsplit("|", 1)[0].endswith("|tts") for k in fields)


def test_redis_failure_buffers_to_postgres(fake_redis, org_ctx, monkeypatch):
    org_id, _workspace_id, ctx = org_ctx

    def _boom_pipeline():
        raise usage_mod.redis.RedisError("redis down")

    monkeypatch.setattr(fake_redis, "pipeline", _boom_pipeline)

    captured = {}

    def _fake_buffer(organization_id, bucket, deltas):
        captured["organization_id"] = organization_id
        captured["bucket"] = bucket
        captured["deltas"] = deltas
        return True

    monkeypatch.setattr(usage_mod, "_buffer_to_postgres", _fake_buffer)

    with llm_usage_context(ctx):
        usage_mod.record_llm_usage(
            "gpt-test",
            UsageSnapshot(prompt_tokens=4, completion_tokens=2),
            usage_date=date(2026, 8, 11),
        )

    assert captured["organization_id"] == org_id
    assert captured["deltas"]["prompt_tokens"] == 4
    assert captured["bucket"]["usage_kind"] == "llm"


def test_flush_commits_and_acks_claim(fake_redis, org_ctx, monkeypatch):
    org_id, _workspace_id, ctx = org_ctx
    with llm_usage_context(ctx):
        usage_mod.record_llm_usage(
            "gpt-test",
            UsageSnapshot(prompt_tokens=4, completion_tokens=2),
            usage_date=date(2026, 8, 11),
        )

    db = MagicMock()
    db.execute.return_value = MagicMock(rowcount=1)
    monkeypatch.setattr(usage_mod, "_flush_pending_buffer", lambda *_args, **_kwargs: 0)

    flushed = usage_mod.flush_usage_to_catalog(db, org_id)
    assert flushed == 1
    db.commit.assert_called_once()
    assert usage_mod._pending_hash_key(org_id) not in fake_redis.hashes
    assert not any(k.startswith("usage:flushing:") for k in fake_redis.hashes)
    assert str(org_id) not in fake_redis.smembers("usage:pending:orgs")
    assert fake_redis.get(usage_mod._flush_lock_key(org_id)) is None


def test_flush_restores_redis_when_db_fails(fake_redis, org_ctx, monkeypatch):
    org_id, _workspace_id, ctx = org_ctx
    with llm_usage_context(ctx):
        usage_mod.record_llm_usage(
            "gpt-test",
            UsageSnapshot(prompt_tokens=7, completion_tokens=3),
            usage_date=date(2026, 8, 11),
        )

    db = MagicMock()
    db.execute.side_effect = RuntimeError("db down")
    monkeypatch.setattr(usage_mod, "_flush_pending_buffer", lambda *_args, **_kwargs: 0)

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


def test_flush_restores_redis_when_committed_claim_insert_fails(
    fake_redis, org_ctx, monkeypatch
):
    """Committed-claim insert must share the usage transaction; failure rolls back."""
    org_id, _workspace_id, ctx = org_ctx
    with llm_usage_context(ctx):
        usage_mod.record_llm_usage(
            "gpt-test",
            UsageSnapshot(prompt_tokens=5, completion_tokens=2),
            usage_date=date(2026, 8, 11),
        )

    db = MagicMock()

    def _execute_side_effect(statement, *_args, **_kwargs):
        if "usage_committed_claims" in str(statement):
            raise RuntimeError("usage_committed_claims unavailable")
        return MagicMock(rowcount=0)

    db.execute.side_effect = _execute_side_effect
    monkeypatch.setattr(usage_mod, "_flush_pending_buffer", lambda *_args, **_kwargs: 0)

    flushed = usage_mod.flush_usage_to_catalog(db, org_id)
    assert flushed == 0
    db.rollback.assert_called()
    db.commit.assert_not_called()

    pending = fake_redis.hgetall(usage_mod._pending_hash_key(org_id))
    prompt = sum(int(v) for k, v in pending.items() if k.endswith("|prompt_tokens"))
    assert prompt == 5
    assert str(org_id) in fake_redis.smembers("usage:pending:orgs")


def test_flush_drops_pending_when_organization_missing(fake_redis, org_ctx, monkeypatch):
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
    monkeypatch.setattr(usage_mod, "_flush_pending_buffer", lambda *_args, **_kwargs: 0)

    flushed = usage_mod.flush_usage_to_catalog(db, org_id)
    assert flushed == 0
    db.rollback.assert_called()
    assert usage_mod._pending_hash_key(org_id) not in fake_redis.hashes
    assert str(org_id) not in fake_redis.smembers("usage:pending:orgs")
    assert not any(k.startswith("usage:flushing:") for k in fake_redis.hashes)


def test_concurrent_flush_does_not_double_count(fake_redis, org_ctx, monkeypatch):
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
    monkeypatch.setattr(usage_mod, "_flush_pending_buffer", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(usage_mod, "_stamp_cost_params", _stub_stamp_cost_params)

    first = usage_mod.flush_usage_to_catalog(db_a, org_id)
    second = usage_mod.flush_usage_to_catalog(db_b, org_id)

    assert first == 1
    assert second == 0
    assert db_a.commit.call_count == 1
    assert db_b.commit.call_count == 0
    # One bucket upsert (2 UPDATE misses + SAVEPOINT/INSERT/RELEASE) plus committed-claim row.
    assert db_a.execute.call_count == 6
    assert db_b.execute.call_count == 0


def test_split_buckets_for_flush():
    buckets = {f"prefix-{idx}": {"prompt_tokens": idx} for idx in range(5)}
    batch, remainder = usage_mod._split_buckets_for_flush(buckets, 2)
    assert len(batch) == 2
    assert len(remainder) == 3
    assert set(batch) | set(remainder) == set(buckets)


def test_flush_redis_processes_multiple_batches_in_one_run(
    fake_redis, org_ctx, monkeypatch
):
    org_id, workspace_id, base_ctx = org_ctx
    monkeypatch.setenv("USAGE_FLUSH_BUCKET_BATCH_SIZE", "2")
    monkeypatch.setenv("USAGE_FLUSH_MAX_BATCHES_PER_RUN", "10")

    for idx in range(5):
        ctx = LLMUsageContext(
            organization_id=base_ctx.organization_id,
            workspace_id=workspace_id,
            product_section=base_ctx.product_section,
            resource_id=uuid4(),
            resource_type="call_import_evaluation",
        )
        with llm_usage_context(ctx):
            usage_mod.record_llm_usage(
                "gpt-test",
                UsageSnapshot(prompt_tokens=idx + 1, completion_tokens=1),
                usage_date=date(2026, 8, 11),
            )

    db = MagicMock()
    db.execute.return_value = MagicMock(rowcount=1)
    monkeypatch.setattr(usage_mod, "_flush_pending_buffer", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(usage_mod, "_stamp_cost_params", _stub_stamp_cost_params)

    flushed = usage_mod.flush_usage_to_catalog(db, org_id)

    assert flushed == 5
    assert db.commit.call_count == 3
    assert usage_mod._pending_hash_key(org_id) not in fake_redis.hashes
    assert not any(k.startswith("usage:flushing:") for k in fake_redis.hashes)
    assert str(org_id) not in fake_redis.smembers("usage:pending:orgs")


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


def test_parse_legacy_resource_bucket_prefix():
    rid = uuid4()
    parsed = usage_mod._parse_bucket_prefix(
        f"{uuid4()}|call_imports|nova-2|{rid}|call_import|2026-08-11|stt"
    )
    assert parsed is not None
    assert parsed["usage_kind"] == "stt"
    assert parsed["context"]["resource_id"] == str(rid)
    assert parsed["context"]["resource_type"] == "call_import"


def test_parse_context_bucket_prefix():
    ctx = '{"resource_id":"00000000-0000-0000-0000-000000000001","resource_type":"call_import_evaluation"}'
    parsed = usage_mod._parse_bucket_prefix(
        f"{uuid4()}|call_imports|gpt-4|{ctx}|2026-08-11|llm"
    )
    assert parsed is not None
    assert parsed["usage_kind"] == "llm"
    assert parsed["context"]["resource_id"] == "00000000-0000-0000-0000-000000000001"


def test_upsert_bucket_sql_uses_valid_empty_jsonb_literal():
    """Regression: '{{}}'::jsonb is invalid JSON and breaks catalog flush."""
    import inspect

    source = inspect.getsource(usage_mod._upsert_bucket)
    assert "'{{}}'::jsonb" not in source
    assert "'{}'::jsonb" in source


def test_upsert_bucket_matches_legacy_resource_context_key(monkeypatch):
    """Per-row context must merge into an existing evaluation-level bucket."""
    org_id = uuid4()
    evaluation_id = uuid4()
    bucket = {
        "workspace_id": uuid4(),
        "product_section": "call_import_evaluations",
        "model": "gpt-test",
        "context": {
            "resource_id": str(evaluation_id),
            "resource_type": "call_import_evaluation",
            "evaluation_row_id": str(uuid4()),
        },
        "usage_date": date(2026, 8, 12),
        "usage_kind": "llm",
    }
    deltas = {"prompt_tokens": 10, "completion_tokens": 5, "call_count": 1}

    exact_update = MagicMock(rowcount=0)
    legacy_update = MagicMock(rowcount=1)
    db = MagicMock()
    db.execute.side_effect = [exact_update, legacy_update]

    usage_mod._upsert_bucket(db, org_id, bucket, deltas)

    assert db.execute.call_count == 2
    legacy_sql = str(db.execute.call_args_list[1][0][0])
    assert "context->>'resource_id'" in legacy_sql
    assert "context->>'resource_type'" in legacy_sql


def test_upsert_bucket_increments_cost_on_update(monkeypatch):
    org_id = uuid4()
    bucket = {
        "workspace_id": uuid4(),
        "product_section": "chat",
        "model": "gpt-test",
        "context": {},
        "usage_date": date(2026, 8, 12),
        "usage_kind": "llm",
    }
    deltas = {"prompt_tokens": 10, "completion_tokens": 5, "call_count": 1}
    db = MagicMock()
    db.execute.return_value = MagicMock(rowcount=1)
    monkeypatch.setattr(
        usage_mod,
        "_stamp_cost_params",
        lambda *args, **kwargs: {
            "input_cost_micro_usd": 100,
            "output_cost_micro_usd": 200,
            "cache_read_cost_micro_usd": 0,
            "cache_creation_cost_micro_usd": 0,
            "reasoning_cost_micro_usd": 0,
            "audio_cost_micro_usd": 0,
            "tts_cost_micro_usd": 0,
            "total_cost_micro_usd": 300,
            "pricing_rate_source": "catalog",
            "pricing_rate_id": str(uuid4()),
        },
    )

    usage_mod._upsert_bucket(db, org_id, bucket, deltas)

    update_sql = str(db.execute.call_args[0][0])
    assert "input_cost_micro_usd = input_cost_micro_usd + :input_cost_micro_usd" in update_sql
    assert "total_cost_micro_usd = total_cost_micro_usd + :total_cost_micro_usd" in update_sql


def test_record_llm_usage_skips_zero_token_snapshot(fake_redis, monkeypatch):
    org_id = uuid4()
    monkeypatch.setattr(usage_mod, "_client", lambda: fake_redis)
    usage_mod.record_llm_usage(
        "gpt-test",
        UsageSnapshot(prompt_tokens=0, completion_tokens=0),
        organization_id=org_id,
        ctx=LLMUsageContext(
            organization_id=org_id,
            product_section=LLMUsageProductSection.CHAT,
        ),
    )
    assert not fake_redis.hgetall(usage_mod._pending_hash_key(org_id))


def test_orphan_recovery_runs_at_most_once_per_interval(fake_redis, monkeypatch):
    org_id = uuid4()
    claim_key = f"usage:flushing:{org_id}:{uuid4()}"
    fake_redis.hashes[claim_key] = {"bucket|prompt_tokens": 3}

    pg_lookups = 0

    def _count_pg_lookup(keys):
        nonlocal pg_lookups
        pg_lookups += 1
        return set()

    monkeypatch.setattr(usage_mod, "_committed_claim_keys_in_pg", _count_pg_lookup)
    monkeypatch.setattr(usage_mod, "_prune_old_committed_claims", lambda: None)

    usage_mod._recover_orphaned_claims()
    usage_mod._recover_orphaned_claims()

    assert pg_lookups == 1
