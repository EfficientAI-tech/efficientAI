"""Tests for auth dependency credential resolution."""

from unittest.mock import MagicMock
from uuid import uuid4

from app.config import settings
from app.core.auth.cookies import COOKIE_ACCESS
from app.core.auth.dependency import (
    _resolve,
    resolve_request_credentials_with_sources,
    resolve_websocket_credentials,
)
from app.core.auth.providers import reset_provider_registry
from app.core.auth.tokens import create_access_token, decode_access_token
from app.models.database import Organization, OrganizationMember, RoleEnum, User


def test_resolve_prefers_query_token_over_stale_access_token_cookie(
    db_session, org_id, monkeypatch
):
    monkeypatch.setattr(
        settings, "AUTH_PROVIDERS", ["api_key", "local_password"]
    )
    reset_provider_registry()
    user_id = uuid4()
    db_session.add(Organization(id=org_id, name="Auth Dep Test Org"))
    db_session.add(
        User(
            id=user_id,
            email="fresh@example.com",
            name="Fresh User",
            is_active=True,
        )
    )
    db_session.add(
        OrganizationMember(
            organization_id=org_id,
            user_id=user_id,
            role=RoleEnum.ADMIN.value,
        )
    )
    db_session.commit()

    fresh_token, _, _ = create_access_token(
        user_id=user_id,
        organization_id=org_id,
        email="fresh@example.com",
    )
    stale_token, _, _ = create_access_token(
        user_id=user_id,
        organization_id=org_id,
        email="stale@example.com",
    )

    request = MagicMock()
    request.headers = {}
    request.cookies = {"access_token": stale_token}
    request.query_params = {"token": fresh_token}

    principal = _resolve(None, None, None, db_session, request=request)

    assert principal is not None
    claims = decode_access_token(fresh_token)
    assert str(principal.user_id) == claims["sub"]
    assert principal.email == "fresh@example.com"


def test_resolve_accepts_eai_access_cookie(db_session, org_id, monkeypatch):
    monkeypatch.setattr(settings, "AUTH_PROVIDERS", ["api_key", "local_password"])
    reset_provider_registry()
    user_id = uuid4()
    db_session.add(Organization(id=org_id, name="Cookie Auth Dep Org"))
    db_session.add(
        User(
            id=user_id,
            email="cookie-dep@example.com",
            name="Cookie User",
            is_active=True,
        )
    )
    db_session.add(
        OrganizationMember(
            organization_id=org_id,
            user_id=user_id,
            role=RoleEnum.ADMIN.value,
        )
    )
    db_session.commit()

    access_token, _, _ = create_access_token(
        user_id=user_id,
        organization_id=org_id,
        email="cookie-dep@example.com",
    )

    request = MagicMock()
    request.headers = {}
    request.cookies = {COOKIE_ACCESS: access_token}
    request.query_params = {}

    principal = _resolve(None, None, None, db_session, request=request)

    assert principal is not None
    assert str(principal.user_id) == str(user_id)


def test_resolve_websocket_credentials_reads_eai_access_cookie(db_session, org_id, monkeypatch):
    monkeypatch.setattr(settings, "AUTH_PROVIDERS", ["api_key", "local_password"])
    reset_provider_registry()
    user_id = uuid4()
    access_token, _, _ = create_access_token(
        user_id=user_id,
        organization_id=org_id,
        email="ws-cookie@example.com",
    )

    websocket = MagicMock()
    websocket.query_params = {}
    websocket.cookies = {COOKIE_ACCESS: access_token}
    websocket.scope = {"query_string": b""}

    cred = resolve_websocket_credentials(websocket)
    assert cred.bearer_token == access_token
    assert cred.api_key is None


def test_resolve_credentials_with_sources_prefers_header_over_cookie():
    request = MagicMock()
    request.headers = {}
    request.cookies = {COOKIE_ACCESS: "cookie-token"}
    request.query_params = {}

    resolved = resolve_request_credentials_with_sources(
        authorization="Bearer header-token",
        request=request,
    )

    assert resolved.credential.bearer_token == "header-token"
    assert resolved.bearer_source == "header"


def test_resolve_credentials_with_sources_marks_cookie_bearer():
    request = MagicMock()
    request.headers = {}
    request.cookies = {COOKIE_ACCESS: "cookie-token"}
    request.query_params = {}

    resolved = resolve_request_credentials_with_sources(request=request)

    assert resolved.credential.bearer_token == "cookie-token"
    assert resolved.bearer_source == "cookie"
