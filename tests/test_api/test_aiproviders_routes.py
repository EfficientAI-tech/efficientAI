"""API tests for AI provider routes."""


def test_create_and_list_aiproviders(authenticated_client):
    payload = {"provider": "openai", "api_key": "openai-key", "name": "OpenAI Primary"}
    create_response = authenticated_client.post("/api/v1/aiproviders", json=payload)

    assert create_response.status_code == 201
    assert create_response.json()["provider"] == "openai"
    assert create_response.json()["api_key"] is None

    list_response = authenticated_client.get("/api/v1/aiproviders")
    assert list_response.status_code == 200
    assert len(list_response.json()) == 1


def test_update_aiprovider(authenticated_client, make_ai_provider):
    provider = make_ai_provider(provider="openai")

    response = authenticated_client.put(
        f"/api/v1/aiproviders/{provider.id}",
        json={"name": "Renamed Provider", "is_active": False},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Renamed Provider"
    assert body["is_active"] is False


def test_delete_aiprovider(authenticated_client, make_ai_provider):
    provider = make_ai_provider(provider="google")

    response = authenticated_client.delete(f"/api/v1/aiproviders/{provider.id}")

    assert response.status_code == 204


def test_create_azure_aiprovider_with_endpoint_url(authenticated_client):
    payload = {
        "provider": "azure",
        "api_key": "azure-key",
        "name": "Azure Production",
        "endpoint_url": "https://eaitest-resource.openai.azure.com",
    }
    create_response = authenticated_client.post("/api/v1/aiproviders", json=payload)

    assert create_response.status_code == 201
    body = create_response.json()
    assert body["provider"] == "azure"
    assert body["endpoint_url"] == "https://eaitest-resource.openai.azure.com"
    assert body["name"] == "Azure Production"


def test_update_azure_endpoint_url(authenticated_client, make_ai_provider):
    provider = make_ai_provider(
        provider="azure",
        name="Azure Key",
        endpoint_url="https://old-resource.openai.azure.com",
    )

    response = authenticated_client.put(
        f"/api/v1/aiproviders/{provider.id}",
        json={"endpoint_url": "https://new-resource.openai.azure.com"},
    )

    assert response.status_code == 200
    assert response.json()["endpoint_url"] == "https://new-resource.openai.azure.com"
