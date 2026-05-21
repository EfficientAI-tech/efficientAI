"""CRUD for reusable Input Parameter schemas used by Call Uploads.

A schema is a workspace-scoped, named bundle of typed parameters that
drives the upload-time mapping UI. The user defines the schema once
(e.g. "Standard Voice QA" with ``conversation_id`` + ``recording_url`` +
``transcript`` + ``agent_name``) and on every CSV/Excel upload the
parameters are mapped to source columns.

Every schema MUST contain exactly one parameter with
``type='conversation_id'`` and ``is_required=True``; this is the
mandatory identity column for each row in the imported batch. The
invariant is enforced here on create + update because it spans the
parent (`call_import_schemas`) and the children
(`call_import_schema_parameters`) which are written in the same
transaction.
"""

from __future__ import annotations

from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.dependencies import (
    get_api_key,
    get_organization_id,
    get_workspace_id,
    require_enterprise_feature,
)
from app.models.database import (
    CallImport,
    CallImportSchema,
    CallImportSchemaParameter,
)
from app.models.enums import CallImportParameterType
from app.models.schemas import (
    CallImportSchemaCreate,
    CallImportSchemaListResponse,
    CallImportSchemaResponse,
    CallImportSchemaUpdate,
)


router = APIRouter(
    prefix="/call-import-schemas",
    tags=["Call Imports"],
    dependencies=[Depends(require_enterprise_feature("call_imports"))],
)


def _serialize_schema(
    schema: CallImportSchema, usage_count: int = 0
) -> CallImportSchemaResponse:
    """Convert an ORM row into the API response, stamping usage_count."""
    payload = CallImportSchemaResponse.model_validate(schema)
    payload.usage_count = usage_count
    return payload


def _materialize_parameters(
    schema_id: UUID, payload_params
) -> List[CallImportSchemaParameter]:
    """Build (but don't persist) parameter rows from the request payload.

    ``ordering`` is stamped from the request order so the UI can rely
    on the parameter list coming back in the order the schema author
    laid it out. The mandatory ``conversation_id`` parameter is forced
    to ``is_required=True`` even if the client omits the flag, to keep
    the invariant safe against partial UI updates.
    """
    rows: List[CallImportSchemaParameter] = []
    for idx, param in enumerate(payload_params):
        is_required = (
            True
            if param.type == CallImportParameterType.CONVERSATION_ID
            else bool(param.is_required)
        )
        rows.append(
            CallImportSchemaParameter(
                schema_id=schema_id,
                name=param.name.strip(),
                type=param.type.value,
                description=(param.description or None),
                is_required=is_required,
                ordering=idx,
            )
        )
    return rows


def _load_schema(
    db: Session, schema_id: UUID, organization_id: UUID, workspace_id: UUID
) -> CallImportSchema:
    """Fetch one schema by id, scoped to the active (org, workspace)."""
    schema = (
        db.query(CallImportSchema)
        .options(selectinload(CallImportSchema.parameters))
        .filter(
            CallImportSchema.id == schema_id,
            CallImportSchema.organization_id == organization_id,
            CallImportSchema.workspace_id == workspace_id,
        )
        .first()
    )
    if not schema:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Call import schema not found",
        )
    return schema


def _count_usage(db: Session, schema_id: UUID) -> int:
    """How many CallImport batches reference this schema."""
    return (
        db.query(func.count(CallImport.id))
        .filter(CallImport.schema_id == schema_id)
        .scalar()
        or 0
    )


@router.get(
    "",
    response_model=CallImportSchemaListResponse,
    operation_id="listCallImportSchemas",
)
async def list_call_import_schemas(
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
) -> CallImportSchemaListResponse:
    """List schemas in the active workspace (alphabetical by name).

    Each entry includes ``usage_count`` so the UI can warn the user
    before deleting a schema that batches are still pinned to.
    """
    del api_key

    schemas = (
        db.query(CallImportSchema)
        .options(selectinload(CallImportSchema.parameters))
        .filter(
            CallImportSchema.organization_id == organization_id,
            CallImportSchema.workspace_id == workspace_id,
        )
        .order_by(CallImportSchema.name.asc())
        .all()
    )

    if not schemas:
        return CallImportSchemaListResponse(items=[], total=0)

    schema_ids = [s.id for s in schemas]
    usage_rows = (
        db.query(CallImport.schema_id, func.count(CallImport.id))
        .filter(CallImport.schema_id.in_(schema_ids))
        .group_by(CallImport.schema_id)
        .all()
    )
    usage_map = {schema_id: int(cnt) for schema_id, cnt in usage_rows}

    items = [_serialize_schema(s, usage_map.get(s.id, 0)) for s in schemas]
    return CallImportSchemaListResponse(items=items, total=len(items))


@router.post(
    "",
    response_model=CallImportSchemaResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="createCallImportSchema",
)
async def create_call_import_schema(
    payload: CallImportSchemaCreate,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
) -> CallImportSchemaResponse:
    """Create a new schema + parameters in the active workspace.

    Pydantic validates the cross-parameter invariants (single
    ``conversation_id``, unique names) before the body reaches this
    handler; we still rely on the DB-level unique index to catch the
    name-collision race.
    """
    del api_key

    name_normalized = payload.name.strip()

    # Pre-flight duplicate check. Production catches this via the partial
    # unique index ``uq_call_import_schemas_ws_name`` on
    # ``LOWER(name)`` (see migration 034), but that's a Postgres
    # expression index — SQLAlchemy's ``Base.metadata.create_all`` used
    # in tests doesn't create it, so SQLite would silently accept
    # duplicates. Doing the lookup in app code keeps the 409 behavior
    # identical across both backends.
    existing = (
        db.query(CallImportSchema.id)
        .filter(
            CallImportSchema.organization_id == organization_id,
            CallImportSchema.workspace_id == workspace_id,
            func.lower(CallImportSchema.name) == name_normalized.lower(),
        )
        .first()
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A schema named '{payload.name}' already exists in this workspace.",
        )

    schema = CallImportSchema(
        organization_id=organization_id,
        workspace_id=workspace_id,
        name=name_normalized,
        description=(payload.description or None),
    )
    db.add(schema)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A schema named '{payload.name}' already exists in this workspace.",
        )

    params = _materialize_parameters(schema.id, payload.parameters)
    for p in params:
        db.add(p)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Parameter names must be unique within a schema.",
        )

    db.refresh(schema)
    return _serialize_schema(schema, usage_count=0)


@router.get(
    "/{schema_id}",
    response_model=CallImportSchemaResponse,
    operation_id="getCallImportSchema",
)
async def get_call_import_schema(
    schema_id: UUID,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
) -> CallImportSchemaResponse:
    """Fetch a single schema with its parameters + usage count."""
    del api_key
    schema = _load_schema(db, schema_id, organization_id, workspace_id)
    return _serialize_schema(schema, _count_usage(db, schema.id))


@router.patch(
    "/{schema_id}",
    response_model=CallImportSchemaResponse,
    operation_id="updateCallImportSchema",
)
async def update_call_import_schema(
    schema_id: UUID,
    payload: CallImportSchemaUpdate,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
) -> CallImportSchemaResponse:
    """Update a schema's metadata and/or replace its parameter list.

    When ``parameters`` is included in the body, the new list FULLY
    REPLACES the existing parameters (delete-then-insert in one
    transaction). Existing CallImport batches that reference this
    schema keep their snapshotted ``parameter_mapping`` unchanged - we
    don't try to retro-validate historical mappings against the new
    schema shape.
    """
    del api_key

    schema = _load_schema(db, schema_id, organization_id, workspace_id)

    body = payload.model_dump(exclude_unset=True)
    if "name" in body and body["name"] is not None:
        schema.name = body["name"].strip()
    if "description" in body:
        schema.description = (body["description"] or None)

    if payload.parameters is not None:
        # Delete-and-recreate keeps the wire format simple (single
        # source of truth: the full list in the request body) and
        # sidesteps complex diffing on the server. The CASCADE on the
        # FK takes care of orphaned children.
        for existing in list(schema.parameters):
            db.delete(existing)
        db.flush()
        for p in _materialize_parameters(schema.id, payload.parameters):
            db.add(p)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Could not save schema - name must be unique within "
                "workspace and parameter names must be unique within schema."
            ),
        )

    db.refresh(schema)
    return _serialize_schema(schema, _count_usage(db, schema.id))


@router.delete(
    "/{schema_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="deleteCallImportSchema",
)
async def delete_call_import_schema(
    schema_id: UUID,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
) -> Response:
    """Delete a schema.

    Refuses with 409 when any ``CallImport`` row still references the
    schema (matches the ``ON DELETE RESTRICT`` FK behavior); the user
    must either delete the dependent batches first or migrate them to
    a different schema before retrying.
    """
    del api_key

    schema = _load_schema(db, schema_id, organization_id, workspace_id)

    usage = _count_usage(db, schema.id)
    if usage > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Cannot delete schema '{schema.name}': it is still in "
                f"use by {usage} call import batch(es)."
            ),
        )

    db.delete(schema)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
