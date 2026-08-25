from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.usage import context as usage_context_mod
from app.services.usage import llm_usage as usage_mod
from app.services.usage.context import (
    LLMUsageProductSection,
    usage_context_for_test_agent_simulation,
)
from app.services.usage.external_agent_usage import (
    extract_external_agent_usage,
    record_external_agent_usage,
)
from app.services.webrtc_bridge.test_agent_processor import TestAgentConfig, TestAgentProcessor
from app.workers.tasks import process_evaluator_result as per_mod


@pytest.fixture
def fake_redis(monkeypatch):
    class _FakeRedis:
        def __init__(self):
            self.hashes = {}
            self.sets = {}
            self.kv = {}

        def hincrby(self, key, field, amount):
            self.hashes.setdefault(key, {})
            self.hashes[key][field] = int(self.hashes[key].get(field, 0)) + int(amount)

        def hgetall(self, key):
            return dict(self.hashes.get(key, {}))

        def sadd(self, key, member):
            self.sets.setdefault(key, set()).add(member)

        def smembers(self, key):
            return set(self.sets.get(key, set()))

        def expire(self, key, ttl):
            return True

        def pipeline(self):
            client = self

            class _Pipe:
                def hincrby(self, key, field, amount):
                    client.hincrby(key, field, amount)
                    return self

                def sadd(self, key, member):
                    client.sadd(key, member)
                    return self

                def expire(self, key, ttl):
                    return self

                def execute(self):
                    return []

            return _Pipe()

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


def test_usage_context_for_test_agent_simulation():
    org_id = uuid4()
    agent_id = uuid4()
    evaluator_id = uuid4()
    persona_id = uuid4()
    scenario_id = uuid4()
    result_id = uuid4()
    conversation_id = uuid4()
    workspace_id = uuid4()

    ctx = usage_context_for_test_agent_simulation(
        organization_id=org_id,
        workspace_id=workspace_id,
        agent_id=agent_id,
        evaluator_id=evaluator_id,
        persona_id=persona_id,
        scenario_id=scenario_id,
        evaluator_result_id=result_id,
        conversation_id=conversation_id,
        provider_platform="vapi",
    )

    assert ctx.product_section == LLMUsageProductSection.TEST_AGENT
    assert ctx.resource_id == agent_id
    assert ctx.extra["agent_id"] == str(agent_id)
    assert ctx.extra["evaluator_id"] == str(evaluator_id)
    assert ctx.extra["persona_id"] == str(persona_id)
    assert ctx.extra["scenario_id"] == str(scenario_id)
    assert ctx.extra["evaluator_result_id"] == str(result_id)
    assert ctx.extra["conversation_id"] == str(conversation_id)
    assert ctx.extra["simulation"] == "llm_to_llm"


def test_extract_external_agent_usage_vapi():
    call_data = {
        "costBreakdown": {
            "llmPromptTokens": 120,
            "llmCompletionTokens": 45,
            "llmCachedPromptTokens": 10,
            "ttsCharacters": 300,
        },
        "durationSeconds": 88,
        "model": "gpt-4o",
    }
    extracted = extract_external_agent_usage(call_data, platform="vapi")
    assert extracted is not None
    assert extracted.model == "gpt-4o"
    assert extracted.llm.prompt_tokens == 120
    assert extracted.llm.completion_tokens == 45
    assert extracted.llm.cache_read_tokens == 10
    assert extracted.tts_characters == 300
    assert extracted.stt_audio_seconds == 88


def test_record_external_agent_usage_vapi(fake_redis):
    org_id = uuid4()
    agent_id = uuid4()
    usage_ctx = usage_context_mod.usage_context_for_evaluator_result(
        SimpleNamespace(
            organization_id=org_id,
            workspace_id=uuid4(),
            agent_id=agent_id,
            evaluator_id=uuid4(),
            id=uuid4(),
            result_id="res-1",
        )
    )
    result = SimpleNamespace(
        organization_id=org_id,
        provider_platform="vapi",
        result_id="res-1",
        call_data={
            "costBreakdown": {
                "llmPromptTokens": 50,
                "llmCompletionTokens": 20,
            }
        },
    )

    record_external_agent_usage(result, usage_ctx=usage_ctx)

    pending_key = usage_mod._pending_hash_key(org_id)
    fields = fake_redis.hgetall(pending_key)
    assert any("evaluators" in k for k in fields)
    prompt = sum(int(v) for k, v in fields.items() if k.endswith("|prompt_tokens"))
    completion = sum(int(v) for k, v in fields.items() if k.endswith("|completion_tokens"))
    assert prompt == 50
    assert completion == 20


def test_test_agent_processor_records_with_simulation_context(fake_redis):
    org_id = uuid4()
    agent_id = uuid4()
    config = TestAgentConfig(
        organization_id=org_id,
        workspace_id=uuid4(),
        agent_id=agent_id,
        evaluator_id=uuid4(),
        persona_id=uuid4(),
        scenario_id=uuid4(),
        llm_model="gpt-4o-mini",
    )
    processor = TestAgentProcessor(config)

    class _Usage:
        def __init__(self):
            self.prompt_tokens = 11
            self.completion_tokens = 4

    class _Response:
        usage = _Usage()

    processor._record_llm_usage(response=_Response())

    pending_key = usage_mod._pending_hash_key(org_id)
    fields = fake_redis.hgetall(pending_key)
    assert any("test_agent" in k for k in fields)
    prompt = sum(int(v) for k, v in fields.items() if k.endswith("|prompt_tokens"))
    assert prompt == 11


def test_record_external_agent_llm_usage_skips_internal_platform(monkeypatch):
    called = {"value": False}

    def _fake_record(*_args, **_kwargs):
        called["value"] = True

    monkeypatch.setattr(
        "app.services.usage.external_agent_usage.record_external_agent_usage",
        _fake_record,
    )

    result = SimpleNamespace(agent_id=uuid4(), provider_platform="internal")
    usage_ctx = SimpleNamespace()
    per_mod._record_external_agent_llm_usage(result, usage_ctx=usage_ctx)
    assert called["value"] is False


def test_process_audio_chunk_with_context_uses_test_agent_section(monkeypatch):
    org_id = uuid4()
    agent_id = uuid4()
    captured_sections = []

    def _fake_generate(**_kwargs):
        ctx = usage_context_mod.get_usage_context()
        if ctx:
            captured_sections.append(ctx.product_section)
        return {"text": "hi there", "processing_time": 0.2}

    from app.models.database import (
        TestAgentConversation,
        TestAgentConversationStatus,
        ModelProvider,
    )
    from app.services.testing.test_agent_service import TestAgentService
    from app.services.usage.context import llm_usage_context

    conversation = TestAgentConversation(
        id=uuid4(),
        organization_id=org_id,
        workspace_id=uuid4(),
        agent_id=agent_id,
        persona_id=uuid4(),
        scenario_id=uuid4(),
        voice_bundle_id=uuid4(),
        status=TestAgentConversationStatus.ACTIVE,
        live_transcription=[],
    )
    voice_bundle = SimpleNamespace(
        stt_provider=ModelProvider.OPENAI,
        stt_model="whisper-1",
        llm_provider=ModelProvider.OPENAI,
        llm_model="gpt-4o-mini",
        llm_config=None,
        llm_temperature=0.7,
        llm_max_tokens=100,
        tts_provider=ModelProvider.OPENAI,
        tts_model="gpt-4o-mini-tts",
        tts_config=None,
    )

    import importlib

    tas_module = importlib.import_module("app.services.testing.test_agent_service")
    service = TestAgentService()
    monkeypatch.setattr(
        tas_module,
        "s3_service",
        SimpleNamespace(upload_file=lambda **_kwargs: "audio/key.wav"),
    )
    monkeypatch.setattr(
        tas_module.transcription_service,
        "transcribe",
        lambda **_kwargs: {"transcript": "hello", "processing_time": 0.1},
    )
    monkeypatch.setattr(
        tas_module.llm_service,
        "generate_response",
        _fake_generate,
    )
    monkeypatch.setattr(
        tas_module.tts_service,
        "synthesize",
        lambda **_kwargs: b"mp3",
    )
    monkeypatch.setattr(
        service,
        "_build_system_prompt",
        lambda *_args, **_kwargs: "system",
    )
    monkeypatch.setattr(
        "app.services.voice_agent.resolve_tts_voice.resolve_effective_tts_voice_id",
        lambda **_kwargs: "voice",
    )

    usage_ctx = usage_context_for_test_agent_simulation(
        organization_id=org_id,
        workspace_id=conversation.workspace_id,
        agent_id=agent_id,
        conversation_id=conversation.id,
    )
    db = SimpleNamespace(commit=lambda: None)

    with llm_usage_context(usage_ctx):
        service._process_audio_chunk_with_context(
            conversation=conversation,
            wav_audio_bytes=b"wav",
            voice_bundle=voice_bundle,
            agent=SimpleNamespace(id=agent_id, language=SimpleNamespace(value="en")),
            persona=SimpleNamespace(id=conversation.persona_id, tts_voice_id=None),
            scenario=SimpleNamespace(id=conversation.scenario_id),
            organization_id=org_id,
            db=db,
            chunk_timestamp=0.0,
        )

    assert captured_sections == [LLMUsageProductSection.TEST_AGENT]
