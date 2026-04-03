"""API tests for prompt-partials routes."""


def test_generate_and_improve_prompt(authenticated_client, monkeypatch, make_ai_provider):
    from importlib import import_module

    llm_service_module = import_module("app.services.ai.llm_service")

    make_ai_provider(provider="openai")
    monkeypatch.setattr(
        llm_service_module.llm_service,
        "generate_response",
        lambda **_kwargs: {"text": "# Prompt\nUse this template."},
    )

    generate_response = authenticated_client.post(
        "/api/v1/prompt-partials/generate",
        json={"description": "Create outbound QA prompt", "tone": "professional"},
    )
    assert generate_response.status_code == 200
    assert "content" in generate_response.json()

    improve_response = authenticated_client.post(
        "/api/v1/prompt-partials/improve",
        json={"content": "old prompt", "instructions": "make concise"},
    )
    assert improve_response.status_code == 200
    assert "content" in improve_response.json()


def test_crud_and_versions_for_prompt_partial(authenticated_client):
    create_response = authenticated_client.post(
        "/api/v1/prompt-partials",
        json={
            "name": "Lead Qualification Prompt",
            "description": "Base prompt",
            "content": "v1 content",
            "tags": ["sales"],
        },
    )
    assert create_response.status_code == 201
    partial_id = create_response.json()["id"]
    assert create_response.json()["current_version"] == 1

    update_response = authenticated_client.put(
        f"/api/v1/prompt-partials/{partial_id}",
        json={"content": "v2 content", "change_summary": "tuned format"},
    )
    assert update_response.status_code == 200
    assert update_response.json()["current_version"] == 2

    versions_response = authenticated_client.get(f"/api/v1/prompt-partials/{partial_id}/versions")
    assert versions_response.status_code == 200
    assert len(versions_response.json()) == 2

    revert_response = authenticated_client.post(f"/api/v1/prompt-partials/{partial_id}/revert/1")
    assert revert_response.status_code == 200
    assert revert_response.json()["content"] == "v1 content"

    clone_response = authenticated_client.post(f"/api/v1/prompt-partials/{partial_id}/clone")
    assert clone_response.status_code == 201
    assert "(Copy)" in clone_response.json()["name"]

    delete_response = authenticated_client.delete(f"/api/v1/prompt-partials/{partial_id}")
    assert delete_response.status_code == 204
