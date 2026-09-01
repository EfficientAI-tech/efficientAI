"""Tests for live voice pipeline LLM provider registry."""

from app.services.judge_alignment.model_catalog import _LLM_CAPABLE_PROVIDERS
from app.services.voice_agent.llm_voice_providers import (
    LLM_VOICE_PROVIDER_KEYS,
    get_llm_provider_registry,
    normalize_llm_model,
)


def test_voice_llm_registry_covers_configurable_providers():
    assert LLM_VOICE_PROVIDER_KEYS == _LLM_CAPABLE_PROVIDERS

    def _fake_get_service(name: str):
        return lambda **kwargs: (name, kwargs)

    registry = get_llm_provider_registry(_fake_get_service)
    assert set(registry.keys()) == LLM_VOICE_PROVIDER_KEYS


def test_normalize_fireworks_model_adds_accounts_prefix():
    assert normalize_llm_model("fireworks", "llama-v3p1-8b-instruct") == (
        "accounts/fireworks/models/llama-v3p1-8b-instruct"
    )
    assert normalize_llm_model(
        "fireworks",
        "accounts/fireworks/models/llama-v3p1-8b-instruct",
    ) == "accounts/fireworks/models/llama-v3p1-8b-instruct"


def test_fireworks_factory_uses_normalized_model():
    captured = {}

    def _fake_get_service(name: str):
        def _factory(**kwargs):
            captured["service"] = name
            captured["kwargs"] = kwargs
            return kwargs

        return _factory

    registry = get_llm_provider_registry(_fake_get_service)
    registry["fireworks"]["factory"]("test-key", "llama-v3p1-8b-instruct", None)

    assert captured["service"] == "FireworksLLMService"
    assert captured["kwargs"]["model"] == "accounts/fireworks/models/llama-v3p1-8b-instruct"
    assert captured["kwargs"]["api_key"] == "test-key"