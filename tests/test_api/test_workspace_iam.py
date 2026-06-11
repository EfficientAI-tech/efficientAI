"""Tests for workspace RBAC: roles, membership, and capability enforcement."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.auth.capabilities import (
    CALLS_VIEW,
    METRICS_VIEW,
    SYSTEM_ROLE_ADMIN,
    SYSTEM_ROLE_VIEWER,
)
from app.core.auth.principal import AuthMethod, Principal
from app.core.auth.dependency import get_principal
from app.database import get_db
from app.dependencies import get_organization_id, get_workspace_context, get_workspace_id
from app.models.database import (
    Organization,
    OrganizationMember,
    RoleEnum,
    User,
    Workspace,
    WorkspaceMember,
    WorkspaceRole,
)
from app.services.workspace_rbac import (
    add_workspace_member,
    resolve_workspace_capabilities,
    seed_system_workspace_roles,
)
from app.api.v1.routes import metrics, workspace_iam, workspaces


@pytest.fixture
def rbac_org(db_session):
    org = Organization(id=uuid4(), name="RBAC Org")
    db_session.add(org)
    db_session.commit()
    return org


@pytest.fixture
def rbac_users(db_session, rbac_org):
    admin = User(id=uuid4(), email="admin@test.local", name="Admin")
    viewer = User(id=uuid4(), email="viewer@test.local", name="Viewer")
    db_session.add_all([admin, viewer])
    db_session.add_all(
        [
            OrganizationMember(
                organization_id=rbac_org.id,
                user_id=admin.id,
                role=RoleEnum.ADMIN,
            ),
            OrganizationMember(
                organization_id=rbac_org.id,
                user_id=viewer.id,
                role=RoleEnum.READER,
            ),
        ]
    )
    db_session.commit()
    return {"admin": admin, "viewer": viewer}


@pytest.fixture
def rbac_workspace(db_session, rbac_org, rbac_users):
    roles = seed_system_workspace_roles(db_session, organization_id=rbac_org.id)
    ws = Workspace(
        id=uuid4(),
        organization_id=rbac_org.id,
        name="Project A",
        slug="project_a",
        is_default=False,
    )
    db_session.add(ws)
    db_session.flush()
    add_workspace_member(
        db_session,
        workspace_id=ws.id,
        user_id=rbac_users["viewer"].id,
        role_id=roles[SYSTEM_ROLE_VIEWER].id,
    )
    db_session.commit()
    return ws


def test_seed_system_roles_idempotent(db_session, rbac_org):
    first = seed_system_workspace_roles(db_session, organization_id=rbac_org.id)
    second = seed_system_workspace_roles(db_session, organization_id=rbac_org.id)
    assert set(first.keys()) == {SYSTEM_ROLE_VIEWER, "Editor", SYSTEM_ROLE_ADMIN}
    assert first[SYSTEM_ROLE_VIEWER].id == second[SYSTEM_ROLE_VIEWER].id


def test_resolve_capabilities_org_admin_bypass(db_session, rbac_org, rbac_users, rbac_workspace):
    principal = Principal(
        organization_id=rbac_org.id,
        auth_method=AuthMethod.LOCAL_PASSWORD,
        user_id=rbac_users["admin"].id,
    )
    caps, membership, role = resolve_workspace_capabilities(
        db_session,
        principal=principal,
        workspace_id=rbac_workspace.id,
        organization_id=rbac_org.id,
    )
    assert CALLS_VIEW in caps
    assert METRICS_VIEW in caps
    assert membership is None
    assert role is None


def test_resolve_capabilities_non_member_empty(db_session, rbac_org, rbac_users, rbac_workspace):
    outsider = User(id=uuid4(), email="out@test.local", name="Out")
    db_session.add(outsider)
    db_session.add(
        OrganizationMember(
            organization_id=rbac_org.id,
            user_id=outsider.id,
            role=RoleEnum.READER,
        )
    )
    db_session.commit()

    principal = Principal(
        organization_id=rbac_org.id,
        auth_method=AuthMethod.LOCAL_PASSWORD,
        user_id=outsider.id,
    )
    caps, membership, role = resolve_workspace_capabilities(
        db_session,
        principal=principal,
        workspace_id=rbac_workspace.id,
        organization_id=rbac_org.id,
    )
    assert caps == set()
    assert membership is None


def test_list_workspaces_filtered_for_member(db_session, rbac_org, rbac_users, rbac_workspace):
    app = FastAPI()
    app.include_router(workspaces.router, prefix="/api/v1")

    def _principal():
        return Principal(
            organization_id=rbac_org.id,
            auth_method=AuthMethod.LOCAL_PASSWORD,
            user_id=rbac_users["viewer"].id,
        )

    def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_principal] = _principal
    app.dependency_overrides[get_organization_id] = lambda: rbac_org.id

    with TestClient(app) as client:
        response = client.get("/api/v1/workspaces")
    assert response.status_code == 200
    names = {w["name"] for w in response.json()}
    assert names == {"Project A"}


def test_workspace_members_require_view_capability(
    db_session, rbac_org, rbac_users, rbac_workspace
):
    app = FastAPI()
    app.include_router(workspace_iam.router, prefix="/api/v1")

    roles = seed_system_workspace_roles(db_session, organization_id=rbac_org.id)
    ws_b = Workspace(
        id=uuid4(),
        organization_id=rbac_org.id,
        name="Closed",
        slug="closed",
        is_default=False,
    )
    db_session.add(ws_b)
    db_session.commit()

    def _principal():
        return Principal(
            organization_id=rbac_org.id,
            auth_method=AuthMethod.LOCAL_PASSWORD,
            user_id=rbac_users["viewer"].id,
        )

    def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_principal] = _principal
    app.dependency_overrides[get_organization_id] = lambda: rbac_org.id

    with TestClient(app) as client:
        ok = client.get(f"/api/v1/workspaces/{rbac_workspace.id}/members")
        denied = client.get(f"/api/v1/workspaces/{ws_b.id}/members")

    assert ok.status_code == 200
    assert denied.status_code == 403

    add_workspace_member(
        db_session,
        workspace_id=ws_b.id,
        user_id=rbac_users["viewer"].id,
        role_id=roles[SYSTEM_ROLE_ADMIN].id,
    )
    db_session.commit()

    with TestClient(app) as client:
        allowed = client.get(f"/api/v1/workspaces/{ws_b.id}/members")
    assert allowed.status_code == 200
