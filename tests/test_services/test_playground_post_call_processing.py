"""Tests for atomic playground post-call processing."""

from uuid import uuid4

import pytest

from app.models.database import (
    Agent,
    CallRecording,
    CallRecordingSource,
    CallRecordingStatus,
    EvaluatorResult,
    EvaluatorResultStatus,
)
from app.services.playground.post_call_processing import (
    claim_playground_evaluator_result_slot,
    record_playground_post_call_usage_once,
)


@pytest.fixture
def playground_agent(db_session, org_id, default_workspace):
    agent = Agent(
        id=uuid4(),
        organization_id=org_id,
        workspace_id=default_workspace.id,
        name="Test Agent",
    )
    db_session.add(agent)
    db_session.commit()
    return agent


def _make_playground_recording(db_session, *, org_id, workspace_id, agent_id, **overrides):
    recording = CallRecording(
        id=overrides.get("id", uuid4()),
        organization_id=org_id,
        workspace_id=workspace_id,
        call_short_id=overrides.get("call_short_id", "654321"),
        status=CallRecordingStatus.UPDATED,
        source=CallRecordingSource.PLAYGROUND,
        call_data=overrides.get("call_data", {}),
        provider_call_id=overrides.get("provider_call_id", "provider-call-1"),
        provider_platform=overrides.get("provider_platform", "retell"),
        agent_id=agent_id,
        evaluator_result_id=overrides.get("evaluator_result_id"),
    )
    db_session.add(recording)
    db_session.commit()
    db_session.refresh(recording)
    return recording


def test_record_playground_post_call_usage_once_is_idempotent(
    db_session, org_id, default_workspace, playground_agent, monkeypatch
):
    recording = _make_playground_recording(
        db_session,
        org_id=org_id,
        workspace_id=default_workspace.id,
        agent_id=playground_agent.id,
        call_data={"call_status": "ended"},
    )
    call_metrics = {"call_status": "ended", "duration_seconds": 42}
    calls = []

    monkeypatch.setattr(
        "app.services.usage.external_agent_usage.apply_playground_provider_usage_from_call_data",
        lambda **kwargs: calls.append(kwargs),
    )

    proceed, updated = record_playground_post_call_usage_once(
        db_session,
        recording.id,
        provider_platform="retell",
        call_metrics=call_metrics,
    )
    assert proceed is True
    assert updated["external_usage_recorded"] is True
    assert len(calls) == 1

    proceed_again, updated_again = record_playground_post_call_usage_once(
        db_session,
        recording.id,
        provider_platform="retell",
        call_metrics=call_metrics,
    )
    assert proceed_again is True
    assert updated_again["external_usage_recorded"] is True
    assert len(calls) == 1


def test_record_playground_post_call_usage_once_skips_when_evaluator_linked(
    db_session, org_id, default_workspace, playground_agent, monkeypatch
):
    existing = EvaluatorResult(
        id=uuid4(),
        result_id="111111",
        organization_id=org_id,
        workspace_id=default_workspace.id,
        agent_id=playground_agent.id,
        name="Existing",
        status=EvaluatorResultStatus.COMPLETED.value,
    )
    db_session.add(existing)
    db_session.flush()

    recording = _make_playground_recording(
        db_session,
        org_id=org_id,
        workspace_id=default_workspace.id,
        agent_id=playground_agent.id,
        evaluator_result_id=existing.id,
    )

    def _fail_apply(**_kwargs):
        raise AssertionError("usage should not be recorded when evaluator already exists")

    monkeypatch.setattr(
        "app.services.usage.external_agent_usage.apply_playground_provider_usage_from_call_data",
        _fail_apply,
    )

    proceed, _ = record_playground_post_call_usage_once(
        db_session,
        recording.id,
        provider_platform="retell",
        call_metrics={"call_status": "ended"},
    )
    assert proceed is False


def test_claim_playground_evaluator_result_slot_skips_after_evaluator_linked(
    db_session, org_id, default_workspace, playground_agent
):
    recording = _make_playground_recording(
        db_session,
        org_id=org_id,
        workspace_id=default_workspace.id,
        agent_id=playground_agent.id,
    )

    locked = claim_playground_evaluator_result_slot(db_session, recording.id)
    assert locked is not None

    evaluator_result = EvaluatorResult(
        result_id="222222",
        organization_id=locked.organization_id,
        workspace_id=locked.workspace_id,
        agent_id=locked.agent_id,
        name="Voice AI Call",
        status=EvaluatorResultStatus.QUEUED.value,
    )
    db_session.add(evaluator_result)
    db_session.flush()
    locked.evaluator_result_id = evaluator_result.id
    db_session.commit()

    locked_again = claim_playground_evaluator_result_slot(db_session, recording.id)
    assert locked_again is None

    assert (
        db_session.query(EvaluatorResult)
        .filter(EvaluatorResult.id == evaluator_result.id)
        .count()
        == 1
    )


def test_record_playground_post_call_usage_once_retries_when_apply_fails(
    db_session, org_id, default_workspace, playground_agent, monkeypatch
):
    recording = _make_playground_recording(
        db_session,
        org_id=org_id,
        workspace_id=default_workspace.id,
        agent_id=playground_agent.id,
        call_data={"call_status": "ended"},
    )
    apply_attempts = {"count": 0}

    def _apply_fail_once(**kwargs):
        apply_attempts["count"] += 1
        if apply_attempts["count"] == 1:
            raise RuntimeError("simulated apply failure")

    monkeypatch.setattr(
        "app.services.usage.external_agent_usage.apply_playground_provider_usage_from_call_data",
        _apply_fail_once,
    )

    proceed, _ = record_playground_post_call_usage_once(
        db_session,
        recording.id,
        provider_platform="retell",
        call_metrics={"call_status": "ended", "duration_seconds": 42},
    )
    assert proceed is False

    db_session.refresh(recording)
    assert not (recording.call_data or {}).get("external_usage_recorded")

    proceed, updated = record_playground_post_call_usage_once(
        db_session,
        recording.id,
        provider_platform="retell",
        call_metrics={"call_status": "ended", "duration_seconds": 42},
    )
    assert proceed is True
    assert updated["external_usage_recorded"] is True
    assert apply_attempts["count"] == 2
