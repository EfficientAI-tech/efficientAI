"""Signup reference code hashing and validation."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.config import settings
from app.models.database import SignupReferenceCode


def hash_reference_code(code: str) -> str:
    normalized = code.strip().upper()
    payload = f"{settings.SECRET_KEY}:signup_ref:{normalized}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _to_aware_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _code_is_usable(row: SignupReferenceCode, *, now: datetime) -> bool:
    if not row.is_active:
        return False
    if row.expires_at is not None and _to_aware_utc(row.expires_at) <= now:
        return False
    if row.max_uses is not None and row.use_count >= row.max_uses:
        return False
    return True


def validate_reference_code_for_signup(db: Session, code: Optional[str]) -> SignupReferenceCode:
    if not code or not code.strip():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="A valid reference code is required to sign up.",
        )

    code_hash = hash_reference_code(code)
    row = (
        db.query(SignupReferenceCode)
        .filter(SignupReferenceCode.code_hash == code_hash)
        .first()
    )
    now = datetime.now(timezone.utc)
    if row is None or not _code_is_usable(row, now=now):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="A valid reference code is required to sign up.",
        )
    return row


def consume_reference_code(db: Session, row: SignupReferenceCode) -> None:
    row.use_count = (row.use_count or 0) + 1
