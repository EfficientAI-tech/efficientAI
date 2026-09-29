from pathlib import Path

import pytest

from app.services.agents.smallest_atoms_protocol import (
    classify_inbound_event,
    extract_assistant_text,
    InboundKind,
    is_write_conflict_message,
    load_fixture_events,
    replay_events_until_turn_complete,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "smallest_atoms_chat"


@pytest.mark.parametrize(
    "fixture_name,expected_text,expected_call_id",
    [
        ("standard_turn.json", "Hello, how can I help you today?", "call_fixture_001"),
        ("turn_without_session_meta.json", "Hi there.", None),
        (
            "multi_chunk_turn.json",
            "First sentence. Second sentence.",
            None,
        ),
    ],
)
def test_fixture_replay_turn_complete(fixture_name, expected_text, expected_call_id):
    events = load_fixture_events(FIXTURES / fixture_name)
    acc = replay_events_until_turn_complete(events)
    assert acc.combined_reply() == expected_text
    if expected_call_id:
        assert acc.meta.get("smallest_call_id") == expected_call_id
    else:
        session_id = acc.meta.get("smallest_call_id")
        if fixture_name == "multi_chunk_turn.json":
            assert session_id == "sess_fixture_002"


def test_fixture_write_conflict():
    events = load_fixture_events(FIXTURES / "write_conflict.json")
    with pytest.raises(ValueError, match="Write Conflict"):
        replay_events_until_turn_complete(events)


def test_agent_transcript_without_role():
    text = extract_assistant_text(
        {"type": "transcript", "text": "Hello from agent", "topic": "agent_response"}
    )
    assert text == "Hello from agent"


def test_classify_transcript_roles():
    assert (
        classify_inbound_event({"type": "transcript", "role": "user", "text": "x"})
        == InboundKind.UNKNOWN
    )
    assert (
        classify_inbound_event({"type": "transcript", "role": "assistant", "text": "y"})
        == InboundKind.ASSISTANT_TEXT
    )


def test_extract_agent_response():
    assert extract_assistant_text({"type": "agent_response", "text": "OK"}) == "OK"


def test_write_conflict_detection():
    assert is_write_conflict_message("Write Conflict")
    assert not is_write_conflict_message("timeout")
