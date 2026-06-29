"""
Settings API Routes
Manage API keys for authenticated users
"""
import base64
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified
from typing import List, Literal, Optional
import secrets
from pydantic import BaseModel

from app.dependencies import (
    get_db,
    get_api_key,
    get_organization_id,
    get_workspace_id,
    require_capability,
)
from app.core.auth.capabilities import REPORTS_VIEW, WORKSPACE_SETTINGS
from app.models.database import APIKey, User, Organization, Workspace
from app.models.schemas import MessageResponse
from app.api.v1.routes.profile import get_current_user
from app.core.exceptions import StorageError
from app.core.license import (
    get_feature_catalog,
    get_license_info,
    is_feature_enabled,
    ENTERPRISE_FEATURES,
)


REPORT_LOGO_CONTENT_TYPES = {
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/webp",
    "image/svg+xml",
}
REPORT_LOGO_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "svg"}
MAX_REPORT_LOGO_BYTES = 5 * 1024 * 1024
REPORT_BRANDING_IMAGE_ROLES = {"internal", "external", "generic"}


class APIKeyCreateRequest(BaseModel):
    name: Optional[str] = None


class ReportBrandingImageResponse(BaseModel):
    id: str
    filename: str
    content_type: str
    size_bytes: int
    role: Literal["internal", "external", "generic"] = "generic"
    updated_at: Optional[str] = None
    data_uri: Optional[str] = None


class ReportBrandingUpdateRequest(BaseModel):
    heading: Optional[str] = None


class ReportBrandingResponse(BaseModel):
    heading: Optional[str] = None
    has_logo: bool
    images: List[ReportBrandingImageResponse] = []

router = APIRouter(prefix="/settings", tags=["Settings"])

# Maximum number of API keys per user
MAX_API_KEYS_PER_USER = 5


@router.get("/license-info")
def license_info(organization_id: UUID = Depends(get_organization_id)):
    """
    Return the current enterprise license status and enabled features.
    When the license is scoped to an org_id, only returns features
    that match the requesting organization.
    """
    data = get_license_info()
    all_licensed = data.get("features", []) if isinstance(data.get("features"), list) else []
    enabled_for_org = [f for f in all_licensed if is_feature_enabled(f, organization_id)]
    return {
        "is_enterprise": bool(enabled_for_org),
        "enabled_features": enabled_for_org,
        "all_enterprise_features": ENTERPRISE_FEATURES,
        "feature_catalog": get_feature_catalog(),
        "organization": data.get("org_id"),
    }


def _report_branding_response(workspace: Workspace) -> ReportBrandingResponse:
    raw = workspace.report_branding if isinstance(workspace.report_branding, dict) else {}
    images_raw = raw.get("images") if isinstance(raw.get("images"), list) else []
    images: list[ReportBrandingImageResponse] = []
    for item in images_raw:
        if not isinstance(item, dict):
            continue
        key = item.get("s3_key")
        if not key:
            continue
        data_uri: Optional[str] = None
        try:
            from app.services.storage.s3_service import s3_service

            image_bytes = s3_service.download_file_by_key(str(key))
            content_type = str(item.get("content_type") or "image/png")
            encoded = base64.b64encode(image_bytes).decode("ascii")
            data_uri = f"data:{content_type};base64,{encoded}"
        except Exception:
            data_uri = None
        images.append(
            ReportBrandingImageResponse(
                id=str(item.get("id") or ""),
                filename=str(item.get("filename") or "logo"),
                content_type=str(item.get("content_type") or "image/png"),
                size_bytes=int(item.get("size_bytes") or 0),
                role=(
                    str(item.get("role"))
                    if str(item.get("role")) in REPORT_BRANDING_IMAGE_ROLES
                    else "generic"
                ),
                updated_at=item.get("updated_at"),
                data_uri=data_uri,
            )
        )

    return ReportBrandingResponse(
        heading=raw.get("heading") if isinstance(raw.get("heading"), str) else None,
        has_logo=bool(images),
        images=images,
    )


@router.get(
    "/report-branding",
    response_model=ReportBrandingResponse,
    dependencies=[Depends(require_capability(REPORTS_VIEW))],
)
def get_report_branding(
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    del api_key
    workspace = (
        db.query(Workspace)
        .filter(
            Workspace.id == workspace_id,
            Workspace.organization_id == organization_id,
        )
        .first()
    )
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return _report_branding_response(workspace)


@router.patch(
    "/report-branding",
    response_model=ReportBrandingResponse,
    dependencies=[Depends(require_capability(WORKSPACE_SETTINGS))],
)
def update_report_branding(
    payload: ReportBrandingUpdateRequest,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    del api_key
    workspace = (
        db.query(Workspace)
        .filter(
            Workspace.id == workspace_id,
            Workspace.organization_id == organization_id,
        )
        .first()
    )
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")
    raw = dict(workspace.report_branding or {})
    heading = (payload.heading or "").strip()
    raw["heading"] = heading or None
    raw.setdefault("images", [])
    workspace.report_branding = raw
    flag_modified(workspace, "report_branding")
    db.commit()
    db.refresh(workspace)
    return _report_branding_response(workspace)


@router.post(
    "/report-branding/images",
    response_model=ReportBrandingResponse,
    dependencies=[Depends(require_capability(WORKSPACE_SETTINGS))],
)
async def upload_report_branding_images(
    files: List[UploadFile] = File(...),
    role: Literal["internal", "external", "generic"] = Form("generic"),
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    del api_key
    if not files:
        raise HTTPException(status_code=400, detail="Upload at least one image.")
    if role not in REPORT_BRANDING_IMAGE_ROLES:
        raise HTTPException(
            status_code=400,
            detail="Branding image role must be internal, external, or generic.",
        )
    workspace = (
        db.query(Workspace)
        .filter(
            Workspace.id == workspace_id,
            Workspace.organization_id == organization_id,
        )
        .first()
    )
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

    from app.services.storage.s3_service import s3_service

    if not s3_service.is_enabled():
        detail = s3_service.get_status_message() or "Cloud blob storage is not enabled or configured."
        raise HTTPException(status_code=503, detail=detail)

    raw = dict(workspace.report_branding or {})
    images = list(raw.get("images") if isinstance(raw.get("images"), list) else [])
    for file in files:
        filename = Path(file.filename or "logo").name
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        content_type = (file.content_type or "").split(";", 1)[0].strip().lower()
        if ext not in REPORT_LOGO_EXTENSIONS or content_type not in REPORT_LOGO_CONTENT_TYPES:
            raise HTTPException(
                status_code=400,
                detail="Upload PNG, JPG, WEBP, or SVG logo images.",
            )

        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail=f"{filename} is empty.")
        if len(content) > MAX_REPORT_LOGO_BYTES:
            raise HTTPException(
                status_code=400,
                detail=f"{filename} is too large. Maximum size is 5 MB.",
            )

        image_id = str(uuid4())
        key = (
            f"{s3_service.prefix}organizations/{organization_id}/workspaces/"
            f"{workspace_id}/report_branding/{image_id}.{ext}"
        )
        try:
            s3_service.upload_file_by_key(content, key, content_type=content_type)
        except StorageError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        images.append(
            {
                "id": image_id,
                "s3_key": key,
                "content_type": content_type,
                "filename": filename,
                "size_bytes": len(content),
                "role": role,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )

    raw["images"] = images
    workspace.report_branding = raw
    flag_modified(workspace, "report_branding")
    db.commit()
    db.refresh(workspace)
    return _report_branding_response(workspace)


@router.delete(
    "/report-branding/images/{image_id}",
    response_model=ReportBrandingResponse,
    dependencies=[Depends(require_capability(WORKSPACE_SETTINGS))],
)
def delete_report_branding_image(
    image_id: str,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    del api_key
    workspace = (
        db.query(Workspace)
        .filter(
            Workspace.id == workspace_id,
            Workspace.organization_id == organization_id,
        )
        .first()
    )
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

    raw = dict(workspace.report_branding or {})
    images = list(raw.get("images") if isinstance(raw.get("images"), list) else [])
    kept = []
    removed = None
    for item in images:
        if isinstance(item, dict) and str(item.get("id")) == image_id:
            removed = item
        else:
            kept.append(item)
    if removed is None:
        raise HTTPException(status_code=404, detail="Report branding image not found")

    old_key = removed.get("s3_key")
    if old_key:
        try:
            from app.services.storage.s3_service import s3_service

            if s3_service.is_enabled():
                s3_service.delete_file_by_key(str(old_key))
        except Exception:
            pass

    raw["images"] = kept
    workspace.report_branding = raw
    flag_modified(workspace, "report_branding")
    db.commit()
    db.refresh(workspace)
    return _report_branding_response(workspace)


def mask_api_key(key: str) -> str:
    """Mask API key for display (show first 8 and last 4 characters)."""
    if len(key) <= 12:
        return "*" * len(key)
    return f"{key[:8]}...{key[-4:]}"


@router.get("/api-keys")
def list_api_keys(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    List all API keys for the current user.
    Returns masked keys for security.
    """
    # Get all API keys for this user
    api_keys = db.query(APIKey).filter(
        APIKey.user_id == current_user.id,
        APIKey.is_active == True
    ).order_by(APIKey.created_at.desc()).all()
    
    # Return masked keys
    result = []
    for key in api_keys:
        result.append({
            "id": str(key.id),
            "key": mask_api_key(key.key),
            "name": key.name,
            "is_active": key.is_active,
            "created_at": key.created_at.isoformat() if key.created_at else None,
            "last_used": key.last_used.isoformat() if key.last_used else None,
        })
    
    return result


@router.post("/api-keys")
def create_api_key(
    request: APIKeyCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Create a new API key for the current user.
    Maximum 5 keys per user.
    Returns the full key (only shown once).
    """
    # Check current key count
    key_count = db.query(APIKey).filter(
        APIKey.user_id == current_user.id,
        APIKey.is_active == True
    ).count()
    
    if key_count >= MAX_API_KEYS_PER_USER:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Maximum of {MAX_API_KEYS_PER_USER} API keys allowed per user. Please delete an existing key first."
        )
    
    # Get user's organization (from first API key or organization membership)
    from app.models.database import OrganizationMember
    org_member = db.query(OrganizationMember).filter(
        OrganizationMember.user_id == current_user.id
    ).first()
    
    if not org_member:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User is not associated with any organization"
        )
    
    organization_id = org_member.organization_id
    
    # Generate secure random API key
    api_key = secrets.token_urlsafe(32)
    
    # Create API key record
    db_key = APIKey(
        key=api_key,
        name=request.name,
        organization_id=organization_id,
        user_id=current_user.id,
        is_active=True
    )
    db.add(db_key)
    db.commit()
    db.refresh(db_key)
    
    # Return full key (only time it's shown)
    return {
        "id": str(db_key.id),
        "key": db_key.key,  # Full key shown only once
        "name": db_key.name,
        "is_active": db_key.is_active,
        "created_at": db_key.created_at.isoformat() if db_key.created_at else None,
        "last_used": None,
        "message": "Save this API key securely. You won't be able to see it again."
    }


@router.delete("/api-keys/{key_id}")
def delete_api_key(
    key_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Delete (deactivate) an API key.
    Only the owner can delete their own keys.
    """
    api_key = db.query(APIKey).filter(
        APIKey.id == key_id,
        APIKey.user_id == current_user.id
    ).first()
    
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found or you don't have permission to delete it"
        )
    
    # Deactivate instead of deleting (soft delete)
    api_key.is_active = False
    db.commit()
    
    return MessageResponse(message="API key deleted successfully")


@router.post("/api-keys/{key_id}/regenerate")
def regenerate_api_key(
    key_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Regenerate an API key.
    Creates a new key and deactivates the old one.
    Returns the new full key (only shown once).
    """
    old_key = db.query(APIKey).filter(
        APIKey.id == key_id,
        APIKey.user_id == current_user.id
    ).first()
    
    if not old_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found or you don't have permission to regenerate it"
        )
    
    # Check if we're at the limit (accounting for the key we're about to deactivate)
    key_count = db.query(APIKey).filter(
        APIKey.user_id == current_user.id,
        APIKey.is_active == True
    ).count()
    
    if key_count >= MAX_API_KEYS_PER_USER:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Maximum of {MAX_API_KEYS_PER_USER} API keys allowed per user. Please delete an existing key first."
        )
    
    # Generate new secure random API key
    new_api_key = secrets.token_urlsafe(32)
    
    # Deactivate old key
    old_key.is_active = False
    
    # Create new API key with same organization and user
    new_db_key = APIKey(
        key=new_api_key,
        name=old_key.name,
        organization_id=old_key.organization_id,
        user_id=old_key.user_id,
        is_active=True
    )
    db.add(new_db_key)
    db.commit()
    db.refresh(new_db_key)
    
    # Return new full key (only time it's shown)
    return {
        "id": str(new_db_key.id),
        "key": new_db_key.key,  # Full key shown only once
        "name": new_db_key.name,
        "is_active": new_db_key.is_active,
        "created_at": new_db_key.created_at.isoformat() if new_db_key.created_at else None,
        "last_used": None,
        "message": "Save this API key securely. You won't be able to see it again."
    }
