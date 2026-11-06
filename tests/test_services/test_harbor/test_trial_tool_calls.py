"""A production agent with a knowledge base calls search_knowledge_base during a Harbor trial."""

import json

import pytest

import app.services.tools.loop as loop_mod
from app.models.database import EvaluatorResult
from app.services.harbor.trial_store import TrialRefs, run_trial_conversation, score_trial
from app.services.knowledge_bases.prompt import CALLER_KB_VOICE_APPENDIX

HITS = [
    {
        "text": "Late orders get a full refund.",
        "document_name": "policy.pdf",
        "page": 2,
        "score": 0.9,
    }
]


@pytest.fixture
def kb_llms(monkeypatch):
    monkeypatch.setattr(
        "app.services.knowledge_bases.retrieval.agent_has_ready_knowledge", lambda *a, **k: True
    )
    monkeypatch.setattr(
        "app.services.tools.providers.knowledge_base.search_knowledge_base", lambda *a, **k: HITS
    )
    production_turns = iter(
        ["Our policy says late orders get a full refund.", "Refund issued, goodbye!"]
    )
    queries = iter(["late order refund policy", "refund processing time"])

    def _with_tools(*, messages, **_):
        if CALLER_KB_VOICE_APPENDIX.strip()[:40] in messages[0]["content"]:
            return {"text": "My order 4411 was late, I want a refund.", "tool_calls": None}
        if messages[-1]["role"] == "tool":
            return {"text": next(production_turns), "tool_calls": None}
        call = {
            "id": None,  # some providers omit ids; the trajectory must still validate
            "type": "function",
            "function": {
                "name": "search_knowledge_base",
                "arguments": json.dumps({"query": next(queries)}),
            },
        }
        return {"text": "", "tool_calls": [call]}

    monkeypatch.setattr(loop_mod.llm_service, "generate_response_with_tools", _with_tools)


def _run_trial(db_session, sim_rows, tmp_path):
    refs = TrialRefs(
        simulation_run_id=sim_rows.run.id,
        scenario_id=sim_rows.scenario.id,
        persona_id=sim_rows.persona.id,
        trial_name="refund__kb1",
    )
    path = tmp_path / "agent" / "trajectory.json"
    run_trial_conversation(
        db_session, refs=refs, trajectory_path=path, production_override=None, test_override=None
    )
    return db_session.query(EvaluatorResult).filter_by(harbor_trial_name="refund__kb1").one(), path


def test_tool_calls_recorded_across_turns(db_session, sim_rows, kb_llms, tmp_path):
    result, path = _run_trial(db_session, sim_rows, tmp_path)

    calls = result.call_data["tool_calls"]
    # One KB call per production turn; earlier turns must not be overwritten by later ones.
    assert [c["arguments"]["query"] for c in calls] == [
        "late order refund policy",
        "refund processing time",
    ]
    assert {c["status"] for c in calls} == {"ok"}
    assert {c["hit_count"] for c in calls} == {1}
    agent_turns = [m for m in result.call_data["messages"] if m["speaker"] == "Speaker 2"]
    assert [m["tool_calls"][0]["turn_index"] for m in agent_turns] == [
        c["turn_index"] for c in calls
    ]
    assert len(result.call_data["knowledge_base_tool_calls"]) == 2

    trajectory = json.loads(path.read_text())
    agent_steps = [s for s in trajectory["steps"] if s["source"] == "agent"]
    assert all(s["tool_calls"][0]["function_name"] == "search_knowledge_base" for s in agent_steps)
    assert all(
        s["observation"]["results"][0]["source_call_id"] == s["tool_calls"][0]["tool_call_id"]
        for s in agent_steps
    )
    validator_mod = pytest.importorskip("harbor.utils.trajectory_validator")
    validator = validator_mod.TrajectoryValidator()
    assert validator.validate(trajectory), validator.get_errors()


@pytest.mark.parametrize(
    "expected,passed",
    [
        ([{"tool": "search_knowledge_base", "args_contains": {"query": "refund"}}], True),
        ([{"tool": "search_knowledge_base", "forbidden": True}], False),
    ],
)
def test_score_trial_applies_tool_expectations(
    db_session, sim_rows, kb_llms, tmp_path, monkeypatch, expected, passed
):
    sim_rows.scenario.expected_tool_calls = expected
    db_session.commit()
    _run_trial(db_session, sim_rows, tmp_path)
    metric = sim_rows.metric

    def _fake_eval(db, *, result, agent, persona, scenario, metric_ids=None):
        return {str(metric.id): {"value": 0.9, "type": "rating"}}, [metric]

    monkeypatch.setattr(
        "app.workers.tasks.process_evaluator_result.evaluate_transcript_metrics", _fake_eval
    )
    rewards, details = score_trial(
        db_session, simulation_run_id=sim_rows.run.id, trial_name="refund__kb1", pass_threshold=0.7
    )

    assert rewards["reward"] == 0.9
    assert rewards["tool_success_rate"] == 1.0
    assert rewards["kb_retrieval_hit_rate"] == 1.0
    assert rewards["tool_expectations_met"] == (1.0 if passed else 0.0)
    assert details["passed"] is passed
    result = db_session.query(EvaluatorResult).filter_by(harbor_trial_name="refund__kb1").one()
    assert result.call_data["tool_evaluation"]["all_expectations_met"] is passed


def test_trial_calls_attached_mcp_connection(db_session, sim_rows, tmp_path, monkeypatch):
    """Production agent calls a real (stdio) MCP server attached via a ToolConnection."""
    import sys
    from pathlib import Path

    from app.config import settings
    from app.models.database import AgentToolConnection, ToolConnection
    from app.services.tools.connections import refresh_connection_tools

    monkeypatch.setattr(settings, "TOOL_CONNECTIONS_ALLOW_STDIO", True)
    monkeypatch.setattr(
        "app.services.knowledge_bases.retrieval.agent_has_ready_knowledge", lambda *a, **k: False
    )
    server = Path(__file__).parents[1] / "test_tools" / "fixtures" / "order_mcp_server.py"
    connection = ToolConnection(
        organization_id=sim_rows.agent.organization_id,
        workspace_id=sim_rows.agent.workspace_id,
        name="Orders",
        slug="orders",
        connection_type="mcp",
        config={"transport": "stdio", "command": sys.executable, "args": [str(server)]},
        simulation_mode="mock_writes",
    )
    db_session.add(connection)
    db_session.flush()
    assert refresh_connection_tools(db_session, connection), connection.last_error
    db_session.add(
        AgentToolConnection(
            agent_id=sim_rows.agent.id,
            tool_connection_id=connection.id,
            organization_id=connection.organization_id,
            workspace_id=connection.workspace_id,
        )
    )
    db_session.commit()

    plan = iter(
        [
            [
                ("orders__lookup_order", {"order_id": "4411"}),
                ("orders__send_message", {"channel": "#ops", "text": "refund 4411"}),
            ],
            None,
            None,
        ]
    )

    def _with_tools(*, messages, tools, **_):
        assert {t["function"]["name"] for t in tools} == {
            "orders__lookup_order",
            "orders__send_message",
        }
        if CALLER_KB_VOICE_APPENDIX.strip()[:40] in messages[0]["content"]:
            return {"text": "Where is order 4411? Goodbye!", "tool_calls": None}
        if messages[-1]["role"] == "tool":
            return {"text": "It shipped on Oct 1 and I've notified the team.", "tool_calls": None}
        step = next(plan)
        if step is None:
            return {"text": "Anything else? Goodbye!", "tool_calls": None}
        calls = [
            {"id": f"c{i}", "type": "function", "function": {"name": n, "arguments": json.dumps(a)}}
            for i, (n, a) in enumerate(step)
        ]
        return {"text": "", "tool_calls": calls}

    monkeypatch.setattr(loop_mod.llm_service, "generate_response_with_tools", _with_tools)
    monkeypatch.setattr(
        "app.services.testing.llm_to_llm_evaluator_simulation.llm_service.generate_response",
        lambda **_: {"text": "Where is order 4411? Thanks, goodbye!"},
    )
    result, _ = _run_trial(db_session, sim_rows, tmp_path)

    calls = {c["tool"]: c for c in result.call_data["tool_calls"]}
    assert calls["orders__lookup_order"]["status"] == "ok"
    assert "shipped" in calls["orders__lookup_order"]["result_preview"]
    assert calls["orders__lookup_order"]["provider"] == "Orders"
    assert calls["orders__send_message"]["status"] == "mocked"
