"""API tests for voice-playground routes."""


def test_list_tts_providers(authenticated_client, monkeypatch, make_ai_provider):
    from app.api.v1.routes import voice_playground as vp_routes

    make_ai_provider(provider="openai")
    monkeypatch.setattr(
        vp_routes,
        "_get_tts_models_by_provider",
        lambda: {"openai": ["gpt-4o-mini-tts"]},
    )
    monkeypatch.setattr(
        vp_routes.model_config_service,
        "get_voices_for_model",
        lambda _model_name: [{"id": "alloy", "name": "Alloy", "gender": "Neutral", "accent": "American"}],
    )

    response = authenticated_client.get("/api/v1/voice-playground/tts-providers")

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["provider"] == "openai"


def test_tts_comparison_crud_and_actions(authenticated_client):
    create_payload = {
        "name": "OpenAI voice check",
        "provider_a": "openai",
        "model_a": "gpt-4o-mini-tts",
        "voices_a": [{"id": "alloy", "name": "Alloy"}],
        "sample_texts": ["Hello this is a test sample."],
        "num_runs": 1,
    }
    create_response = authenticated_client.post("/api/v1/voice-playground/comparisons", json=create_payload)
    assert create_response.status_code == 200
    comparison = create_response.json()
    comparison_id = comparison["id"]
    sample_id = comparison["samples"][0]["id"]

    list_response = authenticated_client.get("/api/v1/voice-playground/comparisons")
    assert list_response.status_code == 200
    assert len(list_response.json()) == 1

    get_response = authenticated_client.get(f"/api/v1/voice-playground/comparisons/{comparison_id}")
    assert get_response.status_code == 200
    assert get_response.json()["id"] == comparison_id

    generate_response = authenticated_client.post(
        f"/api/v1/voice-playground/comparisons/{comparison_id}/generate"
    )
    assert generate_response.status_code == 200
    assert "task_id" in generate_response.json()

    blind_test_response = authenticated_client.post(
        f"/api/v1/voice-playground/comparisons/{comparison_id}/blind-test",
        json={"results": [{"sample_index": 0, "preferred": "A"}]},
    )
    assert blind_test_response.status_code == 200
    assert blind_test_response.json()["message"] == "Blind test results saved"

    sample_response = authenticated_client.get(
        f"/api/v1/voice-playground/comparisons/{comparison_id}/samples/{sample_id}"
    )
    assert sample_response.status_code == 200
    assert sample_response.json()["id"] == sample_id

    analytics_response = authenticated_client.get("/api/v1/voice-playground/analytics")
    assert analytics_response.status_code == 200
    assert isinstance(analytics_response.json(), list)

    delete_response = authenticated_client.delete(f"/api/v1/voice-playground/comparisons/{comparison_id}")
    assert delete_response.status_code == 200
    assert delete_response.json()["message"] == "Comparison deleted"
