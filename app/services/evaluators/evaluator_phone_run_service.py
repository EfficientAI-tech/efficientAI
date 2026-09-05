"""Phone-based evaluator suite runs (Vobiz outbound)."""

from typing import List, Optional, Tuple
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.database import Agent, Evaluator, Scenario
from app.models.schemas import EvaluatorResultResponse
from app.services.evaluators.evaluator_suite_service import generate_unique_result_id
from app.services.telephony.plivo_client import normalize_e164


def initiate_phone_evaluator_call(
    db: Session,
    organization_id: UUID,
    workspace_id: UUID,
    evaluator: Evaluator,
    agent: Agent,
    to_number: str,
    from_number: Optional[str] = None,
) -> Tuple[str, str, Optional[EvaluatorResultResponse]]:
    """Place a Vobiz outbound call for one evaluator combination.

    Returns (call_ref, call_short_id, evaluator_result_response).
    """
    import random
    import string

    from app.models.database import CallRecording, CallRecordingSource, EvaluatorResult, EvaluatorResultStatus
    from app.models.enums import CallRecordingStatus
    from app.config import settings
    from app.services.telephony.vobiz_outbound_pool import release_pool_slot, resolve_outbound_from_number
    from app.services.telephony.vobiz_session import create_call_session
    from app.services.telephony.vobiz_agent_context import vobiz_webhook_base_url
    from app.workers.tasks.initiate_vobiz_outbound import initiate_vobiz_outbound_call_task

    scenario = db.query(Scenario).filter(Scenario.id == evaluator.scenario_id).first()
    scenario_name = scenario.name if scenario else "Unknown Scenario"

    result_id = generate_unique_result_id(db)
    evaluator_result = EvaluatorResult(
        result_id=result_id,
        organization_id=organization_id,
        workspace_id=workspace_id,
        evaluator_id=evaluator.id,
        agent_id=evaluator.agent_id,
        persona_id=evaluator.persona_id,
        scenario_id=evaluator.scenario_id,
        name=scenario_name,
        status=EvaluatorResultStatus.CALL_INITIATING.value,
        audio_s3_key=None,
    )
    db.add(evaluator_result)
    db.commit()
    db.refresh(evaluator_result)

    try:
        from_number_resolved, used_pool, provider = resolve_outbound_from_number(
            db,
            organization_id,
            explicit_from_number=from_number,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    if provider != "vobiz":
        if used_pool:
            release_pool_slot(organization_id)
        raise HTTPException(
            status_code=400,
            detail=(
                f"Phone evaluator outbound requires a Vobiz caller ID; "
                f"resolved provider is {provider}."
            ),
        )

    to_number_norm = normalize_e164(to_number)
    persona_id = evaluator.persona_id
    scenario_id = evaluator.scenario_id
    evaluator_id = evaluator.id

    session = create_call_session(
        agent_id=str(agent.id),
        organization_id=str(organization_id),
        direction="outbound",
        from_number=from_number_resolved,
        to_number=to_number_norm,
        used_pool=used_pool,
        persona_id=str(persona_id) if persona_id else None,
        scenario_id=str(scenario_id) if scenario_id else None,
        evaluator_id=str(evaluator_id),
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
            "evaluator_id": str(evaluator_id),
            "evaluator_result_id": str(evaluator_result.id),
            "direction": "outbound",
            "from_number": from_number_resolved,
            "to_number": to_number_norm,
            "live_transcript": [],
        },
        provider_call_id=None,
        provider_platform="vobiz",
        agent_id=agent.id,
        evaluator_result_id=evaluator_result.id,
    )
    db.add(recording)
    db.commit()
    db.refresh(recording)

    initiate_vobiz_outbound_call_task.delay(
        organization_id=str(organization_id),
        call_ref=session.call_ref,
        from_number=from_number_resolved,
        to_number=to_number_norm,
        answer_url=answer_url,
        events_url=events_url,
        used_pool=used_pool,
        call_recording_id=str(recording.id),
    )

    return session.call_ref, call_short_id, EvaluatorResultResponse.model_validate(evaluator_result)


def run_phone_evaluator_batch(
    db: Session,
    organization_id: UUID,
    workspace_id: UUID,
    agent: Agent,
    evaluators: List[Evaluator],
    to_number: str,
    from_number: Optional[str] = None,
) -> Tuple[List[str], List[EvaluatorResultResponse]]:
    """Initiate phone calls for each evaluator in the list."""
    call_refs: List[str] = []
    results: List[EvaluatorResultResponse] = []
    for evaluator in evaluators:
        call_ref, _short_id, result = initiate_phone_evaluator_call(
            db,
            organization_id,
            workspace_id,
            evaluator,
            agent,
            to_number,
            from_number=from_number,
        )
        call_refs.append(call_ref)
        if result:
            results.append(result)
    return call_refs, results
