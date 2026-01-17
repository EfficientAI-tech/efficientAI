"""
Profile API Routes
Manage user profile and invitations
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from uuid import UUID
from datetime import datetime, timezone

from app.dependencies import get_db, get_api_key
from app.models.database import (
    User, OrganizationMember, Invitation, Organization,
    InvitationStatus, RoleEnum
)
from app.models.schemas import (
    ProfileResponse, InvitationResponse, UserUpdate, MessageResponse,
    InvitationUpdate
)
from app.core.password import hash_password

router = APIRouter(prefix="/profile", tags=["Profile"])


def get_current_user(
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db)
) -> User:
    """
    Get current user from API key.
    Creates user if doesn't exist and adds them to the organization as ADMIN.
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


@router.get("", response_model=ProfileResponse, operation_id="getProfile")
async def get_profile(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get current user's profile.
    """
    # Get all organization memberships
    memberships = db.query(OrganizationMember).filter(
        OrganizationMember.user_id == current_user.id
    ).all()
    
    organizations = []
    for membership in memberships:
        org = db.query(Organization).filter(
            Organization.id == membership.organization_id
        ).first()
        if org:
            # Handle role being either enum or string
            role_value = membership.role.value if hasattr(membership.role, 'value') else membership.role
            organizations.append({
                "id": org.id,
                "name": org.name,
                "role": role_value,
                "joined_at": membership.joined_at.isoformat()
            })
    
    return {
        "id": current_user.id,
        "email": current_user.email,
        "name": current_user.name,
        "first_name": current_user.first_name,
        "last_name": current_user.last_name,
        "created_at": current_user.created_at,
        "organizations": organizations
    }


@router.put("", response_model=ProfileResponse, operation_id="updateProfile")
async def update_profile(
    profile_update: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Update current user's profile.
    """
    if profile_update.name is not None:
        current_user.name = profile_update.name
    
    if profile_update.first_name is not None:
        current_user.first_name = profile_update.first_name
    
    if profile_update.last_name is not None:
        current_user.last_name = profile_update.last_name
    
    if profile_update.email is not None:
        # Check if email is already taken
        existing_user = db.query(User).filter(
            User.email == profile_update.email,
            User.id != current_user.id
        ).first()
        if existing_user:
            raise HTTPException(
                status_code=400,
                detail="Email is already in use"
            )
        current_user.email = profile_update.email
    
    db.commit()
    db.refresh(current_user)
    
    # Get organizations
    memberships = db.query(OrganizationMember).filter(
        OrganizationMember.user_id == current_user.id
    ).all()
    
    organizations = []
    for membership in memberships:
        org = db.query(Organization).filter(
            Organization.id == membership.organization_id
        ).first()
        if org:
            # Handle role being either enum or string
            role_value = membership.role.value if hasattr(membership.role, 'value') else membership.role
            organizations.append({
                "id": org.id,
                "name": org.name,
                "role": role_value,
                "joined_at": membership.joined_at.isoformat()
            })
    
    return {
        "id": current_user.id,
        "email": current_user.email,
        "name": current_user.name,
        "first_name": current_user.first_name,
        "last_name": current_user.last_name,
        "created_at": current_user.created_at,
        "organizations": organizations
    }


@router.get("/invitations", response_model=List[InvitationResponse], operation_id="getMyInvitations")
async def get_my_invitations(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get all invitations for the current user.
    """
    invitations = db.query(Invitation).filter(
        Invitation.email == current_user.email
    ).order_by(Invitation.created_at.desc()).all()
    
    result = []
    for invitation in invitations:
        # Check if expired
        if invitation.status == InvitationStatus.PENDING and invitation.expires_at < datetime.now(timezone.utc):
            invitation.status = InvitationStatus.EXPIRED
            db.commit()
        
        org = db.query(Organization).filter(
            Organization.id == invitation.organization_id
        ).first()
        
        result.append({
            "id": invitation.id,
            "organization_id": invitation.organization_id,
            "email": invitation.email,
            "role": invitation.role,
            "status": invitation.status,
            "expires_at": invitation.expires_at,
            "created_at": invitation.created_at,
            "organization_name": org.name if org else None
        })
    
    return result


@router.post("/invitations/{invitation_id}/accept", response_model=MessageResponse, operation_id="acceptInvitation")
async def accept_invitation(
    invitation_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Accept an invitation to join an organization.
    """
    invitation = db.query(Invitation).filter(
        Invitation.id == invitation_id,
        Invitation.email == current_user.email
    ).first()
    
    if not invitation:
        raise HTTPException(status_code=404, detail="Invitation not found")
    
    if invitation.status != InvitationStatus.PENDING:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot accept invitation with status: {invitation.status.value}"
        )
    
    if invitation.expires_at < datetime.now(timezone.utc):
        invitation.status = InvitationStatus.EXPIRED
        db.commit()
        raise HTTPException(status_code=400, detail="Invitation has expired")
    
    # Check if user is already a member
    existing_member = db.query(OrganizationMember).filter(
        OrganizationMember.organization_id == invitation.organization_id,
        OrganizationMember.user_id == current_user.id
    ).first()
    
    if existing_member:
        raise HTTPException(
            status_code=400,
            detail="User is already a member of this organization"
        )
    
    # Create organization membership
    member = OrganizationMember(
        organization_id=invitation.organization_id,
        user_id=current_user.id,
        role=invitation.role
    )
    db.add(member)
    
    # Update invitation
    invitation.status = InvitationStatus.ACCEPTED
    invitation.accepted_at = datetime.now(timezone.utc)
    invitation.invited_user_id = current_user.id
    
    db.commit()
    
    return {"message": "Invitation accepted successfully"}


@router.post("/invitations/{invitation_id}/decline", response_model=MessageResponse, operation_id="declineInvitation")
async def decline_invitation(
    invitation_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Decline an invitation to join an organization.
    """
    invitation = db.query(Invitation).filter(
        Invitation.id == invitation_id,
        Invitation.email == current_user.email
    ).first()
    
    if not invitation:
        raise HTTPException(status_code=404, detail="Invitation not found")
    
    if invitation.status != InvitationStatus.PENDING:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot decline invitation with status: {invitation.status.value}"
        )
    
    invitation.status = InvitationStatus.DECLINED
    db.commit()
    
    return {"message": "Invitation declined"}

