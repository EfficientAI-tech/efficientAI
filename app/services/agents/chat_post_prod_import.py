"""Helpers for post-prod chat evaluation via call imports."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.models.database import CallImportSchema, CallImportSchemaParameter
from app.models.enums import CallImportParameterType

CHAT_TRANSCRIPT_SCHEMA_NAME = "Chat transcript (post-prod)"


def ensure_chat_transcript_import_schema(
    db: Session,
    *,
    organization_id: UUID,
    workspace_id: UUID,
) -> CallImportSchema:
    existing = (
        db.query(CallImportSchema)
        .filter(
            CallImportSchema.organization_id == organization_id,
            CallImportSchema.workspace_id == workspace_id,
            CallImportSchema.name == CHAT_TRANSCRIPT_SCHEMA_NAME,
        )
        .first()
    )
    if existing:
        return existing

    schema = CallImportSchema(
        organization_id=organization_id,
        workspace_id=workspace_id,
        name=CHAT_TRANSCRIPT_SCHEMA_NAME,
        description="Import production chat logs: conversation id + transcript text (no audio).",
    )
    db.add(schema)
    db.flush()

    params = [
        CallImportSchemaParameter(
            schema_id=schema.id,
            name="conversation_id",
            type=CallImportParameterType.CONVERSATION_ID.value,
            is_required=True,
            ordering=0,
        ),
        CallImportSchemaParameter(
            schema_id=schema.id,
            name="transcript",
            type=CallImportParameterType.TRANSCRIPT.value,
            is_required=True,
            ordering=1,
        ),
    ]
    db.add_all(params)
    db.commit()
    db.refresh(schema)
    return schema
