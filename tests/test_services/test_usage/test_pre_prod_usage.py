from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.usage.context import (
    LLMUsageProductSection,
    usage_context_for_evaluator_result,
    usage_context_for_metric_studio_run,
    usage_context_for_persona_generation,
)
from app.services.usage.external_agent_usage import (
    extract_external_agent_usage,
    record_external_agent_usage,
)


@pytest.fixture
def fake_redis(monkeypatch):
    class _FakeRedis:
        def __init__(self):
            self.hashes = {}

        def hincrby(self, key, field, amount):
            self.hashes.setdefault(key, {})
            self.hashes[key][field] = int(self.hashes[key].get(field, 0)) + int(amount)

        def hgetall(self, key):
            return dict(self.hashes.get(key, {}))

        def sadd(self, key, member):
            return True

        def smembers(self, key):
            return set()

        def expire(self, key, ttl):
            return True

        def pipeline(self):
            client = self

            class _Pipe:
                def hincrby(self, key, field, amount):
                    client.hincrby(key, field, amount)
                    return self

                def sadd(self, key, member):
                    return self

                def expire(self, key, ttl):
                    return self

                def execute(self):
                    return []

            return _Pipe()

    client = _FakeRedis()
    from app.services.usage import llm_usage as usage_mod
    import app.services.usage.read_cache as read_cache_mod

    usage_mod._redis = client
    read_cache_mod._redis = client

    def _forbid_real_redis(*_args, **_kwargs):
        raise AssertionError("usage tests must not open real Redis")

    monkeypatch.setattr(usage_mod.redis, "from_url", _forbid_real_redis)
    monkeypatch.setattr(read_cache_mod.redis, "from_url", _forbid_real_redis)
    yield client
    usage_mod._redis = None
    read_cache_mod._redis = None


def test_usage_context_for_evaluator_result_uses_evaluators_section():
    org_id = uuid4()
    workspace_id = uuid4()
    agent_id = uuid4()
    evaluator_id = uuid4()
    persona_id = uuid4()
    scenario_id = uuid4()
    result_id = uuid4()

    ctx = usage_context_for_evaluator_result(
        SimpleNamespace(
            id=result_id,
            result_id="res-42",
            organization_id=org_id,
            workspace_id=workspace_id,
            agent_id=agent_id,
            evaluator_id=evaluator_id,
            persona_id=persona_id,
            scenario_id=scenario_id,
            provider_platform="vapi",
        )
    )

    assert ctx.product_section == LLMUsageProductSection.EVALUATORS
    assert ctx.resource_id == evaluator_id
    assert ctx.resource_type == "evaluator"
    assert ctx.extra["agent_id"] == str(agent_id)
    assert ctx.extra["evaluator_id"] == str(evaluator_id)
    assert ctx.extra["persona_id"] == str(persona_id)
    assert ctx.extra["scenario_id"] == str(scenario_id)
    assert ctx.extra["synthetic_testing"] == "pre_prod"
    assert ctx.extra["provider_platform"] == "vapi"


def test_usage_context_for_metric_studio_run():
    run_id = uuid4()
    org_id = uuid4()
    workspace_id = uuid4()
    result_row_id = uuid4()

    run = SimpleNamespace(
        id=run_id,
        organization_id=org_id,
        workspace_id=workspace_id,
    )

    ctx = usage_context_for_metric_studio_run(
        run,
        source_kind="evaluator_result",
        source_ref=str(uuid4()),
        result_row_id=result_row_id,
    )

    assert ctx.product_section == LLMUsageProductSection.METRICS
    assert ctx.resource_id == run_id
    assert ctx.resource_type == "metric_studio_run"
    assert ctx.extra["metric_studio_run_id"] == str(run_id)
    assert ctx.extra["metric_studio_result_id"] == str(result_row_id)
    assert ctx.extra["source_kind"] == "evaluator_result"
    assert ctx.extra["synthetic_testing"] == "pre_prod"


def test_usage_context_for_persona_generation():
    org_id = uuid4()
    workspace_id = uuid4()
    agent_id = uuid4()
    agent = SimpleNamespace(
        id=agent_id,
        organization_id=org_id,
        workspace_id=workspace_id,
    )

    ctx = usage_context_for_persona_generation(agent, workspace_id=workspace_id)

    assert ctx.product_section == LLMUsageProductSection.PERSONAS
    assert ctx.resource_id == agent_id
    assert ctx.extra["agent_id"] == str(agent_id)
    assert ctx.extra["synthetic_testing"] == "pre_prod"


def test_extract_external_agent_usage_retell():
    call_data = {
        "llm_token_usage": {"values": [1200, 800, 500], "average": 833, "num_requests": 3},
        "call_cost": {"total_duration_seconds": 95},
        "model": "gpt-4.1",
    }
    extracted = extract_external_agent_usage(call_data, platform="retell")
    assert extracted is not None
    assert extracted.model == "gpt-4.1"
    assert extracted.llm.prompt_tokens == 1750
    assert extracted.llm.completion_tokens == 750
    assert extracted.stt_audio_seconds == 95


def test_extract_external_agent_usage_retell_explicit_split():
    call_data = {
        "llm_token_usage": {
            "values": [900],
            "prompt_tokens": 600,
            "completion_tokens": 300,
        },
        "call_cost": {"total_duration_seconds": 30},
    }
    extracted = extract_external_agent_usage(call_data, platform="retell")
    assert extracted is not None
    assert extracted.llm.prompt_tokens == 600
    assert extracted.llm.completion_tokens == 300


def test_usage_context_for_evaluator_result_playground_section():
    ctx = usage_context_for_evaluator_result(
        SimpleNamespace(
            id=uuid4(),
            result_id="res-playground",
            organization_id=uuid4(),
            workspace_id=uuid4(),
            agent_id=uuid4(),
            evaluator_id=None,
            persona_id=None,
            scenario_id=None,
            provider_platform="vapi",
        )
    )
    assert ctx.product_section == LLMUsageProductSection.PLAYGROUND


def test_record_external_agent_usage_returns_false_when_storage_fails(fake_redis, monkeypatch):
    from app.services.usage import llm_usage as usage_mod
    from app.services.usage.context import usage_context_for_playground_voice_call

    org_id = uuid4()
    agent_id = uuid4()
    usage_ctx = usage_context_for_playground_voice_call(
        organization_id=org_id,
        workspace_id=uuid4(),
        agent_id=agent_id,
        provider_platform="vapi",
        call_short_id="abc123",
    )
    result = SimpleNamespace(
        organization_id=org_id,
        provider_platform="vapi",
        result_id="abc123",
        call_data={
            "costBreakdown": {
                "llmPromptTokens": 40,
                "llmCompletionTokens": 12,
            },
            "durationSeconds": 20,
        },
    )

    monkeypatch.setattr(usage_mod, "_incr_pending", lambda *_args, **_kwargs: False)

    assert record_external_agent_usage(result, usage_ctx=usage_ctx) is False


def test_record_playground_provider_usage_from_call_data_raises_when_storage_fails(
    fake_redis, monkeypatch
):
    from app.services.usage import llm_usage as usage_mod
    from app.services.usage.external_agent_usage import (
        ExternalUsageRecordingError,
        record_playground_provider_usage_from_call_data,
    )

    monkeypatch.setattr(usage_mod, "_incr_pending", lambda *_args, **_kwargs: False)

    with pytest.raises(ExternalUsageRecordingError):
        record_playground_provider_usage_from_call_data(
            organization_id=uuid4(),
            workspace_id=uuid4(),
            agent_id=uuid4(),
            provider_platform="vapi",
            call_short_id="abc123",
            call_data={
                "costBreakdown": {
                    "llmPromptTokens": 40,
                    "llmCompletionTokens": 12,
                },
                "durationSeconds": 20,
            },
        )


def test_record_playground_provider_usage_from_call_data(fake_redis):
    from app.services.usage import llm_usage as usage_mod
    from app.services.usage.external_agent_usage import (
        record_playground_provider_usage_from_call_data,
    )

    org_id = uuid4()
    agent_id = uuid4()
    updated = record_playground_provider_usage_from_call_data(
        organization_id=org_id,
        workspace_id=uuid4(),
        agent_id=agent_id,
        provider_platform="vapi",
        call_short_id="abc123",
        call_data={
            "costBreakdown": {
                "llmPromptTokens": 40,
                "llmCompletionTokens": 12,
            },
            "durationSeconds": 20,
        },
    )
    assert updated["external_usage_recorded"] is True
    fields = fake_redis.hgetall(usage_mod._pending_hash_key(org_id))
    assert any("playground" in k for k in fields)


def test_extract_external_agent_usage_smallest_duration_only():
    extracted = extract_external_agent_usage(
        {"duration_seconds": 42},
        platform="smallest",
    )
    assert extracted is not None
    assert extracted.llm is None
    assert extracted.stt_audio_seconds == 42


def test_extract_external_agent_usage_elevenlabs_duration_only():
    extracted = extract_external_agent_usage(
        {"metadata": {"call_duration_secs": 33}},
        platform="elevenlabs",
    )
    assert extracted is not None
    assert extracted.stt_audio_seconds == 33
