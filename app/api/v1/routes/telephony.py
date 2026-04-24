"""Telephony API routes (provider-agnostic)."""

from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.dependencies import get_api_key, get_db, get_organization_id
from app.models.database import TelephonyIntegration, TelephonyMaskedSession, TelephonyPhoneNumber
from app.models.schemas import (
    TelephonyIntegrationCreate,
    TelephonyIntegrationResponse,
    TelephonyIntegrationUpdate,
    TelephonyMaskingSessionCreate,
    TelephonyMaskingSessionResponse,
    TelephonyOutboundCallRequest,
    TelephonyOutboundCallResponse,
    TelephonyPhoneNumberResponse,
    TelephonyVerifyCheckRequest,
    TelephonyVerifyCheckResponse,
    TelephonyVerifyStartRequest,
    TelephonyVerifyStartResponse,
)
from app.services.telephony.telephony_service import telephony_service

router = APIRouter(prefix="/telephony", tags=["Telephony"])


class TelephonyNumberUpdateRequest(BaseModel):
    """Patch schema for organization number configuration."""

    is_masking_pool: Optional[bool] = None
    agent_id: Optional[UUID] = None
    is_active: Optional[bool] = None


@router.post("/config", response_model=TelephonyIntegrationResponse, status_code=status.HTTP_201_CREATED)
async def create_telephony_config(
    data: TelephonyIntegrationCreate,
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    del api_key
    try:
        return telephony_service.save_integration(organization_id, data.model_dump(), db)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/config", response_model=TelephonyIntegrationResponse)
async def get_telephony_config(
    provider: str = "plivo",
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    del api_key
    try:
        return telephony_service.get_org_integration(organization_id, db, provider=provider)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put("/config", response_model=TelephonyIntegrationResponse)
async def update_telephony_config(
    data: TelephonyIntegrationUpdate,
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    del api_key
    try:
        return telephony_service.save_integration(
            organization_id,
            data.model_dump(exclude_none=True),
            db,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/config/test")
async def test_telephony_config(
    provider: str = "plivo",
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    del api_key
    try:
        ok = telephony_service.test_connection(organization_id, db, provider=provider)
        return {"success": ok}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/numbers/sync", response_model=List[TelephonyPhoneNumberResponse])
async def sync_telephony_numbers(
    provider: str = "plivo",
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    del api_key
    try:
        return telephony_service.sync_numbers(organization_id, db, provider=provider)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/numbers", response_model=List[TelephonyPhoneNumberResponse])
async def list_telephony_numbers(
    provider: Optional[str] = None,
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    del api_key
    return telephony_service.list_numbers(organization_id, db, provider=provider)


@router.patch("/numbers/{number_id}", response_model=TelephonyPhoneNumberResponse)
async def update_telephony_number(
    number_id: UUID,
    data: TelephonyNumberUpdateRequest,
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    del api_key
    number = (
        db.query(TelephonyPhoneNumber)
        .filter(TelephonyPhoneNumber.id == number_id, TelephonyPhoneNumber.organization_id == organization_id)
        .first()
    )
    if not number:
        raise HTTPException(status_code=404, detail="Phone number not found")

    update_data = data.model_dump(exclude_none=True)
    for key, value in update_data.items():
        setattr(number, key, value)
    db.commit()
    db.refresh(number)
    return number


@router.post("/calls/outbound", response_model=TelephonyOutboundCallResponse)
async def create_outbound_call(
    payload: TelephonyOutboundCallRequest,
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    del api_key
    try:
        response = telephony_service.initiate_outbound_call(
            organization_id,
            payload.from_number,
            payload.to_number,
            payload.agent_id,
            db,
        )
        return TelephonyOutboundCallResponse(
            provider_request_uuid=str(
                response.get("request_uuid") or response.get("message_uuid") or response.get("api_id") or ""
            ),
            call_status=str(response.get("message") or response.get("call_status") or "queued"),
            from_number=payload.from_number,
            to_number=payload.to_number,
            message="Outbound call initiated",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/verify/start", response_model=TelephonyVerifyStartResponse)
async def start_verify_session(
    payload: TelephonyVerifyStartRequest,
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    try:
        session = telephony_service.start_voice_otp(
            organization_id,
            payload.phone_number,
            api_key,
            db,
            provider=payload.provider,
        )
        return TelephonyVerifyStartResponse(
            session_id=session.id,
            provider_session_uuid=session.provider_session_uuid,
            status=session.status,
            message="Voice OTP initiated",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/verify/check", response_model=TelephonyVerifyCheckResponse)
async def check_verify_session(
    payload: TelephonyVerifyCheckRequest,
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    del api_key
    try:
        verified, message = telephony_service.check_voice_otp(
            organization_id,
            payload.session_id,
            payload.otp_code,
            db,
            provider=payload.provider,
        )
        return TelephonyVerifyCheckResponse(
            verified=verified,
            status="verified" if verified else "failed",
            message=message,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/masking/sessions", response_model=TelephonyMaskingSessionResponse)
async def create_masking_session(
    payload: TelephonyMaskingSessionCreate,
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    del api_key
    try:
        return telephony_service.create_masking_session(
            org_id=organization_id,
            party_a=payload.party_a_number,
            party_b=payload.party_b_number,
            expires_in_minutes=payload.expires_in_minutes or 60,
            metadata=payload.metadata,
            db=db,
            provider=payload.provider,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/masking/sessions", response_model=List[TelephonyMaskingSessionResponse])
async def list_masking_sessions(
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    del api_key
    return (
        db.query(TelephonyMaskedSession)
        .filter(
            TelephonyMaskedSession.organization_id == organization_id,
            TelephonyMaskedSession.status == "active",
        )
        .order_by(TelephonyMaskedSession.created_at.desc())
        .all()
    )


@router.patch("/masking/sessions/{session_id}")
async def end_masking_session(
    session_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    del api_key
    try:
        telephony_service.end_masking_session(organization_id, session_id, db)
        return {"status": "ended"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


async def _read_webhook_params(request: Request) -> Dict[str, Any]:
    params: Dict[str, Any] = dict(request.query_params)
    try:
        form_data = await request.form()
        params.update(dict(form_data))
    except Exception:
        pass
    return params


@router.post("/webhooks/answer")
async def telephony_answer_webhook(request: Request, db: Session = Depends(get_db)):
    params = await _read_webhook_params(request)
    xml = telephony_service.handle_answer_webhook(params, db)
    return Response(content=xml, media_type="application/xml")


@router.post("/webhooks/events")
async def telephony_events_webhook(request: Request, db: Session = Depends(get_db)):
    params = await _read_webhook_params(request)
    telephony_service.handle_event_webhook(params, db)
    return {"status": "ok"}


@router.post("/webhooks/masking")
async def telephony_masking_webhook(request: Request, db: Session = Depends(get_db)):
    params = await _read_webhook_params(request)
    xml = telephony_service.handle_masking_webhook(params, db)
    return Response(content=xml, media_type="application/xml")
