"""Platform admin routes for cross-org management."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.auth.platform_admin import (
    PlatformAdminPrincipal,
    create_platform_access_token,
    get_platform_admin,
    platform_admin_feature_enabled,
)
from app.core.auth.refresh_tokens import revoke_all_user_refresh_tokens
from app.core.password import hash_password, validate_password_strength, verify_password
from app.database import get_db
from app.models.database import (
    Organization,
    OrganizationMember,
    PlatformAdmin,
    SignupReferenceCode,
    User,
)
from app.services.signup_reference_codes import hash_reference_code

router = APIRouter(prefix="/platform", tags=["Platform Admin"])


class PlatformLoginRequest(BaseModel):
    email: EmailStr
    password: str


class PlatformAdminSummary(BaseModel):
    id: str
    email: str


class PlatformTokenResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int
    admin: PlatformAdminSummary


class OrganizationListItem(BaseModel):
    id: str
    name: str
    is_active: bool
    member_count: int
    created_at: Optional[str] = None
    disabled_at: Optional[str] = None


class OrganizationListResponse(BaseModel):
    items: List[OrganizationListItem]
    total: int
    offset: int
    limit: int


class OrganizationStatsResponse(BaseModel):
    total: int
    active: int
    disabled: int


class OrganizationUpdateRequest(BaseModel):
    is_active: bool


class OrgUserItem(BaseModel):
    id: str
    email: str
    role: str
    is_active: bool


class PlatformPasswordResetRequest(BaseModel):
    new_password: str = Field(min_length=8, max_length=32)


class PlatformPasswordResetResponse(BaseModel):
    user_id: str
    email: str
    message: str = "Password reset successfully"


class SignupCodeCreateRequest(BaseModel):
    code: str = Field(min_length=4, max_length=64)
    label: Optional[str] = Field(default=None, max_length=255)
    max_uses: Optional[int] = Field(default=None, ge=1)
    expires_at: Optional[datetime] = None


class SignupCodeResponse(BaseModel):
    id: str
    label: Optional[str] = None
    max_uses: Optional[int] = None
    use_count: int
    expires_at: Optional[str] = None
    is_active: bool
    created_at: Optional[str] = None
    code: Optional[str] = None


class SignupCodeUpdateRequest(BaseModel):
    is_active: Optional[bool] = None
    max_uses: Optional[int] = Field(default=None, ge=1)
    label: Optional[str] = Field(default=None, max_length=255)


def _validate_password_or_400(password: str) -> None:
    try:
        validate_password_strength(password)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def _serialize_org(org: Organization, member_count: int) -> OrganizationListItem:
    return OrganizationListItem(
        id=str(org.id),
        name=org.name,
        is_active=bool(org.is_active),
        member_count=member_count,
        created_at=org.created_at.isoformat() if org.created_at else None,
        disabled_at=org.disabled_at.isoformat() if org.disabled_at else None,
    )


def _serialize_signup_code(row: SignupReferenceCode, *, include_code: bool = False, code: Optional[str] = None) -> SignupCodeResponse:
    return SignupCodeResponse(
        id=str(row.id),
        label=row.label,
        max_uses=row.max_uses,
        use_count=row.use_count or 0,
        expires_at=row.expires_at.isoformat() if row.expires_at else None,
        is_active=bool(row.is_active),
        created_at=row.created_at.isoformat() if row.created_at else None,
        code=code if include_code else None,
    )


@router.post("/auth/login", response_model=PlatformTokenResponse)
def platform_login(payload: PlatformLoginRequest, db: Session = Depends(get_db)) -> PlatformTokenResponse:
    if not platform_admin_feature_enabled(db):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    admin = (
        db.query(PlatformAdmin)
        .filter(PlatformAdmin.email == payload.email, PlatformAdmin.is_active == True)  # noqa: E712
        .first()
    )
    if admin is None or not verify_password(payload.password, admin.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )

    admin.last_login_at = datetime.now(timezone.utc)
    db.commit()

    access_token, expires_in = create_platform_access_token(
        platform_admin_id=admin.id,
        email=admin.email,
    )
    return PlatformTokenResponse(
        access_token=access_token,
        expires_in=expires_in,
        admin=PlatformAdminSummary(id=str(admin.id), email=admin.email),
    )


@router.get("/auth/me", response_model=PlatformAdminSummary)
def platform_me(
    principal: PlatformAdminPrincipal = Depends(get_platform_admin),
) -> PlatformAdminSummary:
    return PlatformAdminSummary(id=str(principal.platform_admin_id), email=principal.email)


@router.get("/organizations", response_model=OrganizationListResponse)
def list_organizations(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    search: Optional[str] = Query(default=None, max_length=255),
    is_active: Optional[bool] = Query(default=None),
    _principal: PlatformAdminPrincipal = Depends(get_platform_admin),
    db: Session = Depends(get_db),
) -> OrganizationListResponse:
    query = db.query(Organization)
    if search:
        query = query.filter(Organization.name.ilike(f"%{search}%"))
    if is_active is not None:
        query = query.filter(Organization.is_active == is_active)

    total = query.count()
    orgs = (
        query.order_by(Organization.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    member_counts = dict(
        db.query(OrganizationMember.organization_id, func.count(OrganizationMember.id))
        .filter(OrganizationMember.organization_id.in_([org.id for org in orgs]))
        .group_by(OrganizationMember.organization_id)
        .all()
    ) if orgs else {}

    return OrganizationListResponse(
        items=[_serialize_org(org, member_counts.get(org.id, 0)) for org in orgs],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get("/organizations/stats", response_model=OrganizationStatsResponse)
def organization_stats(
    _principal: PlatformAdminPrincipal = Depends(get_platform_admin),
    db: Session = Depends(get_db),
) -> OrganizationStatsResponse:
    total = db.query(func.count(Organization.id)).scalar() or 0
    active = (
        db.query(func.count(Organization.id))
        .filter(Organization.is_active == True)  # noqa: E712
        .scalar()
        or 0
    )
    disabled = total - active
    return OrganizationStatsResponse(total=total, active=active, disabled=disabled)


@router.patch("/organizations/{org_id}", response_model=OrganizationListItem)
def update_organization(
    org_id: UUID,
    payload: OrganizationUpdateRequest,
    _principal: PlatformAdminPrincipal = Depends(get_platform_admin),
    db: Session = Depends(get_db),
) -> OrganizationListItem:
    org = db.query(Organization).filter(Organization.id == org_id).first()
    if org is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")

    org.is_active = payload.is_active
    org.disabled_at = None if payload.is_active else datetime.now(timezone.utc)
    db.commit()
    db.refresh(org)

    member_count = (
        db.query(func.count(OrganizationMember.id))
        .filter(OrganizationMember.organization_id == org.id)
        .scalar()
        or 0
    )
    return _serialize_org(org, member_count)


@router.get("/organizations/{org_id}/users", response_model=List[OrgUserItem])
def list_organization_users(
    org_id: UUID,
    role: Optional[str] = Query(default=None),
    _principal: PlatformAdminPrincipal = Depends(get_platform_admin),
    db: Session = Depends(get_db),
) -> List[OrgUserItem]:
    org = db.query(Organization).filter(Organization.id == org_id).first()
    if org is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")

    query = (
        db.query(User, OrganizationMember)
        .join(OrganizationMember, OrganizationMember.user_id == User.id)
        .filter(OrganizationMember.organization_id == org_id)
    )
    if role:
        query = query.filter(OrganizationMember.role == role)

    rows = query.order_by(User.email.asc()).all()
    items: List[OrgUserItem] = []
    for user, member in rows:
        role_value = member.role.value if hasattr(member.role, "value") else member.role
        items.append(
            OrgUserItem(
                id=str(user.id),
                email=user.email,
                role=role_value,
                is_active=bool(user.is_active),
            )
        )
    return items


@router.post(
    "/organizations/{org_id}/users/{user_id}/reset-password",
    response_model=PlatformPasswordResetResponse,
)
def platform_reset_user_password(
    org_id: UUID,
    user_id: UUID,
    payload: PlatformPasswordResetRequest,
    _principal: PlatformAdminPrincipal = Depends(get_platform_admin),
    db: Session = Depends(get_db),
) -> PlatformPasswordResetResponse:
    member = (
        db.query(OrganizationMember)
        .filter(
            OrganizationMember.organization_id == org_id,
            OrganizationMember.user_id == user_id,
        )
        .first()
    )
    if member is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User is not a member of this organization",
        )

    user = db.query(User).filter(User.id == user_id).first()
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found or inactive",
        )

    _validate_password_or_400(payload.new_password)
    user.password_hash = hash_password(payload.new_password)
    revoke_all_user_refresh_tokens(db, user_id=user.id)
    db.commit()

    return PlatformPasswordResetResponse(user_id=str(user.id), email=user.email)


@router.get("/signup-codes", response_model=List[SignupCodeResponse])
def list_signup_codes(
    _principal: PlatformAdminPrincipal = Depends(get_platform_admin),
    db: Session = Depends(get_db),
) -> List[SignupCodeResponse]:
    rows = (
        db.query(SignupReferenceCode)
        .order_by(SignupReferenceCode.created_at.desc())
        .all()
    )
    return [_serialize_signup_code(row) for row in rows]


@router.post("/signup-codes", response_model=SignupCodeResponse, status_code=status.HTTP_201_CREATED)
def create_signup_code(
    payload: SignupCodeCreateRequest,
    principal: PlatformAdminPrincipal = Depends(get_platform_admin),
    db: Session = Depends(get_db),
) -> SignupCodeResponse:
    code_hash = hash_reference_code(payload.code)
    existing = db.query(SignupReferenceCode).filter(SignupReferenceCode.code_hash == code_hash).first()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A reference code with this value already exists.",
        )

    row = SignupReferenceCode(
        code_hash=code_hash,
        label=payload.label,
        max_uses=payload.max_uses,
        expires_at=payload.expires_at,
        is_active=True,
        created_by=principal.platform_admin_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _serialize_signup_code(row, include_code=True, code=payload.code.strip())


@router.patch("/signup-codes/{code_id}", response_model=SignupCodeResponse)
def update_signup_code(
    code_id: UUID,
    payload: SignupCodeUpdateRequest,
    _principal: PlatformAdminPrincipal = Depends(get_platform_admin),
    db: Session = Depends(get_db),
) -> SignupCodeResponse:
    row = db.query(SignupReferenceCode).filter(SignupReferenceCode.id == code_id).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reference code not found")

    if payload.is_active is not None:
        row.is_active = payload.is_active
    if payload.max_uses is not None:
        row.max_uses = payload.max_uses
    if payload.label is not None:
        row.label = payload.label

    db.commit()
    db.refresh(row)
    return _serialize_signup_code(row)


@router.delete("/signup-codes/{code_id}", response_model=SignupCodeResponse)
def deactivate_signup_code(
    code_id: UUID,
    _principal: PlatformAdminPrincipal = Depends(get_platform_admin),
    db: Session = Depends(get_db),
) -> SignupCodeResponse:
    row = db.query(SignupReferenceCode).filter(SignupReferenceCode.id == code_id).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reference code not found")

    row.is_active = False
    db.commit()
    db.refresh(row)
    return _serialize_signup_code(row)
