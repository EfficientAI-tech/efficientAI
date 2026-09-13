"""Security tests for reader RBAC middleware with query-token auth."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.routes import personas
from app.config import settings
from app.core.auth.tokens import create_access_token
from app.core.password import hash_password
from app.core.rbac_middleware import ReaderReadOnlyMiddleware
from app.database import get_db
from app.dependencies import get_organization_id, get_workspace_id
from app.models.database import OrganizationMember, RoleEnum, User
from app.services.workspace_rbac import add_workspace_member, seed_system_workspace_roles


@pytest.fixture
def enable_local_password(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_PROVIDERS", ["api_key", "local_password"])
    monkeypatch.setattr(settings, "AUTH_LOCAL_ALLOW_SIGNUP", True)
    monkeypatch.setattr(settings, "AUTH_GATED_SIGNUP_ENABLED", False)
    from app.core.auth.providers import reset_provider_registry

    reset_provider_registry()
    return settings


def test_reader_blocked_when_auth_via_query_access_token_only(
    db_session,
    org_id,
    seed_org,
    enable_local_password,
    default_workspace,
    monkeypatch,
):
    user = User(
        id=uuid4(),
        email="reader@example.com",
        password_hash=hash_password("ReaderPass1!"),
        is_active=True,
        session_epoch=1,
    )
    db_session.add(user)
    db_session.add(
        OrganizationMember(
            organization_id=org_id,
            user_id=user.id,
            role=RoleEnum.READER.value,
        )
    )
    roles = seed_system_workspace_roles(db_session, organization_id=org_id)
    add_workspace_member(
        db_session,
        workspace_id=default_workspace.id,
        user_id=user.id,
        role_id=roles["Editor"].id,
    )
    db_session.commit()

    token, _, _ = create_access_token(
        user_id=user.id,
        organization_id=org_id,
        email=user.email,
        session_epoch=user.session_epoch,
    )

    def _override_db():
        yield db_session

    monkeypatch.setattr("app.core.rbac_middleware.get_db", _override_db)

    app = FastAPI()
    app.add_middleware(ReaderReadOnlyMiddleware)
    app.include_router(personas.router, prefix="/api/v1")
    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_organization_id] = lambda: org_id
    app.dependency_overrides[get_workspace_id] = lambda: default_workspace.id

    with TestClient(app) as client:
        response = client.post(
            f"/api/v1/personas?access_token={token}",
            json={"name": "Blocked Persona", "gender": "neutral", "is_custom": False},
            headers={"X-Workspace-Id": str(default_workspace.id)},
        )

    assert response.status_code == 403
    assert "reader" in response.json()["detail"].lower()
