"""Tests for AI metric generation endpoint."""


def test_generate_metric_uses_resolver(authenticated_client, monkeypatch, make_ai_provider):
    from importlib import import_module

    llm_service_module = import_module("app.services.ai.llm_service")
    resolver_module = import_module("app.services.ai.llm_resolver")
    from app.models.enums import ModelProvider

    make_ai_provider(provider="anthropic")

    resolver_calls = []

    def _fake_resolver(org_id, db, provider, model):
        resolver_calls.append({"provider": provider, "model": model})
        return ModelProvider.ANTHROPIC, "claude-sonnet-4-20250514"

    monkeypatch.setattr(resolver_module, "get_llm_provider_and_model", _fake_resolver)
    monkeypatch.setattr(
        llm_service_module.llm_service,
        "generate_response",
        lambda **_kwargs: {
            "text": (
                '{"name":"Booking Confirmation","description":"Checks booking confirmation.",'
                '"metric_type":"boolean","custom_data_type":"boolean","custom_config":{},'
                '"supported_surfaces":["agent"],"enabled_surfaces":["agent"],"suggested_tags":[]}'
            )
        },
    )

    response = authenticated_client.post(
        "/api/v1/metrics/generate",
        json={
            "mode": "description",
            "surface": "agent",
            "description": "Did the agent confirm the booking?",
            "provider": "anthropic",
            "model": "claude-sonnet-4-20250514",
            "llm_config": {"temperature": 0.2},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Booking Confirmation"
    assert body["provider"] == "anthropic"
    assert body["model"] == "claude-sonnet-4-20250514"
    assert resolver_calls == [
        {"provider": "anthropic", "model": "claude-sonnet-4-20250514"}
    ]
