"""The test agent must call the LLM configured on the voice bundle."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

from app.models.database import ModelProvider
from app.services.webrtc_bridge.test_agent_processor import TestAgentConfig, TestAgentProcessor


def _call_with(config: TestAgentConfig) -> dict:
    processor = TestAgentProcessor(config)
    with patch("app.services.ai.llm_service.llm_service.generate_response") as gen, patch.object(
        TestAgentProcessor, "_build_simulation_context", return_value=None
    ):
        gen.return_value = {"text": "hi"}
        processor._sync_llm_call([{"role": "user", "content": "hello"}])
    return gen.call_args.kwargs


def test_bundle_llm_provider_model_and_credential_are_used():
    cred = uuid.uuid4()
    with patch.object(TestAgentProcessor, "_is_reasoning_model", return_value=False):
        kwargs = _call_with(
            TestAgentConfig(
                organization_id=uuid.uuid4(),
                db=MagicMock(),
                llm_provider="fireworks",
                llm_model="glm-5p3",
                llm_credential_id=cred,
                llm_config={"top_p": 0.9},
            )
        )
    assert kwargs["llm_provider"] == ModelProvider.FIREWORKS
    assert kwargs["llm_model"] == "glm-5p3"
    assert kwargs["credential_id"] == cred
    assert kwargs["llm_config"] == {"top_p": 0.9}


def test_defaults_to_openai_gpt4o_mini():
    kwargs = _call_with(TestAgentConfig(organization_id=uuid.uuid4(), db=MagicMock()))
    assert kwargs["llm_provider"] == ModelProvider.OPENAI
    assert kwargs["llm_model"] == "gpt-4o-mini"
    assert kwargs["credential_id"] is None


def test_unknown_provider_falls_back_to_openai():
    kwargs = _call_with(
        TestAgentConfig(organization_id=uuid.uuid4(), db=MagicMock(), llm_provider="nope")
    )
    assert kwargs["llm_provider"] == ModelProvider.OPENAI


import pytest


@pytest.mark.asyncio
async def test_initialize_without_openai_key_for_non_openai_bundle(monkeypatch):
    """Regression: a Fireworks bundle must not require an OpenAI key."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    processor = TestAgentProcessor(
        TestAgentConfig(
            organization_id=uuid.uuid4(),
            db=MagicMock(),
            llm_provider="fireworks",
            llm_model="glm-5p3",
            tts_provider="sarvam",
            tts_api_key="tts-key",
        )
    )
    await processor.initialize()  # must not raise


@pytest.mark.asyncio
async def test_initialize_requires_openai_key_without_db(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    processor = TestAgentProcessor(TestAgentConfig(tts_provider="sarvam", tts_api_key="tts-key"))
    with pytest.raises(ValueError, match="OpenAI API key"):
        await processor.initialize()


def _reasoning_config(**overrides) -> TestAgentConfig:
    return TestAgentConfig(
        organization_id=uuid.uuid4(),
        db=MagicMock(),
        llm_provider="fireworks",
        llm_model="deepseek-v4p1-flash",
        **overrides,
    )


def test_reasoning_model_gets_token_floor_and_low_reasoning():
    with patch.object(TestAgentProcessor, "_is_reasoning_model", return_value=True):
        kwargs = _call_with(_reasoning_config(llm_max_tokens=150))
    assert kwargs["max_tokens"] == 1024
    assert kwargs["llm_config"] == {"reasoning_effort": "low"}


def test_explicit_reasoning_config_is_respected():
    with patch.object(TestAgentProcessor, "_is_reasoning_model", return_value=True):
        kwargs = _call_with(_reasoning_config(llm_config={"reasoning_effort": "high"}))
    assert kwargs["llm_config"] == {"reasoning_effort": "high"}


def test_non_reasoning_model_default_max_tokens():
    with patch.object(TestAgentProcessor, "_is_reasoning_model", return_value=False):
        kwargs = _call_with(TestAgentConfig(organization_id=uuid.uuid4(), db=MagicMock()))
    assert kwargs["max_tokens"] == 400
    assert kwargs["llm_config"] is None


@pytest.mark.asyncio
async def test_empty_llm_reply_is_retried_once_with_larger_budget():
    processor = TestAgentProcessor(_reasoning_config())
    replies = [{"text": "", "finish_reason": "length"}, {"text": "Sure, it's Shubh."}]
    with patch("app.services.ai.llm_service.llm_service.generate_response", side_effect=replies) as gen, patch.object(
        TestAgentProcessor, "_build_simulation_context", return_value=None
    ), patch.object(TestAgentProcessor, "_is_reasoning_model", return_value=True):
        text = await processor._generate_via_llm_service([{"role": "user", "content": "name?"}])
    assert text == "Sure, it's Shubh."
    assert [c.kwargs["max_tokens"] for c in gen.call_args_list] == [1024, 2048]


@pytest.mark.asyncio
async def test_reasoning_override_error_retries_without_it():
    processor = TestAgentProcessor(_reasoning_config())
    replies = [RuntimeError("unsupported reasoning_effort"), {"text": "ok"}]
    with patch("app.services.ai.llm_service.llm_service.generate_response", side_effect=replies) as gen, patch.object(
        TestAgentProcessor, "_build_simulation_context", return_value=None
    ), patch.object(TestAgentProcessor, "_is_reasoning_model", return_value=True):
        text = await processor._generate_via_llm_service([{"role": "user", "content": "hi"}])
    assert text == "ok"
    assert gen.call_args_list[1].kwargs["llm_config"] is None


@pytest.mark.parametrize(
    "provider,model,expected",
    [
        ("fireworks", "deepseek-v4p1-flash", True),
        ("fireworks", "glm-5p3", True),
        ("openai", "gpt-4o-mini", False),
    ],
)
def test_reasoning_model_detection(provider, model, expected):
    processor = TestAgentProcessor(TestAgentConfig(llm_provider=provider, llm_model=model))
    assert processor._is_reasoning_model() is expected
