"""Business logic for telephony provider flows (provider-agnostic)."""

import random
import string
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from loguru import logger
from sqlalchemy.orm import Session

from app.config import settings
from app.core.encryption import decrypt_api_key, encrypt_api_key
from app.models.database import (
    Agent,
    CallRecording,
    CallRecordingSource,
    TelephonyIntegration,
    TelephonyMaskedSession,
    TelephonyPhoneNumber,
    TelephonyVerifySession,
)
from app.models.enums import CallRecordingStatus
from app.services.telephony.exotel_client import ExotelClient
from app.services.telephony.plivo_client import PlivoClient, normalize_e164
from app.services.telephony.plivo_xml import dial_number, reject_call, speak_and_hangup


class TelephonyService:
    """Encapsulates telephony business operations for API routes."""

    def get_org_integration(
        self, org_id: UUID, db: Session, provider: str = "plivo"
    ) -> TelephonyIntegration:
        integration = (
            db.query(TelephonyIntegration)
            .filter(
                TelephonyIntegration.organization_id == org_id,
                TelephonyIntegration.provider == provider,
                TelephonyIntegration.is_active.is_(True),
            )
            .first()
        )
        if not integration:
            raise ValueError(f"Active {provider} telephony integration not found for organization")
        return integration

    def get_provider_client(self, org_id: UUID, db: Session, provider: str):
        integration = self.get_org_integration(org_id, db, provider=provider)
        auth_id = decrypt_api_key(integration.auth_id)
        auth_token = decrypt_api_key(integration.auth_token)
        provider_key = provider.lower()
        if provider_key == "plivo":
            return PlivoClient(auth_id=auth_id, auth_token=auth_token)
        if provider_key == "exotel":
            account_sid = (integration.voice_app_id or "").strip()
            if not account_sid:
                raise ValueError("voice_app_id (Exotel Account SID) is required for Exotel")
            return ExotelClient(
                auth_id=auth_id,
                auth_token=auth_token,
                account_sid=account_sid,
                subdomain=integration.sip_domain or None,
            )
        raise ValueError(f"Unsupported telephony provider: {provider}")

    def save_integration(
        self, org_id: UUID, data: Dict[str, Any], db: Session
    ) -> TelephonyIntegration:
        provider = data.get("provider", "plivo")
        integration = (
            db.query(TelephonyIntegration)
            .filter(
                TelephonyIntegration.organization_id == org_id,
                TelephonyIntegration.provider == provider,
            )
            .first()
        )
        encrypted_auth_id = encrypt_api_key(data["auth_id"]) if data.get("auth_id") else None
        encrypted_auth_token = encrypt_api_key(data["auth_token"]) if data.get("auth_token") else None
        effective_voice_app_id = (
            data.get("voice_app_id")
            if "voice_app_id" in data
            else (integration.voice_app_id if integration else None)
        )
        if provider.lower() == "exotel" and not effective_voice_app_id:
            raise ValueError("voice_app_id (Exotel Account SID) is required for Exotel")

        if integration:
            if encrypted_auth_id:
                integration.auth_id = encrypted_auth_id
            if encrypted_auth_token:
                integration.auth_token = encrypted_auth_token
            if "verify_app_uuid" in data:
                integration.verify_app_uuid = data.get("verify_app_uuid")
            if "voice_app_id" in data:
                integration.voice_app_id = data.get("voice_app_id")
            if "sip_domain" in data:
                integration.sip_domain = data.get("sip_domain")
            if "masking_config" in data:
                integration.masking_config = data.get("masking_config")
            if "is_active" in data:
                integration.is_active = bool(data.get("is_active"))
        else:
            if not encrypted_auth_id or not encrypted_auth_token:
                raise ValueError("auth_id and auth_token are required for first-time setup")
            integration = TelephonyIntegration(
                organization_id=org_id,
                provider=provider,
                auth_id=encrypted_auth_id,
                auth_token=encrypted_auth_token,
                verify_app_uuid=data.get("verify_app_uuid"),
                voice_app_id=data.get("voice_app_id"),
                sip_domain=data.get("sip_domain"),
                masking_config=data.get("masking_config"),
                is_active=bool(data.get("is_active", True)),
            )
            db.add(integration)

        db.commit()
        db.refresh(integration)
        return integration

    def test_connection(self, org_id: UUID, db: Session, provider: str = "plivo") -> bool:
        client = self.get_provider_client(org_id, db, provider=provider)
        ok = client.test_connection()
        integration = self.get_org_integration(org_id, db, provider=provider)
        integration.last_tested_at = datetime.now(timezone.utc)
        db.commit()
        return ok

    def sync_numbers(self, org_id: UUID, db: Session, provider: str = "plivo") -> List[TelephonyPhoneNumber]:
        client = self.get_provider_client(org_id, db, provider=provider)
        integration = self.get_org_integration(org_id, db, provider=provider)
        numbers = client.list_numbers()
        synced: List[TelephonyPhoneNumber] = []

        for num in numbers:
            raw = num.get("number") or num.get("phone_number")
            if not raw:
                continue
            phone_number = normalize_e164(raw)
            existing = (
                db.query(TelephonyPhoneNumber)
                .filter(
                    TelephonyPhoneNumber.organization_id == org_id,
                    TelephonyPhoneNumber.phone_number == phone_number,
                )
                .first()
            )
            payload = {
                "country_iso2": num.get("country_iso"),
                "region": num.get("region"),
                "number_type": num.get("number_type"),
                "capabilities": num.get("capabilities") or {},
                "provider_app_id": num.get("app_id"),
                "is_active": True,
            }
            if existing:
                existing.telephony_integration_id = integration.id
                for key, value in payload.items():
                    setattr(existing, key, value)
                synced.append(existing)
            else:
                row = TelephonyPhoneNumber(
                    organization_id=org_id,
                    telephony_integration_id=integration.id,
                    phone_number=phone_number,
                    **payload,
                )
                db.add(row)
                synced.append(row)

        db.commit()
        return synced

    def list_numbers(self, org_id: UUID, db: Session, provider: Optional[str] = None) -> List[TelephonyPhoneNumber]:
        query = db.query(TelephonyPhoneNumber).filter(TelephonyPhoneNumber.organization_id == org_id)
        if provider:
            query = query.join(
                TelephonyIntegration,
                TelephonyIntegration.id == TelephonyPhoneNumber.telephony_integration_id,
            ).filter(TelephonyIntegration.provider == provider)
        return query.order_by(TelephonyPhoneNumber.created_at.desc()).all()

    def initiate_outbound_call(
        self, org_id: UUID, from_number: str, to_number: str, agent_id: Optional[UUID], db: Session
    ) -> Dict[str, Any]:
        from_number = normalize_e164(from_number)
        to_number = normalize_e164(to_number)

        number_row = (
            db.query(TelephonyPhoneNumber)
            .filter(
                TelephonyPhoneNumber.organization_id == org_id,
                TelephonyPhoneNumber.phone_number == from_number,
                TelephonyPhoneNumber.is_active.is_(True),
            )
            .first()
        )
        if not number_row:
            raise ValueError("from_number is not registered to this organization")

        integration = (
            db.query(TelephonyIntegration)
            .filter(
                TelephonyIntegration.id == number_row.telephony_integration_id,
                TelephonyIntegration.organization_id == org_id,
            )
            .first()
        )
        if not integration:
            raise ValueError("No active telephony integration found for from_number")
        client = self.get_provider_client(org_id, db, provider=integration.provider)

        base = settings.PLIVO_WEBHOOK_BASE_URL.rstrip("/")
        answer_url = f"{base}{settings.API_V1_PREFIX}/telephony/webhooks/answer"
        hangup_url = f"{base}{settings.API_V1_PREFIX}/telephony/webhooks/events"
        response = client.create_outbound_call(
            from_=from_number, to_=to_number, answer_url=answer_url, hangup_url=hangup_url
        )

        call_short_id = "".join(random.choices(string.digits, k=6))
        call_uuid = response.get("request_uuid") or response.get("message_uuid") or response.get("api_id")
        db.add(
            CallRecording(
                organization_id=org_id,
                call_short_id=call_short_id,
                status=CallRecordingStatus.PENDING,
                source=CallRecordingSource.WEBHOOK,
                call_event="outbound_initiated",
                call_data=response,
                provider_call_id=call_uuid,
                provider_platform=integration.provider,
                agent_id=agent_id,
            )
        )
        db.commit()
        return response

    def start_voice_otp(
        self, org_id: UUID, phone_number: str, api_key: str, db: Session, provider: str = "plivo"
    ) -> TelephonyVerifySession:
        del api_key
        integration = self.get_org_integration(org_id, db, provider=provider)
        app_uuid = integration.verify_app_uuid or settings.PLIVO_VERIFY_APP_UUID
        if not app_uuid:
            raise ValueError("verify_app_uuid is not configured for voice OTP")

        recipient = normalize_e164(phone_number)
        callback_url = None
        if settings.PLIVO_WEBHOOK_BASE_URL:
            base = settings.PLIVO_WEBHOOK_BASE_URL.rstrip("/")
            callback_url = f"{base}{settings.API_V1_PREFIX}/telephony/webhooks/events"

        response = self.get_provider_client(org_id, db, provider=provider).start_voice_verification(
            recipient=recipient, app_uuid=app_uuid, callback_url=callback_url
        )

        session_uuid = response.get("session_uuid") or response.get("session_uuid4")
        if not session_uuid:
            raise ValueError("Verify response missing session UUID")

        session = TelephonyVerifySession(
            organization_id=org_id,
            provider_session_uuid=session_uuid,
            recipient_number=recipient,
            channel="voice",
            status=response.get("status", "pending"),
            verify_app_uuid=app_uuid,
            initiated_by="api",
        )
        db.add(session)
        db.commit()
        db.refresh(session)
        return session

    def check_voice_otp(
        self, org_id: UUID, session_id: UUID, otp_code: str, db: Session, provider: str = "plivo"
    ) -> Tuple[bool, str]:
        session = (
            db.query(TelephonyVerifySession)
            .filter(
                TelephonyVerifySession.id == session_id,
                TelephonyVerifySession.organization_id == org_id,
            )
            .first()
        )
        if not session:
            raise ValueError("Verification session not found")

        result = self.get_provider_client(org_id, db, provider=provider).check_verification(
            session_uuid=session.provider_session_uuid,
            otp_code=otp_code.strip(),
        )
        status_value = (result.get("status") or "").lower()
        verified = status_value in {"success", "verified", "approved", "valid"}

        session.status = "verified" if verified else "failed"
        if verified:
            session.verified_at = datetime.now(timezone.utc)
        db.commit()
        return verified, result.get("message", "Verification processed")

    def create_masking_session(
        self,
        org_id: UUID,
        party_a: str,
        party_b: str,
        expires_in_minutes: int,
        metadata: Optional[Dict[str, Any]],
        db: Session,
        provider: str = "plivo",
    ) -> TelephonyMaskedSession:
        integration = self.get_org_integration(org_id, db, provider=provider)
        party_a = normalize_e164(party_a)
        party_b = normalize_e164(party_b)

        active_ids = (
            db.query(TelephonyMaskedSession.masked_number_id)
            .filter(
                TelephonyMaskedSession.organization_id == org_id,
                TelephonyMaskedSession.status == "active",
            )
            .subquery()
        )
        number = (
            db.query(TelephonyPhoneNumber)
            .filter(
                TelephonyPhoneNumber.organization_id == org_id,
                TelephonyPhoneNumber.is_masking_pool.is_(True),
                TelephonyPhoneNumber.is_active.is_(True),
                ~TelephonyPhoneNumber.id.in_(active_ids),
            )
            .first()
        )
        if not number:
            raise ValueError("No available masking pool number")

        expiry = datetime.now(timezone.utc) + timedelta(minutes=max(expires_in_minutes or 60, 1))
        session = TelephonyMaskedSession(
            organization_id=org_id,
            telephony_integration_id=integration.id,
            masked_number_id=number.id,
            masked_number=number.phone_number,
            party_a_number=party_a,
            party_b_number=party_b,
            status="active",
            expires_at=expiry,
            session_metadata=metadata or {},
        )
        db.add(session)
        db.commit()
        db.refresh(session)
        return session

    def end_masking_session(self, org_id: UUID, session_id: UUID, db: Session) -> None:
        session = (
            db.query(TelephonyMaskedSession)
            .filter(TelephonyMaskedSession.id == session_id, TelephonyMaskedSession.organization_id == org_id)
            .first()
        )
        if not session:
            raise ValueError("Masking session not found")
        session.status = "ended"
        session.ended_at = datetime.now(timezone.utc)
        db.commit()

    def handle_answer_webhook(self, params: Dict[str, Any], db: Session) -> str:
        to_number = params.get("To") or params.get("to")
        from_number = params.get("From") or params.get("from")
        call_uuid = (
            params.get("CallUUID")
            or params.get("CallSid")
            or params.get("call_sid")
            or params.get("Sid")
        )
        logger.info("Telephony answer webhook call_uuid={} to={} from={}", call_uuid, to_number, from_number)

        if not to_number:
            return speak_and_hangup("Call could not be routed.")

        to_number = normalize_e164(to_number)
        number = db.query(TelephonyPhoneNumber).filter(TelephonyPhoneNumber.phone_number == to_number).first()
        if not number:
            return reject_call("This number is not configured.")

        if number.agent_id:
            agent = db.query(Agent).filter(Agent.id == number.agent_id).first()
            if agent and agent.phone_number:
                try:
                    return dial_number(normalize_e164(agent.phone_number), to_number)
                except ValueError:
                    logger.warning("Agent {} has non-E.164 phone number", agent.id)

        return speak_and_hangup("No active routing found for this number.")

    def handle_event_webhook(self, params: Dict[str, Any], db: Session) -> None:
        call_uuid = (
            params.get("CallUUID")
            or params.get("RequestUUID")
            or params.get("CallSid")
            or params.get("call_sid")
            or params.get("Sid")
        )
        call_status = params.get("CallStatus") or params.get("Event") or params.get("Status")
        if not call_uuid:
            return

        row = db.query(CallRecording).filter(CallRecording.provider_call_id == call_uuid).first()
        if not row:
            return

        row.status = CallRecordingStatus.UPDATED
        row.call_event = (call_status or "updated").lower()
        current = row.call_data if isinstance(row.call_data, dict) else {}
        current["last_event"] = params
        row.call_data = current
        db.commit()

    def handle_masking_webhook(self, params: Dict[str, Any], db: Session) -> str:
        from_number = params.get("From")
        to_number = params.get("To")
        if not from_number or not to_number:
            return reject_call()

        from_number = normalize_e164(from_number)
        to_number = normalize_e164(to_number)
        now = datetime.now(timezone.utc)

        session = (
            db.query(TelephonyMaskedSession)
            .filter(
                TelephonyMaskedSession.masked_number == to_number,
                TelephonyMaskedSession.status == "active",
                ((TelephonyMaskedSession.party_a_number == from_number) | (TelephonyMaskedSession.party_b_number == from_number)),
            )
            .first()
        )

        if not session:
            return reject_call()
        if session.expires_at and session.expires_at < now:
            session.status = "expired"
            db.commit()
            return reject_call()

        target = session.party_b_number if from_number == session.party_a_number else session.party_a_number
        return dial_number(target, to_number)


telephony_service = TelephonyService()
