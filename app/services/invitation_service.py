"""Shared invitation validation, acceptance, and URL helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.models.database import (
    Invitation,
    InvitationStatus,
    Organization,
    OrganizationMember,
    User,
)
from app.services.workspace_rbac import backfill_org_workspace_memberships


class InvitationError(Exception):
    """Raised when an invitation cannot be used."""

    def __init__(self, detail: str, status_code: int = 400):
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


def to_aware_utc(dt: datetime) -> datetime:
    """Normalize a datetime to timezone-aware UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def build_invite_path(token: str) -> str:
    """Build the frontend-relative invite path for the given token."""
    return f"/invite/{token}"


def build_invite_url(token: str) -> str:
    """Build an absolute invite link (for server-side/email use when base URL is configured)."""
    base = (settings.FRONTEND_BASE_URL or "").strip().rstrip("/")
    if not base and settings.CORS_ORIGINS:
        base = settings.CORS_ORIGINS[0].rstrip("/")
    if not base:
        base = "http://localhost:8000"
    return f"{base}{build_invite_path(token)}"


def get_invitation_by_token(db: Session, token: str) -> Optional[Invitation]:
    return db.query(Invitation).filter(Invitation.token == token).first()


def expire_invitation_if_needed(db: Session, invitation: Invitation) -> None:
    if (
        invitation.status == InvitationStatus.PENDING
        and to_aware_utc(invitation.expires_at) < datetime.now(timezone.utc)
    ):
        invitation.status = InvitationStatus.EXPIRED
        db.commit()


def get_valid_pending_invitation_by_token(db: Session, token: str) -> Invitation:
    invitation = get_invitation_by_token(db, token)
    if invitation is None:
        raise InvitationError("Invitation not found", status_code=404)

    expire_invitation_if_needed(db, invitation)

    if invitation.status == InvitationStatus.EXPIRED:
        raise InvitationError("Invitation has expired", status_code=410)

    if invitation.status != InvitationStatus.PENDING:
        current_status = getattr(invitation.status, "value", invitation.status)
        raise InvitationError(
            f"Invitation is no longer valid (status: {current_status})",
            status_code=410,
        )

    return invitation


def accept_invitation(
    db: Session,
    invitation: Invitation,
    user: User,
    *,
    require_email_match: bool = True,
) -> OrganizationMember:
    """
    Accept an invitation and add the user to the organization.

    Idempotent when the user is already a member of the invited organization.
    """
    if require_email_match and invitation.email.lower() != user.email.lower():
        raise InvitationError(
            "This invitation was sent to a different email address",
            status_code=403,
        )

    expire_invitation_if_needed(db, invitation)
    if invitation.status == InvitationStatus.EXPIRED:
        raise InvitationError("Invitation has expired", status_code=410)

    if invitation.status != InvitationStatus.PENDING:
        current_status = getattr(invitation.status, "value", invitation.status)
        raise InvitationError(
            f"Cannot accept invitation with status: {current_status}",
            status_code=400,
        )

    existing_member = (
        db.query(OrganizationMember)
        .filter(
            OrganizationMember.organization_id == invitation.organization_id,
            OrganizationMember.user_id == user.id,
        )
        .first()
    )
    if existing_member:
        invitation.status = InvitationStatus.ACCEPTED
        invitation.accepted_at = datetime.now(timezone.utc)
        invitation.invited_user_id = user.id
        db.commit()
        return existing_member

    member = OrganizationMember(
        organization_id=invitation.organization_id,
        user_id=user.id,
        role=invitation.role,
    )
    db.add(member)

    invitation.status = InvitationStatus.ACCEPTED
    invitation.accepted_at = datetime.now(timezone.utc)
    invitation.invited_user_id = user.id

    db.flush()
    backfill_org_workspace_memberships(db, organization_id=invitation.organization_id)
    db.commit()
    db.refresh(member)
    return member


def get_invitation_preview(db: Session, token: str) -> dict:
    """Return public preview data for an invite token."""
    invitation = get_invitation_by_token(db, token)
    if invitation is None:
        raise InvitationError("Invitation not found", status_code=404)

    expire_invitation_if_needed(db, invitation)

    org = (
        db.query(Organization)
        .filter(Organization.id == invitation.organization_id)
        .first()
    )
    existing_user = db.query(User).filter(User.email == invitation.email).first()
    user_exists = existing_user is not None
    has_password = bool(existing_user and existing_user.password_hash)

    status_value = getattr(invitation.status, "value", invitation.status)
    return {
        "organization_name": org.name if org else None,
        "email": invitation.email,
        "role": invitation.role,
        "expires_at": invitation.expires_at,
        "status": status_value,
        "user_exists": user_exists,
        "has_password": has_password,
    }


def invitation_to_response_dict(
    db: Session,
    invitation: Invitation,
    *,
    organization_name: Optional[str] = None,
) -> dict:
    """Build an InvitationResponse-compatible dict including invite_url when pending."""
    if organization_name is None:
        org = (
            db.query(Organization)
            .filter(Organization.id == invitation.organization_id)
            .first()
        )
        organization_name = org.name if org else None

    status_value = getattr(invitation.status, "value", invitation.status)
    invite_path = None
    invite_url = None
    if status_value == InvitationStatus.PENDING.value:
        invite_path = build_invite_path(invitation.token)
        invite_url = build_invite_url(invitation.token)

    return {
        "id": invitation.id,
        "organization_id": invitation.organization_id,
        "email": invitation.email,
        "role": invitation.role,
        "status": invitation.status,
        "expires_at": invitation.expires_at,
        "created_at": invitation.created_at,
        "organization_name": organization_name,
        "invite_path": invite_path,
        "invite_url": invite_url,
    }
