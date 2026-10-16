"""Platform historical call import API."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

import requests
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import settings
from app.core.encryption import decrypt_api_key
from app.core.auth import Principal, get_principal
from app.database import get_db
from app.dependencies import (
    get_api_key,
    get_organization_id,
    get_workspace_id,
    require_enterprise_feature,
)
from app.models.database import CallImport, CallImportDiscoverySlice, Integration
from app.models.enums import CallImportStatus

logger = logging.getLogger(__name__)
from app.services.call_imports.audit import stamp_call_import_actor
from app.services.call_imports.platform_discovery import create_discovery_slices
from app.services.call_imports.platform_import_progress import build_platform_import_progress
from app.services.voice_providers.historical.base import get_historical_adapter

router = APIRouter(
    prefix="/call-imports/platform",
    tags=["call-imports"],
    dependencies=[Depends(require_enterprise_feature("call_imports"))],
)


class PlatformImportAgentInput(BaseModel):
    id: str
    name: str
    medium: Optional[str] = None


class PlatformImportFilters(BaseModel):
    agent_ids: List[str] = Field(default_factory=list)
    agents: List[PlatformImportAgentInput] = Field(default_factory=list)
    min_duration_seconds: float = 5.0
    call_statuses: Optional[List[str]] = None
    speed: str = "standard"
    import_provider_transcript: bool = Field(
        default=True,
        description="Persist the voice platform's production transcript on each row (recommended for ElevenLabs).",
    )
    medium: Optional[str] = Field(
        default=None,
        description="voice or chat. Chat imports the transcript only and does not download audio.",
    )


class PlatformCallImportCreate(BaseModel):
    voice_integration_id: UUID
    window_start: datetime
    window_end: datetime
    window_timezone: str = "UTC"
    name: Optional[str] = None
    dataset: Optional[str] = None
    tag_ids: List[UUID] = Field(default_factory=list)
    filters: PlatformImportFilters = Field(default_factory=PlatformImportFilters)
    max_calls: Optional[int] = None


class PlatformCallImportPreviewRequest(PlatformCallImportCreate):
    pass


class PlatformAgentOption(BaseModel):
    id: str
    name: str
    medium: Optional[str] = None


def _resolve_voice_integration(
    db: Session,
    organization_id: UUID,
    integration_id: UUID,
) -> Integration:
    row = (
        db.query(Integration)
        .filter(
            Integration.id == integration_id,
            Integration.organization_id == organization_id,
            Integration.is_active.is_(True),
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Integration not found")
    return row


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _clamp_window_end(window_end: datetime) -> datetime:
    latest = datetime.now(timezone.utc) - timedelta(minutes=15)
    return min(_as_utc(window_end), latest)


def _resolve_platform_max_calls(requested: Optional[int]) -> Optional[int]:
    default_limit = int(settings.PLATFORM_IMPORT_MAX_CALLS_DEFAULT or 0)
    hard_limit = int(settings.PLATFORM_IMPORT_MAX_CALLS_CAP or 0)
    max_calls = requested
    if max_calls is None and default_limit > 0:
        max_calls = default_limit
    if hard_limit > 0:
        if max_calls is None or int(max_calls) <= 0:
            max_calls = hard_limit
        else:
            max_calls = min(int(max_calls), hard_limit)
    return max_calls


def _raise_for_voice_provider_http(err: requests.HTTPError) -> None:
    response = err.response
    code = response.status_code if response is not None else 502
    if code in (401, 403):
        raise HTTPException(
            status_code=code,
            detail="Voice platform rejected the API credential. Update the integration key and try again.",
        ) from err
    if code == 429:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Voice platform rate limit reached. Try again in a few minutes.",
        ) from err
    detail = f"Voice platform request failed (HTTP {code})."
    if response is not None and response.text:
        snippet = response.text.strip().replace("\n", " ")[:240]
        if snippet:
            detail = f"{detail} {snippet}"
    raise HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail=detail,
    ) from err


@router.get("/agents", response_model=List[PlatformAgentOption])
async def list_platform_agents(
    integration_id: UUID = Query(...),
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
) -> List[PlatformAgentOption]:
    del api_key
    if not settings.PLATFORM_IMPORT_FEATURE_ENABLED:
        raise HTTPException(status_code=404, detail="Platform imports are not enabled")
    integration = _resolve_voice_integration(db, organization_id, integration_id)
    from app.services.voice_providers import get_voice_provider

    api_key = decrypt_api_key(integration.api_key)
    provider_cls = get_voice_provider(integration.platform)
    try:
        if integration.platform.lower() == "elevenlabs":
            client = provider_cls(api_key, base_url=integration.api_base_url)
        else:
            client = provider_cls(api_key)
        agents = _list_import_agents(client, integration.platform)
    except requests.HTTPError as err:
        _raise_for_voice_provider_http(err)
    except ValueError as err:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(err) or "Could not list agents for this credential.",
        ) from err
    return agents


def _list_import_agents(client: Any, platform: str) -> List[PlatformAgentOption]:
    """Voice agents, plus chat agents when the provider keeps those separate."""
    platform_key = (platform or "").lower()
    if platform_key == "retell":
        voice = _agent_options(client.list_agents(), medium="voice")
        chat: List[PlatformAgentOption] = []
        try:
            chat = _agent_options(client.list_chat_agents(), medium="chat")
        except (ValueError, requests.HTTPError):
            chat = []
        seen = {row.id for row in voice}
        return voice + [row for row in chat if row.id not in seen]
    return _agent_options(client.list_agents(), medium=None)


def _agent_options(
    agents: List[Dict[str, Any]],
    *,
    medium: Optional[str],
) -> List[PlatformAgentOption]:
    options: List[PlatformAgentOption] = []
    for agent in agents:
        agent_id = str(agent.get("id") or "").strip()
        if not agent_id:
            continue
        options.append(
            PlatformAgentOption(
                id=agent_id,
                name=str(agent.get("name") or agent_id),
                medium=medium,
            )
        )
    return options


@router.post("/preview")
async def preview_platform_import(
    payload: PlatformCallImportPreviewRequest,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    del api_key
    integration = _resolve_voice_integration(db, organization_id, payload.voice_integration_id)
    adapter = get_historical_adapter(integration)
    start = _as_utc(payload.window_start)
    end = _clamp_window_end(payload.window_end)
    if end <= start:
        raise HTTPException(
            status_code=400,
            detail=(
                "window_end must be after window_start. "
                "The import window cannot end within the last 15 minutes."
            ),
        )
    from app.services.voice_providers.historical.base import TimeSlice

    agent = payload.filters.agent_ids[0] if payload.filters.agent_ids else None
    slice = TimeSlice(
        slice_id=0,
        slice_start=start,
        slice_end=end,
        agent_id=agent,
        medium=(payload.filters.medium or "").strip().lower() or None,
    )
    from app.services.call_imports.platform_discovery import plan_time_slices

    agent_ids = payload.filters.agent_ids or None
    discovery_slices = len(
        plan_time_slices(start, end, agent_ids)
    )
    max_pages = settings.PLATFORM_IMPORT_PREVIEW_COUNT_MAX_PAGES
    sample_cap = settings.PLATFORM_IMPORT_PREVIEW_SAMPLE_SIZE

    recordings_in_window = 0
    samples_out: List[Dict[str, Any]] = []
    cursor: Optional[str] = None
    pages_scanned = 0
    count_complete = True
    try:
        while pages_scanned < max_pages:
            items, cursor = adapter.list_page(slice, cursor, page_size=100)
            pages_scanned += 1
            recordings_in_window += len(items)
            for item in items:
                if len(samples_out) >= sample_cap:
                    continue
                samples_out.append(
                    {
                        "conversation_id": item.conversation_id,
                        "agent_id": item.agent_id,
                        "started_at": item.started_at.isoformat() if item.started_at else None,
                        "status": item.status,
                    }
                )
            if not cursor:
                break
        if cursor:
            count_complete = False
    except requests.HTTPError as err:
        _raise_for_voice_provider_http(err)

    return {
        "recordings_in_window": recordings_in_window,
        "recordings_count_complete": count_complete,
        "count_pages_scanned": pages_scanned,
        "discovery_slices": discovery_slices,
        "sample_count": len(samples_out),
        "samples": samples_out,
    }


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def create_platform_call_import(
    payload: PlatformCallImportCreate,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
) -> Dict[str, Any]:
    del api_key
    if idempotency_key:
        from app.workers.concurrency.platform_import_limits import read_create_idempotency

        existing_id = read_create_idempotency(workspace_id, idempotency_key)
        if existing_id:
            return {
                "id": existing_id,
                "status": "accepted",
                "discovery_status": None,
                "message": "Platform import already accepted.",
            }
    if not settings.PLATFORM_IMPORT_FEATURE_ENABLED:
        raise HTTPException(status_code=404, detail="Platform imports are not enabled")

    start = _as_utc(payload.window_start)
    end = _clamp_window_end(payload.window_end)
    integration = _resolve_voice_integration(db, organization_id, payload.voice_integration_id)
    platform = (integration.platform or "").lower()
    if platform not in {"elevenlabs", "vapi", "retell"}:
        raise HTTPException(status_code=400, detail="Unsupported platform for historical import")

    max_calls = _resolve_platform_max_calls(payload.max_calls)

    if end <= start:
        raise HTTPException(
            status_code=400,
            detail=(
                "window_end must be after window_start. "
                "The import window cannot end within the last 15 minutes."
            ),
        )
    import_name = (payload.name or "").strip()
    if not import_name:
        import_name = (
            f"{platform.title()} "
            f"{payload.window_start:%d %b %Y} – {end:%d %b %Y}"
        )

    call_import = CallImport(
        organization_id=organization_id,
        workspace_id=workspace_id,
        provider=platform,
        source_format="platform",
        voice_integration_id=integration.id,
        platform_filters=payload.filters.model_dump(),
        window_start=start,
        window_end=end,
        window_timezone=payload.window_timezone,
        discovery_status="queued",
        max_calls=max_calls,
        dataset=payload.dataset,
        status=CallImportStatus.PROCESSING,
        original_filename=import_name[:512],
        content_modality=(
            "chat" if (payload.filters.medium or "").strip().lower() == "chat" else None
        ),
    )
    stamp_call_import_actor(call_import, principal)
    from app.api.v1.routes.call_imports import _resolve_tags

    call_import.tags = _resolve_tags(db, organization_id, payload.tag_ids)
    db.add(call_import)
    db.flush()

    from app.services.platform_import_imported_agent import ensure_imported_agent_for_platform_import

    try:
        ensure_imported_agent_for_platform_import(db, call_import, principal)
    except Exception:
        logger.exception(
            "Failed to auto-link imported agent prompt for platform import %s",
            call_import.id,
        )

    agent_ids = payload.filters.agent_ids or None
    create_discovery_slices(db, call_import, agent_ids)
    db.commit()
    db.refresh(call_import)

    from app.workers.concurrency.fair_platform_import_dispatch import (
        _schedule_pending_slices_for_import,
    )

    _schedule_pending_slices_for_import(db, call_import.id, limit=2)

    if idempotency_key:
        from app.workers.concurrency.platform_import_limits import store_create_idempotency

        store_create_idempotency(workspace_id, idempotency_key, str(call_import.id))

    return {
        "id": str(call_import.id),
        "status": call_import.status.value,
        "discovery_status": call_import.discovery_status,
        "message": "Platform import accepted. Discovery runs in the background.",
    }


@router.get("/{call_import_id}/progress")
async def get_platform_import_progress(
    call_import_id: UUID,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    del api_key
    call_import = _get_platform_import(db, call_import_id, organization_id, workspace_id)
    payload = build_platform_import_progress(db, call_import)
    for key in ("window_start", "window_end", "updated_at", "last_progress_at"):
        val = payload.get(key)
        if val is not None and hasattr(val, "isoformat"):
            payload[key] = val.isoformat()
    return payload


@router.get("/diagnostics")
async def platform_import_diagnostics(
    api_key: str = Depends(get_api_key),
) -> Dict[str, Any]:
    del api_key
    from app.workers.concurrency.platform_import_limits import platform_import_runtime_stats

    return platform_import_runtime_stats()


@router.post("/{call_import_id}/pause")
async def pause_platform_import(
    call_import_id: UUID,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
) -> Dict[str, str]:
    del api_key
    call_import = _get_platform_import(db, call_import_id, organization_id, workspace_id)
    if call_import.status == CallImportStatus.DELETING:
        raise HTTPException(status_code=409, detail="Import is being deleted")
    call_import.paused_at = datetime.now(timezone.utc)
    call_import.pause_reason = "user_paused"
    from app.workers.concurrency.platform_import_limits import force_release_slice_lock

    slices = (
        db.query(CallImportDiscoverySlice)
        .filter(
            CallImportDiscoverySlice.call_import_id == call_import.id,
            CallImportDiscoverySlice.status.in_(("queued", "running")),
        )
        .all()
    )
    for slice_row in slices:
        force_release_slice_lock(call_import.id, slice_row.slice_id)
        slice_row.status = "pending"
    db.commit()
    return {"status": "paused"}


@router.post("/{call_import_id}/resume")
async def resume_platform_import(
    call_import_id: UUID,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
) -> Dict[str, str]:
    del api_key
    call_import = _get_platform_import(db, call_import_id, organization_id, workspace_id)
    if call_import.status == CallImportStatus.DELETING:
        raise HTTPException(status_code=409, detail="Import is being deleted")
    call_import.paused_at = None
    call_import.pause_reason = None
    db.commit()
    from app.workers.concurrency.fair_platform_import_dispatch import (
        schedule_fair_platform_import_dispatch,
        schedule_platform_discovery_bootstrap,
    )

    schedule_fair_platform_import_dispatch()
    schedule_platform_discovery_bootstrap()
    return {"status": "resumed"}


@router.post("/{call_import_id}/retry-discovery")
async def retry_platform_discovery(
    call_import_id: UUID,
    api_key: str = Depends(get_api_key),
    organization_id: UUID = Depends(get_organization_id),
    workspace_id: UUID = Depends(get_workspace_id),
    db: Session = Depends(get_db),
) -> Dict[str, str]:
    del api_key
    call_import = _get_platform_import(db, call_import_id, organization_id, workspace_id)
    if call_import.status == CallImportStatus.DELETING:
        raise HTTPException(status_code=409, detail="Import is being deleted")
    db.query(CallImportDiscoverySlice).filter(
        CallImportDiscoverySlice.call_import_id == call_import.id,
        CallImportDiscoverySlice.status == "failed",
    ).update({"status": "pending", "attempts": 0})
    call_import.discovery_status = "running"
    db.commit()
    from app.workers.concurrency.fair_platform_import_dispatch import (
        schedule_platform_discovery_bootstrap,
    )

    schedule_platform_discovery_bootstrap()
    return {"status": "accepted"}


def _get_platform_import(
    db: Session,
    call_import_id: UUID,
    organization_id: UUID,
    workspace_id: UUID,
) -> CallImport:
    call_import = (
        db.query(CallImport)
        .filter(
            CallImport.id == call_import_id,
            CallImport.organization_id == organization_id,
            CallImport.workspace_id == workspace_id,
            CallImport.source_format == "platform",
        )
        .first()
    )
    if call_import is None:
        raise HTTPException(status_code=404, detail="Platform import not found")
    return call_import
