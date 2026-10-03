"""PR review P1: OpenRouter Jev must not bypass the org's LLM gateway."""

from __future__ import annotations

import importlib
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.enums import ModelProvider
from app.services.ai.llm_service import LLMService
from app.services.ai.openrouter_jev import gateway_systemone_url, normalize_typesafe_model_id

from tests.test_services.test_ai.test_llm_service import _mock_org_db

llm_module = importlib.import_module("app.services.ai.llm_service")

QUESTIONS = {"resolved": {"type": "noul", "instructions": "Resolved?", "criteria": {"true": "y", "false": "n"}}}
SYSTEMONE_BODY = {
    "model": "jev-1.13.0",
    "answers": {"resolved": {"type": "noul", "noul": 0.9}},
    "usage": {"input_tokens": 10, "output_tokens": 2},
}


@pytest.mark.parametrize("api_base,expected", [
    ("http://bifrost:8080/litellm", "http://bifrost:8080/typesafe/v1/systemone"),
    ("http://bifrost:8080/v1", "http://bifrost:8080/typesafe/v1/systemone"),
    ("https://proxy.example.com/", "https://proxy.example.com/typesafe/v1/systemone"),
])
def test_gateway_systemone_url(api_base, expected):
    assert gateway_systemone_url(api_base) == expected


def test_gateway_systemone_url_requires_base():
    with pytest.raises(RuntimeError):
        gateway_systemone_url("")


@pytest.mark.parametrize("model", ["openrouter/typesafe/jev-1.13.0", "typesafe/jev-1.13.0", "jev-1.13.0"])
def test_normalize_typesafe_model_id(model):
    assert normalize_typesafe_model_id(model) == "jev-1.13.0"


def _service(monkeypatch, stored_key="encrypted-key"):
    service = LLMService()
    monkeypatch.setattr(service, "_get_ai_provider", lambda *_a, **_k: SimpleNamespace(api_key=stored_key))
    encryption_module = importlib.import_module("app.core.encryption")
    monkeypatch.setattr(encryption_module, "decrypt_api_key", lambda value: value)
    return service


def _capture_systemone(monkeypatch):
    calls = {"gateway": [], "direct": []}

    def fake_gateway(**kwargs):
        calls["gateway"].append(kwargs)
        return SYSTEMONE_BODY

    def fake_direct(**kwargs):
        calls["direct"].append(kwargs)
        return SYSTEMONE_BODY

    monkeypatch.setattr(llm_module, "call_systemone", fake_gateway)
    monkeypatch.setattr(llm_module, "call_openrouter_systemone", fake_direct)
    return calls


def _generate(service):
    return service.generate_response(
        messages=[{"role": "user", "content": json.dumps({"state": "call transcript", "questions": QUESTIONS})}],
        llm_provider=ModelProvider.OPENROUTER,
        llm_model="typesafe/jev-1.13.0",
        organization_id=uuid4(),
        db=_mock_org_db(),
    )


def _enable_gateway(monkeypatch, base_url="http://bifrost:8080/litellm", passthrough=True):
    from app.config import settings

    monkeypatch.setattr(settings, "LLM_GATEWAY_ENABLED", True)
    monkeypatch.setattr(settings, "LLM_GATEWAY_BASE_URL", base_url)
    monkeypatch.setattr(settings, "LLM_GATEWAY_VIRTUAL_KEY", "test-vk")
    monkeypatch.setattr(settings, "LLM_GATEWAY_PASSTHROUGH_PROVIDER_KEYS", passthrough)


def test_jev_routes_through_gateway_typesafe_passthrough(monkeypatch):
    _enable_gateway(monkeypatch)
    calls = _capture_systemone(monkeypatch)

    result = _generate(_service(monkeypatch))

    assert calls["direct"] == []  # no bypass to openrouter.ai
    (call,) = calls["gateway"]
    assert call["url"] == "http://bifrost:8080/typesafe/v1/systemone"
    assert call["model_id"] == "jev-1.13.0"
    assert call["extra_headers"]["x-bf-vk"] == "test-vk"
    assert call["questions"] == QUESTIONS and call["state"] == "call transcript"
    assert json.loads(result["text"]) == {"answers": SYSTEMONE_BODY["answers"]}


def test_jev_with_gateway_managed_credential_no_longer_fails(monkeypatch):
    """The stored key is the gateway-managed sentinel, so there's no direct key."""
    from app.services.ai.llm_gateway import GATEWAY_MANAGED_KEY_SENTINEL

    _enable_gateway(monkeypatch, passthrough=False)
    calls = _capture_systemone(monkeypatch)

    _generate(_service(monkeypatch, stored_key=GATEWAY_MANAGED_KEY_SENTINEL))

    (call,) = calls["gateway"]
    assert call["api_key"]  # gateway's virtual key / placeholder, not a provider key
    assert call["api_key"] != GATEWAY_MANAGED_KEY_SENTINEL
    assert calls["direct"] == []


def test_jev_direct_routing_still_calls_openrouter(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "LLM_GATEWAY_ENABLED", False)
    calls = _capture_systemone(monkeypatch)

    _generate(_service(monkeypatch, stored_key="sk-or-real"))

    assert calls["gateway"] == []
    (call,) = calls["direct"]
    assert call["api_key"] == "sk-or-real"


def test_jev_gateway_error_is_not_retried_directly(monkeypatch):
    _enable_gateway(monkeypatch)
    calls = _capture_systemone(monkeypatch)

    def failing(**kwargs):
        raise RuntimeError("System One request to http://bifrost:8080/typesafe/v1/systemone failed (404)")

    monkeypatch.setattr(llm_module, "call_systemone", failing)

    with pytest.raises(RuntimeError, match="typesafe/v1/systemone"):
        _generate(_service(monkeypatch))
    assert calls["direct"] == []
