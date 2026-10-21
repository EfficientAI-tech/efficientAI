"""run_tool_loop + Toolset with the LLM faked: multi-round calls, errors, mocks, round cap."""

import json

import pytest

import app.services.tools.loop as loop_mod
from app.models.enums import ModelProvider
from app.services.tools.base import SIDE_EFFECT_WRITE, ToolResult, ToolSpec
from app.services.tools.toolset import Toolset


class FakeProvider:
    name = "fake"

    def __init__(self):
        self.calls = []

    def list_tools(self):
        params = {"type": "object", "properties": {"q": {"type": "string"}}}
        return [
            ToolSpec("lookup", "Look something up", params, provider=self.name),
            ToolSpec("explode", "Always fails", params, provider=self.name),
            ToolSpec(
                "post_message", "Posts", params, provider=self.name, side_effect=SIDE_EFFECT_WRITE
            ),
        ]

    def call(self, tool_name, arguments):
        self.calls.append((tool_name, arguments))
        if tool_name == "explode":
            raise RuntimeError("backend down")
        return ToolResult(f"result for {arguments.get('q')}", extra={"hit_count": 2})


def _tool_call(call_id, name, arguments):
    raw = arguments if isinstance(arguments, str) else json.dumps(arguments)
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": raw}}


@pytest.fixture
def scripted_llm(monkeypatch):
    """Feed scripted tool-call rounds; returns the list of message lists the LLM saw."""
    seen = []

    def _install(rounds, final_text="final answer"):
        script = iter(rounds)

        def _with_tools(*, messages, tools, **_):
            seen.append(list(messages))
            try:
                calls = next(script)
            except StopIteration:
                return {"text": "done", "tool_calls": None}
            if calls is None:
                return {"text": "plain reply", "tool_calls": None}
            return {"text": "", "tool_calls": calls}

        monkeypatch.setattr(loop_mod.llm_service, "generate_response_with_tools", _with_tools)
        monkeypatch.setattr(
            loop_mod.llm_service, "generate_response", lambda **_: {"text": final_text}
        )
        return seen

    return _install


def _run(toolset, max_rounds=5):
    return loop_mod.run_tool_loop(
        None,
        toolset=toolset,
        messages=[{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}],
        organization_id=None,
        llm_provider=ModelProvider.OPENAI,
        llm_model="gpt-test",
        max_rounds=max_rounds,
    )


def test_multi_round_calls_are_recorded_and_fed_back(scripted_llm):
    seen = scripted_llm(
        [
            [_tool_call("c1", "lookup", {"q": "refund policy"})],
            [_tool_call("c2", "lookup", {"q": "fees"})],
            None,
        ]
    )
    provider = FakeProvider()
    text, records = _run(Toolset([provider]))

    assert text == "plain reply"
    assert [r.tool for r in records] == ["lookup", "lookup"]
    assert all(r.status == "ok" for r in records)
    assert records[0].as_dict()["hit_count"] == 2
    tool_msgs = [m for m in seen[-1] if m["role"] == "tool"]
    assert [m["tool_call_id"] for m in tool_msgs] == ["c1", "c2"]
    assert tool_msgs[0]["content"] == "result for refund policy"


def test_tool_failures_are_errors_returned_to_model(scripted_llm):
    seen = scripted_llm(
        [
            [
                _tool_call("c1", "explode", {"q": "x"}),
                _tool_call("c2", "nope", {}),
                _tool_call("c3", "lookup", "{not json"),
            ],
            None,
        ]
    )
    _, records = _run(Toolset([FakeProvider()]))

    assert [r.status for r in records] == ["error", "error", "error"]
    assert "backend down" in records[0].error
    assert "Unknown tool" in records[1].error
    assert "Invalid JSON" in records[2].error
    assert len([m for m in seen[-1] if m["role"] == "tool"]) == 3


def test_write_tools_mocked_and_scenario_mocks_win(scripted_llm):
    scripted_llm(
        [
            [
                _tool_call("c1", "post_message", {"q": "hello"}),
                _tool_call("c2", "lookup", {"q": "x"}),
            ],
            None,
        ]
    )
    provider = FakeProvider()
    _, records = _run(Toolset([provider], mock_responses={"lookup": {"rows": [1]}}))

    assert [r.status for r in records] == ["mocked", "mocked"]
    assert json.loads(records[0].result_preview) == {"ok": True, "simulated": True}
    assert json.loads(records[1].result_preview) == {"rows": [1]}
    assert provider.calls == []


def test_round_cap_falls_back_to_plain_completion(scripted_llm):
    scripted_llm(
        [[_tool_call(f"c{i}", "lookup", {"q": str(i)})] for i in range(10)], final_text="capped"
    )
    text, records = _run(Toolset([FakeProvider()]), max_rounds=2)

    assert text == "capped"
    assert len(records) == 2


def test_empty_toolset_is_falsy():
    assert not Toolset([])
    assert Toolset([FakeProvider()]).tool_names == ["lookup", "explode", "post_message"]
