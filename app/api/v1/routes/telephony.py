"""Telephony API routes (provider-agnostic)."""

from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.dependencies import get_api_key, get_db, get_organization_id
from app.models.database import TelephonyIntegration, TelephonyMaskedSession, TelephonyDialTarget
from app.models.schemas import (
    TelephonyIntegrationCreate,
    TelephonyIntegrationResponse,
    TelephonyIntegrationUpdate,
    TelephonyDialTargetCreate,
    TelephonyDialTargetResponse,
    TelephonyDialTargetUpdate,
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
from app.services.telephony.number_import_service import import_numbers, list_available_numbers
from app.services.telephony.plivo_client import normalize_e164
from app.services.telephony.webhook_auth import verify_plivo_webhook
from app.services.telephony.platform_outbound_pool import outbound_pool_api_payload

router = APIRouter(prefix="/telephony", tags=["Telephony"])


class TelephonyAvailableNumberResponse(BaseModel):
    e164: str
    provider_number_id: Optional[str] = None
    country: Optional[str] = None
    region: Optional[str] = None
    capabilities: Optional[Dict[str, Any]] = None
    status: Optional[str] = None
    application_id: Optional[str] = None
    already_imported: bool = False
    imported_number_id: Optional[str] = None


class TelephonyImportNumbersRequest(BaseModel):
    provider: str
    numbers: List[str]
    agent_id: Optional[UUID] = None
    credential_id: Optional[UUID] = None


class TelephonyImportNumberResult(BaseModel):
    number: str
    success: bool
    message: str
    answer_url: str
    webhook_configured: Optional[bool] = None
    imported_number_id: Optional[str] = None
    application_id: Optional[str] = None


class TelephonyImportNumbersResponse(BaseModel):
    provider: str
    results: List[TelephonyImportNumberResult]
    answer_url: str


class PlatformOutboundPoolNumberResponse(BaseModel):
    phone_number: str
    provider: str


class PlatformOutboundPoolResponse(BaseModel):
    numbers: List[PlatformOutboundPoolNumberResponse]
    max_concurrent_per_org: int
    shared_across_orgs: bool = True


@router.get("/outbound-pool", response_model=PlatformOutboundPoolResponse)
async def get_platform_outbound_pool(
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
):
    del organization_id, api_key
    return PlatformOutboundPoolResponse(**outbound_pool_api_payload())


@router.post("/config", response_model=TelephonyIntegrationResponse, status_code=status.HTTP_201_CREATED)
async def create_telephony_config(
    data: TelephonyIntegrationCreate,
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    """Create a new telephony credential row.

    Multiple credentials per provider are supported. The first row for a
    given (org, provider) is auto-promoted to default. ``POST`` always
    inserts a new row; use ``PUT /telephony/config`` (with ``id``) to
    update an existing one.
    """
    del api_key
    try:
        return telephony_service.save_integration(
            organization_id,
            data.model_dump(),
            db,
            allow_implicit_update=False,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/configs", response_model=List[TelephonyIntegrationResponse])
async def list_telephony_configs(
    provider: Optional[str] = None,
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    """List every TelephonyIntegration row for this org (newest first).

    Optional ``provider`` filter narrows the list to a single provider.
    """
    del api_key
    return telephony_service.list_org_integrations(organization_id, db, provider=provider)


@router.get("/config", response_model=TelephonyIntegrationResponse)
async def get_telephony_config(
    provider: str = "plivo",
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    """Resolve the default (or only) telephony config for ``provider``."""
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
    """Update a telephony credential.

    When ``data.id`` is provided the named row is updated in place. When
    omitted, the legacy single-row-per-provider flow is preserved (only
    works while the org still has exactly one row for the provider).
    """
    del api_key
    try:
        return telephony_service.save_integration(
            organization_id,
            data.model_dump(exclude_none=True),
            db,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post(
    "/config/{integration_id}/set-default",
    response_model=TelephonyIntegrationResponse,
)
async def set_default_telephony_config(
    integration_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    """Mark this telephony credential as the default for its (org, provider)."""
    del api_key
    try:
        return telephony_service.set_default_integration(organization_id, integration_id, db)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete(
    "/config/{integration_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_telephony_config(
    integration_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    """Delete a telephony credential row.

    If the deleted row was the default, the most recently updated active
    row is auto-promoted in its place. Org-owned phone numbers linked to
    this credential are kept but unlinked so they can fall back to another
    credential or the platform account.
    """
    del api_key
    try:
        telephony_service.delete_integration(organization_id, integration_id, db)
    except ValueError as e:
        if str(e) == "Telephony integration not found":
            raise HTTPException(status_code=404, detail=str(e)) from e
        raise HTTPException(status_code=400, detail=str(e)) from e
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/numbers", response_model=List[TelephonyPhoneNumberResponse])
async def list_telephony_numbers(
    provider: Optional[str] = None,
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    del api_key
    return telephony_service.list_numbers_enriched(organization_id, db, provider=provider)


@router.delete("/numbers/{number_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_telephony_number(
    number_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    """Remove an org-owned phone number from inventory and unlink agents."""
    del api_key
    try:
        telephony_service.remove_org_phone_number(organization_id, number_id, db)
    except ValueError as e:
        message = str(e)
        if message == "Phone number not found":
            raise HTTPException(status_code=404, detail=message) from e
        status_code = (
            status.HTTP_409_CONFLICT
            if "active number-masking sessions" in message
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=status_code, detail=message) from e
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/numbers/available", response_model=List[TelephonyAvailableNumberResponse])
async def list_available_telephony_numbers(
    provider: str,
    credential_id: Optional[UUID] = None,
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    """List remote numbers on a telephony provider account with org import status."""
    del api_key
    try:
        return list_available_numbers(
            db,
            organization_id,
            provider,
            credential_id=credential_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/numbers/import", response_model=TelephonyImportNumbersResponse)
async def import_telephony_numbers(
    payload: TelephonyImportNumbersRequest,
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    """Import selected numbers from a telephony provider into org inventory."""
    del api_key
    try:
        result = import_numbers(
            db,
            organization_id,
            payload.provider,
            numbers=payload.numbers,
            agent_id=payload.agent_id,
            credential_id=payload.credential_id,
        )
        return TelephonyImportNumbersResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/dial-targets", response_model=List[TelephonyDialTargetResponse])
async def list_dial_targets(
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    del api_key
    return (
        db.query(TelephonyDialTarget)
        .filter(TelephonyDialTarget.organization_id == organization_id)
        .order_by(TelephonyDialTarget.label.asc().nullslast(), TelephonyDialTarget.created_at.desc())
        .all()
    )


@router.post("/dial-targets", response_model=TelephonyDialTargetResponse, status_code=status.HTTP_201_CREATED)
async def create_dial_target(
    payload: TelephonyDialTargetCreate,
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    del api_key
    try:
        phone_number = normalize_e164(payload.phone_number)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    existing = (
        db.query(TelephonyDialTarget)
        .filter(
            TelephonyDialTarget.organization_id == organization_id,
            TelephonyDialTarget.phone_number == phone_number,
        )
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="This number is already saved for your organization")

    row = TelephonyDialTarget(
        organization_id=organization_id,
        phone_number=phone_number,
        label=payload.label.strip() if payload.label and payload.label.strip() else None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.put("/dial-targets/{target_id}", response_model=TelephonyDialTargetResponse)
async def update_dial_target(
    target_id: UUID,
    payload: TelephonyDialTargetUpdate,
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    del api_key
    row = (
        db.query(TelephonyDialTarget)
        .filter(
            TelephonyDialTarget.id == target_id,
            TelephonyDialTarget.organization_id == organization_id,
        )
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Dial target not found")

    if payload.phone_number is not None:
        try:
            phone_number = normalize_e164(payload.phone_number)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        duplicate = (
            db.query(TelephonyDialTarget)
            .filter(
                TelephonyDialTarget.organization_id == organization_id,
                TelephonyDialTarget.phone_number == phone_number,
                TelephonyDialTarget.id != target_id,
            )
            .first()
        )
        if duplicate:
            raise HTTPException(status_code=409, detail="This number is already saved for your organization")
        row.phone_number = phone_number

    if payload.label is not None:
        row.label = payload.label.strip() if payload.label.strip() else None

    db.commit()
    db.refresh(row)
    return row


@router.delete("/dial-targets/{target_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_dial_target(
    target_id: UUID,
    organization_id: UUID = Depends(get_organization_id),
    api_key: str = Depends(get_api_key),
    db: Session = Depends(get_db),
):
    del api_key
    row = (
        db.query(TelephonyDialTarget)
        .filter(
            TelephonyDialTarget.id == target_id,
            TelephonyDialTarget.organization_id == organization_id,
        )
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Dial target not found")
    db.delete(row)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
    verify_plivo_webhook(request, params, "answer", db)
    xml = telephony_service.handle_answer_webhook(params, db)
    return Response(content=xml, media_type="application/xml")


@router.post("/webhooks/events")
async def telephony_events_webhook(request: Request, db: Session = Depends(get_db)):
    params = await _read_webhook_params(request)
    verify_plivo_webhook(request, params, "events", db)
    telephony_service.handle_event_webhook(params, db)
    return {"status": "ok"}


@router.post("/webhooks/masking")
async def telephony_masking_webhook(request: Request, db: Session = Depends(get_db)):
    params = await _read_webhook_params(request)
    verify_plivo_webhook(request, params, "masking", db)
    xml = telephony_service.handle_masking_webhook(params, db)
    return Response(content=xml, media_type="application/xml")
