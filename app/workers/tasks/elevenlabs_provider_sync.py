"""Celery tasks for ElevenLabs provider migration sync."""

from __future__ import annotations

import asyncio
import threading
import time
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from loguru import logger

from app.core.encryption import decrypt_api_key
from app.config import settings
from app.database import SessionLocal
from app.models.database import (
    Agent,
    CallRecording,
    CallRecordingSource,
    Integration,
    ProviderSyncJob,
    ProviderSyncJobError,
)
from app.models.enums import CallMediumEnum, CallTypeEnum, IntegrationPlatform
from app.services.observability.call_ingest import upsert_call_recording
from app.services.observability.elevenlabs_monitor_bridge import ElevenLabsMonitorBridge
from app.services.voice_providers import get_voice_provider
from app.services.voice_providers.prompt_sync import sync_provider_prompt
from app.workers.config import celery_app

_MONITOR_SEMAPHORE = threading.BoundedSemaphore(
    max(1, int(settings.ELEVENLABS_MONITOR_MAX_CONCURRENCY))
)


def _job_by_id(db, job_id: str) -> ProviderSyncJob:
    job = db.query(ProviderSyncJob).filter(ProviderSyncJob.id == UUID(job_id)).first()
    if not job:
        raise ValueError(f"Provider sync job not found: {job_id}")
    return job


def _mark_job(db, job: ProviderSyncJob, *, status: Optional[str] = None, phase: Optional[str] = None) -> None:
    if status:
        job.status = status
    if phase:
        job.phase = phase
    if status == "running" and not job.started_at:
        job.started_at = datetime.now(UTC)
    if status in {"completed", "failed", "cancelled"}:
        job.completed_at = datetime.now(UTC)
    db.commit()


def _is_job_cancelled(db, job_id: str) -> bool:
    row = (
        db.query(ProviderSyncJob.status)
        .filter(ProviderSyncJob.id == UUID(job_id))
        .first()
    )
    return bool(row and row[0] == "cancelled")


def _record_error(
    db,
    *,
    job: ProviderSyncJob,
    phase: str,
    error_message: str,
    provider_call_id: Optional[str] = None,
    provider_agent_id: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> None:
    row = ProviderSyncJobError(
        job_id=job.id,
        phase=phase,
        provider_call_id=provider_call_id,
        provider_agent_id=provider_agent_id,
        error_message=error_message[:4000],
        payload=payload,
    )
    db.add(row)
    job.errors_count = int(job.errors_count or 0) + 1
    job.last_error = error_message[:4000]
    db.commit()


def _provider_from_job(db, job: ProviderSyncJob):
    integration = _integration_for_job(db, job)
    platform = (
        integration.platform.value
        if hasattr(integration.platform, "value")
        else str(integration.platform).lower()
    )
    provider_class = get_voice_provider(platform)
    return provider_class(api_key=decrypt_api_key(integration.api_key))


def _integration_for_job(db, job: ProviderSyncJob) -> Integration:
    integration = (
        db.query(Integration)
        .filter(
            Integration.id == job.integration_id,
            Integration.organization_id == job.organization_id,
            Integration.is_active == True,
        )
        .first()
    )
    if not integration:
        raise ValueError("Integration not found or inactive for provider sync job")
    platform = (
        integration.platform.value
        if hasattr(integration.platform, "value")
        else str(integration.platform).lower()
    )
    if platform != IntegrationPlatform.ELEVENLABS.value:
        raise ValueError(f"Unsupported provider for sync job: {platform}")
    return integration


def _trim_insights_only_payload(call_data: Dict[str, Any]) -> Dict[str, Any]:
    raw = call_data.get("raw_data") if isinstance(call_data.get("raw_data"), dict) else {}
    trimmed_raw = {}
    for key in ("metadata", "analysis", "status", "agent_id", "conversation_id", "has_audio", "transcript"):
        if key in raw:
            trimmed_raw[key] = raw[key]
    payload = {
        **call_data,
        "raw_data": trimmed_raw,
        "insights_only": True,
        "audio_storage": "elevenlabs",
    }
    return payload


def _status_to_event(status_name: str) -> str:
    lowered = (status_name or "").strip().lower()
    if lowered in {"done", "ended", "completed", "failed"}:
        return "call_ended"
    if lowered in {"initiated", "in-progress", "processing"}:
        return "call_in_progress"
    return "call_in_progress"


def _throttle(last_request_at: float, *, rps: float) -> float:
    safe_rps = max(float(rps or 1.0), 0.1)
    min_interval = 1.0 / safe_rps
    now = time.monotonic()
    elapsed = now - last_request_at if last_request_at > 0 else min_interval
    if elapsed < min_interval:
        time.sleep(min_interval - elapsed)
        now = time.monotonic()
    return now


@celery_app.task(name="sync_elevenlabs_agents", queue="provider-sync")
def sync_elevenlabs_agents_task(job_id: str) -> Dict[str, Any]:
    db = SessionLocal()
    try:
        job = _job_by_id(db, job_id)
        if job.status == "cancelled":
            return {"status": "cancelled"}
        _mark_job(db, job, status="running", phase="agents")
        provider = _provider_from_job(db, job)
        integration = _integration_for_job(db, job)
        last_req = 0.0

        cursor = None
        total = 0
        while True:
            if _is_job_cancelled(db, job_id):
                return {"status": "cancelled"}
            last_req = _throttle(last_req, rps=settings.ELEVENLABS_SYNC_MAX_RPS)
            payload = provider.list_agents(page_size=100, cursor=cursor)
            for item in payload.get("agents", []):
                if _is_job_cancelled(db, job_id):
                    return {"status": "cancelled"}
                provider_agent_id = str(item.get("id") or "").strip()
                if not provider_agent_id:
                    continue
                name = str(item.get("name") or provider_agent_id).strip()
                agent = (
                    db.query(Agent)
                    .filter(
                        Agent.organization_id == job.organization_id,
                        Agent.workspace_id == job.workspace_id,
                        Agent.voice_ai_integration_id == job.integration_id,
                        Agent.voice_ai_agent_id == provider_agent_id,
                    )
                    .first()
                )
                if not agent:
                    agent = Agent(
                        organization_id=job.organization_id,
                        workspace_id=job.workspace_id,
                        name=name,
                        language="english",
                        call_type=CallTypeEnum.OUTBOUND.value,
                        call_medium=CallMediumEnum.PHONE_CALL.value,
                        voice_ai_integration_id=job.integration_id,
                        voice_ai_agent_id=provider_agent_id,
                        description="Imported from ElevenLabs provider sync",
                    )
                    db.add(agent)
                else:
                    agent.name = name
                    agent.voice_ai_integration_id = job.integration_id
                    agent.voice_ai_agent_id = provider_agent_id
                try:
                    sync_provider_prompt(agent=agent, integration=integration, db=db)
                except Exception as prompt_exc:
                    logger.warning(
                        "Provider prompt sync failed for provider_agent_id={}: {}",
                        provider_agent_id,
                        prompt_exc,
                    )
                total += 1
            db.flush()
            job.agents_synced = total
            db.commit()

            if not payload.get("has_more"):
                break
            cursor = payload.get("next_cursor")
            if not cursor:
                break

        _mark_job(db, job, status="completed", phase="complete")
        return {"status": "ok", "agents_synced": total}
    except Exception as exc:
        logger.exception("sync_elevenlabs_agents_task failed job_id={}", job_id)
        try:
            job = _job_by_id(db, job_id)
            _record_error(db, job=job, phase="agents", error_message=str(exc))
            _mark_job(db, job, status="failed", phase="failed")
        except Exception:
            pass
        raise
    finally:
        db.close()


@celery_app.task(name="sync_elevenlabs_catalog", queue="provider-sync")
def sync_elevenlabs_catalog_task(job_id: str) -> Dict[str, Any]:
    db = SessionLocal()
    try:
        job = _job_by_id(db, job_id)
        if job.status == "cancelled":
            return {"status": "cancelled"}
        _mark_job(db, job, status="running", phase="catalog")
        provider = _provider_from_job(db, job)
        last_req = 0.0
        config = job.config if isinstance(job.config, dict) else {}
        since_unix = config.get("since_unix")
        allowed_agents = config.get("agent_ids")
        if isinstance(allowed_agents, list) and allowed_agents:
            provider_agent_ids = [str(a) for a in allowed_agents if str(a).strip()]
        else:
            provider_agent_ids = [
                row[0]
                for row in (
                    db.query(Agent.voice_ai_agent_id)
                    .filter(
                        Agent.organization_id == job.organization_id,
                        Agent.workspace_id == job.workspace_id,
                        Agent.voice_ai_integration_id == job.integration_id,
                        Agent.voice_ai_agent_id.isnot(None),
                    )
                    .all()
                )
                if row and row[0]
            ]

        total = int(job.conversations_cataloged or 0)
        cursor_state = job.cursor_state if isinstance(job.cursor_state, dict) else {}
        for provider_agent_id in provider_agent_ids:
            if _is_job_cancelled(db, job_id):
                return {"status": "cancelled"}
            cursor = cursor_state.get(provider_agent_id)
            while True:
                if _is_job_cancelled(db, job_id):
                    return {"status": "cancelled"}
                last_req = _throttle(last_req, rps=settings.ELEVENLABS_SYNC_MAX_RPS)
                payload = provider.list_conversations(
                    agent_id=provider_agent_id,
                    cursor=cursor,
                    page_size=100,
                    call_start_after_unix=since_unix,
                )
                conversations = payload.get("conversations") or []
                for item in conversations:
                    if _is_job_cancelled(db, job_id):
                        return {"status": "cancelled"}
                    conversation_id = str(item.get("conversation_id") or "").strip()
                    if not conversation_id:
                        continue
                    linked_agent = (
                        db.query(Agent)
                        .filter(
                            Agent.organization_id == job.organization_id,
                            Agent.voice_ai_integration_id == job.integration_id,
                            Agent.voice_ai_agent_id == provider_agent_id,
                        )
                        .first()
                    )
                    call_data_payload = {
                        "conversation_id": conversation_id,
                        "agent_id": provider_agent_id,
                        "provider_platform": IntegrationPlatform.ELEVENLABS.value,
                        "status": item.get("status"),
                        "call_status": item.get("status"),
                        "duration_seconds": item.get("call_duration_secs"),
                        "start_time_unix_secs": item.get("start_time_unix_secs"),
                        "message_count": item.get("message_count"),
                        "call_successful": item.get("call_successful"),
                        "insights_only": True,
                        "audio_storage": "elevenlabs",
                        "_sync_source": "elevenlabs_catalog",
                        "_sync_job_id": str(job.id),
                    }
                    upsert_call_recording(
                        db=db,
                        organization_id=job.organization_id,
                        workspace_id=linked_agent.workspace_id if linked_agent and linked_agent.workspace_id else job.workspace_id,
                        provider_platform=IntegrationPlatform.ELEVENLABS.value,
                        provider_call_id=conversation_id,
                        call_data_payload=call_data_payload,
                        explicit_agent_id=linked_agent.id if linked_agent else None,
                        call_event=_status_to_event(str(item.get("status") or "")),
                        source=CallRecordingSource.WEBHOOK,
                    )
                    total += 1
                job.conversations_cataloged = total
                cursor = payload.get("next_cursor")
                cursor_state[provider_agent_id] = cursor
                job.cursor_state = cursor_state
                db.commit()
                if not payload.get("has_more") or not cursor:
                    break

        _mark_job(db, job, status="running", phase="enrich")
        return {"status": "ok", "conversations_cataloged": total}
    except Exception as exc:
        logger.exception("sync_elevenlabs_catalog_task failed job_id={}", job_id)
        try:
            job = _job_by_id(db, job_id)
            _record_error(db, job=job, phase="catalog", error_message=str(exc))
            _mark_job(db, job, status="failed", phase="failed")
        except Exception:
            pass
        raise
    finally:
        db.close()


@celery_app.task(name="sync_elevenlabs_enrich", queue="provider-sync")
def sync_elevenlabs_enrich_task(job_id: str) -> Dict[str, Any]:
    db = SessionLocal()
    try:
        job = _job_by_id(db, job_id)
        if job.status == "cancelled":
            return {"status": "cancelled"}
        _mark_job(db, job, status="running", phase="enrich")
        provider = _provider_from_job(db, job)
        last_req = 0.0
        config = job.config if isinstance(job.config, dict) else {}
        since_unix = config.get("since_unix")
        if since_unix:
            since_dt = datetime.fromtimestamp(int(since_unix), tz=UTC)
            rows = (
                db.query(CallRecording)
                .filter(
                    CallRecording.organization_id == job.organization_id,
                    CallRecording.workspace_id == job.workspace_id,
                    CallRecording.provider_platform == IntegrationPlatform.ELEVENLABS.value,
                    CallRecording.updated_at >= since_dt,
                )
                .all()
            )
        else:
            rows = (
                db.query(CallRecording)
                .filter(
                    CallRecording.organization_id == job.organization_id,
                    CallRecording.workspace_id == job.workspace_id,
                    CallRecording.provider_platform == IntegrationPlatform.ELEVENLABS.value,
                )
                .all()
            )

        total = int(job.conversations_enriched or 0)
        for row in rows:
            if _is_job_cancelled(db, job_id):
                return {"status": "cancelled"}
            call_data = row.call_data if isinstance(row.call_data, dict) else {}
            if call_data.get("transcript") and call_data.get("analysis"):
                continue
            provider_call_id = row.provider_call_id or call_data.get("conversation_id")
            if not provider_call_id:
                continue
            try:
                last_req = _throttle(last_req, rps=settings.ELEVENLABS_SYNC_MAX_RPS)
                refreshed = provider.retrieve_call_metrics(str(provider_call_id))
                if not isinstance(refreshed, dict):
                    continue
                merged = {**call_data, **refreshed}
                merged = _trim_insights_only_payload(merged)
                merged["_sync_source"] = "elevenlabs_enrich"
                merged["_sync_job_id"] = str(job.id)
                row.call_data = merged
                total += 1
                job.conversations_enriched = total
                db.commit()
            except Exception as exc:
                _record_error(
                    db,
                    job=job,
                    phase="enrich",
                    error_message=str(exc),
                    provider_call_id=str(provider_call_id),
                )
                db.rollback()
        if _is_job_cancelled(db, job_id):
            return {"status": "cancelled"}
        _mark_job(db, job, status="completed", phase="complete")
        return {"status": "ok", "conversations_enriched": total}
    except Exception as exc:
        logger.exception("sync_elevenlabs_enrich_task failed job_id={}", job_id)
        try:
            job = _job_by_id(db, job_id)
            _record_error(db, job=job, phase="enrich", error_message=str(exc))
            _mark_job(db, job, status="failed", phase="failed")
        except Exception:
            pass
        raise
    finally:
        db.close()


@celery_app.task(name="run_elevenlabs_monitor_bridge", queue="provider-sync")
def run_elevenlabs_monitor_bridge_task(
    *,
    conversation_id: str,
    elevenlabs_api_key: str,
    efficientai_api_key: str,
    workspace_id: Optional[str] = None,
    efficientai_base_url: str = "http://localhost:8000",
    provider_platform: str = "elevenlabs",
) -> Dict[str, Any]:
    acquired = _MONITOR_SEMAPHORE.acquire(timeout=5)
    if not acquired:
        raise RuntimeError("ElevenLabs monitor concurrency limit reached")
    try:
        bridge = ElevenLabsMonitorBridge(
            conversation_id=conversation_id,
            elevenlabs_api_key=elevenlabs_api_key,
            efficientai_api_key=efficientai_api_key,
            workspace_id=workspace_id,
            efficientai_base_url=efficientai_base_url,
            provider_platform=provider_platform,
        )
        asyncio.run(bridge.run())
        return {"status": "ok", "conversation_id": conversation_id}
    finally:
        _MONITOR_SEMAPHORE.release()
