"""Auto-link platform historical imports to imported-agent prompt partials."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple
from uuid import UUID

from sqlalchemy.orm import Session

from sqlalchemy.orm.attributes import flag_modified

from app.models.database import CallImport, CallImportEvaluation, Integration, PromptPartial, PromptPartialVersion
from app.services.imported_agent_constants import (
    AGENT_PROVIDER_PROMPT_TAG_PREFIX,
    IMPORTED_AGENT_TAG,
)
from app.services.call_import_prompt_push import fetch_provider_prompt

logger = logging.getLogger(__name__)

IMPORTED_AGENT_PARTIAL_FILTER_KEY = "imported_agent_partial_id"
CALL_IMPORT_TAG_PREFIX = "__call_import__:"


def platform_voice_agent_link_tag(voice_integration_id: UUID, external_agent_id: str) -> str:
    return f"{AGENT_PROVIDER_PROMPT_TAG_PREFIX}{voice_integration_id}:{external_agent_id}"


def call_import_tag(call_import_id: UUID) -> str:
    return f"{CALL_IMPORT_TAG_PREFIX}{call_import_id}"


def _single_voice_agent_ref(call_import: CallImport) -> Optional[Tuple[str, str]]:
    if getattr(call_import, "source_format", None) != "platform":
        return None
    raw = call_import.platform_filters if isinstance(call_import.platform_filters, dict) else {}
    if (raw.get("medium") or "").strip().lower() == "chat":
        return None
    agents = raw.get("agents") if isinstance(raw.get("agents"), list) else []
    picked: Optional[Dict[str, Any]] = None
    for item in agents:
        if not isinstance(item, dict):
            continue
        agent_id = str(item.get("id") or "").strip()
        if not agent_id:
            continue
        medium = (item.get("medium") or raw.get("medium") or "voice") or "voice"
        if str(medium).strip().lower() == "chat":
            continue
        if picked is not None:
            return None
        picked = {"id": agent_id, "name": str(item.get("name") or agent_id)}
    if picked is not None:
        return picked["id"], picked["name"]
    ids = raw.get("agent_ids") if isinstance(raw.get("agent_ids"), list) else []
    if len(ids) != 1:
        return None
    agent_id = str(ids[0] or "").strip()
    if not agent_id:
        return None
    return agent_id, agent_id


def linked_partial_id(call_import: CallImport) -> Optional[UUID]:
    raw = call_import.platform_filters if isinstance(call_import.platform_filters, dict) else {}
    value = raw.get(IMPORTED_AGENT_PARTIAL_FILTER_KEY)
    if not value:
        return None
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


def _find_partial_by_link_tag(
    db: Session,
    organization_id: UUID,
    workspace_id: UUID,
    link_tag: str,
) -> Optional[PromptPartial]:
    from sqlalchemy import String, cast
    from sqlalchemy.dialects.postgresql import JSONB

    base = db.query(PromptPartial).filter(
        PromptPartial.organization_id == organization_id,
        PromptPartial.workspace_id == workspace_id,
    )
    dialect = db.get_bind().dialect.name if db.get_bind() is not None else "postgresql"
    if dialect == "sqlite":
        needle = f'"{link_tag}"'
        return base.filter(cast(PromptPartial.tags, String).like(f"%{needle}%")).first()
    tags_col = cast(PromptPartial.tags, JSONB)
    return base.filter(tags_col.contains(cast([link_tag], JSONB))).first()


def _principal_label(principal) -> Optional[str]:
    if principal is None:
        return None
    email = getattr(principal, "email", None)
    if email:
        return str(email)
    subject = getattr(principal, "subject", None)
    return str(subject) if subject else None


def _import_batch_label(call_import: CallImport) -> str:
    label = (call_import.original_filename or "").strip()
    if label:
        return label[:120]
    return f"Import {str(call_import.id)[:8]}"


def imported_agent_partial_name(agent_name: str, call_import: CallImport) -> str:
    return f"{agent_name} · {_import_batch_label(call_import)}"


def _persist_import_partial_link(call_import: CallImport, partial: PromptPartial) -> None:
    filters = dict(call_import.platform_filters or {})
    filters[IMPORTED_AGENT_PARTIAL_FILTER_KEY] = str(partial.id)
    call_import.platform_filters = filters
    flag_modified(call_import, "platform_filters")


def ensure_imported_agent_for_platform_import(
    db: Session,
    call_import: CallImport,
    principal=None,
    *,
    fetch_live_prompt: bool = True,
) -> Optional[PromptPartial]:
    """Create one imported-agent partial per platform call import (single voice agent)."""
    if not call_import.voice_integration_id:
        return None
    agent_ref = _single_voice_agent_ref(call_import)
    if agent_ref is None:
        return None

    organization_id = call_import.organization_id
    workspace_id = call_import.workspace_id
    external_agent_id, agent_name = agent_ref
    provider_link_tag = platform_voice_agent_link_tag(
        call_import.voice_integration_id, external_agent_id
    )
    import_tag = call_import_tag(call_import.id)

    partial: Optional[PromptPartial] = None
    existing_id = linked_partial_id(call_import)
    if existing_id:
        partial = (
            db.query(PromptPartial)
            .filter(
                PromptPartial.id == existing_id,
                PromptPartial.organization_id == organization_id,
                PromptPartial.workspace_id == workspace_id,
            )
            .first()
        )
    if partial is None:
        partial = _find_partial_by_link_tag(db, organization_id, workspace_id, import_tag)

    if partial is not None:
        _persist_import_partial_link(call_import, partial)
        return partial

    live_prompt = ""
    if fetch_live_prompt:
        integration = (
            db.query(Integration).filter(Integration.id == call_import.voice_integration_id).first()
        )
        if integration is not None:
            try:
                live_prompt = fetch_provider_prompt(integration, external_agent_id) or ""
            except Exception as exc:
                logger.warning(
                    "Could not fetch live prompt for platform import %s: %s",
                    call_import.id,
                    exc,
                )

    actor = _principal_label(principal)
    import_label = _import_batch_label(call_import)
    tags = [IMPORTED_AGENT_TAG, provider_link_tag, import_tag]
    partial = PromptPartial(
        organization_id=organization_id,
        workspace_id=workspace_id,
        name=imported_agent_partial_name(agent_name, call_import),
        description=None,
        content=live_prompt,
        tags=tags,
        current_version=1,
        created_by=actor,
    )
    db.add(partial)
    db.flush()
    db.add(
        PromptPartialVersion(
            prompt_partial_id=partial.id,
            workspace_id=workspace_id,
            version=1,
            content=live_prompt,
            change_summary="Platform import snapshot (live provider prompt)",
            created_by=actor,
        )
    )
    _persist_import_partial_link(call_import, partial)
    return partial


def relink_evaluation_imported_agent(
    evaluation: CallImportEvaluation,
    partial: PromptPartial,
) -> None:
    """Point evaluation prompt improvements at the current imported-agent partial."""
    raw = (
        dict(evaluation.prompt_improvements)
        if isinstance(evaluation.prompt_improvements, dict)
        else {}
    )
    raw["imported_agent_id"] = str(partial.id)
    if partial.name:
        raw["imported_agent_name"] = partial.name
    evaluation.prompt_improvements = raw
    flag_modified(evaluation, "prompt_improvements")


def resolve_imported_agent_for_call_import(
    db: Session,
    call_import: CallImport,
    principal=None,
) -> Optional[PromptPartial]:
    partial_id = linked_partial_id(call_import)
    if partial_id:
        partial = (
            db.query(PromptPartial)
            .filter(
                PromptPartial.id == partial_id,
                PromptPartial.organization_id == call_import.organization_id,
                PromptPartial.workspace_id == call_import.workspace_id,
            )
            .first()
        )
        if partial is not None:
            return partial
    return ensure_imported_agent_for_platform_import(db, call_import, principal)
