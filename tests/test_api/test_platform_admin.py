"""Tests for platform admin authentication and org management."""

from __future__ import annotations

import pytest

from app.config import settings
from app.core.auth.platform_admin import create_platform_access_token
from app.core.auth.tokens import create_access_token
from app.core.password import hash_password
from app.models.database import (
    Organization,
    OrganizationMember,
    PlatformAdmin,
    RoleEnum,
    User,
)

TEST_PASSWORD = "TestPass1!"
PLATFORM_PASSWORD = "Platform1!"


@pytest.fixture
def enable_local_password(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_PROVIDERS", ["api_key", "local_password"])
    monkeypatch.setattr(settings, "AUTH_LOCAL_ALLOW_SIGNUP", True)
    return settings


@pytest.fixture
def platform_admin_user(db_session):
    admin = PlatformAdmin(
        email="platform@example.com",
        password_hash=hash_password(PLATFORM_PASSWORD),
        is_active=True,
    )
    db_session.add(admin)
    db_session.commit()
    db_session.refresh(admin)
    return admin


@pytest.fixture
def platform_admin_client(client, platform_admin_user):
    token, _ = create_platform_access_token(
        platform_admin_id=platform_admin_user.id,
        email=platform_admin_user.email,
    )
    client.headers.update({"Authorization": f"Bearer {token}"})
    return client


def test_platform_login_returns_token(client, platform_admin_user):
    response = client.post(
        "/api/v1/platform/auth/login",
        json={"email": "platform@example.com", "password": PLATFORM_PASSWORD},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["access_token"]
    assert body["admin"]["email"] == "platform@example.com"


def test_platform_login_returns_404_when_no_admins(client, db_session):
    db_session.query(PlatformAdmin).delete()
    db_session.commit()
    response = client.post(
        "/api/v1/platform/auth/login",
        json={"email": "platform@example.com", "password": PLATFORM_PASSWORD},
    )
    assert response.status_code == 404


def test_platform_routes_reject_org_scoped_token(
    client, db_session, platform_admin_user, enable_local_password
):
    user = User(
        email="user@example.com",
        password_hash=hash_password(TEST_PASSWORD),
        is_active=True,
        auth_provider="local",
    )
    org = Organization(name="Org A")
    db_session.add_all([user, org])
    db_session.flush()
    db_session.add(
        OrganizationMember(
            organization_id=org.id,
            user_id=user.id,
            role=RoleEnum.ADMIN.value,
        )
    )
    db_session.commit()

    org_token, _, _ = create_access_token(
        user_id=user.id,
        organization_id=org.id,
        email=user.email,
    )
    client.headers.update({"Authorization": f"Bearer {org_token}"})
    response = client.get("/api/v1/platform/organizations/stats")
    assert response.status_code == 401


def test_list_organizations_and_stats(platform_admin_client, db_session):
    initial_total = db_session.query(Organization).count()
    initial_active = (
        db_session.query(Organization)
        .filter(Organization.is_active == True)  # noqa: E712
        .count()
    )

    org1 = Organization(name="Alpha Org")
    org2 = Organization(name="Beta Org", is_active=False)
    db_session.add_all([org1, org2])
    db_session.flush()
    user = User(email="member@example.com", is_active=True)
    db_session.add(user)
    db_session.flush()
    db_session.add(
        OrganizationMember(
            organization_id=org1.id,
            user_id=user.id,
            role=RoleEnum.ADMIN.value,
        )
    )
    db_session.commit()

    stats = platform_admin_client.get("/api/v1/platform/organizations/stats")
    assert stats.status_code == 200
    assert stats.json()["total"] == initial_total + 2
    assert stats.json()["active"] == initial_active + 1
    assert stats.json()["disabled"] == (initial_total - initial_active) + 1

    listing = platform_admin_client.get("/api/v1/platform/organizations")
    assert listing.status_code == 200
    items = listing.json()["items"]
    assert len(items) == initial_total + 2
    alpha = next(item for item in items if item["name"] == "Alpha Org")
    assert alpha["member_count"] == 1


def test_disable_organization(platform_admin_client, db_session):
    org = Organization(name="To Disable")
    db_session.add(org)
    db_session.commit()

    response = platform_admin_client.patch(
        f"/api/v1/platform/organizations/{org.id}",
        json={"is_active": False},
    )
    assert response.status_code == 200
    assert response.json()["is_active"] is False

    db_session.refresh(org)
    assert org.is_active is False
    assert org.disabled_at is not None


def test_platform_reset_password(platform_admin_client, client, db_session, enable_local_password):
    org = Organization(name="Reset Org")
    user = User(
        email="admin@reset.org",
        password_hash=hash_password(TEST_PASSWORD),
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
    db_session.commit()

    new_password = "NewPass2!"
    response = platform_admin_client.post(
        f"/api/v1/platform/organizations/{org.id}/users/{user.id}/reset-password",
        json={"new_password": new_password},
    )
    assert response.status_code == 200
    assert response.json()["email"] == "admin@reset.org"

    login = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@reset.org", "password": new_password},
    )
    assert login.status_code == 200


def test_create_and_use_signup_reference_code(
    platform_admin_client, client, db_session, enable_local_password, monkeypatch
):
    monkeypatch.setattr(settings, "AUTH_GATED_SIGNUP_ENABLED", True)

    create = platform_admin_client.post(
        "/api/v1/platform/signup-codes",
        json={"code": "BETA2026", "max_uses": 1, "label": "Beta invite"},
    )
    assert create.status_code == 201
    assert create.json()["code"] == "BETA2026"

    signup = client.post(
        "/api/v1/auth/signup",
        json={
            "email": "gated@example.com",
            "password": TEST_PASSWORD,
            "reference_code": "BETA2026",
        },
    )
    assert signup.status_code == 200

    duplicate = client.post(
        "/api/v1/auth/signup",
        json={
            "email": "gated2@example.com",
            "password": TEST_PASSWORD,
            "reference_code": "BETA2026",
        },
    )
    assert duplicate.status_code == 403


def test_gated_signup_rejects_missing_code(client, enable_local_password, monkeypatch):
    monkeypatch.setattr(settings, "AUTH_GATED_SIGNUP_ENABLED", True)
    response = client.post(
        "/api/v1/auth/signup",
        json={"email": "nogate@example.com", "password": TEST_PASSWORD},
    )
    assert response.status_code == 403


def test_disabled_org_blocks_api_key_auth(authenticated_client, db_session, org_id):
    from app.dependencies import get_api_key, get_organization_id

    org = db_session.query(Organization).filter(Organization.id == org_id).first()
    org.is_active = False
    db_session.commit()

    # The shared test client bypasses auth deps by default; restore real
    # resolution so get_principal (and org-disable checks) actually run.
    authenticated_client.app.dependency_overrides.pop(get_organization_id, None)
    authenticated_client.app.dependency_overrides.pop(get_api_key, None)

    response = authenticated_client.get("/api/v1/iam/organization")
    assert response.status_code == 403
    assert "disabled" in response.json()["detail"].lower()


def test_disabled_org_blocks_login(client, db_session, enable_local_password):
    org = Organization(name="Disabled Org", is_active=False)
    user = User(
        email="locked@example.com",
        password_hash=hash_password(TEST_PASSWORD),
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
    db_session.commit()

    response = client.post(
        "/api/v1/auth/login",
        json={"email": "locked@example.com", "password": TEST_PASSWORD},
    )
    assert response.status_code == 403


def test_auth_config_reports_gated_signup(client, enable_local_password, monkeypatch):
    monkeypatch.setattr(settings, "AUTH_GATED_SIGNUP_ENABLED", True)
    response = client.get("/api/v1/auth/config")
    assert response.status_code == 200
    assert response.json()["gated_signup"] is True
