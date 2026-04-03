"""API tests for settings routes."""

import pytest


@pytest.fixture
def settings_user_override(authenticated_client, user_context):
    from app.api.v1.routes import settings

    authenticated_client.app.dependency_overrides[settings.get_current_user] = lambda: user_context[
        "user"
    ]
    yield
    authenticated_client.app.dependency_overrides.pop(settings.get_current_user, None)


def test_settings_license_info(authenticated_client):
    response = authenticated_client.get("/api/v1/settings/license-info")

    assert response.status_code == 200
    body = response.json()
    assert "enabled_features" in body
    assert "feature_catalog" in body


def test_list_api_keys(settings_user_override, authenticated_client):
    response = authenticated_client.get("/api/v1/settings/api-keys")

    assert response.status_code == 200
    keys = response.json()
    assert len(keys) == 1
    assert keys[0]["name"] == "Owner API Key"


def test_create_and_delete_api_key(settings_user_override, authenticated_client):
    create_response = authenticated_client.post(
        "/api/v1/settings/api-keys",
        json={"name": "Secondary Key"},
    )
    assert create_response.status_code == 200
    key_id = create_response.json()["id"]
    assert create_response.json()["name"] == "Secondary Key"

    delete_response = authenticated_client.delete(f"/api/v1/settings/api-keys/{key_id}")
    assert delete_response.status_code == 200
    assert delete_response.json()["message"] == "API key deleted successfully"
