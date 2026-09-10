"""Refresh token persistence and lifecycle."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Sequence, Tuple
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


def issue_refresh_token(
    db: Session,
    *,
    user_id: UUID,
    organization_id: UUID,
    authenticated_org_ids: Optional[Sequence[str]] = None,
    authenticated_org_epochs: Optional[Dict[str, int]] = None,
) -> str:
    """Create a new refresh token row and return the raw token value."""
    raw = generate_refresh_token_value()
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.AUTH_REFRESH_TOKEN_TTL_DAYS)
    org_ids = list(authenticated_org_ids) if authenticated_org_ids else None
    epochs = dict(authenticated_org_epochs) if authenticated_org_epochs else None
    db.add(
        RefreshToken(
            user_id=user_id,
            organization_id=organization_id,
            token_hash=_hash_token(raw),
            expires_at=expires_at,
            authenticated_org_ids=org_ids,
            authenticated_org_epochs=epochs,
        )
    )
    db.flush()
    return raw


def _org_ids_from_refresh_row(row: RefreshToken) -> Optional[List[UUID]]:
    raw_ids = row.authenticated_org_ids
    if not raw_ids:
        return None
    org_ids: List[UUID] = []
    for raw in raw_ids:
        try:
            org_ids.append(UUID(str(raw)))
        except (TypeError, ValueError):
            continue
    return org_ids or None


def _epochs_from_refresh_row(row: RefreshToken) -> Optional[Dict[str, int]]:
    raw_epochs = row.authenticated_org_epochs
    if not isinstance(raw_epochs, dict):
        return None
    epochs: Dict[str, int] = {}
    for key, value in raw_epochs.items():
        try:
            epochs[str(key)] = int(value)
        except (TypeError, ValueError):
            continue
    return epochs or None


def authenticated_org_ids_from_refresh_row(row: RefreshToken) -> Optional[List[UUID]]:
    return _org_ids_from_refresh_row(row)


def authenticated_org_auth_from_refresh_row(
    row: RefreshToken,
) -> Tuple[Optional[List[UUID]], Optional[Dict[str, int]]]:
    return _org_ids_from_refresh_row(row), _epochs_from_refresh_row(row)


def strip_org_from_user_refresh_auth(
    db: Session,
    *,
    user_id: UUID,
    organization_id: UUID,
) -> None:
    """Remove an org from password-auth lists on all active refresh tokens for a user."""
    org_key = str(organization_id)
    rows = (
        db.query(RefreshToken)
        .filter(
            RefreshToken.user_id == user_id,
            RefreshToken.revoked_at.is_(None),
        )
        .all()
    )
    for row in rows:
        if row.authenticated_org_ids:
            filtered_ids = [raw for raw in row.authenticated_org_ids if str(raw) != org_key]
            row.authenticated_org_ids = filtered_ids or None
        if isinstance(row.authenticated_org_epochs, dict):
            epochs = {
                str(key): value
                for key, value in row.authenticated_org_epochs.items()
                if str(key) != org_key
            }
            row.authenticated_org_epochs = epochs or None


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


def revoke_refresh_tokens_for_user_org(
    db: Session,
    *,
    user_id: UUID,
    organization_id: UUID,
) -> None:
    now = datetime.now(timezone.utc)
    (
        db.query(RefreshToken)
        .filter(
            RefreshToken.user_id == user_id,
            RefreshToken.organization_id == organization_id,
            RefreshToken.revoked_at.is_(None),
        )
        .update({RefreshToken.revoked_at: now}, synchronize_session=False)
    )
