"""API tests for IAM routes."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.config import settings
from app.models.database import Invitation, OrganizationMember
from app.models.enums import InvitationStatus, RoleEnum


@pytest.fixture
def enable_local_password(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_PROVIDERS", ["api_key", "local_password"])
    monkeypatch.setattr(settings, "AUTH_LOCAL_ALLOW_SIGNUP", True)
    monkeypatch.setattr(settings, "AUTH_GATED_SIGNUP_ENABLED", False)
    return settings


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
    body = invite_response.json()
    assert body["email"] == "invitee@example.com"
    assert body["invite_path"]
    assert body["invite_path"].startswith("/invite/")
    assert body["invite_url"]
    assert "/invite/" in body["invite_url"]

    list_response = authenticated_client.get("/api/v1/iam/invitations")
    assert list_response.status_code == 200
    listed = list_response.json()
    assert len(listed) == 1
    assert listed[0]["invite_path"]
    assert listed[0]["invite_url"]


def test_list_invitations_excludes_accepted(
    iam_admin_override, authenticated_client, db_session, org_id, user_context
):
    db_session.add(
        Invitation(
            id=uuid4(),
            organization_id=org_id,
            invited_by_id=user_context["user"].id,
            email="accepted@example.com",
            role="reader",
            status=InvitationStatus.ACCEPTED.value,
            token=f"tok-{uuid4()}",
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        )
    )
    db_session.commit()

    list_response = authenticated_client.get("/api/v1/iam/invitations")
    assert list_response.status_code == 200
    emails = {item["email"] for item in list_response.json()}
    assert "accepted@example.com" not in emails


def test_invite_duplicate_pending_returns_conflict(iam_admin_override, authenticated_client):
    payload = {"email": "dup@example.com", "role": "reader"}
    first = authenticated_client.post("/api/v1/iam/invitations", json=payload)
    assert first.status_code == 201

    second = authenticated_client.post("/api/v1/iam/invitations", json=payload)
    assert second.status_code == 409
    assert second.json()["detail"] == "An invitation is already pending for this email"


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


def test_get_organization(authenticated_client, user_context, org_id, seed_org):
    response = authenticated_client.get("/api/v1/iam/organization")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(org_id)
    assert body["name"] == seed_org.name


def test_update_organization_as_admin(iam_admin_override, authenticated_client, db_session, seed_org):
    response = authenticated_client.patch(
        "/api/v1/iam/organization",
        json={"name": "Renamed Org"},
    )

    assert response.status_code == 200
    assert response.json()["name"] == "Renamed Org"
    db_session.refresh(seed_org)
    assert seed_org.name == "Renamed Org"


def test_update_organization_rejects_reader(authenticated_client, user_context, db_session):
    user_context["membership"].role = RoleEnum.READER.value
    db_session.commit()

    response = authenticated_client.patch(
        "/api/v1/iam/organization",
        json={"name": "Should Fail"},
    )

    assert response.status_code == 403


def test_update_organization_rejects_empty_name(iam_admin_override, authenticated_client):
    response = authenticated_client.patch(
        "/api/v1/iam/organization",
        json={"name": "   "},
    )

    assert response.status_code == 422


def test_remove_user_clears_workspace_memberships(
    iam_admin_override,
    authenticated_client,
    db_session,
    org_id,
    make_user,
    default_workspace,
):
    from app.models.database import Workspace, WorkspaceMember
    from app.services.workspace_rbac import backfill_org_workspace_memberships

    member_user = make_user(email="remove-me@example.com", name="Remove Me")
    db_session.add(
        OrganizationMember(
            organization_id=org_id,
            user_id=member_user.id,
            role=RoleEnum.READER.value,
        )
    )
    db_session.commit()
    backfill_org_workspace_memberships(db_session, organization_id=org_id)

    assert (
        db_session.query(WorkspaceMember)
        .join(Workspace, Workspace.id == WorkspaceMember.workspace_id)
        .filter(
            Workspace.organization_id == org_id,
            WorkspaceMember.user_id == member_user.id,
        )
        .count()
        == 1
    )

    response = authenticated_client.delete(f"/api/v1/iam/users/{member_user.id}")
    assert response.status_code == 204

    assert (
        db_session.query(WorkspaceMember)
        .join(Workspace, Workspace.id == WorkspaceMember.workspace_id)
        .filter(
            Workspace.organization_id == org_id,
            WorkspaceMember.user_id == member_user.id,
        )
        .count()
        == 0
    )
    assert (
        db_session.query(OrganizationMember)
        .filter(
            OrganizationMember.organization_id == org_id,
            OrganizationMember.user_id == member_user.id,
        )
        .first()
        is None
    )


def test_remove_user_deletes_org_credential(
    iam_admin_override,
    authenticated_client,
    db_session,
    org_id,
    make_user,
):
    from app.core.auth.org_credentials import (
        get_credential,
        get_session_revocation_floor,
        provision_membership_credential,
        set_org_password_hash,
    )
    from app.core.password import hash_password
    from app.models.database import OrganizationMemberCredential

    member_user = make_user(email="credential-cleanup@example.com", name="Credential Cleanup")
    db_session.add(
        OrganizationMember(
            organization_id=org_id,
            user_id=member_user.id,
            role=RoleEnum.READER.value,
        )
    )
    db_session.flush()
    credential = provision_membership_credential(
        db_session, user_id=member_user.id, organization_id=org_id
    )
    set_org_password_hash(credential, hash_password("RemoveMe1!"))
    db_session.commit()

    assert get_credential(db_session, user_id=member_user.id, organization_id=org_id) is not None

    response = authenticated_client.delete(f"/api/v1/iam/users/{member_user.id}")
    assert response.status_code == 204

    assert get_credential(db_session, user_id=member_user.id, organization_id=org_id) is None
    assert (
        db_session.query(OrganizationMemberCredential)
        .filter(
            OrganizationMemberCredential.organization_id == org_id,
            OrganizationMemberCredential.user_id == member_user.id,
        )
        .first()
        is None
    )
    assert get_session_revocation_floor(
        db_session, user_id=member_user.id, organization_id=org_id
    ) >= 1


def test_removed_member_reinvite_does_not_reactivate_old_access_token(
    iam_admin_override,
    authenticated_client,
    client,
    db_session,
    org_id,
    make_user,
    user_context,
    enable_local_password,
):
    from datetime import datetime, timedelta, timezone

    import pytest

    from app.core.auth.local import LocalPasswordProvider
    from app.core.auth.org_credentials import get_credential, set_org_password_hash
    from app.core.auth.providers import AuthError, RawCredential, reset_provider_registry
    from app.models.database import Invitation, InvitationStatus
    from app.services.invitation_service import accept_invitation
    from app.services.organization_provisioning import provision_default_workspace
    from app.core.auth.org_credentials import provision_membership_credential
    from app.core.password import hash_password

    password = "ReturnPass1!"
    member_user = make_user(email="returning@example.com", name="Returning User")
    db_session.add(
        OrganizationMember(
            organization_id=org_id,
            user_id=member_user.id,
            role=RoleEnum.READER.value,
        )
    )
    db_session.flush()
    credential = provision_membership_credential(
        db_session, user_id=member_user.id, organization_id=org_id
    )
    set_org_password_hash(credential, hash_password(password))
    db_session.commit()

    login = client.post(
        "/api/v1/auth/login",
        json={
            "email": member_user.email,
            "password": password,
            "organization_id": str(org_id),
        },
    )
    assert login.status_code == 200
    old_access_token = login.json()["access_token"]

    removed = authenticated_client.delete(f"/api/v1/iam/users/{member_user.id}")
    assert removed.status_code == 204

    provision_default_workspace(
        db_session,
        organization_id=org_id,
        created_by_user_id=user_context["user"].id,
    )
    invitation = Invitation(
        organization_id=org_id,
        invited_by_id=user_context["user"].id,
        email=member_user.email,
        role=RoleEnum.READER.value,
        status=InvitationStatus.PENDING.value,
        token="returning-member",
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )
    db_session.add(invitation)
    db_session.commit()

    accept_invitation(db_session, invitation, member_user)

    restored = get_credential(db_session, user_id=member_user.id, organization_id=org_id)
    assert restored is not None
    assert restored.session_epoch >= 1

    provider = LocalPasswordProvider()
    reset_provider_registry()
    with pytest.raises(AuthError):
        provider.authenticate(RawCredential(bearer_token=old_access_token), db_session)
