"""Tests for usage bucket context helpers."""

from uuid import uuid4

from app.services.usage.bucket_context import (
    build_bucket_context,
    context_bucket_token,
    legacy_resource_context,
    parse_context_bucket_token,
    resource_id_from_context,
)


def test_build_and_parse_context_roundtrip():
    rid = uuid4()
    ctx = build_bucket_context(
        resource_id=rid,
        resource_type="call_import_evaluation",
        extra={"agent_id": str(uuid4())},
    )
    token = context_bucket_token(ctx)
    parsed = parse_context_bucket_token(token)
    assert parsed["resource_id"] == str(rid)
    assert parsed["resource_type"] == "call_import_evaluation"
    assert "agent_id" in parsed


def test_extra_rejects_metric_keys():
    ctx = build_bucket_context(
        resource_id=uuid4(),
        extra={"prompt_tokens": "999", "agent_id": str(uuid4())},
    )
    assert "prompt_tokens" not in ctx
    assert "agent_id" in ctx


def test_legacy_resource_context():
    rid = uuid4()
    ctx = legacy_resource_context(rid, "call_import")
    assert resource_id_from_context(ctx) == rid
