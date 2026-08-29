"""Service-layer tests for LLM service."""

import importlib
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.enums import ModelProvider
from app.services.ai.llm_service import LLMService

llm_module = importlib.import_module("app.services.ai.llm_service")


def _mock_org_db(org_settings=None):
    org = SimpleNamespace(llm_gateway_settings=org_settings)
    return SimpleNamespace(
        query=lambda *_args, **_kwargs: SimpleNamespace(
            filter=lambda *_a, **_k: SimpleNamespace(first=lambda: org)
        )
    )


@pytest.fixture(autouse=True)
def _reset_llm_gateway_settings():
    from app.config import settings

    original = (
        settings.LLM_GATEWAY_ENABLED,
        settings.LLM_GATEWAY_BASE_URL,
        settings.LLM_GATEWAY_VIRTUAL_KEY,
        settings.LLM_GATEWAY_PASSTHROUGH_PROVIDER_KEYS,
    )
    settings.LLM_GATEWAY_ENABLED = False
    settings.LLM_GATEWAY_BASE_URL = None
    settings.LLM_GATEWAY_VIRTUAL_KEY = None
    settings.LLM_GATEWAY_PASSTHROUGH_PROVIDER_KEYS = True
    yield
    (
        settings.LLM_GATEWAY_ENABLED,
        settings.LLM_GATEWAY_BASE_URL,
        settings.LLM_GATEWAY_VIRTUAL_KEY,
        settings.LLM_GATEWAY_PASSTHROUGH_PROVIDER_KEYS,
    ) = original


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
    assert (
        LLMService._litellm_model_name(ModelProvider.AZURE, "azure-gpt-5-mini")
        == "azure/gpt-5-mini"
    )
    assert (
        LLMService._litellm_model_name(ModelProvider.AZURE, "azure-openai-gpt4")
        == "azure/gpt-4"
    )


def test_generate_response_raises_when_provider_not_configured(monkeypatch):
    service = LLMService()
    monkeypatch.setattr(service, "_get_ai_provider", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(llm_module, "resolve_integration", lambda *_args, **_kwargs: None)
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
    monkeypatch.setattr(service, "_get_ai_provider", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(llm_module, "resolve_integration", lambda *_args, **_kwargs: None)
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
        db=_mock_org_db(),
        temperature=0.2,
    )

    assert result["text"] == "hello from model"
    assert result["model"] == "gpt-4o-mini"
    assert result["usage"]["total_tokens"] == 15
    assert result["processing_time"] >= 0


def test_generate_response_applies_llm_gateway(monkeypatch):
    from app.config import settings

    settings.LLM_GATEWAY_ENABLED = True
    settings.LLM_GATEWAY_BASE_URL = "http://localhost:8080/litellm"
    settings.LLM_GATEWAY_VIRTUAL_KEY = "test-vk"

    service = LLMService()
    monkeypatch.setattr(
        service,
        "_get_ai_provider",
        lambda *_args, **_kwargs: SimpleNamespace(api_key="encrypted-key"),
    )

    encryption_module = importlib.import_module("app.core.encryption")
    monkeypatch.setattr(encryption_module, "decrypt_api_key", lambda value: f"decrypted::{value}")

    captured = {}

    def _fake_completion(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="via bifrost"),
                    finish_reason="stop",
                )
            ],
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        )

    monkeypatch.setattr(llm_module.litellm, "completion", _fake_completion)

    org_id = uuid4()
    db = _mock_org_db()

    result = service.generate_response(
        messages=[{"role": "user", "content": "hello"}],
        llm_provider=ModelProvider.OPENAI,
        llm_model="gpt-4o-mini",
        organization_id=org_id,
        db=db,
    )

    assert result["text"] == "via bifrost"
    assert captured["api_base"] == "http://localhost:8080/litellm"
    assert captured["extra_headers"]["x-bf-vk"] == "test-vk"


def test_generate_response_sarvam_integration_direct_skips_gateway(monkeypatch):
    """Integration LLM credentials must honour per-credential direct routing."""
    from app.config import settings

    settings.LLM_GATEWAY_ENABLED = True
    settings.LLM_GATEWAY_BASE_URL = "http://localhost:8080/litellm"
    settings.LLM_GATEWAY_VIRTUAL_KEY = "test-vk"

    service = LLMService()
    integration = SimpleNamespace(routing_mode="direct")
    monkeypatch.setattr(service, "_get_ai_provider", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        llm_module,
        "resolve_integration",
        lambda *_args, **_kwargs: integration,
    )
    monkeypatch.setattr(
        service,
        "_resolve_api_key",
        lambda *_args, **_kwargs: "sarvam-api-key",
    )

    captured = {}

    def _fake_completion(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="sarvam reply"),
                    finish_reason="stop",
                )
            ],
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        )

    monkeypatch.setattr(llm_module.litellm, "completion", _fake_completion)

    result = service.generate_response(
        messages=[{"role": "user", "content": "hello"}],
        llm_provider=ModelProvider.SARVAM,
        llm_model="sarvam-30b",
        organization_id=uuid4(),
        db=_mock_org_db(),
    )

    assert result["text"] == "sarvam reply"
    assert captured["model"] == "sarvam/sarvam-30b"
    assert captured.get("api_base") is None
    assert captured.get("custom_llm_provider") is None
    assert captured["api_key"] == "sarvam-api-key"


def test_generate_response_wraps_litellm_errors(monkeypatch):
    service = LLMService()
    monkeypatch.setattr(service, "_get_ai_provider", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(llm_module, "resolve_integration", lambda *_args, **_kwargs: None)
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
            db=_mock_org_db(),
        )


def test_build_azure_litellm_kwargs_from_provider_endpoint_url():
    provider = SimpleNamespace(
        name="Should Not Be Used",
        endpoint_url="https://my-resource.openai.azure.com/",
    )
    kwargs, remaining, uses_v1 = llm_module._build_azure_litellm_kwargs(provider, None)

    assert uses_v1 is True
    assert kwargs["api_base"] == "https://my-resource.openai.azure.com/openai/v1"
    assert "azure_endpoint" not in kwargs
    assert remaining is None


def test_build_azure_litellm_kwargs_from_provider_name():
    provider = SimpleNamespace(name="https://my-resource.openai.azure.com/")
    kwargs, remaining, uses_v1 = llm_module._build_azure_litellm_kwargs(provider, None)

    assert uses_v1 is True
    assert kwargs["api_base"] == "https://my-resource.openai.azure.com/openai/v1"
    assert "azure_endpoint" not in kwargs
    assert remaining is None


def test_build_azure_litellm_kwargs_normalizes_v1_chat_completions_url():
    provider = SimpleNamespace(
        name="https://eaitest-resource.openai.azure.com/openai/v1/chat/completions"
    )
    kwargs, remaining, uses_v1 = llm_module._build_azure_litellm_kwargs(provider, None)

    assert uses_v1 is True
    assert kwargs["api_base"] == "https://eaitest-resource.openai.azure.com/openai/v1"
    assert "azure_endpoint" not in kwargs
    assert remaining is None


def test_build_azure_litellm_kwargs_from_config():
    kwargs, remaining, uses_v1 = llm_module._build_azure_litellm_kwargs(
        None,
        {
            "azure_endpoint": "https://foundry.example.com",
            "api_version": "2024-10-21",
            "temperature": 0.2,
        },
    )

    assert uses_v1 is False
    assert kwargs["api_base"] == "https://foundry.example.com"
    assert kwargs["azure_endpoint"] == "https://foundry.example.com"
    assert kwargs["api_version"] == "2024-10-21"
    assert remaining == {"temperature": 0.2}


def test_generate_response_azure_foundry_uses_openai_v1_routing(monkeypatch):
    service = LLMService()
    provider = SimpleNamespace(
        api_key="encrypted-key",
        endpoint_url="https://eaitest-resource.openai.azure.com",
        name="Azure Test",
    )
    monkeypatch.setattr(service, "_get_ai_provider", lambda *_args, **_kwargs: provider)

    encryption_module = importlib.import_module("app.core.encryption")
    monkeypatch.setattr(encryption_module, "decrypt_api_key", lambda value: "azure-api-key")

    captured = {}

    def _fake_completion(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="azure ok"),
                    finish_reason="stop",
                )
            ],
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        )

    monkeypatch.setattr(llm_module.litellm, "completion", _fake_completion)

    result = service.generate_response(
        messages=[{"role": "user", "content": "hello"}],
        llm_provider=ModelProvider.AZURE,
        llm_model="azure-gpt-5-mini",
        organization_id=uuid4(),
        db=_mock_org_db(),
    )

    assert result["text"] == "azure ok"
    assert captured["model"] == "openai/gpt-5-mini"
    assert captured["api_base"] == "https://eaitest-resource.openai.azure.com/openai/v1"
    assert "azure_endpoint" not in captured


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("openai/gpt-5.6", True),
        ("openai/gpt-5.6-sol", True),
        ("openai/gpt-5-mini", True),
        ("openai/gpt-5-chat-latest", False),
        ("openai/gpt-4o-mini", False),
        ("openai/o3-mini", True),
    ],
)
def test_model_only_supports_default_temperature(model, expected):
    assert llm_module._model_only_supports_default_temperature(model) is expected


def test_normalize_temperature_for_model_drops_non_default():
    call_kwargs = {"temperature": 0.7, "model": "openai/gpt-5.6"}
    llm_module._normalize_temperature_for_model("openai/gpt-5.6", call_kwargs)
    assert "temperature" not in call_kwargs


def test_normalize_temperature_for_model_keeps_default_and_other_models():
    gpt4_kwargs = {"temperature": 0.7}
    llm_module._normalize_temperature_for_model("openai/gpt-4o-mini", gpt4_kwargs)
    assert gpt4_kwargs["temperature"] == 0.7

    gpt5_default_kwargs = {"temperature": 1}
    llm_module._normalize_temperature_for_model("openai/gpt-5.6", gpt5_default_kwargs)
    assert gpt5_default_kwargs["temperature"] == 1


def test_generate_response_omits_temperature_for_gpt_5_6(monkeypatch):
    service = LLMService()
    provider = SimpleNamespace(api_key="encrypted-key")
    monkeypatch.setattr(service, "_get_ai_provider", lambda *_args, **_kwargs: provider)

    encryption_module = importlib.import_module("app.core.encryption")
    monkeypatch.setattr(encryption_module, "decrypt_api_key", lambda value: "openai-api-key")

    captured = {}

    def _fake_completion(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="ok"),
                    finish_reason="stop",
                )
            ],
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        )

    monkeypatch.setattr(llm_module.litellm, "completion", _fake_completion)

    service.generate_response(
        messages=[{"role": "user", "content": "hello"}],
        llm_provider=ModelProvider.OPENAI,
        llm_model="gpt-5.6",
        organization_id=uuid4(),
        db=_mock_org_db(),
        temperature=0.7,
        task_defaults={"temperature": 0.7},
    )

    assert captured["model"] == "openai/gpt-5.6"
    assert "temperature" not in captured
