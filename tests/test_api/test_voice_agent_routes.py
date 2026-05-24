"""API tests for voice-agent routes."""

from uuid import uuid4

import pytest

from app.config import settings
from app.core.password import hash_password
from app.models.database import (
    Organization,
    OrganizationMember,
    RoleEnum,
    User,
)


def test_voice_agent_connect_returns_ws_url(authenticated_client, user_context, make_ai_provider):
    # Ensure org has a Google provider so /connect validation passes.
    make_ai_provider(provider="google")

    response = authenticated_client.get("/api/v1/voice-agent/connect?X-API-Key=test_api_key_123")

    assert response.status_code == 200
    assert "/api/v1/voice-agent/ws" in response.json()["ws_url"]
    assert "X-API-Key=test_api_key_123" in response.json()["ws_url"]


def test_voice_agent_connect_returns_401_without_credentials(client):
    """Hitting /connect with no auth at all should be rejected."""
    response = client.get("/api/v1/voice-agent/connect")
    assert response.status_code == 401


def test_voice_agent_connect_accepts_bearer_access_token(
    client, db_session, monkeypatch
):
    """
    With email/password (or SSO) login, the user only has a Bearer access
    token - no API key. /connect must accept the Bearer token and embed it
    in the WebSocket URL it returns.
    """
    # Enable local-password provider so the bearer token issued by /auth/login
    # is recognised by the auth registry.
    monkeypatch.setattr(settings, "AUTH_PROVIDERS", ["api_key", "local_password"])

    org = Organization(id=uuid4(), name="Bearer Org")
    user = User(
        id=uuid4(),
        email="bearer-user@example.com",
        password_hash=hash_password("the-password"),
        is_active=True,
        auth_provider="local",
    )
    db_session.add_all([org, user])
    db_session.flush()
    db_session.add(
        OrganizationMember(
            organization_id=org.id,
            user_id=user.id,
            role=RoleEnum.ADMIN.value,
        )
    )
    # Configure a Google AI provider for this org so /connect validation passes.
    from app.models.database import AIProvider, ModelProvider

    db_session.add(
        AIProvider(
            id=uuid4(),
            organization_id=org.id,
            provider=ModelProvider.GOOGLE.value,
            api_key="enc-google-key",
            name="Google Key",
            is_active=True,
        )
    )
    db_session.commit()

    login_response = client.post(
        "/api/v1/auth/login",
        json={"email": "bearer-user@example.com", "password": "the-password"},
    )
    assert login_response.status_code == 200
    access_token = login_response.json()["access_token"]
    assert access_token

    response = client.get(
        "/api/v1/voice-agent/connect",
        headers={"Authorization": f"Bearer {access_token}"},
    )

    assert response.status_code == 200, response.text
    ws_url = response.json()["ws_url"]
    assert "/api/v1/voice-agent/ws" in ws_url
    # The bearer token must be embedded as ?token=... so the subsequent
    # WebSocket connection authenticates the same way.
    assert f"token={access_token}" in ws_url
    # And we must NOT leak an API key the caller never supplied.
    assert "X-API-Key=" not in ws_url


def test_voice_agent_audio_lists_files(authenticated_client, monkeypatch):
    from app.api.v1.routes import voice_agent as voice_agent_routes

    monkeypatch.setattr(
        voice_agent_routes.s3_service,
        "list_audio_files",
        lambda **_kwargs: [
            {
                "key": "org/audio/response.mp3",
                "filename": "response.mp3",
                "size": 1024,
                "last_modified": "2026-01-01T00:00:00Z",
            }
        ],
    )

    response = authenticated_client.get("/api/v1/voice-agent/audio")

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["filename"] == "response.mp3"
