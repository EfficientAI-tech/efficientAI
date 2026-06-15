"""Tests for workspace RBAC: roles, membership, and capability enforcement."""

from __future__ import annotations

from uuid import uuid4
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.auth.capabilities import (
    CALLS_VIEW,
    METRICS_VIEW,
    SYSTEM_ROLE_ADMIN,
    SYSTEM_ROLE_VIEWER,
    WORKSPACE_MEMBERS_MANAGE,
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
    writer = User(id=uuid4(), email="writer@test.local", name="Writer")
    db_session.add_all([admin, viewer, writer])
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
            OrganizationMember(
                organization_id=rbac_org.id,
                user_id=writer.id,
                role=RoleEnum.WRITER,
            ),
        ]
    )
    db_session.commit()
    return {"admin": admin, "viewer": viewer, "writer": writer}


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


def _iam_test_app(db_session, principal_factory):
    app = FastAPI()
    app.include_router(workspace_iam.router, prefix="/api/v1")

    def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_principal] = principal_factory
    return app


def test_list_capabilities_requires_auth():
    app = FastAPI()
    app.include_router(workspace_iam.router, prefix="/api/v1")

    with TestClient(app) as client:
        response = client.get("/api/v1/capabilities")
    assert response.status_code == 401


def test_list_capabilities_with_auth(db_session, rbac_org, rbac_users):
    app = _iam_test_app(
        db_session,
        lambda: Principal(
            organization_id=rbac_org.id,
            auth_method=AuthMethod.LOCAL_PASSWORD,
            user_id=rbac_users["admin"].id,
        ),
    )
    app.dependency_overrides[get_organization_id] = lambda: rbac_org.id

    with TestClient(app) as client:
        response = client.get("/api/v1/capabilities")
    assert response.status_code == 200
    assert isinstance(response.json(), list)
    assert len(response.json()) > 0


def test_org_reader_workspace_admin_capabilities_but_writes_blocked(
    db_session, rbac_org, rbac_users, rbac_workspace
):
    roles = seed_system_workspace_roles(db_session, organization_id=rbac_org.id)
    add_workspace_member(
        db_session,
        workspace_id=rbac_workspace.id,
        user_id=rbac_users["viewer"].id,
        role_id=roles[SYSTEM_ROLE_ADMIN].id,
    )
    db_session.commit()

    principal = Principal(
        organization_id=rbac_org.id,
        auth_method=AuthMethod.LOCAL_PASSWORD,
        user_id=rbac_users["viewer"].id,
    )
    caps, _, _ = resolve_workspace_capabilities(
        db_session,
        principal=principal,
        workspace_id=rbac_workspace.id,
        organization_id=rbac_org.id,
    )
    assert WORKSPACE_MEMBERS_MANAGE in caps

    from app.core.rbac_middleware import ReaderReadOnlyMiddleware

    app = FastAPI()
    app.add_middleware(ReaderReadOnlyMiddleware)
    app.include_router(workspace_iam.router, prefix="/api/v1")

    def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_organization_id] = lambda: rbac_org.id
    app.dependency_overrides[get_principal] = lambda: principal

    target_user = User(id=uuid4(), email="target@test.local", name="Target")
    db_session.add(target_user)
    db_session.add(
        OrganizationMember(
            organization_id=rbac_org.id,
            user_id=target_user.id,
            role=RoleEnum.READER,
        )
    )
    db_session.flush()
    add_workspace_member(
        db_session,
        workspace_id=rbac_workspace.id,
        user_id=target_user.id,
        role_id=roles[SYSTEM_ROLE_VIEWER].id,
    )
    db_session.commit()

    editor_role = roles["Editor"]

    with patch("app.core.rbac_middleware._resolve_principal", return_value=principal), patch(
        "app.core.rbac_middleware.get_org_role",
        return_value=RoleEnum.READER,
    ):
        with TestClient(app) as client:
            get_resp = client.get(
                f"/api/v1/workspaces/{rbac_workspace.id}/members",
                headers={"Authorization": "Bearer test-token"},
            )
            patch_resp = client.patch(
                f"/api/v1/workspaces/{rbac_workspace.id}/members/{target_user.id}",
                json={"role_id": str(editor_role.id)},
                headers={"Authorization": "Bearer test-token"},
            )

    assert get_resp.status_code == 200
    assert patch_resp.status_code == 403
    assert "reader" in patch_resp.json()["detail"].lower()


def test_self_demote_workspace_admin_forbidden(
    db_session, rbac_org, rbac_users, rbac_workspace
):
    roles = seed_system_workspace_roles(db_session, organization_id=rbac_org.id)
    add_workspace_member(
        db_session,
        workspace_id=rbac_workspace.id,
        user_id=rbac_users["writer"].id,
        role_id=roles[SYSTEM_ROLE_ADMIN].id,
    )
    db_session.commit()

    app = _iam_test_app(
        db_session,
        lambda: Principal(
            organization_id=rbac_org.id,
            auth_method=AuthMethod.LOCAL_PASSWORD,
            user_id=rbac_users["writer"].id,
        ),
    )
    app.dependency_overrides[get_organization_id] = lambda: rbac_org.id

    with TestClient(app) as client:
        response = client.patch(
            f"/api/v1/workspaces/{rbac_workspace.id}/members/{rbac_users['writer'].id}",
            json={"role_id": str(roles[SYSTEM_ROLE_VIEWER].id)},
        )

    assert response.status_code == 403
    assert "cannot demote your own workspace admin role" in response.json()["detail"].lower()


def test_demote_other_workspace_admin_allowed(
    db_session, rbac_org, rbac_users, rbac_workspace
):
    roles = seed_system_workspace_roles(db_session, organization_id=rbac_org.id)
    other_admin = User(id=uuid4(), email="other-admin@test.local", name="Other Admin")
    db_session.add(other_admin)
    db_session.add(
        OrganizationMember(
            organization_id=rbac_org.id,
            user_id=other_admin.id,
            role=RoleEnum.WRITER,
        )
    )
    db_session.flush()
    add_workspace_member(
        db_session,
        workspace_id=rbac_workspace.id,
        user_id=rbac_users["writer"].id,
        role_id=roles[SYSTEM_ROLE_ADMIN].id,
    )
    add_workspace_member(
        db_session,
        workspace_id=rbac_workspace.id,
        user_id=other_admin.id,
        role_id=roles[SYSTEM_ROLE_ADMIN].id,
    )
    db_session.commit()

    app = _iam_test_app(
        db_session,
        lambda: Principal(
            organization_id=rbac_org.id,
            auth_method=AuthMethod.LOCAL_PASSWORD,
            user_id=rbac_users["writer"].id,
        ),
    )
    app.dependency_overrides[get_organization_id] = lambda: rbac_org.id

    with TestClient(app) as client:
        response = client.patch(
            f"/api/v1/workspaces/{rbac_workspace.id}/members/{other_admin.id}",
            json={"role_id": str(roles[SYSTEM_ROLE_VIEWER].id)},
        )

    assert response.status_code == 200
    assert response.json()["role_name"] == SYSTEM_ROLE_VIEWER


def test_self_remove_requires_workspace_in_org(db_session, rbac_org, rbac_users):
    roles = seed_system_workspace_roles(db_session, organization_id=rbac_org.id)
    other_org = Organization(id=uuid4(), name="Other Org")
    db_session.add(other_org)
    db_session.flush()
    other_ws = Workspace(
        id=uuid4(),
        organization_id=other_org.id,
        name="Foreign",
        slug="foreign",
        is_default=False,
    )
    db_session.add(other_ws)
    db_session.flush()
    add_workspace_member(
        db_session,
        workspace_id=other_ws.id,
        user_id=rbac_users["viewer"].id,
        role_id=roles[SYSTEM_ROLE_VIEWER].id,
    )
    db_session.commit()

    app = _iam_test_app(
        db_session,
        lambda: Principal(
            organization_id=rbac_org.id,
            auth_method=AuthMethod.LOCAL_PASSWORD,
            user_id=rbac_users["viewer"].id,
        ),
    )
    app.dependency_overrides[get_organization_id] = lambda: rbac_org.id

    with TestClient(app) as client:
        response = client.delete(
            f"/api/v1/workspaces/{other_ws.id}/members/{rbac_users['viewer'].id}",
        )

    assert response.status_code == 404
    assert db_session.query(WorkspaceMember).filter(
        WorkspaceMember.workspace_id == other_ws.id,
        WorkspaceMember.user_id == rbac_users["viewer"].id,
    ).first() is not None


def test_update_workspace_missing_returns_404_not_403(
    db_session, rbac_org, rbac_users, rbac_workspace
):
    app = FastAPI()
    app.include_router(workspaces.router, prefix="/api/v1")

    def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_principal] = lambda: Principal(
        organization_id=rbac_org.id,
        auth_method=AuthMethod.LOCAL_PASSWORD,
        user_id=rbac_users["writer"].id,
    )
    app.dependency_overrides[get_organization_id] = lambda: rbac_org.id

    missing_id = uuid4()
    with TestClient(app) as client:
        response = client.patch(
            f"/api/v1/workspaces/{missing_id}",
            json={"name": "Renamed"},
        )

    assert response.status_code == 404


def test_require_capability_missing_capability_returns_403():
    """Regression: require_capability must not NameError on status import."""
    from uuid import uuid4

    from fastapi import HTTPException

    from app.core.auth.capabilities import CALLS_DELETE, CALLS_VIEW
    from app.dependencies import WorkspaceContext, require_capability

    dep = require_capability(CALLS_DELETE)
    ctx = WorkspaceContext(
        workspace_id=uuid4(),
        organization_id=uuid4(),
        capabilities=frozenset([CALLS_VIEW]),
        role_name="Viewer",
    )

    with pytest.raises(HTTPException) as exc_info:
        dep(ctx=ctx)

    assert exc_info.value.status_code == 403
    assert "Workspace Admin role" in exc_info.value.detail
    assert "Viewer" in exc_info.value.detail


def test_capability_denied_message_maps_editor_and_admin():
    from app.core.auth.capabilities import (
        CALLS_DELETE,
        CALLS_IMPORT,
        capability_denied_message,
    )

    delete_msg = capability_denied_message(
        CALLS_DELETE,
        role_name="Viewer",
        workspace_label="the active workspace",
    )
    assert "Workspace Admin role" in delete_msg
    assert "Viewer" in delete_msg

    import_msg = capability_denied_message(
        CALLS_IMPORT,
        role_name="Viewer",
        workspace_label="the active workspace",
    )
    assert "Editor role" in import_msg
    assert "Viewer" in import_msg


def _iam_admin_client(db_session, rbac_org, rbac_users):
    app = FastAPI()
    app.include_router(workspace_iam.router, prefix="/api/v1")

    def _principal():
        return Principal(
            organization_id=rbac_org.id,
            auth_method=AuthMethod.LOCAL_PASSWORD,
            user_id=rbac_users["admin"].id,
        )

    def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_principal] = _principal
    app.dependency_overrides[get_organization_id] = lambda: rbac_org.id
    return TestClient(app)


def test_workspace_role_crud(db_session, rbac_org, rbac_users):
    with _iam_admin_client(db_session, rbac_org, rbac_users) as client:
        create = client.post(
            "/api/v1/workspace-roles",
            json={
                "name": "Eval Runner",
                "description": "Can view and run evals",
                "capabilities": ["evals.view", "evals.run"],
            },
        )
        assert create.status_code == 201
        role_id = create.json()["id"]
        assert create.json()["is_system"] is False

        listed = client.get("/api/v1/workspace-roles")
        assert listed.status_code == 200
        names = {r["name"] for r in listed.json()}
        assert "Eval Runner" in names

        update = client.patch(
            f"/api/v1/workspace-roles/{role_id}",
            json={
                "name": "Eval Runner Plus",
                "capabilities": ["evals.view", "evals.run", "reports.view"],
            },
        )
        assert update.status_code == 200
        assert update.json()["name"] == "Eval Runner Plus"
        assert "reports.view" in update.json()["capabilities"]

        delete = client.delete(f"/api/v1/workspace-roles/{role_id}")
        assert delete.status_code == 204


def test_cannot_update_system_workspace_role(db_session, rbac_org, rbac_users):
    roles = seed_system_workspace_roles(db_session, organization_id=rbac_org.id)
    viewer_role = roles[SYSTEM_ROLE_VIEWER]

    with _iam_admin_client(db_session, rbac_org, rbac_users) as client:
        response = client.patch(
            f"/api/v1/workspace-roles/{viewer_role.id}",
            json={"name": "Renamed Viewer"},
        )
    assert response.status_code == 400
    assert "System roles cannot be modified" in response.json()["detail"]
