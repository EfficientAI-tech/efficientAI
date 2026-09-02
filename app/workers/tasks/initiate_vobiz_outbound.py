"""Celery task to initiate Vobiz outbound calls asynchronously."""

from __future__ import annotations

from uuid import UUID

from loguru import logger

from app.database import SessionLocal
from app.models.database import CallRecording
from app.services.telephony.vobiz_client import build_vobiz_client_for_org
from app.services.telephony.vobiz_outbound_pool import release_pool_slot
from app.services.telephony.vobiz_session import delete_call_session, get_call_session
from app.workers.config import celery_app


@celery_app.task(name="initiate_vobiz_outbound_call", bind=True, max_retries=2)
def initiate_vobiz_outbound_call_task(
    self,
    *,
    organization_id: str,
    call_ref: str,
    from_number: str,
    to_number: str,
    answer_url: str,
    events_url: str,
    used_pool: bool,
    call_recording_id: str,
) -> dict:
    org_uuid = UUID(organization_id)
    db = SessionLocal()
    try:
        row = db.query(CallRecording).filter(CallRecording.id == UUID(call_recording_id)).first()
        sip_headers = None
        if row:
            from efficientai.integrations.efficientai_traces.correlation import (
                build_outbound_sip_headers,
            )

            sip_headers = build_outbound_sip_headers(
                call_short_id=row.call_short_id,
                evaluator_result_id=str(row.evaluator_result_id) if row.evaluator_result_id else None,
                agent_id=str(row.agent_id) if row.agent_id else None,
            )
            data = row.call_data if isinstance(row.call_data, dict) else {}
            data["efficientai_sip_headers"] = sip_headers
            row.call_data = data
            db.commit()

        client, _ = build_vobiz_client_for_org(db, org_uuid)
        response = client.create_outbound_call(
            from_=from_number,
            to_=to_number,
            answer_url=answer_url,
            hangup_url=events_url,
            sip_headers=sip_headers,
        )
        call_uuid = (
            response.get("request_uuid")
            or response.get("message_uuid")
            or response.get("api_id")
            or response.get("call_uuid")
            or ""
        )

        row = db.query(CallRecording).filter(CallRecording.id == UUID(call_recording_id)).first()
        if row:
            row.provider_call_id = str(call_uuid) if call_uuid else None
            row.call_event = "ringing"
            data = row.call_data if isinstance(row.call_data, dict) else {}
            data.update(response)
            row.call_data = data
            db.commit()

        return {"status": "ok", "provider_call_id": str(call_uuid or "")}
    except Exception as exc:
        logger.error("Vobiz outbound initiation failed for call_ref={}: {}", call_ref, exc)
        row = db.query(CallRecording).filter(CallRecording.id == UUID(call_recording_id)).first()
        if row:
            row.call_event = "failed"
            data = row.call_data if isinstance(row.call_data, dict) else {}
            data["error"] = str(exc)
            row.call_data = data
            db.commit()
        session = get_call_session(call_ref)
        if session and used_pool:
            release_pool_slot(org_uuid)
        delete_call_session(call_ref)
        raise self.retry(exc=exc, countdown=5) from exc
    finally:
        db.close()
