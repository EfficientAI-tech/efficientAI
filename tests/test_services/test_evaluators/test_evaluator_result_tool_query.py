"""Production tool_call filters on evaluator result list queries."""

from datetime import datetime, timezone

from app.services.evaluators.evaluator_results_query import build_evaluator_results_query


def test_has_tool_calls_matches_python_rollup_sources(
    db_session,
    org_id,
    default_workspace,
    make_agent,
    make_evaluator,
    make_evaluator_result,
):
    agent = make_agent()
    evaluator = make_evaluator(agent_id=agent.id)
    ts = datetime(2026, 10, 21, 10, 0, tzinfo=timezone.utc)
    with_tools = make_evaluator_result(
        evaluator_id=evaluator.id,
        agent_id=agent.id,
        result_id="tc0002",
        timestamp=ts,
        call_data={
            "tool_calls": [
                {"tool": "lookup", "provider": "zepto", "side": "production", "status": "ok"},
            ]
        },
    )
    make_evaluator_result(
        evaluator_id=evaluator.id,
        agent_id=agent.id,
        result_id="tc0003",
        timestamp=ts,
        call_data={
            "knowledge_base_tool_calls": [
                {"tool": "search_knowledge_base", "status": "ok"},
            ]
        },
    )
    make_evaluator_result(
        evaluator_id=evaluator.id,
        agent_id=agent.id,
        result_id="tc0004",
        timestamp=ts,
        call_data={"source": "sim"},
    )
    query = build_evaluator_results_query(
        db_session,
        organization_id=org_id,
        workspace_id=default_workspace.id,
        agent_id=str(agent.id),
        playground=False,
        has_tool_calls=True,
    )
    ids = {row.id for row in query.all()}
    assert with_tools.id in ids
    assert len(ids) == 2


def test_tool_product_filter_is_case_exact(
    db_session,
    org_id,
    default_workspace,
    make_agent,
    make_evaluator,
    make_evaluator_result,
):
    agent = make_agent()
    evaluator = make_evaluator(agent_id=agent.id)
    ts = datetime(2026, 10, 21, 10, 0, tzinfo=timezone.utc)
    with_tools = make_evaluator_result(
        evaluator_id=evaluator.id,
        agent_id=agent.id,
        result_id="tc0012",
        timestamp=ts,
        call_data={
            "tool_calls": [
                {"tool": "lookup", "provider": "zepto", "side": "production", "status": "ok"},
            ]
        },
    )
    query = build_evaluator_results_query(
        db_session,
        organization_id=org_id,
        workspace_id=default_workspace.id,
        agent_id=str(agent.id),
        playground=False,
        tool_product="zepto",
    )
    ids = {row.id for row in query.all()}
    assert ids == {with_tools.id}