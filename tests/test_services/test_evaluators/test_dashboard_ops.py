"""Dashboard ops rollups: usage role, cost legs, and tool calls."""

from datetime import date, datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from app.services.evaluators.evaluator_results_dashboard_ops import (
    ToolCallSource,
    UsageSpendRow,
    rollup_tool_calls,
    rollup_usage,
)
from app.services.usage.context import (
    LLMUsageProductSection,
    resolve_usage_role,
    usage_context_for_evaluator_result,
    usage_context_for_playground_voice_call,
    usage_context_for_test_agent_simulation,
)


def test_resolve_usage_role_prefers_explicit_role_over_section():
    assert (
        resolve_usage_role(
            "playground",
            {"usage_role": "judge", "agent_id": "a"},
        )
        == "judge"
    )


def test_resolve_usage_role_infers_historical_rows():
    assert resolve_usage_role("evaluators", {"simulation_leg": "production_agent"}) == "agent"
    assert resolve_usage_role("test_agent", {}) == "simulator"
    assert resolve_usage_role("evaluators", {"agent_id": "a"}) == "judge"
    assert resolve_usage_role("playground", {"agent_id": "a"}) == "agent"
    assert resolve_usage_role("voice_playground", {}) == "agent"
    assert resolve_usage_role("metrics", {"agent_id": "a"}) == "judge"
    assert resolve_usage_role("agents", {"agent_id": "a"}) is None


def test_context_helpers_stamp_usage_role():
    agent_id = uuid4()
    simulator = usage_context_for_test_agent_simulation(
        organization_id=uuid4(),
        workspace_id=uuid4(),
        agent_id=agent_id,
    )
    assert simulator.extra["usage_role"] == "simulator"

    judge = usage_context_for_evaluator_result(
        SimpleNamespace(
            id=uuid4(),
            result_id="r",
            organization_id=uuid4(),
            workspace_id=uuid4(),
            agent_id=agent_id,
            evaluator_id=uuid4(),
            persona_id=None,
            scenario_id=None,
            provider_platform=None,
        )
    )
    assert judge.extra["usage_role"] == "judge"
    assert judge.product_section == LLMUsageProductSection.EVALUATORS

    live = usage_context_for_playground_voice_call(
        organization_id=uuid4(),
        workspace_id=uuid4(),
        agent_id=agent_id,
        provider_platform="vapi",
    )
    assert live.extra["usage_role"] == "agent"


def _spend(**kwargs) -> UsageSpendRow:
    defaults = dict(
        product_section="evaluators",
        model="gpt-4.1",
        usage_kind="llm",
        usage_date=date(2026, 11, 16),
        context={},
        total_cost_micro_usd=1_500_000,
    )
    defaults.update(kwargs)
    return UsageSpendRow(**defaults)


def test_rollup_usage_splits_layers_and_roles_and_drops_other_modes():
    agent_id = uuid4()
    other = uuid4()
    rows = [
        _spend(
            context={"agent_id": str(agent_id), "simulation_leg": "production_agent"},
            usage_kind="llm",
            total_cost_micro_usd=2_000_000,
            model="gpt-4.1",
        ),
        _spend(
            context={"agent_id": str(agent_id), "simulation_leg": "production_agent"},
            usage_kind="stt",
            total_cost_micro_usd=500_000,
            model="stt-1",
        ),
        _spend(
            product_section="test_agent",
            context={"agent_id": str(agent_id)},
            usage_kind="tts",
            total_cost_micro_usd=250_000,
            model="tts-1",
        ),
        _spend(
            product_section="evaluators",
            context={"agent_id": str(agent_id), "usage_role": "judge"},
            usage_kind="llm",
            total_cost_micro_usd=100_000,
            model="judge-model",
        ),
        _spend(
            product_section="playground",
            context={"agent_id": str(agent_id), "usage_role": "agent"},
            total_cost_micro_usd=9_000_000,
        ),
        _spend(
            product_section="agents",
            context={"agent_id": str(other)},
            total_cost_micro_usd=4_000_000,
        ),
        _spend(
            context={"simulation_leg": "production_agent"},
            total_cost_micro_usd=3_000_000,
        ),
    ]

    by_agent, by_model, by_day = rollup_usage(
        rows,
        playground=False,
        agent_names={agent_id: "Support"},
    )

    assert len(by_agent) == 1
    agent = by_agent[0]
    assert agent.agent_name == "Support"
    assert agent.llm_usd == 2.1
    assert agent.stt_usd == 0.5
    assert agent.tts_usd == 0.25
    assert agent.agent_usd == 2.5
    assert agent.simulator_usd == 0.25
    assert agent.judge_usd == 0.1
    assert agent.total_usd == 2.85
    assert {item.model for item in agent.models} == {"gpt-4.1", "stt-1", "tts-1", "judge-model"}

    models = {(item.model, item.cost_usd) for item in by_model}
    assert ("gpt-4.1", 2.0) in models
    assert ("judge-model", 0.1) in models
    assert all(item.model != "playground" for item in by_model)

    roles = {item.role for item in by_day}
    assert roles == {"agent", "simulator", "judge"}

    live_agents, _, _ = rollup_usage(rows, playground=True)
    assert len(live_agents) == 1
    assert live_agents[0].total_usd == 9.0


def test_rollup_usage_scenario_filter_drops_rows_without_scenario():
    agent_id = uuid4()
    scenario_id = uuid4()
    rows = [
        _spend(
            context={
                "agent_id": str(agent_id),
                "scenario_id": str(scenario_id),
                "simulation_leg": "production_agent",
            }
        ),
        _spend(
            context={"agent_id": str(agent_id), "simulation_leg": "production_agent"},
            model="other",
        ),
    ]
    matched, _, _ = rollup_usage(
        rows,
        playground=False,
        scenario_ids={str(scenario_id)},
    )
    assert len(matched) == 1
    assert matched[0].models[0].model == "gpt-4.1"

    empty, _, _ = rollup_usage(rows, playground=False, scenario_ids=set())
    assert empty == []


def test_rollup_tool_calls_counts_production_side_and_kb_fallback():
    agent_id = uuid4()
    when = datetime(2026, 11, 16, 12, tzinfo=timezone.utc)
    rows = [
        ToolCallSource(
            agent_id=agent_id,
            timestamp=when,
            call_data={
                "tool_calls": [
                    {"tool": "lookup", "side": "production", "status": "ok"},
                    {"tool": "lookup", "side": "production", "status": "error"},
                    {"tool": "caller_tool", "side": "test", "status": "ok"},
                ]
            },
        ),
        ToolCallSource(
            agent_id=agent_id,
            timestamp=when,
            call_data={
                "knowledge_base_tool_calls": [
                    {"tool": "kb", "status": "ok"},
                ]
            },
        ),
        ToolCallSource(
            agent_id=None,
            timestamp=when,
            call_data={"tool_calls": [{"tool": "ignored", "status": "ok"}]},
        ),
    ]
    by_day, by_tool = rollup_tool_calls(rows, agent_names={agent_id: "Support"})
    assert len(by_day) == 1
    assert by_day[0].calls == 3
    assert by_day[0].errors == 1
    assert by_day[0].agent_name == "Support"
    tools = {item.tool: (item.calls, item.errors) for item in by_tool}
    assert tools == {"lookup": (2, 1), "kb": (1, 0)}
