"""Per-organization password and session epoch helpers."""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.password import verify_password
from app.models.database import Organization, OrganizationMember, OrganizationMemberCredential, User


def get_credential(
    db: Session,
    *,
    user_id: UUID,
    organization_id: UUID,
) -> Optional[OrganizationMemberCredential]:
    return (
        db.query(OrganizationMemberCredential)
        .filter(
            OrganizationMemberCredential.user_id == user_id,
            OrganizationMemberCredential.organization_id == organization_id,
        )
        .first()
    )


def get_or_create_credential(
    db: Session,
    *,
    user_id: UUID,
    organization_id: UUID,
    user: Optional[User] = None,
) -> OrganizationMemberCredential:
    row = get_credential(db, user_id=user_id, organization_id=organization_id)
    if row is not None:
        return row

    if user is None:
        user = db.query(User).filter(User.id == user_id).first()

    row = OrganizationMemberCredential(
        organization_id=organization_id,
        user_id=user_id,
        password_hash=user.password_hash if user is not None else None,
        auth_provider=user.auth_provider if user is not None else None,
        session_epoch=int(getattr(user, "session_epoch", 0) or 0) if user is not None else 0,
    )
    db.add(row)
    db.flush()
    return row


def resolve_password_hash(
    credential: Optional[OrganizationMemberCredential],
    user: User,
) -> Optional[str]:
    if credential is not None and credential.password_hash:
        return credential.password_hash
    return user.password_hash


def resolve_session_epoch(
    credential: Optional[OrganizationMemberCredential],
    user: User,
) -> int:
    if credential is not None:
        return int(credential.session_epoch or 0)
    return int(getattr(user, "session_epoch", 0) or 0)


def bump_org_session_epoch(credential: OrganizationMemberCredential) -> int:
    current = int(credential.session_epoch or 0)
    credential.session_epoch = current + 1
    return credential.session_epoch


def set_org_password_hash(
    credential: OrganizationMemberCredential,
    password_hash: str,
    *,
    auth_provider: Optional[str] = "local",
) -> None:
    credential.password_hash = password_hash
    if auth_provider and not credential.auth_provider:
        credential.auth_provider = auth_provider


def org_has_password(
    db: Session,
    *,
    user: User,
    organization_id: UUID,
) -> bool:
    credential = get_credential(db, user_id=user.id, organization_id=organization_id)
    return bool(resolve_password_hash(credential, user))


def match_password_memberships(
    db: Session,
    *,
    user: User,
    password: str,
) -> List[Tuple[OrganizationMember, Organization]]:
    rows = (
        db.query(OrganizationMember, Organization, OrganizationMemberCredential)
        .join(Organization, Organization.id == OrganizationMember.organization_id)
        .outerjoin(
            OrganizationMemberCredential,
            (OrganizationMemberCredential.organization_id == OrganizationMember.organization_id)
            & (OrganizationMemberCredential.user_id == OrganizationMember.user_id),
        )
        .filter(
            OrganizationMember.user_id == user.id,
            Organization.is_active == True,  # noqa: E712
        )
        .order_by(OrganizationMember.joined_at.asc())
        .all()
    )

    matched: List[Tuple[OrganizationMember, Organization]] = []
    for member, org, credential in rows:
        password_hash = resolve_password_hash(credential, user)
        if password_hash and verify_password(password, password_hash):
            matched.append((member, org))
    return matched


def authenticated_org_id_strings(org_ids: Sequence[UUID]) -> List[str]:
    return [str(org_id) for org_id in org_ids]
