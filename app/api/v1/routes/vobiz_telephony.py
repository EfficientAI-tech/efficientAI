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
from app.services.telephony.call_recording_lifecycle import (
    create_inbound_call_recording,
    finalize_call_on_media_disconnect,
    find_call_recording,
    ingest_carrier_recording_url,
    link_provider_call_id,
    mark_call_in_progress,
    update_call_from_vobiz_event,
)
from app.services.telephony.vobiz_client import build_vobiz_client_for_org
from app.services.telephony.vobiz_number_service import (
    deactivate_imported_number,
    import_vobiz_numbers,
    list_available_vobiz_numbers,
)
from app.services.telephony.webhook_auth import verify_vobiz_webhook
from app.services.telephony.vobiz_outbound_pool import (
    outbound_pool_api_payload,
    release_pool_slot,
    resolve_outbound_from_number,
)
from app.services.telephony.vobiz_session import create_call_session, delete_call_session, get_call_session
from app.services.telephony.vobiz_xml import reject_call, speak_and_hangup, stream_to_agent
from app.services.voice_agent.bot_fast_api import run_bot
from app.services.voice_agent.voice_bundle import run_voice_bundle_fastapi
from efficientai.runner.utils import parse_telephony_websocket
from efficientai.serializers.vobiz import VobizFrameSerializer

# Exposed at module scope so tests can patch `.delay` without importing Celery tasks.
initiate_vobiz_outbound_call_task = None

router = APIRouter(prefix="/telephony/vobiz", tags=["Vobiz Telephony"])
webhook_router = APIRouter(prefix="/telephony/vobiz", tags=["Vobiz Telephony Webhooks"])
ws_router = APIRouter(prefix="/telephony/vobiz", tags=["Vobiz Telephony Media"])


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
    call_short_id: str = ""
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
    provider: str = "vobiz"
    results: List[VobizImportNumberResult]
    answer_url: str


class VobizOutboundPoolNumberResponse(BaseModel):
    phone_number: str
    provider: str


class VobizOutboundPoolResponse(BaseModel):
    numbers: List[VobizOutboundPoolNumberResponse]
    max_concurrent_per_org: int
    shared_across_orgs: bool = True


def _parse_request_payload(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if hasattr(raw, "items"):
        return dict(raw)
    return {}


async def _read_webhook_payload(request: Request) -> Dict[str, Any]:
    if not getattr(request.state, "webhook_raw_body", None):
        request.state.webhook_raw_body = await request.body()
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
        message = str(e)
        if message == "Imported number not found":
            raise HTTPException(status_code=404, detail=message) from e
        status_code = (
            status.HTTP_409_CONFLICT
            if "active number-masking sessions" in message
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=status_code, detail=message) from e
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/outbound-pool", response_model=VobizOutboundPoolResponse)
async def get_vobiz_outbound_pool(
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
):
    del organization_id, api_key
    return VobizOutboundPoolResponse(**outbound_pool_api_payload())


@router.post("/calls/outbound", response_model=VobizOutboundCallResponse)
async def create_vobiz_outbound_call(
    payload: VobizOutboundCallRequest,
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    del api_key
    try:
        build_vobiz_client_for_org(db, organization_id)
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
        from_number, used_pool, provider = resolve_outbound_from_number(
            db,
            organization_id,
            explicit_from_number=payload.from_number,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    if provider != "vobiz":
        if used_pool:
            release_pool_slot(organization_id)
        raise HTTPException(
            status_code=400,
            detail=(
                f"Outbound via the Vobiz API requires a Vobiz caller ID; "
                f"resolved provider is {provider}. Use org-owned numbers or "
                f"configure Vobiz entries in telephony.outbound_pool."
            ),
        )

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
    events_url = (
        f"{base}{settings.API_V1_PREFIX}/telephony/vobiz/webhooks/events"
        f"?call_ref={session.call_ref}"
    )
    recording_url = f"{base}{settings.API_V1_PREFIX}/telephony/vobiz/webhooks/recording-ready"

    call_short_id = "".join(random.choices(string.digits, k=6))
    recording = CallRecording(
        organization_id=organization_id,
        workspace_id=agent.workspace_id,
        call_short_id=call_short_id,
        status=CallRecordingStatus.PENDING,
        source=CallRecordingSource.WEBHOOK,
        call_event="outbound_initiated",
        call_data={
            "call_ref": session.call_ref,
            "call_short_id": call_short_id,
            "recording_callback": recording_url,
            "used_pool": used_pool,
            "evaluator_id": str(evaluator_id) if evaluator_id else None,
            "direction": "outbound",
            "from_number": from_number,
            "to_number": to_number,
            "live_transcript": [],
        },
        provider_call_id=None,
        provider_platform="vobiz",
        agent_id=agent.id,
    )
    db.add(recording)
    db.commit()
    db.refresh(recording)

    task = initiate_vobiz_outbound_call_task
    if task is None:
        from app.workers.tasks.initiate_vobiz_outbound import (
            initiate_vobiz_outbound_call_task as task,
        )

    task.delay(
        organization_id=str(organization_id),
        call_ref=session.call_ref,
        from_number=from_number,
        to_number=to_number,
        answer_url=answer_url,
        events_url=events_url,
        used_pool=used_pool,
        call_recording_id=str(recording.id),
    )

    return VobizOutboundCallResponse(
        provider_request_uuid="",
        call_status="queued",
        from_number=from_number,
        to_number=to_number,
        call_ref=session.call_ref,
        call_short_id=call_short_id,
    )


@webhook_router.post("/webhooks/answer")
@webhook_router.get("/webhooks/answer")
async def vobiz_answer_webhook(
    request: Request,
    call_ref: Optional[str] = None,
    db: Session = Depends(get_db),
):
    payload = await _read_webhook_payload(request)
    params = extract_webhook_params(payload)
    if not call_ref:
        call_ref = request.query_params.get("call_ref")
    verify_vobiz_webhook(request, payload, "answer", db, call_ref=call_ref)
    logger.info(
        "Vobiz answer webhook To={} From={} call_ref={}",
        params.get("to"),
        params.get("from"),
        call_ref or request.query_params.get("call_ref"),
    )
    agent_id, organization_id, session_token = _resolve_agent_for_answer(
        db, params, call_ref=call_ref
    )
    if not agent_id or not organization_id:
        return Response(content=reject_call("No active routing found for this number."), media_type="application/xml")

    if not session_token:
        agent = db.query(Agent).filter(Agent.id == agent_id).first()
        inbound_evaluator_id: Optional[UUID] = None
        inbound_evaluator_result_id: Optional[UUID] = None
        inbound_persona_id: Optional[UUID] = None
        inbound_scenario_id: Optional[UUID] = None
        if agent and agent.workspace_id:
            from app.services.evaluators.evaluator_inbound_service import (
                consume_inbound_evaluator_combination,
                create_inbound_evaluator_result,
                find_inbound_suite_for_agent,
            )

            suite = find_inbound_suite_for_agent(
                db, agent, organization_id, agent.workspace_id
            )
            if suite:
                selected, _idx, _next_idx = consume_inbound_evaluator_combination(db, suite)
                inbound_evaluator_id = selected.id
                inbound_persona_id = selected.persona_id
                inbound_scenario_id = selected.scenario_id
                result_row = create_inbound_evaluator_result(
                    db,
                    organization_id,
                    agent.workspace_id,
                    selected,
                )
                inbound_evaluator_result_id = result_row.id

        session = create_call_session(
            agent_id=str(agent_id),
            organization_id=str(organization_id),
            direction="inbound",
            from_number=params.get("from"),
            to_number=params.get("to"),
            persona_id=str(inbound_persona_id) if inbound_persona_id else None,
            scenario_id=str(inbound_scenario_id) if inbound_scenario_id else None,
            evaluator_id=str(inbound_evaluator_id) if inbound_evaluator_id else None,
        )
        session_token = session.call_ref
        persona_id = session.persona_id
        scenario_id = session.scenario_id
        if agent:
            inbound_row = create_inbound_call_recording(
                db,
                agent=agent,
                organization_id=organization_id,
                call_ref=session_token,
                from_number=params.get("from"),
                to_number=params.get("to"),
                provider_call_id=params.get("call_uuid"),
                evaluator_id=inbound_evaluator_id,
                evaluator_result_id=inbound_evaluator_result_id,
            )
            # region agent log
            from app.utils.debug_agent_log import agent_debug_log

            agent_debug_log(
                "vobiz_telephony.py:answer_webhook",
                "inbound CallRecording created",
                {
                    "call_ref": session_token,
                    "call_short_id": inbound_row.call_short_id,
                    "provider_call_id": params.get("call_uuid"),
                },
                "H1",
            )
            # endregion
    else:
        existing_session = get_call_session(session_token)
        persona_id = existing_session.persona_id if existing_session else None
        scenario_id = existing_session.scenario_id if existing_session else None

    call_uuid = params.get("call_uuid")
    if session_token and call_uuid:
        link_provider_call_id(db, call_ref=session_token, provider_call_id=call_uuid)

    ws_url = build_vobiz_ws_url(
        agent_id=str(agent_id),
        session=session_token,
        persona_id=persona_id,
        scenario_id=scenario_id,
    )
    record_action_url = None
    if settings.VOBIZ_CARRIER_SESSION_RECORDING:
        record_action_url = (
            f"{vobiz_webhook_base_url()}{settings.API_V1_PREFIX}/telephony/vobiz/webhooks/recording-ready"
            f"?call_ref={session_token}"
        )
    xml = stream_to_agent(ws_url, record_action_url=record_action_url)
    return Response(content=xml, media_type="application/xml")


@webhook_router.post("/webhooks/events")
async def vobiz_events_webhook(
    request: Request,
    db: Session = Depends(get_db),
):
    payload = await _read_webhook_payload(request)
    params = extract_webhook_params(payload)
    call_ref = request.query_params.get("call_ref") or payload.get("call_ref")
    verify_vobiz_webhook(request, payload, "events", db, call_ref=call_ref)
    call_uuid = params.get("call_uuid")
    if not call_uuid:
        return {"status": "ignored"}

    update_call_from_vobiz_event(
        db,
        provider_call_id=call_uuid,
        call_status=params.get("call_status"),
        payload=payload,
        call_ref=call_ref,
    )

    row = find_call_recording(
        db,
        provider_call_id=call_uuid,
        call_ref=call_ref,
    )
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


@webhook_router.post("/webhooks/recording-ready")
async def vobiz_recording_ready_webhook(
    request: Request,
    db: Session = Depends(get_db),
):
    payload = await _read_webhook_payload(request)
    params = extract_webhook_params(payload)
    call_ref = request.query_params.get("call_ref") or payload.get("call_ref")
    verify_vobiz_webhook(request, payload, "recording", db, call_ref=call_ref)
    recording_url = params.get("recording_url")
    call_uuid = params.get("call_uuid")
    logger.info(
        "Vobiz recording ready call_uuid={} recording_id={} url={}",
        call_uuid,
        params.get("recording_id"),
        recording_url,
    )
    if call_uuid:
        call_ref = request.query_params.get("call_ref") or payload.get("call_ref")
        row = find_call_recording(
            db,
            provider_call_id=call_uuid,
            call_ref=call_ref,
        )
        if row:
            from sqlalchemy.orm.attributes import flag_modified

            current = dict(row.call_data) if isinstance(row.call_data, dict) else {}
            current["recording"] = payload
            if recording_url:
                current["recording_url"] = recording_url
            row.call_data = current
            flag_modified(row, "call_data")
            db.commit()
            if recording_url and settings.VOBIZ_CARRIER_SESSION_RECORDING:
                ingest_carrier_recording_url(db, row, recording_url)
            elif recording_url and not settings.VOBIZ_CARRIER_SESSION_RECORDING:
                logger.debug(
                    "Skipping Vobiz carrier recording ingest (VOBIZ_CARRIER_SESSION_RECORDING=false) "
                    "call_short_id={}",
                    row.call_short_id,
                )
            # region agent log
            from app.utils.debug_agent_log import agent_debug_log

            agent_debug_log(
                "vobiz_telephony.py:recording_ready",
                "recording webhook persisted",
                {
                    "call_short_id": row.call_short_id,
                    "call_ref": call_ref,
                    "call_uuid": call_uuid,
                    "has_recording_url": bool(recording_url),
                },
                "H4",
            )
            # endregion
        else:
            # region agent log
            from app.utils.debug_agent_log import agent_debug_log

            agent_debug_log(
                "vobiz_telephony.py:recording_ready",
                "recording webhook: no CallRecording match",
                {"call_uuid": call_uuid, "call_ref": call_ref},
                "H4",
            )
            # endregion
    return {"status": "ok"}


@ws_router.websocket("/ws")
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

    persona_id = persona_id or session.persona_id
    scenario_id = scenario_id or session.scenario_id

    await websocket.accept()
    db = next(get_db())
    call_row = find_call_recording(db, call_ref=session_token, provider_call_id=None)
    call_short_id = call_row.call_short_id if call_row else None
    # region agent log
    from app.utils.debug_agent_log import agent_debug_log

    agent_debug_log(
        "vobiz_telephony.py:media_websocket",
        "CallRecording lookup for media session",
        {
            "call_ref": session_token,
            "call_short_id": call_short_id,
            "found_row": call_row is not None,
            "provider_call_id": call_row.provider_call_id if call_row else None,
        },
        "H1",
    )
    # endregion
    if not call_short_id:
        logger.warning(
            "No CallRecording for Vobiz session {}; live transcript and recording will not be linked",
            session_token,
        )
    try:
        mark_call_in_progress(db, call_ref=session_token)
        try:
            transport_type, call_data = await parse_telephony_websocket(websocket)
            if transport_type not in {"plivo", "unknown"}:
                logger.warning("Unexpected telephony transport type for Vobiz: {}", transport_type)
            stream_id = call_data.get("stream_id") or ""
            call_id = call_data.get("call_id")
            if call_id:
                link_provider_call_id(db, call_ref=session_token, provider_call_id=str(call_id))
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
                from app.services.voice_agent.call_silence_hangup import resolve_agent_silence_hangup_secs

                hangup_secs = resolve_agent_silence_hangup_secs(context.agent)
                await run_voice_bundle_fastapi(
                    websocket,
                    context.system_instruction,
                    str(context.organization_id),
                    str(context.workspace_id) if context.workspace_id else None,
                    agent_id,
                    persona_id,
                    scenario_id,
                    voice_bundle=context.voice_bundle,
                    persona=context.persona,
                    stt_api_key=context.stt_api_key,
                    tts_api_key=context.tts_api_key,
                    llm_api_key=context.llm_api_key,
                    serializer=serializer,
                    telephony_mode=True,
                    call_short_id=call_short_id,
                    silence_hangup_secs=hangup_secs,
                )
            else:
                if not context.google_api_key:
                    await websocket.close(code=1011, reason="Google API key not configured for agent")
                    return
                from app.services.voice_agent.call_silence_hangup import resolve_agent_silence_hangup_secs

                hangup_secs = resolve_agent_silence_hangup_secs(context.agent)
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
                    call_short_id=call_short_id,
                    silence_hangup_secs=hangup_secs,
                    persona=context.persona,
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
            from app.database import SessionLocal

            finalize_db = SessionLocal()
            try:
                finalize_call_on_media_disconnect(finalize_db, call_ref=session_token)
            finally:
                finalize_db.close()
            delete_call_session(session_token)
    finally:
        db.close()
