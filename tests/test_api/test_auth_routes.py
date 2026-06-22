"""API tests for auth routes.

Covers the flexible-auth scenarios introduced for OSS/Enterprise deployments:

- Provider discovery via ``GET /auth/config``
- Local email/password signup + login
- Attaching a password to an API-key-only user (credential linking)
- Organization switching (scoped Bearer tokens, with API keys blocked)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4, UUID

import pytest

from app.config import settings
from app.core.auth.principal import AuthMethod, Principal
from app.core.password import hash_password
from app.models.database import (
    APIKey,
    Organization,
    OrganizationMember,
    RoleEnum,
    User,
    Workspace,
)
from app.services.organization_provisioning import provision_default_workspace

TEST_PASSWORD = "TestPass1!"


def _bind_api_key_to_user(db_session, *, api_key: str, org_id: UUID, user: User) -> APIKey:
    """Point the shared test API key at ``user``, replacing any bootstrap binding."""
    db_session.query(APIKey).filter(APIKey.key == api_key).delete()
    db_session.flush()
    key = APIKey(
        id=uuid4(),
        key=api_key,
        name="Test Key",
        organization_id=org_id,
        user_id=user.id,
        is_active=True,
    )
    db_session.add(key)
    membership = (
        db_session.query(OrganizationMember)
        .filter(
            OrganizationMember.organization_id == org_id,
            OrganizationMember.user_id == user.id,
        )
        .first()
    )
    if membership is None:
        db_session.add(
            OrganizationMember(
                organization_id=org_id,
                user_id=user.id,
                role=RoleEnum.ADMIN.value,
            )
        )
    db_session.commit()
    return key


# ---------------------------------------------------------------------------
# Existing smoke tests (kept verbatim - they guard the API-key path).
# ---------------------------------------------------------------------------

def test_generate_api_key_requires_authentication(client):
    """The endpoint used to be anonymous; it now demands a valid caller."""
    response = client.post("/api/v1/auth/generate-key", json={"name": "Primary Key"})
    assert response.status_code == 401


def test_generate_api_key_binds_new_key_to_caller_org(
    authenticated_client, user_context, db_session, org_id
):
    before = (
        db_session.query(APIKey)
        .filter(APIKey.organization_id == org_id)
        .count()
    )

    response = authenticated_client.post(
        "/api/v1/auth/generate-key", json={"name": "Secondary Key"}
    )

    assert response.status_code == 201
    body = response.json()
    assert body["key"]
    assert body["name"] == "Secondary Key"
    assert body["is_active"] is True

    # A new key was created inside the caller's existing org - not a new org.
    after_keys = (
        db_session.query(APIKey)
        .filter(APIKey.organization_id == org_id)
        .all()
    )
    assert len(after_keys) == before + 1
    created = next(k for k in after_keys if k.name == "Secondary Key")
    assert created.user_id == user_context["user"].id


def test_validate_api_key_returns_valid(authenticated_client):
    response = authenticated_client.post("/api/v1/auth/validate")

    assert response.status_code == 200
    assert response.json() == {"valid": True, "message": "API key is valid"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def enable_local_password(monkeypatch):
    """Enable the local_password provider + self-service signup for a test."""
    monkeypatch.setattr(settings, "AUTH_PROVIDERS", ["api_key", "local_password"])
    monkeypatch.setattr(settings, "AUTH_LOCAL_ALLOW_SIGNUP", True)
    return settings


@pytest.fixture
def disable_signup(monkeypatch, enable_local_password):
    monkeypatch.setattr(settings, "AUTH_LOCAL_ALLOW_SIGNUP", False)
    return settings


def _override_principal(test_client, principal: Principal):
    """Pin ``get_principal`` so the route sees the exact Principal we want."""
    from app.core.auth import dependency as auth_dep

    test_client.app.dependency_overrides[auth_dep.get_principal] = lambda: principal


def _clear_principal_override(test_client):
    from app.core.auth import dependency as auth_dep

    test_client.app.dependency_overrides.pop(auth_dep.get_principal, None)


# ---------------------------------------------------------------------------
# GET /auth/config - provider discovery
# ---------------------------------------------------------------------------

def test_auth_config_defaults_to_api_key_only(client, monkeypatch):
    """OSS default - only api_key is enabled, local_password is listed but off."""
    monkeypatch.setattr(settings, "AUTH_PROVIDERS", ["api_key"])

    response = client.get("/api/v1/auth/config")

    assert response.status_code == 200
    body = response.json()
    providers = {p["name"]: p for p in body["providers"]}

    assert providers["api_key"]["enabled"] is True
    assert providers["local_password"]["enabled"] is False
    assert providers["local_password"]["supports_signup"] is False
    # external_oidc only appears when the license enables it - unlicensed here.
    assert "external_oidc" not in providers


def test_auth_config_reports_local_password_and_signup_flag(
    client, enable_local_password
):
    response = client.get("/api/v1/auth/config")

    assert response.status_code == 200
    providers = {p["name"]: p for p in response.json()["providers"]}

    assert providers["local_password"]["enabled"] is True
    assert providers["local_password"]["supports_password"] is True
    assert providers["local_password"]["supports_signup"] is True


def test_auth_config_signup_flag_reflects_settings(client, disable_signup):
    response = client.get("/api/v1/auth/config")

    providers = {p["name"]: p for p in response.json()["providers"]}
    assert providers["local_password"]["enabled"] is True
    assert providers["local_password"]["supports_signup"] is False


# ---------------------------------------------------------------------------
# POST /auth/signup
# ---------------------------------------------------------------------------

def test_signup_creates_user_org_and_admin_membership(
    client, db_session, enable_local_password
):
    response = client.post(
        "/api/v1/auth/signup",
        json={
            "email": "alice@example.com",
            "password": "Correct1!Horse",
            "first_name": "Alice",
            "last_name": "Nguyen",
            "organization_name": "Acme Inc",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["access_token"]
    assert body["token_type"].lower() == "bearer"
    assert body["expires_in"] > 0
    assert body["user"]["email"] == "alice@example.com"
    assert body["user"]["role"] == RoleEnum.ADMIN.value
    assert body["user"]["has_password"] is True
    assert body["user"]["email_is_placeholder"] is False

    user = db_session.query(User).filter(User.email == "alice@example.com").one()
    org = db_session.query(Organization).filter(Organization.name == "Acme Inc").one()
    membership = (
        db_session.query(OrganizationMember)
        .filter(
            OrganizationMember.user_id == user.id,
            OrganizationMember.organization_id == org.id,
        )
        .one()
    )
    assert membership.role == RoleEnum.ADMIN.value

    workspace = (
        db_session.query(Workspace)
        .filter(
            Workspace.organization_id == org.id,
            Workspace.is_default.is_(True),
        )
        .one()
    )
    assert workspace.name == "Default"
    assert workspace.slug == "default"


def test_signup_rejects_duplicate_email(client, db_session, enable_local_password):
    db_session.add(
        User(
            email="taken@example.com",
            password_hash=hash_password("Existing1!"),
            is_active=True,
        )
    )
    db_session.commit()

    response = client.post(
        "/api/v1/auth/signup",
        json={"email": "taken@example.com", "password": "NewPass1!"},
    )

    assert response.status_code == 409
    assert "already exists" in response.json()["detail"].lower()


def test_signup_returns_403_when_self_service_signup_is_disabled(
    client, disable_signup
):
    response = client.post(
        "/api/v1/auth/signup",
        json={"email": "blocked@example.com", "password": "SomePass1!"},
    )

    assert response.status_code == 403
    assert "signup is disabled" in response.json()["detail"].lower()


def test_signup_returns_404_when_local_password_disabled(client, monkeypatch):
    monkeypatch.setattr(settings, "AUTH_PROVIDERS", ["api_key"])

    response = client.post(
        "/api/v1/auth/signup",
        json={"email": "nope@example.com", "password": "SomePass1!"},
    )

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# POST /auth/login
# ---------------------------------------------------------------------------

def _seed_user_with_org(db_session, email, password, *, role=RoleEnum.ADMIN.value):
    """Create a user + org + membership + return (user, org)."""
    org = Organization(id=uuid4(), name="Login Test Org")
    user = User(
        id=uuid4(),
        email=email,
        password_hash=hash_password(password),
        is_active=True,
        auth_provider="local",
    )
    db_session.add_all([org, user])
    db_session.flush()
    db_session.add(
        OrganizationMember(organization_id=org.id, user_id=user.id, role=role)
    )
    db_session.commit()
    return user, org


def test_login_with_correct_password_returns_token(
    client, db_session, enable_local_password
):
    _seed_user_with_org(db_session, "bob@example.com", "TestPass1!")

    response = client.post(
        "/api/v1/auth/login",
        json={"email": "bob@example.com", "password": "TestPass1!"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["access_token"]
    assert body["user"]["email"] == "bob@example.com"
    assert body["user"]["role"] == RoleEnum.ADMIN.value
    assert body["user"]["has_password"] is True


def test_login_rejects_wrong_password_with_401(
    client, db_session, enable_local_password
):
    _seed_user_with_org(db_session, "bob@example.com", "TestPass1!")

    response = client.post(
        "/api/v1/auth/login",
        json={"email": "bob@example.com", "password": "wrong"},
    )

    assert response.status_code == 401
    # Don't leak whether the email exists.
    assert "invalid email or password" in response.json()["detail"].lower()


def test_login_rejects_unknown_email_with_same_401(client, enable_local_password):
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@example.com", "password": "anything"},
    )

    assert response.status_code == 401
    assert "invalid email or password" in response.json()["detail"].lower()


def test_login_rejects_user_without_membership_with_403(
    client, db_session, enable_local_password
):
    # User exists with a password but no OrganizationMember row.
    db_session.add(
        User(
            email="lonely@example.com",
            password_hash=hash_password("ThePass1!"),
            is_active=True,
        )
    )
    db_session.commit()

    response = client.post(
        "/api/v1/auth/login",
        json={"email": "lonely@example.com", "password": "ThePass1!"},
    )

    assert response.status_code == 403
    assert "not a member of any organization" in response.json()["detail"].lower()


def _seed_user_with_multiple_orgs(db_session, email, password):
    user = User(
        id=uuid4(),
        email=email,
        password_hash=hash_password(password),
        is_active=True,
        auth_provider="local",
    )
    org_a = Organization(id=uuid4(), name="Org Alpha")
    org_b = Organization(id=uuid4(), name="Org Beta")
    db_session.add_all([user, org_a, org_b])
    db_session.flush()
    db_session.add_all(
        [
            OrganizationMember(organization_id=org_a.id, user_id=user.id, role=RoleEnum.ADMIN.value),
            OrganizationMember(organization_id=org_b.id, user_id=user.id, role=RoleEnum.READER.value),
        ]
    )
    db_session.commit()
    return user, org_a, org_b


def test_login_with_multiple_orgs_requires_selection(
    client, db_session, enable_local_password
):
    _seed_user_with_multiple_orgs(db_session, "multi@example.com", "TestPass1!")

    response = client.post(
        "/api/v1/auth/login",
        json={"email": "multi@example.com", "password": "TestPass1!"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["requires_org_selection"] is True
    assert "access_token" not in body
    assert len(body["organizations"]) == 2
    names = {org["name"] for org in body["organizations"]}
    assert names == {"Org Alpha", "Org Beta"}


def test_login_with_organization_id_returns_scoped_token(
    client, db_session, enable_local_password
):
    _user, org_a, org_b = _seed_user_with_multiple_orgs(
        db_session, "multi@example.com", "TestPass1!"
    )

    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "multi@example.com",
            "password": "TestPass1!",
            "organization_id": str(org_b.id),
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["access_token"]
    assert body["user"]["organization_id"] == str(org_b.id)
    assert body["user"]["role"] == RoleEnum.READER.value


def test_login_rejects_invalid_organization_id_with_403(
    client, db_session, enable_local_password
):
    _seed_user_with_multiple_orgs(db_session, "multi@example.com", "TestPass1!")

    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "multi@example.com",
            "password": "TestPass1!",
            "organization_id": str(uuid4()),
        },
    )

    assert response.status_code == 403
    assert "not a member" in response.json()["detail"].lower()


def test_provision_default_workspace_is_idempotent(db_session, org_id, seed_org):
    first = provision_default_workspace(db_session, organization_id=org_id)
    second = provision_default_workspace(db_session, organization_id=org_id)
    db_session.commit()

    assert first.id == second.id
    count = (
        db_session.query(Workspace)
        .filter(
            Workspace.organization_id == org_id,
            Workspace.is_default.is_(True),
        )
        .count()
    )
    assert count == 1


# ---------------------------------------------------------------------------
# POST /auth/password - credential linking
# ---------------------------------------------------------------------------

def test_api_key_user_can_attach_password_and_real_email(
    authenticated_client, db_session, org_id, api_key, seed_org, enable_local_password
):
    """An API-key-only user (placeholder email) links a real email + password."""
    api_key_id = uuid4()
    synthetic_email = f"api_user_{api_key_id}@efficientai.local"
    user = User(
        id=uuid4(),
        email=synthetic_email,
        name="API User",
        is_active=True,
    )
    db_session.add(user)
    db_session.flush()
    _bind_api_key_to_user(db_session, api_key=api_key, org_id=org_id, user=user)
    db_session.commit()

    response = authenticated_client.post(
        "/api/v1/auth/password",
        json={
            "new_password": "FreshPass1!",
            "email": "alice@example.com",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "alice@example.com"
    assert body["has_password"] is True
    assert body["email_is_placeholder"] is False

    db_session.refresh(user)
    assert user.email == "alice@example.com"
    assert user.password_hash is not None


def test_set_password_rejects_email_change_for_non_placeholder_user(
    authenticated_client, db_session, org_id, api_key, seed_org, enable_local_password
):
    user = User(
        id=uuid4(),
        email="real@example.com",
        name="Real User",
        is_active=True,
    )
    db_session.add(user)
    db_session.flush()
    _bind_api_key_to_user(db_session, api_key=api_key, org_id=org_id, user=user)

    response = authenticated_client.post(
        "/api/v1/auth/password",
        json={
            "new_password": "FreshPass1!",
            "email": "different@example.com",
        },
    )

    assert response.status_code == 400
    assert "email can only be changed" in response.json()["detail"].lower()
    db_session.refresh(user)
    assert user.email == "real@example.com"


def test_rotating_password_requires_current_password(
    authenticated_client, db_session, org_id, api_key, seed_org, enable_local_password
):
    user = User(
        id=uuid4(),
        email="rotator@example.com",
        password_hash=hash_password("Original1!"),
        is_active=True,
    )
    db_session.add(user)
    db_session.flush()
    _bind_api_key_to_user(db_session, api_key=api_key, org_id=org_id, user=user)

    # Missing current_password -> 401.
    missing_current = authenticated_client.post(
        "/api/v1/auth/password",
        json={"new_password": "BrandNew1!"},
    )
    assert missing_current.status_code == 401

    # Wrong current_password -> 401.
    wrong_current = authenticated_client.post(
        "/api/v1/auth/password",
        json={
            "new_password": "BrandNew1!",
            "current_password": "not-the-real-one",
        },
    )
    assert wrong_current.status_code == 401

    # Correct current_password -> 200 and password actually changes.
    correct = authenticated_client.post(
        "/api/v1/auth/password",
        json={
            "new_password": "BrandNew1!",
            "current_password": "Original1!",
        },
    )
    assert correct.status_code == 200

    db_session.refresh(user)
    from app.core.password import verify_password

    assert verify_password("BrandNew1!", user.password_hash) is True
    assert verify_password("Original1!", user.password_hash) is False


# ---------------------------------------------------------------------------
# POST /auth/switch-org - scoped token re-issuance
# ---------------------------------------------------------------------------

def test_switch_org_mints_token_for_target_org(
    client, db_session, enable_local_password
):
    """Happy path: user is a member of two orgs and switches into the second."""
    user, source_org = _seed_user_with_org(
        db_session, "multi@example.com", "ThePass1!"
    )

    target_org = Organization(id=uuid4(), name="Target Org")
    db_session.add(target_org)
    db_session.flush()
    db_session.add(
        OrganizationMember(
            organization_id=target_org.id,
            user_id=user.id,
            role=RoleEnum.READER.value,
        )
    )
    db_session.commit()

    principal = Principal(
        organization_id=source_org.id,
        auth_method=AuthMethod.LOCAL_PASSWORD,
        user_id=user.id,
        email=user.email,
    )
    _override_principal(client, principal)
    try:
        response = client.post(
            "/api/v1/auth/switch-org",
            json={"organization_id": str(target_org.id)},
        )
    finally:
        _clear_principal_override(client)

    assert response.status_code == 200
    body = response.json()
    assert body["access_token"]
    assert body["user"]["organization_id"] == str(target_org.id)
    # Role reflects the target-org membership, not the source-org role.
    assert body["user"]["role"] == RoleEnum.READER.value


def test_switch_org_rejects_api_key_caller_with_403(client, db_session, seed_org):
    """API keys are single-tenant and must not be able to pivot between orgs."""
    principal = Principal(
        organization_id=seed_org.id,
        auth_method=AuthMethod.API_KEY,
        user_id=uuid4(),
        api_key_id=uuid4(),
    )
    _override_principal(client, principal)
    try:
        response = client.post(
            "/api/v1/auth/switch-org",
            json={"organization_id": str(uuid4())},
        )
    finally:
        _clear_principal_override(client)

    assert response.status_code == 403
    assert "api keys are bound" in response.json()["detail"].lower()


def test_switch_org_rejects_non_member_target_with_403(client, db_session):
    user, source_org = _seed_user_with_org(
        db_session, "outsider@example.com", "ThePass1!"
    )
    forbidden_org = Organization(id=uuid4(), name="Not Your Org")
    db_session.add(forbidden_org)
    db_session.commit()

    principal = Principal(
        organization_id=source_org.id,
        auth_method=AuthMethod.LOCAL_PASSWORD,
        user_id=user.id,
        email=user.email,
    )
    _override_principal(client, principal)
    try:
        response = client.post(
            "/api/v1/auth/switch-org",
            json={"organization_id": str(forbidden_org.id)},
        )
    finally:
        _clear_principal_override(client)

    assert response.status_code == 403
    assert "not a member" in response.json()["detail"].lower()


def test_switch_org_rejects_non_uuid_target_with_400(client, db_session):
    user, source_org = _seed_user_with_org(
        db_session, "typo@example.com", "ThePass1!"
    )
    principal = Principal(
        organization_id=source_org.id,
        auth_method=AuthMethod.LOCAL_PASSWORD,
        user_id=user.id,
        email=user.email,
    )
    _override_principal(client, principal)
    try:
        response = client.post(
            "/api/v1/auth/switch-org",
            json={"organization_id": "not-a-uuid"},
        )
    finally:
        _clear_principal_override(client)

    assert response.status_code == 400
    assert "must be a valid uuid" in response.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Refresh tokens, logout revocation, password policy
# ---------------------------------------------------------------------------

def test_signup_rejects_weak_password(client, enable_local_password):
    response = client.post(
        "/api/v1/auth/signup",
        json={"email": "weak@example.com", "password": "alllowercase"},
    )
    assert response.status_code == 400
    assert "uppercase" in response.json()["detail"].lower()


def test_login_returns_refresh_token(client, db_session, enable_local_password):
    _seed_user_with_org(db_session, "bob@example.com", TEST_PASSWORD)
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "bob@example.com", "password": TEST_PASSWORD},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["access_token"]
    assert body["refresh_token"]


def test_refresh_rotates_tokens(client, db_session, enable_local_password):
    _seed_user_with_org(db_session, "bob@example.com", TEST_PASSWORD)
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "bob@example.com", "password": TEST_PASSWORD},
    ).json()
    old_refresh = login["refresh_token"]

    refreshed = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": old_refresh},
    )
    assert refreshed.status_code == 200
    body = refreshed.json()
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["refresh_token"] != old_refresh

    stale = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": old_refresh},
    )
    assert stale.status_code == 401


def test_logout_revokes_access_and_refresh_tokens(
    client, db_session, enable_local_password
):
    _seed_user_with_org(db_session, "bob@example.com", TEST_PASSWORD)
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "bob@example.com", "password": TEST_PASSWORD},
    ).json()
    access_token = login["access_token"]
    refresh_token = login["refresh_token"]

    logout = client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"refresh_token": refresh_token},
    )
    assert logout.status_code == 200

    me = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert me.status_code == 401

    refresh = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    assert refresh.status_code == 401
