"""API tests for model-config routes."""


def test_get_all_models(authenticated_client, monkeypatch):
    from app.api.v1.routes import model_config as model_config_routes

    monkeypatch.setattr(
        model_config_routes.model_config_service,
        "get_all_models",
        lambda: {"openai": {"llm": ["gpt-4o-mini"]}},
    )

    response = authenticated_client.get("/api/v1/model-config/models")

    assert response.status_code == 200
    assert "openai" in response.json()


def test_get_provider_options_and_models_by_type(authenticated_client, monkeypatch):
    from app.api.v1.routes import model_config as model_config_routes

    monkeypatch.setattr(
        model_config_routes.model_config_service,
        "get_model_options_by_provider",
        lambda _provider: {"stt": ["whisper-1"], "llm": ["gpt-4o-mini"], "tts": []},
    )
    monkeypatch.setattr(
        model_config_routes.model_config_service,
        "get_tts_voices_by_provider",
        lambda _provider: {"gpt-4o-mini-tts": [{"id": "alloy"}]},
    )
    monkeypatch.setattr(
        model_config_routes.model_config_service,
        "get_models_by_type",
        lambda _provider, model_type: ["whisper-1"] if model_type == "stt" else [],
    )

    options_response = authenticated_client.get("/api/v1/model-config/providers/openai/options")
    assert options_response.status_code == 200
    assert "tts_voices" in options_response.json()

    type_response = authenticated_client.get("/api/v1/model-config/providers/openai/types/stt/models")
    assert type_response.status_code == 200
    assert type_response.json() == ["whisper-1"]
