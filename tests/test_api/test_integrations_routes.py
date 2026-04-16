"""API tests for integrations routes."""


def test_create_and_list_integrations(authenticated_client):
    payload = {"platform": "retell", "api_key": "secret-key", "name": "Retell Main"}
    create_response = authenticated_client.post("/api/v1/integrations", json=payload)

    assert create_response.status_code == 201
    body = create_response.json()
    assert body["platform"] == "retell"
    assert body["name"] == "Retell Main"

    list_response = authenticated_client.get("/api/v1/integrations")
    assert list_response.status_code == 200
    assert len(list_response.json()) == 1


def test_update_integration(authenticated_client, make_integration):
    integration = make_integration(platform="retell")
    response = authenticated_client.put(
        f"/api/v1/integrations/{integration.id}",
        json={"name": "Updated Integration", "public_key": "pub-key"},
    )

    assert response.status_code == 200
    assert response.json()["name"] == "Updated Integration"
    assert response.json()["public_key"] == "pub-key"


def test_get_integration_api_key(authenticated_client, monkeypatch, make_integration):
    from app.api.v1.routes import integrations as integrations_route

    integration = make_integration(platform="retell", api_key="encrypted")
    monkeypatch.setattr(integrations_route, "decrypt_api_key", lambda _v: "decrypted-key")

    response = authenticated_client.get(f"/api/v1/integrations/{integration.id}/api-key")

    assert response.status_code == 200
    assert response.json()["api_key"] == "decrypted-key"


def test_create_smallest_integration_validates_key_and_sets_default_name(authenticated_client, monkeypatch):
    from app.api.v1.routes import integrations as integrations_route

    calls = {"count": 0}

    def _validate(api_key: str):
        calls["count"] += 1
        assert api_key == "smallest-secret"
        return {"email": "owner@smallest.ai"}

    monkeypatch.setattr(integrations_route, "_validate_smallest_connection", _validate)

    response = authenticated_client.post(
        "/api/v1/integrations",
        json={"platform": "smallest", "api_key": "smallest-secret"},
    )

    assert response.status_code == 201
    assert response.json()["platform"] == "smallest"
    assert response.json()["name"] == "Smallest (owner@smallest.ai)"
    assert calls["count"] == 1


def test_update_smallest_integration_validates_updated_key(authenticated_client, monkeypatch, make_integration):
    from app.api.v1.routes import integrations as integrations_route

    integration = make_integration(platform="smallest", api_key="encrypted")
    calls = {"count": 0}

    def _validate(api_key: str):
        calls["count"] += 1
        assert api_key == "next-smallest-key"
        return {"email": "owner@smallest.ai"}

    monkeypatch.setattr(integrations_route, "_validate_smallest_connection", _validate)

    response = authenticated_client.put(
        f"/api/v1/integrations/{integration.id}",
        json={"api_key": "next-smallest-key"},
    )

    assert response.status_code == 200
    assert calls["count"] == 1
