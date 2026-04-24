"""
Shared helpers for OIDC-based auth providers.

The external OIDC provider verifies a Bearer JWT against the issuer's JWKS
endpoint and then upserts the (user, org, membership) triple so that downstream
routes can treat it the same as a local user. This module centralises the
fetching, caching, and mapping.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from uuid import UUID

import httpx
from jose import JWTError, jwt
from loguru import logger
from sqlalchemy.orm import Session

from app.core.auth.principal import Principal
from app.core.auth.providers import AuthError
from app.models.database import Organization, OrganizationMember, User
from app.models.enums import RoleEnum


# -- JWKS cache ---------------------------------------------------------------

@dataclass
class _JwksEntry:
    keys: List[Dict[str, Any]]
    fetched_at: float


_JWKS_TTL_SECONDS = 3600  # 1 hour
_jwks_cache: Dict[str, _JwksEntry] = {}
_jwks_lock = threading.Lock()


def fetch_jwks(jwks_uri: str) -> List[Dict[str, Any]]:
    """Return the list of signing keys for the given JWKS URI (1-hour cache)."""
    now = time.monotonic()
    with _jwks_lock:
        entry = _jwks_cache.get(jwks_uri)
        if entry and (now - entry.fetched_at) < _JWKS_TTL_SECONDS:
            return entry.keys

    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(jwks_uri)
            resp.raise_for_status()
            keys = resp.json().get("keys", [])
    except Exception as e:
        raise AuthError(f"Could not fetch JWKS from {jwks_uri}: {e}")

    with _jwks_lock:
        _jwks_cache[jwks_uri] = _JwksEntry(keys=keys, fetched_at=now)
    return keys


def reset_jwks_cache() -> None:
    """Clear the JWKS cache - useful in tests or after a key rotation."""
    with _jwks_lock:
        _jwks_cache.clear()


# -- Token verification -------------------------------------------------------

def verify_jwt(
    token: str,
    *,
    jwks_uri: str,
    issuer: str,
    audience: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Verify a JWT against a JWKS endpoint. Returns the decoded claims.

    Matches the key by `kid`. Falls back to trying every key if `kid` is
    missing - this happens with some cloud IdPs on signature rollover.
    """
    keys = fetch_jwks(jwks_uri)
    try:
        header = jwt.get_unverified_header(token)
    except JWTError as e:
        raise AuthError(f"Malformed token header: {e}")

    kid = header.get("kid")
    candidate_keys: List[Dict[str, Any]]
    if kid:
        candidate_keys = [k for k in keys if k.get("kid") == kid] or keys
    else:
        candidate_keys = keys

    last_error: Optional[Exception] = None
    for key in candidate_keys:
        try:
            options = {}
            if audience is None:
                options["verify_aud"] = False
            return jwt.decode(
                token,
                key,
                algorithms=[key.get("alg", "RS256")],
                issuer=issuer,
                audience=audience,
                options=options,
            )
        except JWTError as e:
            last_error = e
            continue

    raise AuthError(f"Token signature could not be verified: {last_error}")


# -- JIT user+org provisioning ------------------------------------------------

def upsert_user_and_membership(
    db: Session,
    *,
    external_id: str,
    email: str,
    organization_name: str,
    provider_name: str,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    default_role: RoleEnum = RoleEnum.ADMIN,
) -> tuple[User, Organization]:
    """
    Find-or-create a user by external_id, attaching them to an organization.

    On first login from a brand-new IdP subject:
      - Create a User row keyed by `external_id` + email
      - Create (or reuse) an Organization named `organization_name`
      - Add the user as a member with `default_role`

    Subsequent logins simply look the user up by `external_id`.
    """
    user: Optional[User] = (
        db.query(User).filter(User.external_id == external_id).first()
        if hasattr(User, "external_id")
        else None
    )

    if user is None and email:
        user = db.query(User).filter(User.email == email).first()
        if user and hasattr(User, "external_id") and not user.external_id:
            user.external_id = external_id
            user.auth_provider = provider_name

    if user is None:
        user_kwargs: Dict[str, Any] = {
            "email": email,
            "first_name": first_name,
            "last_name": last_name,
            "name": (first_name + " " + last_name).strip() if first_name or last_name else None,
            "password_hash": None,
            "is_active": True,
        }
        if hasattr(User, "external_id"):
            user_kwargs["external_id"] = external_id
        if hasattr(User, "auth_provider"):
            user_kwargs["auth_provider"] = provider_name
        user = User(**user_kwargs)
        db.add(user)
        db.flush()
        logger.info(f"Provisioned new user {email} from {provider_name}")

    # Prefer an existing org the user already belongs to; otherwise find-or-create
    # an org matching the requested name.
    existing_member = (
        db.query(OrganizationMember)
        .filter(OrganizationMember.user_id == user.id)
        .first()
    )
    if existing_member:
        organization = (
            db.query(Organization)
            .filter(Organization.id == existing_member.organization_id)
            .first()
        )
        if organization is not None:
            db.commit()
            return user, organization

    organization = db.query(Organization).filter(Organization.name == organization_name).first()
    if organization is None:
        organization = Organization(name=organization_name)
        db.add(organization)
        db.flush()
        logger.info(f"Provisioned new organization '{organization_name}' for {email}")

    member = OrganizationMember(
        organization_id=organization.id,
        user_id=user.id,
        role=default_role.value if hasattr(default_role, "value") else default_role,
    )
    db.add(member)
    db.commit()
    return user, organization


def principal_from_oidc_claims(
    db: Session,
    claims: Dict[str, Any],
    *,
    auth_method,
    provider_name: str,
    organization_claim_path: Optional[List[str]] = None,
    default_organization_name: Optional[str] = None,
) -> Principal:
    """
    Map a verified OIDC claims dict into a `Principal`, provisioning
    the user and their organization on first sight.
    """
    sub = claims.get("sub")
    email = claims.get("email") or claims.get("preferred_username")
    if not sub or not email:
        raise AuthError("Token is missing required claims (sub, email)")

    # Find the org name from the configured claim path, e.g. ["org", "name"] or
    # ["https://efficientai.com/org"]. Fall back to the configured default.
    org_name = default_organization_name or email.split("@")[-1]
    if organization_claim_path:
        cursor: Any = claims
        for key in organization_claim_path:
            if isinstance(cursor, dict) and key in cursor:
                cursor = cursor[key]
            else:
                cursor = None
                break
        if isinstance(cursor, str) and cursor.strip():
            org_name = cursor.strip()

    first_name = claims.get("given_name")
    last_name = claims.get("family_name")

    user, organization = upsert_user_and_membership(
        db,
        external_id=f"{provider_name}:{sub}",
        email=email,
        organization_name=org_name,
        provider_name=provider_name,
        first_name=first_name,
        last_name=last_name,
    )

    return Principal(
        organization_id=organization.id,
        auth_method=auth_method,
        user_id=user.id,
        email=email,
        token_sub=sub,
    )
