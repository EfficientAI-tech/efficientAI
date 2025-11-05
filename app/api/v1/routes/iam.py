"""
IAM (Identity and Access Management) API Routes
Manage users, invitations, and roles within organizations
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from uuid import UUID
from datetime import datetime, timedelta
import secrets

from app.dependencies import get_db, get_organization_id, get_api_key
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


def get_user_from_api_key(api_key: str, db: Session) -> User:
    """
    Get user associated with API key.
    For now, creates a user if doesn't exist.
    """
    from app.models.database import APIKey
    
    db_key = db.query(APIKey).filter(APIKey.key == api_key).first()
    if not db_key:
        raise HTTPException(status_code=401, detail="Invalid API key")
    
    # If API key has user, return it
    if db_key.user_id:
        user = db.query(User).filter(User.id == db_key.user_id).first()
        if user:
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
        db.commit()
    
    return user


def require_admin_role(
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db)
):
    """
    Dependency to ensure user has ADMIN role in organization.
    """
    user = get_user_from_api_key(api_key, db)
    
    member = db.query(OrganizationMember).filter(
        OrganizationMember.organization_id == organization_id,
        OrganizationMember.user_id == user.id
    ).first()
    
    if not member or member.role != RoleEnum.ADMIN:
        raise HTTPException(
            status_code=403,
            detail="Admin role required for this operation"
        )
    
    return user


@router.get("/users", response_model=List[OrganizationMemberResponse])
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
                    "is_active": user.is_active,
                    "created_at": user.created_at
                }
            })
    
    return result


@router.post("/invitations", response_model=InvitationResponse, status_code=status.HTTP_201_CREATED)
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
        if existing_invitation.expires_at < datetime.utcnow():
            existing_invitation.status = InvitationStatus.EXPIRED
            db.commit()
        else:
            raise HTTPException(
                status_code=400,
                detail="An invitation is already pending for this email"
            )
    
    # Create invitation
    invitation_token = secrets.token_urlsafe(32)
    expires_at = datetime.utcnow() + timedelta(days=7)  # 7 days expiry
    
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


@router.get("/invitations", response_model=List[InvitationResponse])
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
        if invitation.status == InvitationStatus.PENDING and invitation.expires_at < datetime.utcnow():
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


@router.put("/users/{user_id}/role", response_model=OrganizationMemberResponse)
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
            "is_active": user.is_active,
            "created_at": user.created_at
        }
    }


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
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


@router.delete("/invitations/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT)
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

