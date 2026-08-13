"""Platform admin JWT issuance and FastAPI dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple
from uuid import UUID, uuid4

from fastapi import Depends, Header, HTTPException, status
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.database import PlatformAdmin

PLATFORM_ISSUER = "efficientai-platform"
PLATFORM_SCOPE = "platform_admin"
ALGORITHM = "HS256"


@dataclass(frozen=True)
class PlatformAdminPrincipal:
    platform_admin_id: UUID
    email: str


def create_platform_access_token(
    *,
    platform_admin_id: UUID,
    email: str,
    expires_in_minutes: Optional[int] = None,
) -> Tuple[str, int]:
    ttl_minutes = expires_in_minutes or getattr(settings, "AUTH_LOCAL_TOKEN_TTL_MINUTES", 15)
    ttl_seconds = ttl_minutes * 60
    now = datetime.now(timezone.utc)
    payload: Dict[str, Any] = {
        "iss": PLATFORM_ISSUER,
        "sub": str(platform_admin_id),
        "email": email,
        "scope": PLATFORM_SCOPE,
        "jti": str(uuid4()),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=ttl_minutes)).timestamp()),
    }
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)
    return token, ttl_seconds


def decode_platform_access_token(token: str) -> Dict[str, Any]:
    return jwt.decode(
        token,
        settings.SECRET_KEY,
        algorithms=[ALGORITHM],
        issuer=PLATFORM_ISSUER,
        options={"verify_aud": False},
    )


def _extract_bearer(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def platform_admin_feature_enabled(db: Session) -> bool:
    return (
        db.query(PlatformAdmin.id)
        .filter(PlatformAdmin.is_active == True)  # noqa: E712
        .first()
        is not None
    )


def require_platform_admin_feature(db: Session = Depends(get_db)) -> None:
    if not platform_admin_feature_enabled(db):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


def get_platform_admin(
    authorization: Optional[str] = Header(None, alias="Authorization"),
    db: Session = Depends(get_db),
    _feature: None = Depends(require_platform_admin_feature),
) -> PlatformAdminPrincipal:
    bearer = _extract_bearer(authorization)
    if not bearer:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required (send Authorization: Bearer ...)",
        )

    try:
        claims = decode_platform_access_token(bearer)
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid platform admin token: {exc}",
        ) from exc

    if claims.get("scope") != PLATFORM_SCOPE:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid platform admin token scope.",
        )

    try:
        admin_id = UUID(claims["sub"])
    except (KeyError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed platform admin token.",
        ) from exc

    admin = (
        db.query(PlatformAdmin)
        .filter(PlatformAdmin.id == admin_id, PlatformAdmin.is_active == True)  # noqa: E712
        .first()
    )
    if admin is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Platform admin no longer active.",
        )

    return PlatformAdminPrincipal(platform_admin_id=admin.id, email=admin.email)
