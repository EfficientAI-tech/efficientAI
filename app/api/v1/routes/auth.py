"""Authentication routes.

Covers three concerns:

1. Provider discovery (`GET /auth/config`) - the frontend calls this on boot
   so it can show API key, local login, Keycloak, and OIDC buttons depending
   on what the backend has enabled.

2. Local email+password auth (`POST /auth/signup`, `POST /auth/login`,
   `POST /auth/logout`, `GET /auth/me`) - issues app-signed JWTs for the OSS
   tier when enabled in config.

3. API key management (`POST /auth/generate-key`, `POST /auth/validate`).
   `generate-key` used to be an anonymous endpoint that created a new org on
   every call, which meant anyone on the internet could spin up an unlimited
   number of orgs. It now requires an authenticated caller (Bearer or an
   existing API key) and binds the new key to the caller's org.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional
import secrets

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.config import settings
from app.core.auth import Principal, get_principal
from app.core.auth.tokens import create_access_token
from app.core.license import get_enabled_features, has_auth_feature
from app.core.password import hash_password, verify_password
from app.database import get_db
from app.dependencies import get_api_key
from app.models.database import (
    APIKey,
    Organization,
    OrganizationMember,
    RoleEnum,
    User,
)

router = APIRouter(prefix="/auth", tags=["Authentication"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class AuthProviderConfig(BaseModel):
    """Provider metadata returned to the frontend for login-method discovery."""

    name: str
    enabled: bool
    display_name: str
    description: Optional[str] = None
    # Frontend hints - which fields should the login form render?
    supports_password: bool = False
    supports_signup: bool = False
    # OIDC providers publish enough info for the SPA to do code-flow+PKCE.
    oidc_issuer: Optional[str] = None
    oidc_client_id: Optional[str] = None
    oidc_authorize_url: Optional[str] = None


class AuthConfigResponse(BaseModel):
    providers: List[AuthProviderConfig]
    tier: str  # "oss" | "enterprise"


class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=256)
    organization_name: Optional[str] = Field(default=None, max_length=255)
    first_name: Optional[str] = Field(default=None, max_length=255)
    last_name: Optional[str] = Field(default=None, max_length=255)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int  # seconds
    user: "UserSummary"


class UserSummary(BaseModel):
    id: str
    email: str
    name: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    organization_id: str
    role: Optional[str] = None


class APIKeyCreate(BaseModel):
    name: Optional[str] = None


class APIKeyResponse(BaseModel):
    id: str
    key: str
    name: Optional[str] = None
    is_active: bool
    created_at: Optional[str] = None


TokenResponse.model_rebuild()


# ---------------------------------------------------------------------------
# Provider discovery
# ---------------------------------------------------------------------------

@router.get("/config", response_model=AuthConfigResponse)
def get_auth_config() -> AuthConfigResponse:
    """Return which login methods the frontend should render on /login."""
    enabled = set(p.lower() for p in (settings.AUTH_PROVIDERS or []))
    features = get_enabled_features()
    tier = "enterprise" if features else "oss"

    providers: List[AuthProviderConfig] = [
        AuthProviderConfig(
            name="api_key",
            enabled="api_key" in enabled,
            display_name="API Key",
            description="Sign in with an EfficientAI API key.",
        ),
        AuthProviderConfig(
            name="local_password",
            enabled="local_password" in enabled,
            display_name="Email & Password",
            description="Sign in with your EfficientAI email and password.",
            supports_password=True,
            supports_signup="local_password" in enabled and settings.AUTH_LOCAL_ALLOW_SIGNUP,
        ),
    ]

    if "keycloak" in enabled and has_auth_feature("keycloak_sso"):
        base = (settings.AUTH_KEYCLOAK_BASE_URL or "").rstrip("/")
        realm = settings.AUTH_KEYCLOAK_REALM
        providers.append(
            AuthProviderConfig(
                name="keycloak",
                enabled=bool(base and realm),
                display_name="Single Sign-On (Keycloak)",
                description="Sign in through your organization's identity provider.",
                oidc_issuer=f"{base}/realms/{realm}" if base and realm else None,
                oidc_client_id=settings.AUTH_KEYCLOAK_CLIENT_ID,
                oidc_authorize_url=(
                    f"{base}/realms/{realm}/protocol/openid-connect/auth"
                    if base and realm
                    else None
                ),
            )
        )

    if "external_oidc" in enabled and has_auth_feature("oidc_sso"):
        providers.append(
            AuthProviderConfig(
                name="external_oidc",
                enabled=bool(settings.AUTH_OIDC_ISSUER),
                display_name="Single Sign-On (OIDC)",
                description="Sign in through your enterprise identity provider.",
                oidc_issuer=settings.AUTH_OIDC_ISSUER,
                oidc_client_id=settings.AUTH_OIDC_CLIENT_ID,
            )
        )

    return AuthConfigResponse(providers=providers, tier=tier)


# ---------------------------------------------------------------------------
# Local password auth
# ---------------------------------------------------------------------------

def _local_password_enabled() -> None:
    if "local_password" not in {p.lower() for p in (settings.AUTH_PROVIDERS or [])}:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Local password login is not enabled on this deployment.",
        )


def _user_to_summary(user: User, organization_id, role: Optional[str]) -> UserSummary:
    return UserSummary(
        id=str(user.id),
        email=user.email,
        name=user.name,
        first_name=user.first_name,
        last_name=user.last_name,
        organization_id=str(organization_id),
        role=role,
    )


@router.post("/signup", response_model=TokenResponse)
def signup(payload: SignupRequest, db: Session = Depends(get_db)) -> TokenResponse:
    """
    Create a new User + Organization pair and return a login token.

    Only available in OSS/self-hosted deployments where
    `auth.local_password.allow_signup = true` (the default). Cloud SaaS
    turns this off and routes signup through the billing flow.
    """
    _local_password_enabled()
    if not settings.AUTH_LOCAL_ALLOW_SIGNUP:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Self-service signup is disabled. Contact your administrator for access.",
        )

    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists. Try signing in instead.",
        )

    org_name = (payload.organization_name or payload.email.split("@")[0] + "'s Org").strip()

    user = User(
        email=payload.email,
        password_hash=hash_password(payload.password),
        first_name=payload.first_name,
        last_name=payload.last_name,
        name=((payload.first_name or "") + " " + (payload.last_name or "")).strip() or None,
        is_active=True,
        auth_provider="local",
    )
    organization = Organization(name=org_name)
    db.add(organization)
    db.add(user)
    db.flush()

    membership = OrganizationMember(
        organization_id=organization.id,
        user_id=user.id,
        role=RoleEnum.ADMIN.value,
    )
    db.add(membership)
    user.last_login_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(user)
    db.refresh(organization)

    token = create_access_token(
        user_id=user.id,
        organization_id=organization.id,
        email=user.email,
    )
    return TokenResponse(
        access_token=token,
        expires_in=settings.AUTH_LOCAL_TOKEN_TTL_MINUTES * 60,
        user=_user_to_summary(user, organization.id, RoleEnum.ADMIN.value),
    )


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    """Verify email/password and return a short-lived Bearer token."""
    _local_password_enabled()

    user = db.query(User).filter(User.email == payload.email).first()
    if (
        user is None
        or not user.is_active
        or not user.password_hash
        or not verify_password(payload.password, user.password_hash)
    ):
        # Same error regardless of whether the email exists - don't leak
        # whether an email is registered.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )

    membership = (
        db.query(OrganizationMember)
        .filter(OrganizationMember.user_id == user.id)
        .first()
    )
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account is not a member of any organization. Contact your administrator.",
        )

    user.last_login_at = datetime.now(timezone.utc)
    db.commit()

    token = create_access_token(
        user_id=user.id,
        organization_id=membership.organization_id,
        email=user.email,
    )
    role_value = membership.role.value if hasattr(membership.role, "value") else membership.role
    return TokenResponse(
        access_token=token,
        expires_in=settings.AUTH_LOCAL_TOKEN_TTL_MINUTES * 60,
        user=_user_to_summary(user, membership.organization_id, role_value),
    )


@router.get("/me", response_model=UserSummary)
def me(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)) -> UserSummary:
    """Return the current authenticated user (Bearer or API key)."""
    user: Optional[User] = None
    if principal.user_id:
        user = db.query(User).filter(User.id == principal.user_id).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No user is attached to this credential.",
        )
    membership = (
        db.query(OrganizationMember)
        .filter(
            OrganizationMember.user_id == user.id,
            OrganizationMember.organization_id == principal.organization_id,
        )
        .first()
    )
    role_value = None
    if membership:
        role_value = membership.role.value if hasattr(membership.role, "value") else membership.role
    return _user_to_summary(user, principal.organization_id, role_value)


@router.post("/logout")
def logout(principal: Principal = Depends(get_principal)) -> dict:
    """
    Log the current session out.

    The app-signed tokens are stateless and short-lived, so logout is a
    client-side gesture: the frontend clears the stored token. We return 200
    so the client can call this uniformly regardless of provider, and so we
    have a single place to plug in token-revocation lists later if needed.
    """
    return {"success": True, "auth_method": principal.auth_method.value}


# ---------------------------------------------------------------------------
# API key management
# ---------------------------------------------------------------------------

MAX_API_KEYS_PER_ORG = 20


@router.post("/generate-key", response_model=APIKeyResponse, status_code=status.HTTP_201_CREATED)
def generate_api_key(
    key_data: APIKeyCreate,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> APIKeyResponse:
    """
    Issue a new API key bound to the caller's organization.

    This used to be anonymous and created a fresh org on every call - a
    security hole in any multi-tenant deployment. It now requires the caller
    to already be authenticated (Bearer or an existing API key). The created
    key inherits `principal.organization_id` and `principal.user_id`.
    """
    existing_count = (
        db.query(APIKey)
        .filter(
            APIKey.organization_id == principal.organization_id,
            APIKey.is_active == True,  # noqa: E712
        )
        .count()
    )
    if existing_count >= MAX_API_KEYS_PER_ORG:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Organization has reached the limit of {MAX_API_KEYS_PER_ORG} "
                "active API keys. Delete an existing key first."
            ),
        )

    api_key_value = secrets.token_urlsafe(32)
    db_key = APIKey(
        key=api_key_value,
        name=key_data.name,
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        is_active=True,
    )
    db.add(db_key)
    db.commit()
    db.refresh(db_key)

    return APIKeyResponse(
        id=str(db_key.id),
        key=db_key.key,
        name=db_key.name,
        is_active=db_key.is_active,
        created_at=db_key.created_at.isoformat() if db_key.created_at else None,
    )


@router.post("/validate")
def validate_api_key(api_key: str = Depends(get_api_key)) -> dict:
    """Lightweight endpoint the frontend uses to confirm the stored key still works."""
    return {"valid": True, "message": "API key is valid"}
