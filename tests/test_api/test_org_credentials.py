"""Tests for org-scoped passwords and admin reset."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.core.auth.local import LocalPasswordProvider
from app.core.auth.org_credentials import get_or_create_credential
from app.core.auth.providers import AuthError, RawCredential, reset_provider_registry
from app.core.auth.refresh_tokens import issue_refresh_token
from app.core.auth.tokens import create_access_token
from app.core.password import hash_password, verify_password
from app.models.database import Organization, OrganizationMember, RoleEnum, User


@pytest.fixture
def enable_local_password(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "AUTH_PROVIDERS", ["api_key", "local_password"])
    monkeypatch.setattr(settings, "AUTH_LOCAL_ALLOW_SIGNUP", True)


def _seed_multi_org_user(db_session, email: str, password: str):
    org_a = Organization(id=uuid4(), name="Org A")
    org_b = Organization(id=uuid4(), name="Org B")
    user = User(
        id=uuid4(),
        email=email,
        password_hash=hash_password(password),
        is_active=True,
        auth_provider="local",
    )
    db_session.add_all([org_a, org_b, user])
    db_session.flush()
    db_session.add_all(
        [
            OrganizationMember(organization_id=org_a.id, user_id=user.id, role=RoleEnum.ADMIN.value),
            OrganizationMember(organization_id=org_b.id, user_id=user.id, role=RoleEnum.READER.value),
        ]
    )
    db_session.flush()
    cred_a = get_or_create_credential(
        db_session, user_id=user.id, organization_id=org_a.id, user=user
    )
    cred_b = get_or_create_credential(
        db_session, user_id=user.id, organization_id=org_b.id, user=user
    )
    cred_a.password_hash = user.password_hash
    cred_b.password_hash = user.password_hash
    db_session.commit()
    return user, org_a, org_b, cred_a, cred_b


def test_admin_reset_password_only_invalidates_target_org_session(
    client, db_session, org_id, seed_org, enable_local_password
):
    org_b = Organization(id=uuid4(), name="Org B")
    user = User(
        id=uuid4(),
        email="multi-reset@example.com",
        password_hash=hash_password("Original1!"),
        is_active=True,
        auth_provider="local",
    )
    db_session.add_all([org_b, user])
    db_session.flush()
    db_session.add_all(
        [
            OrganizationMember(organization_id=org_id, user_id=user.id, role=RoleEnum.READER.value),
            OrganizationMember(organization_id=org_b.id, user_id=user.id, role=RoleEnum.READER.value),
        ]
    )
    db_session.flush()
    cred_a = get_or_create_credential(
        db_session, user_id=user.id, organization_id=org_id, user=user
    )
    cred_b = get_or_create_credential(
        db_session, user_id=user.id, organization_id=org_b.id, user=user
    )
    cred_a.password_hash = user.password_hash
    cred_b.password_hash = user.password_hash
    org_a_id = org_id

    admin = User(
        id=uuid4(),
        email="admin-reset@example.com",
        password_hash=hash_password("AdminPass1!"),
        is_active=True,
        auth_provider="local",
    )
    db_session.add(admin)
    db_session.flush()
    db_session.add(
        OrganizationMember(
            organization_id=org_a_id,
            user_id=admin.id,
            role=RoleEnum.ADMIN.value,
        )
    )
    db_session.flush()
    from app.core.auth.org_credentials import provision_membership_credential, set_org_password_hash

    admin_cred = provision_membership_credential(
        db_session, user_id=admin.id, organization_id=org_a_id
    )
    set_org_password_hash(admin_cred, hash_password("AdminPass1!"))
    db_session.commit()

    login_admin = client.post(
        "/api/v1/auth/login",
        json={"email": admin.email, "password": "AdminPass1!", "organization_id": str(org_a_id)},
    )
    assert login_admin.status_code == 200
    admin_token = login_admin.json()["access_token"]

    login_user_b = client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": "Original1!", "organization_id": str(org_b.id)},
    )
    assert login_user_b.status_code == 200
    user_b_token = login_user_b.json()["access_token"]

    reset = client.post(
        f"/api/v1/iam/users/{user.id}/reset-password",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"new_password": "ResetInA1!"},
    )
    assert reset.status_code == 200

    db_session.refresh(cred_a)
    db_session.refresh(cred_b)
    assert verify_password("ResetInA1!", cred_a.password_hash)
    assert verify_password("Original1!", cred_b.password_hash)
    assert cred_a.session_epoch == 1
    assert cred_b.session_epoch == 0

    provider = LocalPasswordProvider()
    reset_provider_registry()
    provider.authenticate(RawCredential(bearer_token=user_b_token), db_session)

    login_user_a = client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": "ResetInA1!", "organization_id": str(org_a_id)},
    )
    assert login_user_a.status_code == 200

    login_user_b_old = client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": "Original1!", "organization_id": str(org_b.id)},
    )
    assert login_user_b_old.status_code == 200


def test_login_only_unlocks_orgs_with_matching_password(
    client, db_session, enable_local_password
):
    user, org_a, org_b, _cred_a, cred_b = _seed_multi_org_user(
        db_session, "picker@example.com", "SharedPass1!"
    )
    cred_b.password_hash = hash_password("Different2!")
    db_session.commit()

    login_a = client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": "SharedPass1!", "organization_id": str(org_a.id)},
    )
    assert login_a.status_code == 200
    assert login_a.json()["access_token"]

    login_b = client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": "SharedPass1!", "organization_id": str(org_b.id)},
    )
    assert login_b.status_code == 401


def test_password_change_does_not_unlock_other_org(
    client, db_session, org_id, seed_org, enable_local_password
):
    org_b = Organization(id=uuid4(), name="Org B")
    user = User(
        id=uuid4(),
        email="leak-check@example.com",
        password_hash=hash_password("SharedPass1!"),
        is_active=True,
        auth_provider="local",
    )
    db_session.add_all([org_b, user])
    db_session.flush()
    db_session.add_all(
        [
            OrganizationMember(organization_id=org_id, user_id=user.id, role=RoleEnum.ADMIN.value),
            OrganizationMember(organization_id=org_b.id, user_id=user.id, role=RoleEnum.READER.value),
        ]
    )
    db_session.flush()
    cred_a = get_or_create_credential(
        db_session, user_id=user.id, organization_id=org_id, user=user
    )
    cred_b = get_or_create_credential(
        db_session, user_id=user.id, organization_id=org_b.id, user=user
    )
    cred_a.password_hash = user.password_hash
    cred_b.password_hash = hash_password("Different2!")
    db_session.commit()

    login_a = client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": "SharedPass1!", "organization_id": str(org_id)},
    )
    assert login_a.status_code == 200
    token_a = login_a.json()["access_token"]

    change = client.post(
        "/api/v1/auth/password",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"current_password": "SharedPass1!", "new_password": "ChangedA1!"},
    )
    assert change.status_code == 200

    db_session.refresh(user)
    db_session.refresh(cred_a)
    db_session.refresh(cred_b)
    assert verify_password("ChangedA1!", cred_a.password_hash)
    assert verify_password("Different2!", cred_b.password_hash)
    assert user.password_hash and verify_password("SharedPass1!", user.password_hash)

    login_b_new = client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": "ChangedA1!", "organization_id": str(org_b.id)},
    )
    assert login_b_new.status_code == 401

    login_b_old = client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": "Different2!", "organization_id": str(org_b.id)},
    )
    assert login_b_old.status_code == 200


def test_password_change_invalidates_only_current_org_session(
    db_session, org_id, seed_org, enable_local_password, client
):
    from app.core.auth.org_credentials import bump_org_session_epoch

    reset_provider_registry()
    other_org = Organization(id=uuid4(), name="Other Org")
    user = User(
        id=uuid4(),
        email="epoch-org@example.com",
        password_hash=hash_password("Original1!"),
        is_active=True,
        session_epoch=0,
        auth_provider="local",
    )
    db_session.add_all([other_org, user])
    db_session.flush()
    db_session.add_all(
        [
            OrganizationMember(organization_id=org_id, user_id=user.id, role=RoleEnum.ADMIN.value),
            OrganizationMember(organization_id=other_org.id, user_id=user.id, role=RoleEnum.READER.value),
        ]
    )
    db_session.flush()
    cred_current = get_or_create_credential(
        db_session, user_id=user.id, organization_id=org_id, user=user
    )
    cred_other = get_or_create_credential(
        db_session, user_id=user.id, organization_id=other_org.id, user=user
    )
    cred_current.password_hash = user.password_hash
    cred_other.password_hash = user.password_hash
    db_session.commit()

    token_current, _, _ = create_access_token(
        user_id=user.id,
        organization_id=org_id,
        email=user.email,
        session_epoch=cred_current.session_epoch,
        authenticated_org_ids=[str(org_id), str(other_org.id)],
    )
    token_other, _, _ = create_access_token(
        user_id=user.id,
        organization_id=other_org.id,
        email=user.email,
        session_epoch=cred_other.session_epoch,
        authenticated_org_ids=[str(org_id), str(other_org.id)],
    )

    provider = LocalPasswordProvider()
    provider.authenticate(RawCredential(bearer_token=token_current), db_session)
    provider.authenticate(RawCredential(bearer_token=token_other), db_session)

    bump_org_session_epoch(cred_current)
    db_session.commit()

    with pytest.raises(AuthError, match="Session expired"):
        provider.authenticate(RawCredential(bearer_token=token_current), db_session)
    provider.authenticate(RawCredential(bearer_token=token_other), db_session)


def test_accept_invitation_inherits_existing_org_password(db_session):
    from datetime import datetime, timedelta, timezone

    from app.core.auth.org_credentials import (
        get_credential,
        match_password_memberships,
        provision_membership_credential,
        set_org_password_hash,
    )
    from app.models.database import Invitation, InvitationStatus
    from app.services.invitation_service import accept_invitation
    from app.services.organization_provisioning import provision_default_workspace

    password = "InvitePass1!"
    home_org = Organization(id=uuid4(), name="Home Org")
    invited_org = Organization(id=uuid4(), name="Invited Org")
    inviter = User(id=uuid4(), email="inviter@example.com", is_active=True)
    user = User(
        id=uuid4(),
        email="invitee@example.com",
        password_hash=hash_password(password),
        is_active=True,
        auth_provider="local",
    )
    db_session.add_all([home_org, invited_org, inviter, user])
    db_session.flush()
    db_session.add(
        OrganizationMember(organization_id=home_org.id, user_id=user.id, role=RoleEnum.ADMIN.value)
    )
    db_session.flush()
    home_cred = provision_membership_credential(
        db_session, user_id=user.id, organization_id=home_org.id, user=user
    )
    set_org_password_hash(home_cred, user.password_hash)
    provision_default_workspace(
        db_session,
        organization_id=invited_org.id,
        created_by_user_id=inviter.id,
    )

    invitation = Invitation(
        organization_id=invited_org.id,
        invited_by_id=inviter.id,
        email=user.email,
        role=RoleEnum.WRITER.value,
        status=InvitationStatus.PENDING.value,
        token="invite-inherit",
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )
    db_session.add(invitation)
    db_session.commit()

    accept_invitation(db_session, invitation, user)

    invited_cred = get_credential(
        db_session, user_id=user.id, organization_id=invited_org.id
    )
    assert invited_cred is not None
    assert invited_cred.password_hash == home_cred.password_hash
    assert verify_password(password, invited_cred.password_hash)

    matched = match_password_memberships(db_session, user=user, password=password)
    assert {org.id for _, org in matched} == {home_org.id, invited_org.id}


def test_accept_invitation_uses_source_org_password_not_oldest(db_session):
    from datetime import datetime, timedelta, timezone

    from app.core.auth.org_credentials import (
        get_credential,
        match_password_memberships,
        provision_membership_credential,
        set_org_password_hash,
    )
    from app.models.database import Invitation, InvitationStatus
    from app.services.invitation_service import accept_invitation
    from app.services.organization_provisioning import provision_default_workspace

    password_a = "OrgAPass1!"
    password_b = "OrgBPass1!"
    org_a = Organization(id=uuid4(), name="Org A")
    org_b = Organization(id=uuid4(), name="Org B")
    invited_org = Organization(id=uuid4(), name="Invited Org")
    inviter = User(id=uuid4(), email="inviter@example.com", is_active=True)
    user = User(
        id=uuid4(),
        email="invitee@example.com",
        is_active=True,
        auth_provider="local",
    )
    db_session.add_all([org_a, org_b, invited_org, inviter, user])
    db_session.flush()
    db_session.add_all(
        [
            OrganizationMember(organization_id=org_a.id, user_id=user.id, role=RoleEnum.ADMIN.value),
            OrganizationMember(organization_id=org_b.id, user_id=user.id, role=RoleEnum.READER.value),
        ]
    )
    db_session.flush()
    cred_a = provision_membership_credential(
        db_session, user_id=user.id, organization_id=org_a.id, user=user
    )
    cred_b = provision_membership_credential(
        db_session, user_id=user.id, organization_id=org_b.id, user=user
    )
    set_org_password_hash(cred_a, hash_password(password_a))
    set_org_password_hash(cred_b, hash_password(password_b))
    provision_default_workspace(
        db_session,
        organization_id=invited_org.id,
        created_by_user_id=inviter.id,
    )
    invitation = Invitation(
        organization_id=invited_org.id,
        invited_by_id=inviter.id,
        email=user.email,
        role=RoleEnum.WRITER.value,
        status=InvitationStatus.PENDING.value,
        token="invite-source-org",
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )
    db_session.add(invitation)
    db_session.commit()

    accept_invitation(
        db_session,
        invitation,
        user,
        source_organization_id=org_b.id,
    )

    invited_cred = get_credential(
        db_session, user_id=user.id, organization_id=invited_org.id
    )
    assert invited_cred is not None
    assert invited_cred.password_hash == cred_b.password_hash
    assert invited_cred.password_hash != cred_a.password_hash
    assert verify_password(password_b, invited_cred.password_hash)
    assert not verify_password(password_a, invited_cred.password_hash)

    matched_b = match_password_memberships(db_session, user=user, password=password_b)
    assert {org.id for _, org in matched_b} == {org_b.id, invited_org.id}
    matched_a = match_password_memberships(db_session, user=user, password=password_a)
    assert {org.id for _, org in matched_a} == {org_a.id}


def test_accept_invitation_skips_inheritance_when_org_passwords_differ(db_session):
    from datetime import datetime, timedelta, timezone

    from app.core.auth.org_credentials import (
        get_credential,
        provision_membership_credential,
        set_org_password_hash,
    )
    from app.models.database import Invitation, InvitationStatus
    from app.services.invitation_service import accept_invitation
    from app.services.organization_provisioning import provision_default_workspace

    org_a = Organization(id=uuid4(), name="Org A")
    org_b = Organization(id=uuid4(), name="Org B")
    invited_org = Organization(id=uuid4(), name="Invited Org")
    inviter = User(id=uuid4(), email="inviter@example.com", is_active=True)
    user = User(
        id=uuid4(),
        email="invitee@example.com",
        is_active=True,
        auth_provider="local",
    )
    db_session.add_all([org_a, org_b, invited_org, inviter, user])
    db_session.flush()
    db_session.add_all(
        [
            OrganizationMember(organization_id=org_a.id, user_id=user.id, role=RoleEnum.ADMIN.value),
            OrganizationMember(organization_id=org_b.id, user_id=user.id, role=RoleEnum.READER.value),
        ]
    )
    db_session.flush()
    cred_a = provision_membership_credential(
        db_session, user_id=user.id, organization_id=org_a.id, user=user
    )
    cred_b = provision_membership_credential(
        db_session, user_id=user.id, organization_id=org_b.id, user=user
    )
    set_org_password_hash(cred_a, hash_password("OrgAPass1!"))
    set_org_password_hash(cred_b, hash_password("OrgBPass1!"))
    provision_default_workspace(
        db_session,
        organization_id=invited_org.id,
        created_by_user_id=inviter.id,
    )
    invitation = Invitation(
        organization_id=invited_org.id,
        invited_by_id=inviter.id,
        email=user.email,
        role=RoleEnum.WRITER.value,
        status=InvitationStatus.PENDING.value,
        token="invite-no-inherit",
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )
    db_session.add(invitation)
    db_session.commit()

    accept_invitation(db_session, invitation, user)

    invited_cred = get_credential(
        db_session, user_id=user.id, organization_id=invited_org.id
    )
    assert invited_cred is not None
    assert invited_cred.password_hash is None
