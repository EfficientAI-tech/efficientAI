"""Tests for observability call ingest helpers."""

from uuid import uuid4

from app.models.database import CallRecordingSource
from app.services.observability.call_ingest import persist_playground_voice_call


def test_persist_playground_voice_call_merges_live_transcript(db_session, org_id, default_workspace, make_agent):
    agent = make_agent()
    result_id = "882211"
    existing = persist_playground_voice_call(
        db_session,
        organization_id=org_id,
        workspace_id=default_workspace.id,
        agent_id=agent.id,
        result_id=result_id,
        call_metadata={"duration": 12.5},
        provider_platform="efficientai",
    )
    assert existing is not None
    existing.call_data = {
        **(existing.call_data or {}),
        "startedAt": "2026-08-07T09:18:00.000Z",
        "live_transcript": [
            {"role": "user", "content": "Hello there"},
            {"role": "agent", "content": "Hi, how can I help?"},
        ],
        "messages": [
            {"role": "user", "content": "Hello there"},
            {"role": "bot", "content": "Hi, how can I help?"},
        ],
    }
    db_session.commit()

    updated = persist_playground_voice_call(
        db_session,
        organization_id=org_id,
        workspace_id=default_workspace.id,
        agent_id=agent.id,
        result_id=result_id,
        call_metadata={
            "duration": 60.0,
            "trace_id": "abc123trace",
            "speaker_segments": [
                {"speaker": "user", "text": "Hello there", "start": 0.0, "end": 1.0},
            ],
        },
        provider_platform="efficientai",
    )

    assert updated is not None
    assert updated.agent_id == agent.id
    assert updated.trace_id == "abc123trace"
    assert updated.call_event == "call_ended"
    assert updated.source == CallRecordingSource.PLAYGROUND

    call_data = updated.call_data
    assert len(call_data["messages"]) == 2
    assert call_data["messages"][0]["content"] == "Hello there"
    assert call_data["messages"][1]["content"] == "Hi, how can I help?"
    assert call_data.get("endedAt")
    assert call_data.get("startedAt") == "2026-08-07T09:18:00.000Z"


def test_persist_playground_voice_call_sets_agent_on_create(db_session, org_id, default_workspace, make_agent):
    agent = make_agent()
    recording = persist_playground_voice_call(
        db_session,
        organization_id=org_id,
        workspace_id=default_workspace.id,
        agent_id=agent.id,
        result_id=str(uuid4().int % 900000 + 100000),
        call_metadata={"transcription": "user spoke", "trace_id": "trace-xyz"},
    )
    assert recording is not None
    assert recording.agent_id == agent.id
    assert recording.trace_id == "trace-xyz"
