"""Unit tests for voice bundle LLM provider registry and instantiation."""

from unittest.mock import MagicMock, patch

import pytest

from app.services.voice_agent import voice_bundle as vb

# Mirror _LLM_CAPABLE_PROVIDERS from model_catalog.py without importing that module.
_EXPECTED_LLM_PROVIDERS = {
    "openai",
    "anthropic",
    "google",
    "xai",
    "fireworks",
    "cohere",
    "mistral",
    "meta",
    "together",
    "perplexity",
    "azure",
    "aws",
    "openrouter",
    "custom",
    "sarvam",
}


def test_llm_registry_covers_all_capable_providers():
    registry = vb._get_llm_providers()
    assert set(registry.keys()) == _EXPECTED_LLM_PROVIDERS
    for provider, cfg in registry.items():
        assert cfg.get("env_key"), f"{provider} missing env_key"
        assert cfg.get("default_model"), f"{provider} missing default_model"


def test_normalize_fireworks_model_adds_accounts_prefix():
    assert (
        vb._normalize_fireworks_model("deepseek-v4-pro")
        == "accounts/fireworks/models/deepseek-v4-pro"
    )
    assert (
        vb._normalize_fireworks_model("accounts/fireworks/models/foo")
        == "accounts/fireworks/models/foo"
    )


@patch.object(vb, "_get_service")
def test_instantiate_fireworks_uses_normalized_model(mock_get_service):
    mock_service_cls = MagicMock()
    mock_get_service.return_value = mock_service_cls

    vb._instantiate_llm_service(
        "fireworks",
        {"service_name": "FireworksLLMService"},
        api_key="fw-key",
        model="deepseek-v4-pro",
        params=None,
    )

    mock_get_service.assert_called_once_with("FireworksLLMService")
    mock_service_cls.assert_called_once_with(
        api_key="fw-key",
        model="accounts/fireworks/models/deepseek-v4-pro",
    )


@patch.object(vb, "_get_service")
def test_instantiate_sarvam_uses_openai_compatible_base_url(mock_get_service):
    mock_service_cls = MagicMock()
    mock_get_service.return_value = mock_service_cls

    vb._instantiate_llm_service(
        "sarvam",
        {},
        api_key="sarvam-key",
        model="sarvam-30b",
        params=None,
    )

    mock_get_service.assert_called_once_with("OpenAILLMService")
    mock_service_cls.assert_called_once_with(
        api_key="sarvam-key",
        model="sarvam-30b",
        base_url="https://api.sarvam.ai/v1",
    )


@patch.object(vb, "_get_service")
def test_instantiate_gateway_uses_openai_client(mock_get_service):
    mock_service_cls = MagicMock()
    mock_get_service.return_value = mock_service_cls

    vb._instantiate_llm_service(
        "cohere",
        {},
        api_key="gateway-key",
        model="command-r-plus",
        params=None,
        llm_gateway_base_url="http://localhost:8080/v1",
        llm_gateway_model="my-bifrost-model",
    )

    mock_get_service.assert_called_once_with("OpenAILLMService")
    mock_service_cls.assert_called_once_with(
        api_key="gateway-key",
        model="my-bifrost-model",
        base_url="http://localhost:8080/v1",
    )


def test_gateway_only_provider_without_gateway_raises():
    with pytest.raises(ValueError, match="requires gateway routing"):
        vb._instantiate_llm_service(
            "cohere",
            {},
            api_key="cohere-key",
            model="command-r-plus",
            params=None,
        )


def test_unknown_provider_not_in_registry():
    registry = vb._get_llm_providers()
    assert "deepgram" not in registry
