"""
IAM (Identity and Access Management) API Routes
Manage users, invitations, and roles within organizations
"""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from typing import List, Optional
from uuid import UUID
from datetime import datetime, timedelta, timezone
import secrets

from app.dependencies import get_db, get_organization_id, get_api_key
from app.core.auth import Principal, get_principal
from app.core.auth.rbac import require_admin
from app.models.database import (
    User, OrganizationMember, Invitation, Organization,
    RoleEnum, InvitationStatus
)
from app.models.schemas import (
    InvitationCreate, InvitationResponse, OrganizationMemberResponse,
    RoleUpdate, MessageResponse, UserResponse
)
from app.core.password import hash_password

router = APIRouter(prefix="/iam", tags=["IAM"])


def _to_aware_utc(dt: datetime) -> datetime:
    """Normalize datetimes to timezone-aware UTC for safe comparisons."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def get_user_from_api_key(api_key: str, db: Session) -> User:
    """
    Get user associated with API key.
    Creates a user if doesn't exist and adds them to the organization as ADMIN.
    """
    from app.models.database import APIKey
    
    db_key = db.query(APIKey).filter(APIKey.key == api_key).first()
    if not db_key:
        raise HTTPException(status_code=401, detail="Invalid API key")
    
    # If API key has user, return it
    if db_key.user_id:
        user = db.query(User).filter(User.id == db_key.user_id).first()
        if user:
            # Ensure user is a member of the organization
            existing_member = db.query(OrganizationMember).filter(
                OrganizationMember.organization_id == db_key.organization_id,
                OrganizationMember.user_id == user.id
            ).first()
            
            if not existing_member:
                # Add user to organization as ADMIN (they created the API key)
                member = OrganizationMember(
                    organization_id=db_key.organization_id,
                    user_id=user.id,
                    role=RoleEnum.ADMIN
                )
                db.add(member)
                db.commit()
            
            return user
    
    # Otherwise, create a user for this API key
    # Use a placeholder email if not available
    email = f"api_user_{db_key.id}@efficientai.local"
    user = db.query(User).filter(User.email == email).first()
    if not user:
        user = User(
            email=email,
            name=db_key.name or "API User",
            password_hash=None
        )
        db.add(user)
        db.flush()
        
        # Link API key to user
        db_key.user_id = user.id
        
        # Add user to organization as ADMIN (they created the API key)
        member = OrganizationMember(
            organization_id=db_key.organization_id,
            user_id=user.id,
            role=RoleEnum.ADMIN
        )
        db.add(member)
        db.commit()
    else:
        # User exists but might not be in organization
        existing_member = db.query(OrganizationMember).filter(
            OrganizationMember.organization_id == db_key.organization_id,
            OrganizationMember.user_id == user.id
        ).first()
        
        if not existing_member:
            # Link API key to user if not already linked
            if not db_key.user_id:
                db_key.user_id = user.id
            
            # Add user to organization as ADMIN
            member = OrganizationMember(
                organization_id=db_key.organization_id,
                user_id=user.id,
                role=RoleEnum.ADMIN
            )
            db.add(member)
            db.commit()
    
    return user


def require_admin_role(
    principal: Principal = Depends(require_admin),
    db: Session = Depends(get_db),
) -> User:
    """
    Resolve the authenticated admin caller to a `User` row.

    Authentication + role check live in `require_admin` (the shared RBAC
    dependency), which understands every auth provider - API key, Bearer
    (local password), and SSO. This wrapper only exists so existing IAM
    handlers can continue to use `current_user: User = Depends(require_admin_role)`
    and read `current_user.id` / `current_user.email` directly.
    """
    user: Optional[User] = None
    if principal.user_id is not None:
        user = db.query(User).filter(User.id == principal.user_id).first()

    # API keys can be unbound to a user. Fall back to the legacy provisioning
    # path so behavior matches what callers used to get.
    if user is None:
        from app.models.database import APIKey
        if principal.api_key_id is not None:
            db_key = db.query(APIKey).filter(APIKey.id == principal.api_key_id).first()
            if db_key is not None:
                user = get_user_from_api_key(db_key.key, db)

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticated credential is not bound to a user.",
        )
    return user


@router.get("/users", response_model=List[OrganizationMemberResponse], operation_id="listOrganizationUsers")
async def list_organization_users(
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db)
):
    """
    List all users in the organization.
    Requires at least READER role.
    """
    members = db.query(OrganizationMember).filter(
        OrganizationMember.organization_id == organization_id
    ).all()
    
    result = []
    for member in members:
        user = db.query(User).filter(User.id == member.user_id).first()
        if user:
            result.append({
                "id": member.id,
                "user_id": member.user_id,
                "organization_id": member.organization_id,
                "role": member.role,
                "joined_at": member.joined_at,
                "user": {
                    "id": user.id,
                    "email": user.email,
                    "name": user.name,
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                    "is_active": user.is_active,
                    "created_at": user.created_at
                }
            })
    
    return result


@router.post("/invitations", response_model=InvitationResponse, status_code=status.HTTP_201_CREATED, operation_id="inviteUser")
async def invite_user(
    invitation_data: InvitationCreate,
    organization_id: UUID = Depends(get_organization_id),
    current_user: User = Depends(require_admin_role),
    db: Session = Depends(get_db)
):
    """
    Invite a user to the organization.
    Requires ADMIN role.
    """
    # Check if user already exists
    existing_user = db.query(User).filter(User.email == invitation_data.email).first()
    
    # Check if user is already a member
    if existing_user:
        existing_member = db.query(OrganizationMember).filter(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.user_id == existing_user.id
        ).first()
        if existing_member:
            raise HTTPException(
                status_code=400,
                detail="User is already a member of this organization"
            )
    
    # Check for existing pending invitation
    existing_invitation = db.query(Invitation).filter(
        Invitation.organization_id == organization_id,
        Invitation.email == invitation_data.email,
        Invitation.status == InvitationStatus.PENDING
    ).first()
    
    if existing_invitation:
        # Check if expired
        if _to_aware_utc(existing_invitation.expires_at) < datetime.now(timezone.utc):
            existing_invitation.status = InvitationStatus.EXPIRED
            db.commit()
        else:
            raise HTTPException(
                status_code=400,
                detail="An invitation is already pending for this email"
            )
    
    # Create invitation
    invitation_token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(days=7)  # 7 days expiry
    
    invitation = Invitation(
        organization_id=organization_id,
        invited_user_id=existing_user.id if existing_user else None,
        invited_by_id=current_user.id,
        email=invitation_data.email,
        role=invitation_data.role,
        status=InvitationStatus.PENDING,
        token=invitation_token,
        expires_at=expires_at
    )
    
    db.add(invitation)
    db.commit()
    db.refresh(invitation)
    
    # Get organization name
    org = db.query(Organization).filter(Organization.id == organization_id).first()
    
    return {
        "id": invitation.id,
        "organization_id": invitation.organization_id,
        "email": invitation.email,
        "role": invitation.role,
        "status": invitation.status,
        "expires_at": invitation.expires_at,
        "created_at": invitation.created_at,
        "organization_name": org.name if org else None
    }


@router.get("/invitations", response_model=List[InvitationResponse], operation_id="listInvitations")
async def list_invitations(
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db)
):
    """
    List all invitations for the organization.
    Requires at least READER role.
    """
    invitations = db.query(Invitation).filter(
        Invitation.organization_id == organization_id
    ).order_by(Invitation.created_at.desc()).all()
    
    org = db.query(Organization).filter(Organization.id == organization_id).first()
    org_name = org.name if org else None
    
    result = []
    for invitation in invitations:
        # Check if expired
        if invitation.status == InvitationStatus.PENDING and _to_aware_utc(invitation.expires_at) < datetime.now(timezone.utc):
            invitation.status = InvitationStatus.EXPIRED
            db.commit()
        
        result.append({
            "id": invitation.id,
            "organization_id": invitation.organization_id,
            "email": invitation.email,
            "role": invitation.role,
            "status": invitation.status,
            "expires_at": invitation.expires_at,
            "created_at": invitation.created_at,
            "organization_name": org_name
        })
    
    return result


@router.put("/users/{user_id}/role", response_model=OrganizationMemberResponse, operation_id="updateUserRole")
async def update_user_role(
    user_id: UUID,
    role_update: RoleUpdate,
    organization_id: UUID = Depends(get_organization_id),
    current_user: User = Depends(require_admin_role),
    db: Session = Depends(get_db)
):
    """
    Update a user's role in the organization.
    Requires ADMIN role.
    """
    member = db.query(OrganizationMember).filter(
        OrganizationMember.organization_id == organization_id,
        OrganizationMember.user_id == user_id
    ).first()
    
    if not member:
        raise HTTPException(
            status_code=404,
            detail="User is not a member of this organization"
        )
    
    # Prevent removing the last admin
    if member.role == RoleEnum.ADMIN and role_update.role != RoleEnum.ADMIN:
        admin_count = db.query(OrganizationMember).filter(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.role == RoleEnum.ADMIN
        ).count()
        
        if admin_count <= 1:
            raise HTTPException(
                status_code=400,
                detail="Cannot remove the last admin from the organization"
            )
    
    member.role = role_update.role
    db.commit()
    db.refresh(member)
    
    user = db.query(User).filter(User.id == member.user_id).first()
    
    return {
        "id": member.id,
        "user_id": member.user_id,
        "organization_id": member.organization_id,
        "role": member.role,
        "joined_at": member.joined_at,
        "user": {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "is_active": user.is_active,
            "created_at": user.created_at
        }
    }


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT, operation_id="removeUser")
async def remove_user(
    user_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    current_user: User = Depends(require_admin_role),
    db: Session = Depends(get_db)
):
    """
    Remove a user from the organization.
    Requires ADMIN role.
    """
    # Prevent users from removing themselves
    if user_id == current_user.id:
        raise HTTPException(
            status_code=400,
            detail="You cannot remove yourself from the organization"
        )
    
    member = db.query(OrganizationMember).filter(
        OrganizationMember.organization_id == organization_id,
        OrganizationMember.user_id == user_id
    ).first()
    
    if not member:
        raise HTTPException(
            status_code=404,
            detail="User is not a member of this organization"
        )
    
    # Prevent removing the last admin
    if member.role == RoleEnum.ADMIN:
        admin_count = db.query(OrganizationMember).filter(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.role == RoleEnum.ADMIN
        ).count()
        
        if admin_count <= 1:
            raise HTTPException(
                status_code=400,
                detail="Cannot remove the last admin from the organization"
            )
    
    db.delete(member)
    db.commit()
    return None


@router.delete("/invitations/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT, operation_id="cancelInvitation")
async def cancel_invitation(
    invitation_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    current_user: User = Depends(require_admin_role),
    db: Session = Depends(get_db)
):
    """
    Cancel an invitation.
    Requires ADMIN role.
    """
    invitation = db.query(Invitation).filter(
        Invitation.id == invitation_id,
        Invitation.organization_id == organization_id
    ).first()
    
    if not invitation:
        raise HTTPException(status_code=404, detail="Invitation not found")
    
    if invitation.status != InvitationStatus.PENDING:
        raise HTTPException(
            status_code=400,
            detail="Can only cancel pending invitations"
        )
    
    invitation.status = InvitationStatus.DECLINED
    db.commit()
    return None


# ---------------------------------------------------------------------------
# Admin-initiated password reset
# ---------------------------------------------------------------------------
#
# The self-service password change endpoint at `POST /auth/password` requires
# the user to know their current password. When a member loses access (forgot
# password, no email recovery configured, etc.) an org admin needs a way to
# set a new password for them so they can log back in.
#
# Rules:
#   - Caller must be an ADMIN of the same organization as the target user.
#   - Target user must be an active member of the same organization (so an
#     admin from Org A can never reset a password belonging to Org B).
#   - Admins cannot reset their own password through this endpoint - they
#     must use `POST /auth/password` so the current-password check runs.
#     This avoids accidentally bypassing the rotation flow on yourself.


class AdminPasswordReset(BaseModel):
    """Payload for an admin resetting another member's password."""

    new_password: str = Field(min_length=8, max_length=256)


class AdminPasswordResetResponse(BaseModel):
    """Confirmation response for a successful admin password reset."""

    user_id: UUID
    email: str
    message: str = "Password reset successfully"


@router.post(
    "/users/{user_id}/reset-password",
    response_model=AdminPasswordResetResponse,
    operation_id="adminResetUserPassword",
)
async def admin_reset_user_password(
    user_id: UUID,
    payload: AdminPasswordReset,
    organization_id: UUID = Depends(get_organization_id),
    current_user: User = Depends(require_admin_role),
    db: Session = Depends(get_db),
) -> AdminPasswordResetResponse:
    """
    Reset another organization member's password.

    Requires the caller to be an ADMIN of the organization. The new password
    is set immediately; existing Bearer tokens for that user remain valid
    until their natural expiry (the app does not maintain a server-side
    token revocation list yet). Communicate the new password to the user
    out-of-band.
    """
    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "You cannot reset your own password via this endpoint. "
                "Use POST /auth/password to change your password."
            ),
        )

    # Target must be a member of the same org. This is the security boundary
    # that prevents an admin in Org A from resetting passwords in Org B.
    member = (
        db.query(OrganizationMember)
        .filter(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.user_id == user_id,
        )
        .first()
    )
    if not member:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User is not a member of this organization",
        )

    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    target.password_hash = hash_password(payload.new_password)
    if not target.auth_provider:
        target.auth_provider = "local"
    db.commit()
    db.refresh(target)

    return AdminPasswordResetResponse(
        user_id=target.id,
        email=target.email,
    )

