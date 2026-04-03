"""API tests for IAM routes."""

import pytest

from app.models.database import OrganizationMember


@pytest.fixture
def iam_admin_override(authenticated_client, user_context):
    from app.api.v1.routes import iam

    authenticated_client.app.dependency_overrides[iam.require_admin_role] = lambda: user_context["user"]
    yield
    authenticated_client.app.dependency_overrides.pop(iam.require_admin_role, None)


def test_list_organization_users(authenticated_client, user_context):
    response = authenticated_client.get("/api/v1/iam/users")

    assert response.status_code == 200
    users = response.json()
    assert len(users) == 1
    assert users[0]["user"]["email"] == user_context["user"].email


def test_invite_and_list_invitations(iam_admin_override, authenticated_client):
    invite_response = authenticated_client.post(
        "/api/v1/iam/invitations",
        json={"email": "invitee@example.com", "role": "reader"},
    )
    assert invite_response.status_code == 201
    assert invite_response.json()["email"] == "invitee@example.com"

    list_response = authenticated_client.get("/api/v1/iam/invitations")
    assert list_response.status_code == 200
    assert len(list_response.json()) == 1


def test_update_user_role(iam_admin_override, authenticated_client, db_session, org_id, make_user):
    user_to_update = make_user(email="reader@example.com", name="Reader User")
    membership = OrganizationMember(
        organization_id=org_id,
        user_id=user_to_update.id,
        role="reader",
    )
    db_session.add(membership)
    db_session.commit()

    response = authenticated_client.put(
        f"/api/v1/iam/users/{user_to_update.id}/role",
        json={"role": "admin"},
    )

    assert response.status_code == 200
    assert response.json()["role"] == "admin"
