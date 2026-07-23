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
