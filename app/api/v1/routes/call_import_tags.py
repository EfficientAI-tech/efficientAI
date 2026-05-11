"""CRUD for CallImportTag - the optional secondary classification on top
of the free-text ``CallImport.dataset`` segregation.

Tags are scoped per organization and unique by ``(organization_id, name)``.
A tag can be attached to many call imports (and an import can carry many
tags) via the ``call_import_tag_assignments`` join table.
"""

from __future__ import annotations

from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_api_key, get_organization_id
from app.models.database import CallImportTag
from app.models.schemas import (
    CallImportTagCreate,
    CallImportTagResponse,
    CallImportTagUpdate,
)


router = APIRouter(prefix="/call-import-tags", tags=["Call Imports"])


@router.get(
    "",
    response_model=List[CallImportTagResponse],
    operation_id="listCallImportTags",
)
async def list_call_import_tags(
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
) -> List[CallImportTag]:
    """List every tag defined for this organization (alphabetical by name)."""
    return (
        db.query(CallImportTag)
        .filter(CallImportTag.organization_id == organization_id)
        .order_by(CallImportTag.name.asc())
        .all()
    )


@router.post(
    "",
    response_model=CallImportTagResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="createCallImportTag",
)
async def create_call_import_tag(
    payload: CallImportTagCreate,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
) -> CallImportTag:
    """Create a new tag scoped to this organization."""
    tag = CallImportTag(
        organization_id=organization_id,
        name=payload.name.strip(),
        color=payload.color,
    )
    db.add(tag)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A tag named '{payload.name}' already exists",
        )
    db.refresh(tag)
    return tag


@router.patch(
    "/{tag_id}",
    response_model=CallImportTagResponse,
    operation_id="updateCallImportTag",
)
async def update_call_import_tag(
    tag_id: UUID,
    payload: CallImportTagUpdate,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
) -> CallImportTag:
    """Rename or recolor an existing tag."""
    tag = (
        db.query(CallImportTag)
        .filter(
            CallImportTag.id == tag_id,
            CallImportTag.organization_id == organization_id,
        )
        .first()
    )
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")

    update_data = payload.model_dump(exclude_unset=True)
    if "name" in update_data:
        tag.name = update_data["name"].strip()
    if "color" in update_data:
        tag.color = update_data["color"]

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A tag with that name already exists",
        )
    db.refresh(tag)
    return tag


@router.delete(
    "/{tag_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="deleteCallImportTag",
)
async def delete_call_import_tag(
    tag_id: UUID,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
) -> Response:
    """Delete a tag. Existing tag assignments are removed by ON DELETE CASCADE."""
    tag = (
        db.query(CallImportTag)
        .filter(
            CallImportTag.id == tag_id,
            CallImportTag.organization_id == organization_id,
        )
        .first()
    )
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")

    db.delete(tag)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
