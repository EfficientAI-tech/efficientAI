"""Per-organization password and session epoch helpers."""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.password import verify_password
from app.models.database import (
    Organization,
    OrganizationMember,
    OrganizationMemberCredential,
    OrganizationMemberSessionRevocation,
    User,
)


def get_session_revocation_floor(
    db: Session,
    *,
    user_id: UUID,
    organization_id: UUID,
) -> int:
    row = (
        db.query(OrganizationMemberSessionRevocation)
        .filter(
            OrganizationMemberSessionRevocation.user_id == user_id,
            OrganizationMemberSessionRevocation.organization_id == organization_id,
        )
        .first()
    )
    if row is None:
        return 0
    return int(row.min_session_epoch or 0)


def _upsert_session_revocation_floor(
    db: Session,
    *,
    user_id: UUID,
    organization_id: UUID,
    next_floor: int,
) -> int:
    dialect_name = db.get_bind().dialect.name
    if dialect_name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as dialect_insert
    elif dialect_name == "sqlite":
        from sqlalchemy.dialects.sqlite import insert as dialect_insert
    else:
        row = (
            db.query(OrganizationMemberSessionRevocation)
            .filter(
                OrganizationMemberSessionRevocation.user_id == user_id,
                OrganizationMemberSessionRevocation.organization_id == organization_id,
            )
            .first()
        )
        if row is None:
            db.add(
                OrganizationMemberSessionRevocation(
                    organization_id=organization_id,
                    user_id=user_id,
                    min_session_epoch=next_floor,
                )
            )
        else:
            row.min_session_epoch = max(int(row.min_session_epoch or 0), next_floor)
        db.flush()
        return get_session_revocation_floor(
            db, user_id=user_id, organization_id=organization_id
        )

    table = OrganizationMemberSessionRevocation.__table__
    stmt = dialect_insert(table).values(
        organization_id=organization_id,
        user_id=user_id,
        min_session_epoch=next_floor,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["organization_id", "user_id"],
        set_={
            "min_session_epoch": func.max(
                table.c.min_session_epoch,
                stmt.excluded.min_session_epoch,
            )
        },
    )
    db.execute(stmt)
    db.flush()
    return get_session_revocation_floor(
        db, user_id=user_id, organization_id=organization_id
    )


def record_org_membership_session_revocation(
    db: Session,
    *,
    user_id: UUID,
    organization_id: UUID,
    credential: Optional[OrganizationMemberCredential] = None,
) -> int:
    """Remember the next required session epoch after membership removal."""
    prior_floor = get_session_revocation_floor(
        db, user_id=user_id, organization_id=organization_id
    )
    if credential is not None:
        next_floor = max(prior_floor, int(credential.session_epoch or 0) + 1)
    else:
        next_floor = max(prior_floor + 1, 1) if prior_floor else 1

    return _upsert_session_revocation_floor(
        db,
        user_id=user_id,
        organization_id=organization_id,
        next_floor=next_floor,
    )


def revoke_org_membership_credential(
    db: Session,
    *,
    user_id: UUID,
    organization_id: UUID,
) -> bool:
    credential = get_credential(db, user_id=user_id, organization_id=organization_id)
    record_org_membership_session_revocation(
        db,
        user_id=user_id,
        organization_id=organization_id,
        credential=credential,
    )
    if credential is None:
        return False
    db.delete(credential)
    db.flush()
    return True


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
    return provision_membership_credential(
        db,
        user_id=user_id,
        organization_id=organization_id,
        user=user,
    )


def user_has_any_org_credentials(db: Session, user_id: UUID) -> bool:
    return (
        db.query(OrganizationMemberCredential.id)
        .filter(OrganizationMemberCredential.user_id == user_id)
        .first()
        is not None
    )


def find_source_password_for_new_membership(
    db: Session,
    user_id: UUID,
    *,
    user: Optional[User] = None,
    source_organization_id: Optional[UUID] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """Pick a password hash to seed a new membership credential.

    When ``source_organization_id`` is provided (e.g. the org the user
    authenticated into before accepting an invite), only that org's credential
    is used. Otherwise inheritance happens only when every existing org
    credential shares the same hash, or when no org credentials exist yet
    (legacy ``users.password_hash`` backfill).
    """
    if source_organization_id is not None:
        source = get_credential(
            db, user_id=user_id, organization_id=source_organization_id
        )
        if source is not None and source.password_hash:
            return source.password_hash, source.auth_provider
        return None, None

    creds_with_password = (
        db.query(OrganizationMemberCredential)
        .filter(
            OrganizationMemberCredential.user_id == user_id,
            OrganizationMemberCredential.password_hash.isnot(None),
        )
        .all()
    )
    if not creds_with_password:
        if user is None:
            user = db.query(User).filter(User.id == user_id).first()
        if user is not None and user.password_hash:
            return user.password_hash, user.auth_provider or "local"
        return None, None

    distinct_hashes = {cred.password_hash for cred in creds_with_password}
    if len(distinct_hashes) == 1:
        first = creds_with_password[0]
        return first.password_hash, first.auth_provider
    return None, None


def provision_membership_credential(
    db: Session,
    *,
    user_id: UUID,
    organization_id: UUID,
    password_hash: Optional[str] = None,
    auth_provider: Optional[str] = None,
    user: Optional[User] = None,
    source_organization_id: Optional[UUID] = None,
) -> OrganizationMemberCredential:
    row = get_credential(db, user_id=user_id, organization_id=organization_id)
    if row is not None:
        return row

    if password_hash is None:
        inherited_hash, inherited_provider = find_source_password_for_new_membership(
            db,
            user_id,
            user=user,
            source_organization_id=source_organization_id,
        )
        if inherited_hash:
            password_hash = inherited_hash
        if auth_provider is None and inherited_provider:
            auth_provider = inherited_provider

    session_epoch = get_session_revocation_floor(
        db, user_id=user_id, organization_id=organization_id
    )
    row = OrganizationMemberCredential(
        organization_id=organization_id,
        user_id=user_id,
        password_hash=password_hash,
        auth_provider=auth_provider,
        session_epoch=session_epoch,
    )
    db.add(row)
    db.flush()
    return row


def user_has_any_local_password(db: Session, user: User) -> bool:
    if user.password_hash:
        return True
    return (
        db.query(OrganizationMemberCredential.id)
        .filter(
            OrganizationMemberCredential.user_id == user.id,
            OrganizationMemberCredential.password_hash.isnot(None),
        )
        .first()
        is not None
    )


def resolve_password_hash(
    db: Session,
    user: User,
    credential: Optional[OrganizationMemberCredential],
) -> Optional[str]:
    if credential is not None and credential.password_hash:
        return credential.password_hash
    if (
        credential is None
        and not user_has_any_org_credentials(db, user.id)
        and user.password_hash
    ):
        return user.password_hash
    return None


def resolve_current_password_hash(
    credential: Optional[OrganizationMemberCredential],
    user: User,
) -> Optional[str]:
    """Verify password rotations only — never used for login matching."""
    if credential is not None:
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
    return bool(resolve_password_hash(db, user, credential))


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
        password_hash = resolve_password_hash(db, user, credential)
        if password_hash and verify_password(password, password_hash):
            matched.append((member, org))
    return matched


def authenticated_org_id_strings(org_ids: Sequence[UUID]) -> List[str]:
    return [str(org_id) for org_id in org_ids]


def build_authenticated_org_epochs(
    db: Session,
    user: User,
    org_ids: Sequence[UUID],
) -> Dict[str, int]:
    epochs: Dict[str, int] = {}
    for org_id in org_ids:
        credential = get_credential(db, user_id=user.id, organization_id=org_id)
        epochs[str(org_id)] = resolve_session_epoch(credential, user)
    return epochs


def filter_authenticated_orgs_by_epoch(
    db: Session,
    user: User,
    org_ids: Sequence[UUID],
    epochs: Optional[Dict[str, int]],
) -> Tuple[List[UUID], Dict[str, int]]:
    """Drop orgs whose stored password-auth epoch no longer matches the credential."""
    valid_ids: List[UUID] = []
    valid_epochs: Dict[str, int] = {}
    for org_id in org_ids:
        key = str(org_id)
        stored_epoch = (epochs or {}).get(key)
        if stored_epoch is None:
            continue
        credential = get_credential(db, user_id=user.id, organization_id=org_id)
        if resolve_session_epoch(credential, user) != int(stored_epoch):
            continue
        valid_ids.append(org_id)
        valid_epochs[key] = int(stored_epoch)
    return valid_ids, valid_epochs
