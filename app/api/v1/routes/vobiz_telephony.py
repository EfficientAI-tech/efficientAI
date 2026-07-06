"""Vobiz telephony API routes (per-org BYO credentials + platform pool fallback)."""

from __future__ import annotations

import random
import string
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, WebSocket, WebSocketDisconnect, status
from loguru import logger
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.dependencies import get_api_key, get_db, get_organization_id
from app.models.database import Agent, CallRecording, CallRecordingSource, Evaluator, TelephonyPhoneNumber
from app.models.enums import CallRecordingStatus
from app.services.telephony.phone_routing import resolve_inbound_agent_for_number
from app.services.telephony.plivo_client import normalize_e164
from app.services.telephony.vobiz_agent_context import (
    build_vobiz_ws_url,
    extract_webhook_params,
    resolve_vobiz_agent_context,
    vobiz_webhook_base_url,
)
from app.services.telephony.vobiz_client import build_vobiz_client_for_org
from app.services.telephony.vobiz_number_service import (
    deactivate_imported_number,
    import_vobiz_numbers,
    list_available_vobiz_numbers,
)
from app.services.telephony.vobiz_outbound_pool import (
    configured_outbound_pool,
    release_pool_slot,
    resolve_outbound_from_number,
)
from app.services.telephony.vobiz_session import create_call_session, delete_call_session, get_call_session
from app.services.telephony.vobiz_xml import reject_call, speak_and_hangup, stream_to_agent
from app.services.voice_agent.bot_fast_api import run_bot
from app.services.voice_agent.voice_bundle import run_voice_bundle_fastapi
from efficientai.runner.utils import parse_telephony_websocket
from efficientai.serializers.vobiz import VobizFrameSerializer

router = APIRouter(prefix="/telephony/vobiz", tags=["Vobiz Telephony"])


class VobizOutboundCallRequest(BaseModel):
    to_number: str
    agent_id: UUID
    from_number: Optional[str] = None
    persona_id: Optional[UUID] = None
    scenario_id: Optional[UUID] = None
    evaluator_id: Optional[UUID] = None


class VobizOutboundCallResponse(BaseModel):
    provider_request_uuid: str
    call_status: str
    from_number: str
    to_number: str
    call_ref: str
    message: str = "Outbound call initiated"


class VobizAvailableNumberResponse(BaseModel):
    e164: str
    provider_number_id: Optional[str] = None
    country: Optional[str] = None
    region: Optional[str] = None
    capabilities: Optional[Dict[str, Any]] = None
    status: Optional[str] = None
    application_id: Optional[str] = None
    already_imported: bool = False
    imported_number_id: Optional[str] = None


class VobizImportNumbersRequest(BaseModel):
    numbers: List[str]
    agent_id: Optional[UUID] = None


class VobizImportNumberResult(BaseModel):
    number: str
    success: bool
    message: str
    answer_url: str
    webhook_configured: Optional[bool] = None
    imported_number_id: Optional[str] = None
    application_id: Optional[str] = None


class VobizImportNumbersResponse(BaseModel):
    results: List[VobizImportNumberResult]
    answer_url: str


class VobizOutboundPoolResponse(BaseModel):
    numbers: List[str]
    max_concurrent_per_org: int
    shared_across_orgs: bool = True


def _parse_request_payload(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if hasattr(raw, "items"):
        return dict(raw)
    return {}


async def _read_webhook_payload(request: Request) -> Dict[str, Any]:
    params: Dict[str, Any] = dict(request.query_params)
    content_type = (request.headers.get("content-type") or "").lower()
    if "application/json" in content_type:
        try:
            body = await request.json()
            if isinstance(body, dict):
                params.update(body)
                return params
        except Exception:
            pass
    try:
        form = await request.form()
        params.update(_parse_request_payload(form))
    except Exception:
        pass
    return params


def _resolve_agent_for_answer(
    db: Session,
    params: Dict[str, Any],
    *,
    call_ref: Optional[str] = None,
) -> tuple[Optional[UUID], Optional[UUID], Optional[str]]:
    """Return (agent_id, organization_id, session_token)."""
    if call_ref:
        session = get_call_session(call_ref)
        if session and session.agent_id and session.organization_id:
            return UUID(session.agent_id), UUID(session.organization_id), call_ref

    agent_id, organization_id = resolve_inbound_agent_for_number(db, params.get("to"))
    if not agent_id or not organization_id:
        return None, None, None
    return agent_id, organization_id, None


@router.get("/numbers/available", response_model=List[VobizAvailableNumberResponse])
async def list_vobiz_available_numbers(
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    del api_key
    try:
        return list_available_vobiz_numbers(db, organization_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/numbers/import", response_model=VobizImportNumbersResponse)
async def import_vobiz_numbers_route(
    payload: VobizImportNumbersRequest,
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    del api_key
    try:
        result = import_vobiz_numbers(
            db,
            organization_id,
            numbers=payload.numbers,
            agent_id=payload.agent_id,
        )
        return VobizImportNumbersResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.delete("/numbers/{number_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_imported_vobiz_number(
    number_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    del api_key
    try:
        deactivate_imported_number(db, organization_id, number_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/outbound-pool", response_model=VobizOutboundPoolResponse)
async def get_vobiz_outbound_pool(
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
):
    del organization_id, api_key
    return VobizOutboundPoolResponse(
        numbers=configured_outbound_pool(),
        max_concurrent_per_org=max(int(settings.VOBIZ_OUTBOUND_POOL_MAX_CONCURRENT_PER_ORG or 5), 1),
        shared_across_orgs=True,
    )


@router.post("/calls/outbound", response_model=VobizOutboundCallResponse)
async def create_vobiz_outbound_call(
    payload: VobizOutboundCallRequest,
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    del api_key
    try:
        client, _ = build_vobiz_client_for_org(db, organization_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    agent = db.query(Agent).filter(
        Agent.id == payload.agent_id,
        Agent.organization_id == organization_id,
    ).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found for organization")

    persona_id = payload.persona_id
    scenario_id = payload.scenario_id
    evaluator_id = payload.evaluator_id

    if payload.evaluator_id:
        evaluator = db.query(Evaluator).filter(
            Evaluator.id == payload.evaluator_id,
            Evaluator.organization_id == organization_id,
        ).first()
        if not evaluator:
            raise HTTPException(status_code=404, detail="Evaluator not found for organization")
        if evaluator.agent_id:
            agent = db.query(Agent).filter(
                Agent.id == evaluator.agent_id,
                Agent.organization_id == organization_id,
            ).first()
            if not agent:
                raise HTTPException(status_code=404, detail="Agent not found for evaluator")
            payload = payload.model_copy(update={"agent_id": agent.id})
        persona_id = persona_id or evaluator.persona_id
        scenario_id = scenario_id or evaluator.scenario_id

    try:
        from_number, used_pool = resolve_outbound_from_number(
            db,
            organization_id,
            explicit_from_number=payload.from_number,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    to_number = normalize_e164(payload.to_number)

    session = create_call_session(
        agent_id=str(agent.id),
        organization_id=str(organization_id),
        direction="outbound",
        from_number=from_number,
        to_number=to_number,
        used_pool=used_pool,
        persona_id=str(persona_id) if persona_id else None,
        scenario_id=str(scenario_id) if scenario_id else None,
        evaluator_id=str(evaluator_id) if evaluator_id else None,
    )

    base = vobiz_webhook_base_url()
    answer_url = (
        f"{base}{settings.API_V1_PREFIX}/telephony/vobiz/webhooks/answer"
        f"?call_ref={session.call_ref}"
    )
    events_url = f"{base}{settings.API_V1_PREFIX}/telephony/vobiz/webhooks/events"
    recording_url = f"{base}{settings.API_V1_PREFIX}/telephony/vobiz/webhooks/recording-ready"

    try:
        response = client.create_outbound_call(
            from_=from_number,
            to_=to_number,
            answer_url=answer_url,
            hangup_url=events_url,
        )
    except ValueError as e:
        delete_call_session(session.call_ref)
        if used_pool:
            release_pool_slot(organization_id)
        raise HTTPException(status_code=400, detail=str(e)) from e

    call_uuid = (
        response.get("request_uuid")
        or response.get("message_uuid")
        or response.get("api_id")
        or response.get("call_uuid")
        or ""
    )
    call_short_id = "".join(random.choices(string.digits, k=6))
    db.add(
        CallRecording(
            organization_id=organization_id,
            workspace_id=agent.workspace_id,
            call_short_id=call_short_id,
            status=CallRecordingStatus.PENDING,
            source=CallRecordingSource.WEBHOOK,
            call_event="outbound_initiated",
            call_data={**response, "call_ref": session.call_ref, "recording_callback": recording_url, "used_pool": used_pool, "evaluator_id": str(evaluator_id) if evaluator_id else None},
            provider_call_id=call_uuid or None,
            provider_platform="vobiz",
            agent_id=agent.id,
        )
    )
    db.commit()

    return VobizOutboundCallResponse(
        provider_request_uuid=str(call_uuid or ""),
        call_status=str(response.get("message") or response.get("status") or "initiated"),
        from_number=from_number,
        to_number=to_number,
        call_ref=session.call_ref,
    )


@router.post("/webhooks/answer")
@router.get("/webhooks/answer")
async def vobiz_answer_webhook(
    request: Request,
    call_ref: Optional[str] = None,
    db: Session = Depends(get_db),
):
    payload = await _read_webhook_payload(request)
    params = extract_webhook_params(payload)
    logger.info(
        "Vobiz answer webhook To={} From={} call_ref={}",
        params.get("to"),
        params.get("from"),
        call_ref or request.query_params.get("call_ref"),
    )
    if not call_ref:
        call_ref = request.query_params.get("call_ref")

    agent_id, organization_id, session_token = _resolve_agent_for_answer(
        db, params, call_ref=call_ref
    )
    if not agent_id or not organization_id:
        return Response(content=reject_call("No active routing found for this number."), media_type="application/xml")

    if not session_token:
        session = create_call_session(
            agent_id=str(agent_id),
            organization_id=str(organization_id),
            direction="inbound",
            from_number=params.get("from"),
            to_number=params.get("to"),
        )
        session_token = session.call_ref
        persona_id = None
        scenario_id = None
    else:
        existing_session = get_call_session(session_token)
        persona_id = existing_session.persona_id if existing_session else None
        scenario_id = existing_session.scenario_id if existing_session else None

    ws_url = build_vobiz_ws_url(
        agent_id=str(agent_id),
        session=session_token,
        persona_id=persona_id,
        scenario_id=scenario_id,
    )
    record_action_url = f"{vobiz_webhook_base_url()}{settings.API_V1_PREFIX}/telephony/vobiz/webhooks/recording-ready"
    xml = stream_to_agent(ws_url, record_action_url=record_action_url)
    return Response(content=xml, media_type="application/xml")


@router.post("/webhooks/events")
async def vobiz_events_webhook(
    request: Request,
    db: Session = Depends(get_db),
):
    payload = await _read_webhook_payload(request)
    params = extract_webhook_params(payload)
    call_uuid = params.get("call_uuid")
    if not call_uuid:
        return {"status": "ignored"}

    row = db.query(CallRecording).filter(CallRecording.provider_call_id == call_uuid).first()
    if row:
        row.status = CallRecordingStatus.UPDATED
        row.call_event = (params.get("call_status") or "updated").lower()
        current = row.call_data if isinstance(row.call_data, dict) else {}
        current["last_event"] = payload
        row.call_data = current
        db.commit()

    call_ref = request.query_params.get("call_ref") or payload.get("call_ref")
    terminal_statuses = {
        "completed",
        "hangup",
        "failed",
        "busy",
        "no-answer",
        "canceled",
    }
    if call_ref and (params.get("call_status") or "").lower() in terminal_statuses:
        session = get_call_session(call_ref)
        if session and session.used_pool:
            release_pool_slot(UUID(session.organization_id))
        delete_call_session(call_ref)
    elif row and (params.get("call_status") or "").lower() in terminal_statuses:
        call_data = row.call_data if isinstance(row.call_data, dict) else {}
        if call_data.get("used_pool"):
            release_pool_slot(row.organization_id)

    return {"status": "ok"}


@router.post("/webhooks/recording-ready")
async def vobiz_recording_ready_webhook(
    request: Request,
    db: Session = Depends(get_db),
):
    payload = await _read_webhook_payload(request)
    params = extract_webhook_params(payload)
    recording_url = params.get("recording_url")
    call_uuid = params.get("call_uuid")
    logger.info(
        "Vobiz recording ready call_uuid={} recording_id={} url={}",
        call_uuid,
        params.get("recording_id"),
        recording_url,
    )
    if call_uuid:
        row = db.query(CallRecording).filter(CallRecording.provider_call_id == call_uuid).first()
        if row:
            current = row.call_data if isinstance(row.call_data, dict) else {}
            current["recording"] = payload
            if recording_url:
                current["recording_url"] = recording_url
            row.call_data = current
            db.commit()
    return {"status": "ok"}


@router.websocket("/ws")
async def vobiz_media_websocket(websocket: WebSocket):
    agent_id = websocket.query_params.get("agent_id")
    session_token = websocket.query_params.get("session")
    persona_id = websocket.query_params.get("persona_id")
    scenario_id = websocket.query_params.get("scenario_id")

    if not agent_id or not session_token:
        await websocket.close(code=1008, reason="agent_id and session are required")
        return

    session = get_call_session(session_token)
    if not session:
        await websocket.close(code=1008, reason="Invalid or expired call session")
        return
    if session.agent_id != agent_id:
        await websocket.close(code=1008, reason="Session does not match agent")
        return

    await websocket.accept()
    db = next(get_db())
    try:
        try:
            transport_type, call_data = await parse_telephony_websocket(websocket)
            if transport_type not in {"plivo", "unknown"}:
                logger.warning("Unexpected telephony transport type for Vobiz: {}", transport_type)
            stream_id = call_data.get("stream_id") or ""
            call_id = call_data.get("call_id")
            if not stream_id:
                await websocket.close(code=1011, reason="Missing stream id from Vobiz")
                return

            context = resolve_vobiz_agent_context(
                db,
                agent_id=UUID(agent_id),
                organization_id=UUID(session.organization_id),
                persona_id=persona_id,
                scenario_id=scenario_id,
            )
            serializer = VobizFrameSerializer(
                stream_id=stream_id,
                call_id=call_id,
                auth_id=settings.VOBIZ_AUTH_ID,
                auth_token=settings.VOBIZ_AUTH_TOKEN,
                params=VobizFrameSerializer.InputParams(
                    sample_rate=8000,
                    api_base=settings.VOBIZ_API_BASE,
                ),
            )

            if context.use_voice_bundle_pipeline:
                await run_voice_bundle_fastapi(
                    websocket,
                    context.system_instruction,
                    str(context.organization_id),
                    agent_id,
                    persona_id,
                    scenario_id,
                    voice_bundle=context.voice_bundle,
                    stt_api_key=context.stt_api_key,
                    tts_api_key=context.tts_api_key,
                    llm_api_key=context.llm_api_key,
                    serializer=serializer,
                    telephony_mode=True,
                )
            else:
                if not context.google_api_key:
                    await websocket.close(code=1011, reason="Google API key not configured for agent")
                    return
                await run_bot(
                    websocket,
                    context.google_api_key,
                    context.system_instruction,
                    str(context.organization_id),
                    agent_id,
                    persona_id,
                    scenario_id,
                    model_name=context.model_name,
                    serializer=serializer,
                    telephony_mode=True,
                )
        except ValueError as e:
            logger.error("Vobiz media websocket setup failed: {}", e)
            await websocket.close(code=1011, reason=str(e))
        except WebSocketDisconnect:
            logger.info("Vobiz media websocket disconnected")
        except Exception as e:
            logger.error("Vobiz media websocket error: {}", e, exc_info=True)
            try:
                await websocket.close(code=1011, reason="Server error")
            except Exception:
                pass
        finally:
            delete_call_session(session_token)
    finally:
        db.close()
