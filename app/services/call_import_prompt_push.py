"""Compose reviewed prompt suggestions and push them to a live voice agent."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.auth.principal import Principal
from app.models.database import (
    CallImport,
    CallImportEvaluation,
    Integration,
    PromptPartial,
    PromptPartialVersion,
    PromptPush,
)
from app.models.schemas import AgentFlowGraph
from app.services.imported_agent_constants import AGENT_PROVIDER_PROMPT_TAG_PREFIX
from app.services.voice_providers.prompt_sync import (
    build_voice_provider_from_integration,
    fetch_provider_prompt,
)

CONFIRM_PHRASE = "confirm"
VOICE_PUSH_PLATFORMS = {"elevenlabs", "vapi", "retell"}


class PromptPushError(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


def normalize_prompt(text: Optional[str]) -> str:
    lines = (text or "").replace("\r\n", "\n").split("\n")
    return "\n".join(line.rstrip() for line in lines).strip()


def applied_suggestion_text(item: Dict[str, Any]) -> str:
    edited = item.get("edited_text")
    if isinstance(edited, str) and edited.strip():
        return edited
    suggested = item.get("suggested_text")
    return suggested if isinstance(suggested, str) else ""


def compose_accepted_prompt(base: str, suggestions: List[Any]) -> str:
    text = base or ""
    for item in suggestions:
        if not isinstance(item, dict) or item.get("review_status") != "accepted":
            continue
        replacement = applied_suggestion_text(item).strip()
        if not replacement:
            continue
        anchor = item.get("anchor_excerpt") or ""
        if item.get("change_type") == "edit" and isinstance(anchor, str) and anchor and anchor in text:
            text = text.replace(anchor, replacement, 1)
            continue
        text = text.rstrip() + "\n\n" + replacement + "\n"
    return text


def review_counts(suggestions: List[Any]) -> Tuple[int, int, int]:
    accepted = rejected = pending = 0
    for item in suggestions:
        if not isinstance(item, dict):
            continue
        status = item.get("review_status") or "pending"
        if status == "accepted":
            accepted += 1
        elif status == "rejected":
            rejected += 1
        else:
            pending += 1
    return accepted, rejected, pending


def _suggestions(evaluation: CallImportEvaluation) -> List[Any]:
    raw = evaluation.prompt_improvements if isinstance(evaluation.prompt_improvements, dict) else {}
    items = raw.get("suggestions")
    return items if isinstance(items, list) else []


def _compose_base_prompt(evaluation: CallImportEvaluation, partial_content: str) -> str:
    raw = evaluation.prompt_improvements if isinstance(evaluation.prompt_improvements, dict) else {}
    frozen = raw.get("compose_base_prompt")
    if isinstance(frozen, str):
        return frozen
    return partial_content or ""


def mark_prompt_improvements_applied(
    evaluation: CallImportEvaluation,
    applied_content: str,
) -> None:
    raw = (
        dict(evaluation.prompt_improvements)
        if isinstance(evaluation.prompt_improvements, dict)
        else {}
    )
    suggestions = list(raw.get("suggestions") or [])
    for item in suggestions:
        if isinstance(item, dict) and item.get("review_status") == "accepted":
            item["review_status"] = "applied"
    raw["suggestions"] = suggestions
    raw["compose_base_prompt"] = applied_content
    evaluation.prompt_improvements = raw
    flag_modified(evaluation, "prompt_improvements")


def _require_review(_evaluation: CallImportEvaluation) -> bool:
    return True


def set_suggestion_review(
    evaluation: CallImportEvaluation,
    suggestion_id: str,
    review_status: str,
    edited_text: Optional[str],
) -> None:
    raw = dict(evaluation.prompt_improvements or {})
    suggestions = list(raw.get("suggestions") or [])
    found = False
    for item in suggestions:
        if isinstance(item, dict) and item.get("id") == suggestion_id:
            item["review_status"] = review_status
            if edited_text is not None:
                item["edited_text"] = edited_text
            found = True
            break
    if not found:
        raise PromptPushError(404, "Suggestion not found")
    raw["suggestions"] = suggestions
    evaluation.prompt_improvements = raw
    flag_modified(evaluation, "prompt_improvements")


def single_platform_agent(call_import: CallImport) -> Dict[str, Any]:
    if getattr(call_import, "source_format", None) != "platform":
        raise PromptPushError(400, "Push is only available for a platform import.")
    if not call_import.voice_integration_id:
        raise PromptPushError(400, "This import has no voice integration to push to.")
    filters = call_import.platform_filters if isinstance(call_import.platform_filters, dict) else {}
    if (filters.get("medium") or "").lower() == "chat" or getattr(call_import, "content_modality", None) == "chat":
        raise PromptPushError(400, "Chat agents are not updated from this screen.")
    agents = filters.get("agents") if isinstance(filters.get("agents"), list) else []
    ids = filters.get("agent_ids") if isinstance(filters.get("agent_ids"), list) else []
    if len(agents) == 1 and isinstance(agents[0], dict) and agents[0].get("id"):
        agent = agents[0]
    elif len(ids) == 1 and ids[0]:
        agent = {"id": str(ids[0]), "name": str(ids[0])}
    else:
        raise PromptPushError(
            400,
            "Push requires one specific agent. Imports of all agents cannot be pushed.",
        )
    if (agent.get("medium") or "").lower() == "chat":
        raise PromptPushError(400, "Chat agents are not updated from this screen.")
    return agent


def _actor_label(principal: Optional[Principal]) -> Optional[str]:
    if principal is None:
        return None
    if principal.email:
        return principal.email
    if principal.user_id is not None:
        return str(principal.user_id)
    return None


def _platform_key(integration: Integration) -> str:
    platform = integration.platform.value if hasattr(integration.platform, "value") else integration.platform
    return str(platform or "").lower()


def _load_integration(db: Session, integration_id: UUID, organization_id: UUID) -> Integration:
    integration = (
        db.query(Integration)
        .filter(Integration.id == integration_id, Integration.organization_id == organization_id)
        .first()
    )
    if integration is None:
        raise PromptPushError(404, "Voice integration not found")
    if _platform_key(integration) not in VOICE_PUSH_PLATFORMS:
        raise PromptPushError(400, "Only ElevenLabs, Vapi, and Retell agents can be updated.")
    return integration


def _parse_provider_link_tag(tag: str) -> Optional[Tuple[UUID, str]]:
    if not isinstance(tag, str) or not tag.startswith(AGENT_PROVIDER_PROMPT_TAG_PREFIX):
        return None
    rest = tag[len(AGENT_PROVIDER_PROMPT_TAG_PREFIX) :]
    integration_raw, agent_id = rest.split(":", 1) if ":" in rest else ("", "")
    agent_id = agent_id.strip()
    if not integration_raw or not agent_id:
        return None
    try:
        return UUID(integration_raw.strip()), agent_id
    except (TypeError, ValueError):
        return None


def resolve_push_target(
    db: Session,
    partial: PromptPartial,
) -> Tuple[Integration, str, Optional[str]]:
    """Integration + external agent id from last live push or import link tags."""
    row = (
        db.query(PromptPush)
        .filter(
            PromptPush.prompt_partial_id == partial.id,
            PromptPush.integration_id.isnot(None),
            PromptPush.status == "pushed",
        )
        .order_by(PromptPush.created_at.desc())
        .first()
    )
    if row is not None and row.integration_id:
        integration = _load_integration(db, row.integration_id, partial.organization_id)
        return integration, row.external_agent_id, row.external_agent_name

    for tag in partial.tags or []:
        parsed = _parse_provider_link_tag(tag)
        if parsed is None:
            continue
        integration_id, external_agent_id = parsed
        integration = _load_integration(db, integration_id, partial.organization_id)
        return integration, external_agent_id, partial.name

    raise PromptPushError(
        400,
        "No live agent is linked to this partial. Use a single-agent platform import.",
    )


def _write_version(
    db: Session,
    partial: PromptPartial,
    content: str,
    change_summary: str,
    created_by: Optional[str],
) -> int:
    if normalize_prompt(content) == normalize_prompt(partial.content):
        return partial.current_version
    new_version_num = partial.current_version + 1
    db.add(
        PromptPartialVersion(
            prompt_partial_id=partial.id,
            workspace_id=partial.workspace_id,
            version=new_version_num,
            content=content,
            change_summary=change_summary,
            created_by=created_by,
        )
    )
    partial.content = content
    partial.current_version = new_version_num
    if isinstance(partial.agent_flowchart, dict) and partial.agent_flowchart.get("nodes"):
        try:
            from app.services.agent_flowchart import strip_node_prompt_mappings

            graph = AgentFlowGraph.model_validate(partial.agent_flowchart)
            partial.agent_flowchart = strip_node_prompt_mappings(graph).model_dump(mode="json")
            flag_modified(partial, "agent_flowchart")
        except Exception:
            pass
    return new_version_num


def _record_push(
    db: Session,
    *,
    partial: PromptPartial,
    version: int,
    provider: str,
    external_agent_id: str,
    external_agent_name: Optional[str],
    integration_id: Optional[UUID],
    evaluation_id: Optional[UUID],
    pushed_by: Optional[str],
    status: str,
    error_message: Optional[str],
) -> PromptPush:
    row = PromptPush(
        organization_id=partial.organization_id,
        workspace_id=partial.workspace_id,
        prompt_partial_id=partial.id,
        prompt_version=version,
        provider=provider,
        external_agent_id=external_agent_id,
        external_agent_name=external_agent_name,
        integration_id=integration_id,
        evaluation_id=evaluation_id,
        pushed_by=pushed_by,
        status=status,
        error_message=(error_message or "")[:500] or None,
    )
    db.add(row)
    return row


def _push_text(
    db: Session,
    *,
    partial: PromptPartial,
    integration: Integration,
    external_agent_id: str,
    external_agent_name: Optional[str],
    expected_base: str,
    next_content: str,
    change_summary: str,
    evaluation_id: Optional[UUID],
    principal: Optional[Principal],
) -> PromptPush:
    provider_key = _platform_key(integration)
    actor = _actor_label(principal)
    if normalize_prompt(next_content) == normalize_prompt(expected_base):
        raise PromptPushError(400, "Nothing accepted to push.")
    try:
        live = fetch_provider_prompt(integration, external_agent_id)
    except Exception as exc:
        raise PromptPushError(502, f"Could not read the live prompt: {exc}") from exc
    if live is None:
        raise PromptPushError(409, "Could not read the live prompt, so it was not overwritten.")
    if normalize_prompt(live) != normalize_prompt(expected_base):
        raise PromptPushError(
            409,
            "The live agent prompt no longer matches the prompt that was reviewed. Refresh the agent prompt and review again.",
        )
    provider = build_voice_provider_from_integration(integration)
    try:
        provider.update_agent_prompt(external_agent_id, next_content)
    except Exception as exc:
        _record_push(
            db,
            partial=partial,
            version=partial.current_version,
            provider=provider_key,
            external_agent_id=external_agent_id,
            external_agent_name=external_agent_name,
            integration_id=integration.id,
            evaluation_id=evaluation_id,
            pushed_by=actor,
            status="failed",
            error_message=str(exc),
        )
        db.commit()
        raise PromptPushError(502, f"The provider rejected the prompt: {exc}") from exc
    version = _write_version(db, partial, next_content, change_summary, actor)
    row = _record_push(
        db,
        partial=partial,
        version=version,
        provider=provider_key,
        external_agent_id=external_agent_id,
        external_agent_name=external_agent_name,
        integration_id=integration.id,
        evaluation_id=evaluation_id,
        pushed_by=actor,
        status="pushed",
        error_message=None,
    )
    db.commit()
    db.refresh(row)
    return row


def preview_evaluation_push(
    db: Session,
    evaluation: CallImportEvaluation,
    call_import: CallImport,
    organization_id: UUID,
    workspace_id: UUID,
) -> Dict[str, Any]:
    suggestions = _suggestions(evaluation)
    accepted, rejected, pending = review_counts(suggestions)
    require_review = _require_review(evaluation)
    partial, relinked = resolve_imported_partial_for_evaluation(
        db, evaluation, organization_id, workspace_id, call_import
    )
    if relinked:
        db.commit()
        db.refresh(partial)
    base = _compose_base_prompt(evaluation, partial.content or "")
    composed = compose_accepted_prompt(base, suggestions)
    block_reason = None
    provider = None
    agent_id = None
    agent_name = None
    live_prompt: Optional[str] = None
    saved_matches_live: Optional[bool] = None
    integration = None
    try:
        agent = single_platform_agent(call_import)
        integration = _load_integration(db, call_import.voice_integration_id, organization_id)
        provider = _platform_key(integration)
        agent_id = str(agent.get("id"))
        agent_name = agent.get("name") or agent_id
    except PromptPushError as exc:
        block_reason = exc.detail
    if block_reason is None and integration is not None and agent_id:
        try:
            live_prompt = fetch_provider_prompt(integration, agent_id) or ""
            saved_matches_live = normalize_prompt(live_prompt) == normalize_prompt(base)
            if not saved_matches_live:
                block_reason = (
                    "Saved partial differs from the provider. Save to Partials still works; "
                    "use Push live in Prompt Partials to update the agent, or refresh from the provider first."
                )
        except Exception as exc:
            block_reason = f"Could not read the live prompt: {exc}"
    save_block_reason = None
    if require_review and pending:
        save_block_reason = "Accept or reject every suggestion before saving."
    elif accepted == 0:
        save_block_reason = "Accept at least one change before saving."
    elif normalize_prompt(composed) == normalize_prompt(base):
        save_block_reason = "Accepted changes do not alter the prompt."

    live_block_reason = save_block_reason
    if live_block_reason is None and block_reason:
        live_block_reason = block_reason
    if live_block_reason is None and saved_matches_live is False:
        live_block_reason = (
            "Saved partial differs from the provider. Push live from Prompt Partials after saving, "
            "or align the saved copy from the provider before updating live from this evaluation."
        )

    content_changes = normalize_prompt(composed) != normalize_prompt(base)
    current_version = int(getattr(partial, "current_version", None) or 1)
    next_version = current_version + 1 if content_changes else current_version
    return {
        "base_prompt": base,
        "live_prompt": live_prompt or "",
        "composed_prompt": composed,
        "saved_prompt_matches_live": saved_matches_live,
        "imported_agent_name": getattr(partial, "name", None),
        "imported_agent_id": str(partial.id),
        "relinked_imported_agent": relinked,
        "partial_current_version": current_version,
        "partial_next_version": next_version,
        "accepted_count": accepted,
        "rejected_count": rejected,
        "pending_count": pending,
        "require_review": require_review,
        "can_save_version": save_block_reason is None,
        "can_push": live_block_reason is None,
        "block_reason": live_block_reason,
        "save_block_reason": save_block_reason,
        "provider": provider,
        "external_agent_id": agent_id,
        "external_agent_name": agent_name,
    }


def resolve_imported_partial_for_evaluation(
    db: Session,
    evaluation: CallImportEvaluation,
    organization_id: UUID,
    workspace_id: UUID,
    call_import: Optional[CallImport] = None,
    principal: Optional[Principal] = None,
) -> Tuple[PromptPartial, bool]:
    """Resolve the evaluation's imported-agent partial, recreating from the import if deleted."""
    from app.services.platform_import_imported_agent import (
        relink_evaluation_imported_agent,
        resolve_imported_agent_for_call_import,
    )

    raw = evaluation.prompt_improvements if isinstance(evaluation.prompt_improvements, dict) else {}
    stored_id = raw.get("imported_agent_id")
    partial: Optional[PromptPartial] = None
    relinked = False

    if stored_id:
        try:
            partial_uuid = UUID(str(stored_id))
        except (TypeError, ValueError):
            partial_uuid = None
        if partial_uuid:
            partial = (
                db.query(PromptPartial)
                .filter(
                    PromptPartial.id == partial_uuid,
                    PromptPartial.organization_id == organization_id,
                    PromptPartial.workspace_id == workspace_id,
                )
                .first()
            )

    if partial is None and call_import is not None:
        partial = resolve_imported_agent_for_call_import(db, call_import, principal)
        if partial is not None:
            relink_evaluation_imported_agent(evaluation, partial)
            relinked = True

    if partial is None and not stored_id:
        raise PromptPushError(400, "Generate prompt suggestions before pushing.")
    if partial is None:
        raise PromptPushError(
            404,
            "Imported agent prompt not found and could not be recreated from this import.",
        )

    if not relinked and stored_id and str(partial.id) != str(stored_id):
        relink_evaluation_imported_agent(evaluation, partial)
        relinked = True

    return partial, relinked


def _imported_partial(
    db: Session,
    evaluation: CallImportEvaluation,
    organization_id: UUID,
    workspace_id: UUID,
    call_import: Optional[CallImport] = None,
    principal: Optional[Principal] = None,
) -> PromptPartial:
    partial, relinked = resolve_imported_partial_for_evaluation(
        db, evaluation, organization_id, workspace_id, call_import, principal
    )
    if relinked:
        db.commit()
        db.refresh(partial)
    return partial


def save_evaluation_prompt_version(
    db: Session,
    evaluation: CallImportEvaluation,
    call_import: CallImport,
    organization_id: UUID,
    workspace_id: UUID,
    confirm: str,
    principal: Optional[Principal],
) -> PromptPartial:
    if confirm != CONFIRM_PHRASE:
        raise PromptPushError(400, "Type confirm to save the prompt version.")
    preview = preview_evaluation_push(db, evaluation, call_import, organization_id, workspace_id)
    if not preview.get("can_save_version"):
        raise PromptPushError(
            400, preview.get("save_block_reason") or "This prompt cannot be saved."
        )
    partial = _imported_partial(
        db, evaluation, organization_id, workspace_id, call_import, principal
    )
    label = evaluation.name or str(evaluation.id)
    actor = _actor_label(principal)
    _write_version(
        db,
        partial,
        preview["composed_prompt"],
        f"Saved from evaluation {label} (push later)",
        actor,
    )
    mark_prompt_improvements_applied(evaluation, preview["composed_prompt"])
    db.commit()
    db.refresh(partial)
    return partial


def push_evaluation_prompt(
    db: Session,
    evaluation: CallImportEvaluation,
    call_import: CallImport,
    organization_id: UUID,
    workspace_id: UUID,
    confirm: str,
    principal: Optional[Principal],
    *,
    push_to_live: bool = True,
) -> PromptPush:
    if confirm != CONFIRM_PHRASE:
        raise PromptPushError(400, "Type confirm to push the live prompt.")
    if not push_to_live:
        partial = save_evaluation_prompt_version(
            db, evaluation, call_import, organization_id, workspace_id, confirm, principal
        )
        row = PromptPush(
            organization_id=partial.organization_id,
            workspace_id=partial.workspace_id,
            prompt_partial_id=partial.id,
            prompt_version=partial.current_version,
            provider="saved_only",
            external_agent_id="n/a",
            external_agent_name=None,
            integration_id=None,
            evaluation_id=evaluation.id,
            pushed_by=_actor_label(principal),
            status="saved_only",
            error_message=None,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row
    preview = preview_evaluation_push(db, evaluation, call_import, organization_id, workspace_id)
    if not preview["can_push"]:
        raise PromptPushError(400, preview["block_reason"] or "This prompt cannot be pushed.")
    partial = _imported_partial(
        db, evaluation, organization_id, workspace_id, call_import, principal
    )
    agent = single_platform_agent(call_import)
    integration = _load_integration(db, call_import.voice_integration_id, organization_id)
    label = evaluation.name or str(evaluation.id)
    row = _push_text(
        db,
        partial=partial,
        integration=integration,
        external_agent_id=str(agent.get("id")),
        external_agent_name=agent.get("name") or str(agent.get("id")),
        expected_base=partial.content or "",
        next_content=preview["composed_prompt"],
        change_summary=f"Pushed from evaluation {label}",
        evaluation_id=evaluation.id,
        principal=principal,
    )
    mark_prompt_improvements_applied(evaluation, preview["composed_prompt"])
    db.commit()
    return row


def _version_row(db: Session, partial: PromptPartial, version_number: int) -> PromptPartialVersion:
    version = (
        db.query(PromptPartialVersion)
        .filter(
            PromptPartialVersion.prompt_partial_id == partial.id,
            PromptPartialVersion.version == version_number,
        )
        .first()
    )
    if version is None:
        raise PromptPushError(404, "Prompt version not found")
    return version


def preview_version_push(
    db: Session,
    partial: PromptPartial,
    version_number: int,
    organization_id: UUID,
) -> Dict[str, Any]:
    version = _version_row(db, partial, version_number)
    integration, external_agent_id, external_agent_name = resolve_push_target(db, partial)
    try:
        live = fetch_provider_prompt(integration, external_agent_id) or ""
    except Exception as exc:
        raise PromptPushError(502, f"Could not read the live prompt: {exc}") from exc
    block_reason = None
    drift_warning = None
    if normalize_prompt(version.content) == normalize_prompt(live):
        block_reason = "This version already matches the live provider prompt."
    elif normalize_prompt(partial.content or "") != normalize_prompt(live):
        drift_warning = (
            f"Provider prompt differs from your current saved copy (v{partial.current_version}). "
            "This push will replace the live agent with the selected version."
        )
    is_current = version_number == partial.current_version
    return {
        "live_prompt": live,
        "version_prompt": version.content,
        "version": version.version,
        "provider": _platform_key(integration),
        "external_agent_id": external_agent_id,
        "external_agent_name": external_agent_name,
        "can_push": block_reason is None,
        "block_reason": block_reason,
        "drift_warning": drift_warning,
        "is_current_version": is_current,
    }


def push_version_rollback(
    db: Session,
    partial: PromptPartial,
    version_number: int,
    organization_id: UUID,
    confirm: str,
    principal: Optional[Principal],
) -> PromptPush:
    if confirm != CONFIRM_PHRASE:
        raise PromptPushError(400, "Type confirm to push the live prompt.")
    preview = preview_version_push(db, partial, version_number, organization_id)
    if not preview["can_push"]:
        raise PromptPushError(400, preview["block_reason"] or "This version cannot be pushed.")
    integration, external_agent_id, external_agent_name = resolve_push_target(db, partial)
    try:
        live = fetch_provider_prompt(integration, external_agent_id)
    except Exception as exc:
        raise PromptPushError(502, f"Could not read the live prompt: {exc}") from exc
    if live is None:
        raise PromptPushError(409, "Could not read the live prompt, so it was not overwritten.")
    live_norm = normalize_prompt(live)
    next_norm = normalize_prompt(preview["version_prompt"])
    if next_norm == live_norm:
        raise PromptPushError(400, "This version already matches the live provider prompt.")
    summary = (
        f"Pushed v{version_number} to live agent"
        if preview.get("is_current_version")
        else f"Pushed v{version_number} to live (from v{partial.current_version})"
    )
    return _push_text(
        db,
        partial=partial,
        integration=integration,
        external_agent_id=external_agent_id,
        external_agent_name=external_agent_name,
        expected_base=live,
        next_content=preview["version_prompt"],
        change_summary=summary,
        evaluation_id=None,
        principal=principal,
    )
