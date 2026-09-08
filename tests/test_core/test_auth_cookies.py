"""Tests for httpOnly cookie sessions and CSRF middleware."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import settings
from app.core.auth.cookies import COOKIE_ACCESS, COOKIE_CSRF, COOKIE_REFRESH, CSRF_HEADER
from app.core.csrf_middleware import CsrfMiddleware
from app.core.password import hash_password
from app.models.database import Organization, OrganizationMember, RoleEnum, User


@pytest.fixture
def cookie_auth_client(db_session, org_id, monkeypatch):
    monkeypatch.setattr(settings, "AUTH_COOKIE_SESSION_ENABLED", True)
    monkeypatch.setattr(settings, "AUTH_PROVIDERS", ["api_key", "local_password"])
    monkeypatch.setattr(settings, "AUTH_LOCAL_ALLOW_SIGNUP", True)
    from app.core.auth.providers import reset_provider_registry

    reset_provider_registry()

    org = Organization(id=org_id, name="Cookie Test Org")
    user = User(
        id=uuid4(),
        email="cookie@example.com",
        password_hash=hash_password("CookiePass1!"),
        is_active=True,
        session_epoch=0,
    )
    db_session.add(org)
    db_session.add(user)
    db_session.add(
        OrganizationMember(
            organization_id=org_id,
            user_id=user.id,
            role=RoleEnum.ADMIN.value,
        )
    )
    db_session.commit()

    from app.api.v1.routes import auth
    from app.database import get_db

    app = FastAPI()
    app.add_middleware(CsrfMiddleware)
    app.include_router(auth.router, prefix="/api/v1")

    def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db

    with TestClient(app) as client:
        yield client, user


def test_login_sets_http_only_session_cookies(cookie_auth_client):
    client, _user = cookie_auth_client
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "cookie@example.com", "password": "CookiePass1!"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["access_token"] == ""
    assert body["refresh_token"] is None
    assert COOKIE_ACCESS in response.cookies
    assert COOKIE_REFRESH in response.cookies
    assert COOKIE_CSRF in response.cookies


def test_csrf_required_for_cookie_authenticated_mutations(cookie_auth_client):
    client, _user = cookie_auth_client
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "cookie@example.com", "password": "CookiePass1!"},
    )
    assert login.status_code == 200
    csrf = login.cookies.get(COOKIE_CSRF)
    assert csrf

    blocked = client.post("/api/v1/auth/logout")
    assert blocked.status_code == 403

    allowed = client.post(
        "/api/v1/auth/logout",
        headers={CSRF_HEADER: csrf},
    )
    assert allowed.status_code == 200
