"""Build WebSocket stream XML for inbound carrier answer webhooks."""

from __future__ import annotations

from typing import Any, Dict

from loguru import logger
from sqlalchemy.orm import Session

from app.services.telephony.inbound_media_session import prepare_inbound_media_session
from app.services.telephony.plivo_xml import reject_call, speak_and_hangup
from app.services.telephony.twilio_xml import stream_to_agent as twilio_stream_to_agent
from app.services.telephony.vobiz_xml import stream_to_agent as vobiz_stream_to_agent


def build_inbound_stream_answer_xml(
    db: Session,
    params: Dict[str, Any],
    *,
    provider_platform: str = "plivo",
) -> str:
    """Return Plivo/Vobiz-compatible XML that streams inbound audio to the voice agent."""
    to_number = params.get("To") or params.get("to")
    from_number = params.get("From") or params.get("from")
    call_uuid = (
        params.get("CallUUID")
        or params.get("CallSid")
        or params.get("call_sid")
        or params.get("Sid")
    )

    if not to_number:
        return speak_and_hangup("Call could not be routed.")

    prepared = prepare_inbound_media_session(
        db, params, provider_platform=provider_platform
    )
    if not prepared:
        logger.warning(
            "Inbound stream answer miss: to={} from={} call_uuid={}",
            to_number,
            from_number,
            call_uuid,
        )
        return reject_call("No active routing found for this number.")

    logger.info(
        "Inbound stream answer agent_id={} session={} to={} from={} call_uuid={}",
        prepared.agent_id,
        prepared.call_ref,
        to_number,
        from_number,
        call_uuid,
    )

    platform = (provider_platform or "plivo").lower()
    if platform == "twilio":
        return twilio_stream_to_agent(prepared.ws_url)
    return vobiz_stream_to_agent(prepared.ws_url, record_action_url=prepared.record_action_url)
