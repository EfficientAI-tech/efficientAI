"""Tests for Vobiz call recording lifecycle helpers."""

from uuid import uuid4

from app.models.database import CallRecording, CallRecordingSource
from app.models.enums import CallRecordingStatus
from app.services.telephony.call_recording_lifecycle import (
    append_live_transcript_turn,
    conversation_turns_to_messages,
    finalize_call_on_media_disconnect,
    find_call_recording,
    link_provider_call_id,
    persist_telephony_call_artifacts,
    update_call_from_vobiz_event,
)


def _make_vobiz_recording(
    db_session,
    org_id,
    *,
    workspace_id,
    call_ref: str,
    provider_call_id=None,
    call_event="call_in_progress",
):
    row = CallRecording(
        organization_id=org_id,
        workspace_id=workspace_id,
        call_short_id="123456",
        status=CallRecordingStatus.PENDING,
        source=CallRecordingSource.WEBHOOK,
        call_event=call_event,
        call_data={"call_ref": call_ref, "live_transcript": []},
        provider_call_id=provider_call_id,
        provider_platform="vobiz",
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row


def test_find_call_recording_matches_request_uuid_in_call_data(db_session, org_id, seed_org, default_workspace):
    call_ref = "ref-1"
    row = _make_vobiz_recording(
        db_session,
        org_id,
        workspace_id=default_workspace.id,
        call_ref=call_ref,
        provider_call_id="request-uuid-1",
        call_event="ringing",
    )
    row.call_data = {**row.call_data, "request_uuid": "request-uuid-1"}
    db_session.commit()

    found = find_call_recording(db_session, provider_call_id="request-uuid-1")
    assert found is not None
    assert found.id == row.id


def test_link_provider_call_id_updates_row(db_session, org_id, seed_org, default_workspace):
    call_ref = "ref-2"
    row = _make_vobiz_recording(
        db_session,
        org_id,
        workspace_id=default_workspace.id,
        call_ref=call_ref,
        provider_call_id="request-uuid-2",
    )

    linked = link_provider_call_id(db_session, call_ref=call_ref, provider_call_id="call-uuid-2")
    assert linked is not None
    assert linked.provider_call_id == "call-uuid-2"
    assert linked.call_data["call_uuid"] == "call-uuid-2"


def test_finalize_call_on_media_disconnect_marks_call_ended(db_session, org_id, seed_org, default_workspace):
    call_ref = "ref-3"
    _make_vobiz_recording(
        db_session,
        org_id,
        workspace_id=default_workspace.id,
        call_ref=call_ref,
        call_event="call_in_progress",
    )

    result = finalize_call_on_media_disconnect(db_session, call_ref=call_ref)
    assert result is not None
    assert result.call_event == "call_ended"
    assert result.call_data.get("ended_at")


def test_resolve_telephony_messages_prefers_live_user_turns():
    from app.services.telephony.call_recording_lifecycle import resolve_telephony_messages

    messages = resolve_telephony_messages(
        live_transcript=[
            {"role": "user", "content": "Hello", "timestamp": "2026-01-01T00:00:00+00:00"},
            {"role": "agent", "content": "Hi there", "timestamp": "2026-01-01T00:00:01+00:00"},
        ],
        conversation_turns=[
            {"speaker": "assistant", "text": "Hi there", "start": 0.0},
        ],
    )
    assert len(messages) == 2
    assert messages[0]["role"] == "user"
    assert messages[1]["role"] == "assistant"


def test_append_live_transcript_turn_persists_to_db(db_session, org_id, seed_org, default_workspace):
    call_ref = "ref-append"
    row = _make_vobiz_recording(
        db_session,
        org_id,
        workspace_id=default_workspace.id,
        call_ref=call_ref,
    )

    append_live_transcript_turn(
        db_session,
        call_short_id=row.call_short_id,
        role="user",
        content="Hello there",
    )

    db_session.expire_all()
    updated = db_session.query(CallRecording).filter(CallRecording.id == row.id).first()
    assert len(updated.call_data["live_transcript"]) == 1
    assert updated.call_data["live_transcript"][0]["content"] == "Hello there"


def test_persist_telephony_call_artifacts_writes_messages(db_session, org_id, seed_org, default_workspace):
    call_ref = "ref-persist"
    row = _make_vobiz_recording(
        db_session,
        org_id,
        workspace_id=default_workspace.id,
        call_ref=call_ref,
    )

    persist_telephony_call_artifacts(
        db_session,
        call_short_id=row.call_short_id,
        conversation_turns=[
            {"speaker": "user", "text": "Hi", "start": 0.0},
            {"speaker": "assistant", "text": "Hello", "start": 1.0},
        ],
        s3_key="org/audio/call.wav",
        duration=12.5,
    )

    db_session.expire_all()
    updated = db_session.query(CallRecording).filter(CallRecording.id == row.id).first()
    assert len(updated.call_data["messages"]) == 2
    assert updated.call_data["recording_s3_key"] == "org/audio/call.wav"
    assert updated.call_data["ended_at"]


def test_conversation_turns_to_messages_maps_roles():
    messages = conversation_turns_to_messages(
        [
            {"speaker": "user", "text": "Question", "start": 1.0},
            {"speaker": "assistant", "text": "Answer", "start": 2.0},
        ]
    )
    assert messages[0]["role"] == "user"
    assert messages[1]["role"] == "assistant"


def test_update_call_from_vobiz_event_uses_call_ref_when_ids_differ(db_session, org_id, seed_org, default_workspace):
    call_ref = "ref-4"
    row = _make_vobiz_recording(
        db_session,
        org_id,
        workspace_id=default_workspace.id,
        call_ref=call_ref,
        provider_call_id="request-uuid-4",
        call_event="call_in_progress",
    )

    updated = update_call_from_vobiz_event(
        db_session,
        provider_call_id="call-uuid-4",
        call_status="completed",
        call_ref=call_ref,
    )
    assert updated is not None
    assert updated.id == row.id
    assert updated.call_event == "call_ended"
