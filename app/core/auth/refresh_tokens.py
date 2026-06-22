"""Refresh token persistence and lifecycle."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy.orm import Session

from app.config import settings
from app.models.database import RefreshToken


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _to_aware_utc(dt: datetime) -> datetime:
    """Normalize datetimes for safe comparison across SQLite and Postgres."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def generate_refresh_token_value() -> str:
    return secrets.token_urlsafe(32)


def issue_refresh_token(db: Session, *, user_id: UUID, organization_id: UUID) -> str:
    """Create a new refresh token row and return the raw token value."""
    raw = generate_refresh_token_value()
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.AUTH_REFRESH_TOKEN_TTL_DAYS)
    db.add(
        RefreshToken(
            user_id=user_id,
            organization_id=organization_id,
            token_hash=_hash_token(raw),
            expires_at=expires_at,
        )
    )
    db.flush()
    return raw


def validate_refresh_token(db: Session, raw: str) -> RefreshToken:
    """Return a valid, non-revoked refresh token row or raise ValueError."""
    row = (
        db.query(RefreshToken)
        .filter(
            RefreshToken.token_hash == _hash_token(raw),
            RefreshToken.revoked_at.is_(None),
        )
        .first()
    )
    if row is None:
        raise ValueError("Invalid refresh token.")
    if _to_aware_utc(row.expires_at) < datetime.now(timezone.utc):
        raise ValueError("Refresh token has expired.")
    return row


def revoke_refresh_token(db: Session, raw: str) -> None:
    row = db.query(RefreshToken).filter(RefreshToken.token_hash == _hash_token(raw)).first()
    if row is not None and row.revoked_at is None:
        row.revoked_at = datetime.now(timezone.utc)


def revoke_all_user_refresh_tokens(db: Session, user_id: UUID) -> None:
    now = datetime.now(timezone.utc)
    (
        db.query(RefreshToken)
        .filter(
            RefreshToken.user_id == user_id,
            RefreshToken.revoked_at.is_(None),
        )
        .update({RefreshToken.revoked_at: now}, synchronize_session=False)
    )
