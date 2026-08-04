"""Tests for inbound evaluator result enqueue after telephony."""

from uuid import uuid4

from app.models.database import (
    Agent,
    CallRecording,
    CallRecordingSource,
    CallRecordingStatus,
    Evaluator,
    EvaluatorResult,
    Persona,
    Scenario,
)
from app.models.enums import EvaluatorResultStatus
from app.services.evaluators.evaluator_inbound_service import (
    enqueue_linked_evaluator_result_if_ready,
)


class _FakeAsyncResult:
    def __init__(self):
        self.id = "fake-celery-task-id"


def test_enqueue_linked_evaluator_result_copies_artifacts_and_dispatches(
    db_session, seed_org, default_workspace, monkeypatch
):
    org = seed_org
    workspace_id = default_workspace.id

    agent = Agent(
        organization_id=org.id,
        workspace_id=workspace_id,
        agent_id="111222",
        name="Inbound Agent",
        call_type="inbound",
        call_medium="phone_call",
    )
    db_session.add(agent)
    db_session.flush()

    persona = Persona(
        organization_id=org.id,
        workspace_id=workspace_id,
        name="Caller",
    )
    scenario = Scenario(
        organization_id=org.id,
        workspace_id=workspace_id,
        name="Greeting",
        agent_id=agent.id,
    )
    db_session.add_all([persona, scenario])
    db_session.flush()

    evaluator = Evaluator(
        evaluator_id="100001",
        organization_id=org.id,
        workspace_id=workspace_id,
        agent_id=agent.id,
        persona_id=persona.id,
        scenario_id=scenario.id,
    )
    db_session.add(evaluator)
    db_session.flush()

    result = EvaluatorResult(
        result_id="123456",
        organization_id=org.id,
        workspace_id=workspace_id,
        evaluator_id=evaluator.id,
        agent_id=agent.id,
        persona_id=persona.id,
        scenario_id=scenario.id,
        name="Greeting",
        status=EvaluatorResultStatus.QUEUED.value,
    )
    db_session.add(result)
    db_session.flush()

    recording = CallRecording(
        organization_id=org.id,
        workspace_id=workspace_id,
        call_short_id="654321",
        status=CallRecordingStatus.UPDATED,
        source=CallRecordingSource.WEBHOOK,
        call_event="call_ended",
        provider_platform="vobiz",
        provider_call_id=str(uuid4()),
        agent_id=agent.id,
        evaluator_result_id=result.id,
        call_data={
            "messages": [
                {"role": "assistant", "content": "Hello"},
                {"role": "user", "content": "Hi"},
            ],
            "recording_s3_key": "audio/org/eval/test.mp3",
            "duration_seconds": 42.0,
        },
    )
    db_session.add(recording)
    db_session.commit()

    delayed = []

    class _CapturingTask:
        def delay(self, result_id):
            delayed.append(result_id)
            return _FakeAsyncResult()

    import sys
    import types

    capturing_task = _CapturingTask()
    fake_celery_app = types.ModuleType("app.workers.celery_app")
    fake_celery_app.process_evaluator_result_task = capturing_task
    monkeypatch.setitem(sys.modules, "app.workers.celery_app", fake_celery_app)

    assert enqueue_linked_evaluator_result_if_ready(db_session, recording) is True
    assert len(delayed) == 1
    assert delayed[0] == str(result.id)

    db_session.refresh(result)
    assert result.celery_task_id == "fake-celery-task-id"
    assert "Caller: Hi" in (result.transcription or "")
    assert result.audio_s3_key == "audio/org/eval/test.mp3"
    assert result.duration_seconds == 42.0


def test_inbound_evaluator_persona_scenario_wired_into_call_session(
    db_session, seed_org, default_workspace, monkeypatch
):
    """Round-robin evaluator persona/scenario must reach call session and voice prompt."""
    from app.models.schemas import EvaluatorSuiteCreate
    from app.services.evaluators.evaluator_inbound_service import (
        consume_inbound_evaluator_combination,
        find_inbound_suite_for_agent,
    )
    from app.services.evaluators.evaluator_suite_service import (
        activate_evaluator_suite,
        create_evaluator_suite,
    )
    from app.services.telephony.vobiz_agent_context import (
        build_system_instruction,
        build_vobiz_ws_url,
    )
    from app.services.telephony.vobiz_session import create_call_session, get_call_session

    monkeypatch.setattr(
        "app.services.telephony.vobiz_agent_context.vobiz_webhook_base_url",
        lambda: "https://public.example.com",
    )
    monkeypatch.setattr(
        "app.services.media_urls.media_ws_base_url",
        lambda: "wss://public.example.com",
    )

    org = seed_org
    workspace_id = default_workspace.id

    agent = Agent(
        organization_id=org.id,
        workspace_id=workspace_id,
        agent_id="222333",
        name="Inbound Agent",
        call_type="inbound",
        call_medium="phone_call",
    )
    persona = Persona(
        organization_id=org.id,
        workspace_id=workspace_id,
        name="Eval Persona",
    )
    db_session.add(agent)
    db_session.add(persona)
    db_session.flush()

    scenario = Scenario(
        organization_id=org.id,
        workspace_id=workspace_id,
        name="Inbound wiring",
        agent_id=agent.id,
    )
    db_session.add(scenario)
    db_session.flush()

    suite_resp = create_evaluator_suite(
        db_session,
        org.id,
        workspace_id,
        EvaluatorSuiteCreate(
            agent_id=agent.id,
            persona_id=persona.id,
            scenario_ids=[scenario.id],
        ),
    )
    from app.models.database import EvaluatorSuite

    suite = db_session.query(EvaluatorSuite).filter(EvaluatorSuite.id == suite_resp.id).one()
    activate_evaluator_suite(db_session, suite)

    found = find_inbound_suite_for_agent(db_session, agent, org.id, workspace_id)
    assert found is not None
    selected, _idx, _next_idx = consume_inbound_evaluator_combination(db_session, found)

    session = create_call_session(
        agent_id=str(agent.id),
        organization_id=str(org.id),
        direction="inbound",
        from_number="+919111111111",
        to_number="+919876543210",
        persona_id=str(selected.persona_id) if selected.persona_id else None,
        scenario_id=str(selected.scenario_id) if selected.scenario_id else None,
        evaluator_id=str(selected.id),
    )

    stored = get_call_session(session.call_ref)
    assert stored is not None
    assert stored.persona_id == str(persona.id)
    assert stored.scenario_id == str(scenario.id)

    ws_url = build_vobiz_ws_url(
        agent_id=str(agent.id),
        session=session.call_ref,
        persona_id=stored.persona_id,
        scenario_id=stored.scenario_id,
    )
    assert f"persona_id={persona.id}" in ws_url
    assert f"scenario_id={scenario.id}" in ws_url

    instruction = build_system_instruction(
        db_session,
        agent=agent,
        organization_id=org.id,
        workspace_id=workspace_id,
        persona_id=stored.persona_id,
        scenario_id=stored.scenario_id,
    )
    assert instruction is not None
    assert persona.name in instruction
    assert scenario.name in instruction


def test_enqueue_skips_when_no_artifacts(db_session, seed_org, default_workspace):
    org = seed_org
    workspace_id = default_workspace.id

    result = EvaluatorResult(
        result_id="999888",
        organization_id=org.id,
        workspace_id=workspace_id,
        name="Empty",
        status=EvaluatorResultStatus.QUEUED.value,
    )
    db_session.add(result)
    db_session.flush()

    recording = CallRecording(
        organization_id=org.id,
        workspace_id=workspace_id,
        call_short_id="111111",
        status=CallRecordingStatus.PENDING,
        source=CallRecordingSource.WEBHOOK,
        evaluator_result_id=result.id,
        call_data={},
    )
    db_session.add(recording)
    db_session.commit()

    assert enqueue_linked_evaluator_result_if_ready(db_session, recording) is False
