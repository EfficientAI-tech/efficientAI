"""API tests for auth routes."""

from app.models.database import APIKey, Organization


def test_generate_api_key_creates_org_and_key(client, db_session):
    response = client.post("/api/v1/auth/generate-key", json={"name": "Primary Key"})

    assert response.status_code == 200
    body = response.json()
    assert body["key"]
    assert body["name"] == "Primary Key"
    assert body["is_active"] is True

    assert db_session.query(Organization).count() == 1
    assert db_session.query(APIKey).count() == 1


def test_validate_api_key_returns_valid(authenticated_client):
    response = authenticated_client.post("/api/v1/auth/validate")

    assert response.status_code == 200
    assert response.json() == {"valid": True, "message": "API key is valid"}
