"""Build WebSocket stream XML for inbound carrier answer webhooks."""

from __future__ import annotations

from typing import Any, Dict, Optional
from uuid import UUID

from loguru import logger
from sqlalchemy.orm import Session

from app.config import settings
from app.models.database import Agent
from app.services.telephony.call_recording_lifecycle import (
    create_inbound_call_recording,
    link_provider_call_id,
)
from app.services.telephony.phone_routing import resolve_inbound_agent_for_number
from app.services.telephony.plivo_xml import reject_call, speak_and_hangup
from app.services.telephony.vobiz_agent_context import build_carrier_ws_url, vobiz_webhook_base_url
from app.services.telephony.vobiz_session import create_call_session
from app.services.telephony.vobiz_xml import stream_to_agent


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

    agent_id, organization_id = resolve_inbound_agent_for_number(db, to_number)
    if not agent_id or not organization_id:
        logger.warning(
            "Inbound stream answer miss: to={} from={} call_uuid={}",
            to_number,
            from_number,
            call_uuid,
        )
        return reject_call("No active routing found for this number.")

    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        return reject_call("No active routing found for this number.")

    inbound_evaluator_id: Optional[UUID] = None
    inbound_evaluator_result_id: Optional[UUID] = None
    inbound_persona_id: Optional[UUID] = None
    inbound_scenario_id: Optional[UUID] = None
    if agent.workspace_id:
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
        from_number=from_number,
        to_number=to_number,
        persona_id=str(inbound_persona_id) if inbound_persona_id else None,
        scenario_id=str(inbound_scenario_id) if inbound_scenario_id else None,
        evaluator_id=str(inbound_evaluator_id) if inbound_evaluator_id else None,
    )

    create_inbound_call_recording(
        db,
        agent=agent,
        organization_id=organization_id,
        call_ref=session.call_ref,
        from_number=from_number,
        to_number=to_number,
        provider_call_id=call_uuid,
        evaluator_id=inbound_evaluator_id,
        evaluator_result_id=inbound_evaluator_result_id,
        provider_platform=provider_platform,
    )

    if call_uuid:
        link_provider_call_id(db, call_ref=session.call_ref, provider_call_id=call_uuid)

    ws_url = build_carrier_ws_url(
        agent_id=str(agent_id),
        session=session.call_ref,
        persona_id=str(inbound_persona_id) if inbound_persona_id else None,
        scenario_id=str(inbound_scenario_id) if inbound_scenario_id else None,
    )

    record_action_url = None
    if settings.VOBIZ_CARRIER_SESSION_RECORDING and provider_platform == "vobiz":
        record_action_url = (
            f"{vobiz_webhook_base_url()}{settings.API_V1_PREFIX}/telephony/vobiz/webhooks/recording-ready"
            f"?call_ref={session.call_ref}"
        )

    logger.info(
        "Inbound stream answer agent_id={} session={} to={} from={} call_uuid={}",
        agent_id,
        session.call_ref,
        to_number,
        from_number,
        call_uuid,
    )

    return stream_to_agent(ws_url, record_action_url=record_action_url)
