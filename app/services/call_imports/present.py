"""Serialization and display helpers for call import API responses."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.database import CallImport, CallImportRow, CallImportTag
from app.models.enums import CallImportStatus
from app.services.call_imports.audit import (
    actor_emails_for_call_import,
    emails_for_user_ids,
    user_ids_from_call_imports,
)
from app.models.schemas import (
    CallImportResponse,
    CallImportRowResponse,
    PlatformImportAgentRef,
)

def _normalize_dataset(raw: Optional[str]) -> Optional[str]:
    """Trim and treat empty strings as 'no dataset' (NULL)."""
    if raw is None:
        return None
    cleaned = raw.strip()
    return cleaned or None


def _normalize_import_display_name(raw: Optional[str]) -> Optional[str]:
    """Trim a user-facing import/batch label; empty clears to NULL."""
    if raw is None:
        return None
    cleaned = raw.strip()
    if not cleaned:
        return None
    return cleaned[:512]


def _imported_agent_partial_id(call_import: CallImport):
    from app.services.platform_import_imported_agent import linked_partial_id

    return linked_partial_id(call_import)


def _platform_agent_refs(call_import: CallImport) -> list:
    """Agent id and name saved with a platform import, for later eval and prompt work."""
    raw = getattr(call_import, "platform_filters", None) or {}
    if not isinstance(raw, dict):
        return []
    refs = []
    for agent in raw.get("agents") or []:
        if not isinstance(agent, dict):
            continue
        agent_id = str(agent.get("id") or "").strip()
        if not agent_id:
            continue
        medium = agent.get("medium") or raw.get("medium")
        refs.append(
            {
                "id": agent_id,
                "name": str(agent.get("name") or agent_id),
                "medium": str(medium).strip().lower() if medium else None,
            }
        )
    if refs:
        return refs
    medium = raw.get("medium")
    for agent_id in raw.get("agent_ids") or []:
        text = str(agent_id or "").strip()
        if not text:
            continue
        refs.append(
            {
                "id": text,
                "name": text,
                "medium": str(medium).strip().lower() if medium else None,
            }
        )
    return refs


_agent_name_lookup_after: Dict[str, float] = {}


def _remember_platform_agent_names(db: Session, call_import: CallImport) -> None:
    """Fill in display names for imports that only stored the provider agent id."""
    import time

    refs = _platform_agent_refs(call_import)
    if not refs or not call_import.voice_integration_id:
        return
    if all(ref["name"] and ref["name"] != ref["id"] for ref in refs):
        return
    lookup_key = str(call_import.id)
    now = time.time()
    if _agent_name_lookup_after.get(lookup_key, 0) > now:
        return
    from sqlalchemy.orm.attributes import flag_modified

    from app.core.encryption import decrypt_api_key
    from app.models.database import Integration
    from app.services.voice_providers import get_voice_provider

    integration = (
        db.query(Integration)
        .filter(Integration.id == call_import.voice_integration_id)
        .first()
    )
    if integration is None or not integration.api_key:
        return
    try:
        from app.api.v1.routes.platform_call_imports import _list_import_agents

        api_key = decrypt_api_key(integration.api_key)
        provider_cls = get_voice_provider(integration.platform)
        if (integration.platform or "").lower() == "elevenlabs":
            client = provider_cls(api_key, base_url=integration.api_base_url)
        else:
            client = provider_cls(api_key)
        listed = _list_import_agents(client, integration.platform)
    except Exception:
        _agent_name_lookup_after[lookup_key] = time.time() + 300
        return
    by_id = {row.id: row for row in listed}
    updated = []
    changed = False
    for ref in refs:
        match = by_id.get(ref["id"])
        name = ref["name"]
        medium = ref.get("medium")
        if match is not None and match.name and match.name != ref["id"]:
            name = match.name
        if match is not None and match.medium:
            medium = match.medium
        if name != ref["name"] or medium != ref.get("medium"):
            changed = True
        updated.append({"id": ref["id"], "name": name, "medium": medium})
    if not changed:
        _agent_name_lookup_after[lookup_key] = time.time() + 300
        return
    filters = dict(call_import.platform_filters or {})
    filters["agents"] = updated
    call_import.platform_filters = filters
    flag_modified(call_import, "platform_filters")
    db.commit()


def _serialize_call_import(
    db: Session,
    call_import: CallImport,
    *,
    user_emails: Optional[Dict[UUID, str]] = None,
) -> CallImportResponse:
    """Catalog parent fields; counters come from SQL rollup (not Redis merge)."""
    from app.services.call_imports.bulk_ops import (
        _any_evaluation_needs_ui_poll,
        _latest_evaluation_progress_for_ui,
        rollup_call_import_batch_status,
    )
    from app.services.call_imports.progress_counters import (
        clear_import_progress_redis,
        read_import_progress,
    )

    redis_completed, redis_failed = read_import_progress(call_import.id)
    if (
        redis_completed
        or redis_failed
        or int(call_import.completed_rows or 0) > int(call_import.total_rows or 0)
        or int(call_import.failed_rows or 0) > int(call_import.total_rows or 0)
    ):
        rollup_call_import_batch_status(db, call_import)
        db.flush()

    clear_import_progress_redis(call_import.id)
    db.refresh(call_import)
    total = int(call_import.total_rows or 0)
    completed = min(int(call_import.completed_rows or 0), total) if total else int(
        call_import.completed_rows or 0
    )
    failed = min(int(call_import.failed_rows or 0), total) if total else int(
        call_import.failed_rows or 0
    )
    # Shard rows are the live count. The catalog counter lags during download.
    source = (getattr(call_import, "source_format", None) or "").lower()
    batch_status = (
        call_import.status.value
        if isinstance(call_import.status, CallImportStatus)
        else str(call_import.status or "")
    )
    if source == "platform" and batch_status in {"pending", "processing"}:
        from app.services.call_imports.bulk_ops import (
            _aggregate_import_row_status_counts,
        )

        agg_total, agg_completed, agg_failed, _, _ = (
            _aggregate_import_row_status_counts(db, call_import.id)
        )
        if agg_total > 0:
            total = agg_total
            completed = agg_completed
            failed = agg_failed
    if user_emails is None:
        user_emails = emails_for_user_ids(
            db, user_ids_from_call_imports([call_import])
        )
    created_email, updated_email = actor_emails_for_call_import(
        call_import, user_emails
    )
    base = CallImportResponse.model_validate(call_import)
    return base.model_copy(
        update={
            "total_rows": total,
            "completed_rows": completed,
            "failed_rows": failed,
            "platform_agents": [
                PlatformImportAgentRef.model_validate(ref)
                for ref in _platform_agent_refs(call_import)
            ],
            "imported_agent_partial_id": _imported_agent_partial_id(call_import),
            **_latest_evaluation_progress_for_ui(db, call_import.id),
            "any_evaluation_poll_active": _any_evaluation_needs_ui_poll(
                db, call_import.id
            ),
            "created_by_email": created_email,
            "last_updated_by_email": updated_email,
        }
    )
def _resolve_tags(
    db: Session, organization_id: UUID, tag_ids: Optional[List[UUID]]
) -> List[CallImportTag]:
    """Look up tag rows by id, scoped to the organization.

    Raises HTTPException(400) if any id is unknown for the org.
    """
    if not tag_ids:
        return []
    rows = (
        db.query(CallImportTag)
        .filter(
            CallImportTag.organization_id == organization_id,
            CallImportTag.id.in_(tag_ids),
        )
        .all()
    )
    found_ids = {row.id for row in rows}
    missing = [str(tag_id) for tag_id in tag_ids if tag_id not in found_ids]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown call_import_tag id(s): {missing}",
        )
    return rows
def _tag_response_payload(tags: Optional[List[CallImportTag]]) -> List[Dict[str, Any]]:
    """Shape a CallImport's tag relationship for the upload response."""
    return [
        {
            "id": tag.id,
            "name": tag.name,
            "color": tag.color,
            "created_at": tag.created_at,
            "updated_at": tag.updated_at,
        }
        for tag in (tags or [])
    ]
def _call_import_row_list_response(row: CallImportRow) -> CallImportRowResponse:
    """List payload. Transcript text is loaded by the single-row GET."""
    return CallImportRowResponse(
        id=row.id,
        row_index=row.row_index,
        conversation_id=row.conversation_id,
        recording_url=row.recording_url,
        recording_date=row.recording_date,
        transcript=None,
        transcript_source=row.transcript_source,
        transcript_provider=row.transcript_provider,
        transcript_model=row.transcript_model,
        transcript_status=row.transcript_status,
        transcript_error=row.transcript_error,
        transcribed_at=row.transcribed_at,
        diarised_transcript=None,
        diarised_transcript_provider=row.diarised_transcript_provider,
        diarised_transcript_model=row.diarised_transcript_model,
        diarised_transcript_status=row.diarised_transcript_status,
        diarised_transcript_error=row.diarised_transcript_error,
        diarised_at=row.diarised_at,
        diarised_llm_provider=row.diarised_llm_provider,
        diarised_llm_model=row.diarised_llm_model,
        diarised_prompt=None,
        diarised_segments=None,
        diarised_speaker_swap=bool(row.diarised_speaker_swap),
        status=row.status,
        recording_s3_key=row.recording_s3_key,
        recording_content_type=row.recording_content_type,
        recording_size_bytes=row.recording_size_bytes,
        error_message=row.error_message,
        attempts=row.attempts,
        raw_columns=None,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )
