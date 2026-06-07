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


def test_metric_partial_kind_filter_and_validation(authenticated_client):
    valid_category_content = (
        '{"schema_version":1,"metric_kind":"category","description":"Context",'
        '"children":[{"name":"Booked","description":"Appointment set","example":"See you Tuesday"}]}'
    )
    valid_single_content = (
        '{"schema_version":1,"metric_kind":"single","description":"True when agent confirms date"}'
    )

    metric_response = authenticated_client.post(
        "/api/v1/prompt-partials",
        json={
            "name": "Call Outcome Labels",
            "description": "Category metric prompt",
            "content": valid_category_content,
            "tags": ["__metric_partial__"],
        },
    )
    assert metric_response.status_code == 201
    metric_id = metric_response.json()["id"]

    regular_response = authenticated_client.post(
        "/api/v1/prompt-partials",
        json={
            "name": "Generic Prompt",
            "content": "plain text prompt",
            "tags": ["sales"],
        },
    )
    assert regular_response.status_code == 201
    regular_id = regular_response.json()["id"]

    invalid_response = authenticated_client.post(
        "/api/v1/prompt-partials",
        json={
            "name": "Broken Metric Partial",
            "content": "not-json",
            "tags": ["__metric_partial__"],
        },
    )
    assert invalid_response.status_code == 400

    metric_list = authenticated_client.get("/api/v1/prompt-partials?kind=metric")
    assert metric_list.status_code == 200
    metric_ids = {item["id"] for item in metric_list.json()}
    assert metric_id in metric_ids
    assert regular_id not in metric_ids

    partial_list = authenticated_client.get("/api/v1/prompt-partials?kind=partial")
    assert partial_list.status_code == 200
    partial_ids = {item["id"] for item in partial_list.json()}
    assert regular_id in partial_ids
    assert metric_id not in partial_ids

    update_response = authenticated_client.put(
        f"/api/v1/prompt-partials/{metric_id}",
        json={"content": valid_single_content, "change_summary": "switch to single"},
    )
    assert update_response.status_code == 200
    assert update_response.json()["current_version"] == 2

    bad_update = authenticated_client.put(
        f"/api/v1/prompt-partials/{metric_id}",
        json={"content": "still-not-json"},
    )
    assert bad_update.status_code == 400
