"""Tests for auth dependency credential resolution."""

from unittest.mock import MagicMock
from uuid import uuid4

from app.config import settings
from app.core.auth.dependency import _resolve
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
