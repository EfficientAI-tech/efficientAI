"""Shared inbound PSTN session setup before carrier media streaming."""

from __future__ import annotations

from dataclasses import dataclass
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
from app.services.telephony.vobiz_agent_context import build_carrier_ws_url, vobiz_webhook_base_url
from app.services.telephony.vobiz_session import create_call_session


@dataclass
class InboundMediaSession:
    ws_url: str
    call_ref: str
    agent_id: UUID
    organization_id: UUID
    telephony_integration_id: Optional[UUID]
    provider_call_id: Optional[str]
    record_action_url: Optional[str]


def prepare_inbound_media_session(
    db: Session,
    params: Dict[str, Any],
    *,
    provider_platform: str,
) -> Optional[InboundMediaSession]:
    to_number = params.get("To") or params.get("to")
    from_number = params.get("From") or params.get("from")
    call_uuid = (
        params.get("CallUUID")
        or params.get("CallSid")
        or params.get("call_sid")
        or params.get("call_control_id")
        or params.get("Sid")
    )

    if not to_number:
        logger.warning("Inbound media session missing To number")
        return None

    agent_id, organization_id, telephony_integration_id = resolve_inbound_agent_for_number(
        db, to_number
    )
    if not agent_id or not organization_id:
        logger.warning(
            "Inbound media session routing miss: to={} from={} call_uuid={}",
            to_number,
            from_number,
            call_uuid,
        )
        return None

    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        return None

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

        suite = find_inbound_suite_for_agent(db, agent, organization_id, agent.workspace_id)
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
        telephony_integration_id=telephony_integration_id,
    )

    if call_uuid:
        link_provider_call_id(db, call_ref=session.call_ref, provider_call_id=str(call_uuid))

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

    return InboundMediaSession(
        ws_url=ws_url,
        call_ref=session.call_ref,
        agent_id=agent_id,
        organization_id=organization_id,
        telephony_integration_id=telephony_integration_id,
        provider_call_id=str(call_uuid) if call_uuid else None,
        record_action_url=record_action_url,
    )
