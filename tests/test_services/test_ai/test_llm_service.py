"""Service-layer tests for LLM service."""

import importlib
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.enums import ModelProvider
from app.services.ai.llm_service import LLMService

llm_module = importlib.import_module("app.services.ai.llm_service")


def test_litellm_model_name_maps_known_provider_prefixes():
    assert LLMService._litellm_model_name(ModelProvider.OPENAI, "gpt-4o") == "openai/gpt-4o"
    assert LLMService._litellm_model_name(ModelProvider.GOOGLE, "gemini-1.5-pro") == "gemini/gemini-1.5-pro"
    assert LLMService._litellm_model_name(ModelProvider.AWS, "claude") == "bedrock/claude"
    assert LLMService._litellm_model_name(ModelProvider.XAI, "grok-4.3") == "xai/grok-4.3"
    assert (
        LLMService._litellm_model_name(ModelProvider.FIREWORKS, "deepseek-v4-pro")
        == "fireworks_ai/accounts/fireworks/models/deepseek-v4-pro"
    )
    assert (
        LLMService._litellm_model_name(ModelProvider.SARVAM, "sarvam-30b")
        == "sarvam/sarvam-30b"
    )


def test_generate_response_raises_when_provider_not_configured(monkeypatch):
    service = LLMService()
    monkeypatch.setattr(service, "_resolve_api_key", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("AI provider sarvam not configured for this organization.")))

    with pytest.raises(RuntimeError, match="not configured"):
        service.generate_response(
            messages=[{"role": "user", "content": "hello"}],
            llm_provider=ModelProvider.OPENAI,
            llm_model="gpt-4o-mini",
            organization_id=uuid4(),
            db=object(),
        )


def test_generate_response_success_with_normalized_usage(monkeypatch):
    service = LLMService()
    monkeypatch.setattr(
        service,
        "_resolve_api_key",
        lambda *_args, **_kwargs: "decrypted-key",
    )

    # ``llm_service.generate_response`` reads ``finish_reason`` off the
    # first choice to flag truncated outputs (so JSON-parsing callers
    # can blame the right thing). The stub has to include it; "stop"
    # = the normal completion path.
    fake_response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content="hello from model"),
                finish_reason="stop",
            )
        ],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15),
    )
    monkeypatch.setattr(llm_module.litellm, "completion", lambda **_kwargs: fake_response)

    result = service.generate_response(
        messages=[{"role": "user", "content": "hello"}],
        llm_provider=ModelProvider.OPENAI,
        llm_model="gpt-4o-mini",
        organization_id=uuid4(),
        db=object(),
        temperature=0.2,
    )

    assert result["text"] == "hello from model"
    assert result["model"] == "gpt-4o-mini"
    assert result["usage"]["total_tokens"] == 15
    assert result["processing_time"] >= 0


def test_generate_response_wraps_litellm_errors(monkeypatch):
    service = LLMService()
    monkeypatch.setattr(
        service,
        "_resolve_api_key",
        lambda *_args, **_kwargs: "decrypted-key",
    )

    monkeypatch.setattr(
        llm_module.litellm,
        "completion",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("provider timeout")),
    )

    with pytest.raises(RuntimeError, match="LLM generation failed"):
        service.generate_response(
            messages=[{"role": "user", "content": "hello"}],
            llm_provider=ModelProvider.OPENAI,
            llm_model="gpt-4o-mini",
            organization_id=uuid4(),
            db=object(),
        )
