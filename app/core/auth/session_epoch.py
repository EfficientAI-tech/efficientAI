"""Session epoch helpers — invalidate all JWTs on password change."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.models.database import User


def bump_user_session_epoch(user: User) -> int:
    current = int(getattr(user, "session_epoch", 0) or 0)
    user.session_epoch = current + 1
    return user.session_epoch


def bump_session_epoch_for_user_id(db: Session, user_id: UUID) -> None:
    user = db.query(User).filter(User.id == user_id).first()
    if user is not None:
        bump_user_session_epoch(user)
