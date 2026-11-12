"""Tool-call sidecars must replay next to the assistant turn that produced them."""

from app.services.agents.chat_production_leg import (
    _agent_messages,
    _assistant_turn_index,
    _store_tool_sidecar,
)

TOOL_CALL = {"role": "assistant", "content": None, "tool_calls": [{"id": "t1"}]}
TOOL_RESULT = {"role": "tool", "tool_call_id": "t1", "content": "order shipped"}


def test_tool_results_stay_with_the_turn_that_called_the_tool():
    transcript = [{"speaker": "Speaker 1", "text": "hi"}]
    sidecars: list = []

    # Turn 0: no tool call; nothing stored yet.
    assert _assistant_turn_index(transcript) == 0
    transcript += [
        {"speaker": "Speaker 2", "text": "Hello! How can I help?"},
        {"speaker": "Speaker 1", "text": "where is my order"},
    ]

    # Turn 1 calls a tool.
    turn = _assistant_turn_index(transcript)
    assert turn == 1
    sidecars = _store_tool_sidecar(sidecars, turn, [TOOL_CALL, TOOL_RESULT])
    assert sidecars == [[], [TOOL_CALL, TOOL_RESULT]]
    transcript += [
        {"speaker": "Speaker 2", "text": "It has shipped."},
        {"speaker": "Speaker 1", "text": "thanks"},
    ]

    messages = _agent_messages("sys", transcript, tool_sidecars=sidecars)
    roles = [(m["role"], m.get("content")) for m in messages]
    assert roles == [
        ("system", "sys"),
        ("user", "hi"),
        ("assistant", "Hello! How can I help?"),
        ("user", "where is my order"),
        ("assistant", None),
        ("tool", "order shipped"),
        ("assistant", "It has shipped."),
        ("user", "thanks"),
    ]


def test_retrying_a_turn_replaces_its_sidecar():
    sidecars = [[], [TOOL_CALL, TOOL_RESULT]]
    assert _store_tool_sidecar(sidecars, 1, []) == [[], []]
    assert _store_tool_sidecar(sidecars, 3, [TOOL_RESULT]) == [
        [],
        [TOOL_CALL, TOOL_RESULT],
        [],
        [TOOL_RESULT],
    ]
