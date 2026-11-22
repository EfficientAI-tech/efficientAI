"""Copilot read tools over imports, simulations and metrics; and the MCP endpoint."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.core.auth.capabilities import ALL_CAPABILITIES
from app.models.database import CallImport, CallImportEvaluation, SimulationRun
from app.services.copilot.registry import LLMChoice, ToolContext, execute

NOW = datetime.now(timezone.utc)


@pytest.fixture
def ctx(org_id, default_workspace):
    return ToolContext(
        organization_id=org_id,
        workspace_id=default_workspace.id,
        user_id=uuid4(),
        capabilities=frozenset(ALL_CAPABILITIES),
        timezone="UTC",
        session_id=uuid4(),
        llm=LLMChoice(provider=None, model="", credential_id=None),
    )


@pytest.fixture
def run_tool(db_session, ctx):
    def _run(name, args, context=None):
        result = execute(
            context or ctx, name, args,
            session_factory=lambda: Session(bind=db_session.connection(), join_transaction_mode="create_savepoint"),
        )
        assert result.status == "ok", result.content
        return json.loads(result.content)

    return _run


@pytest.fixture
def enterprise(monkeypatch):
    monkeypatch.setattr("app.core.license.is_feature_enabled", lambda feature, org: True)


def _agg(metric_id, name, count, *, mean=None, values=None):
    return SimpleNamespace(
        metric_id=metric_id, metric_name=name, metric_type="boolean", count=count, error_count=0,
        mean=mean, median=None, p25=None, p75=None,
        value_counts=[SimpleNamespace(label=k, count=v) for k, v in (values or {}).items()],
        classification_facets=None,
    )


def _evaluation(db_session, org_id, ws_id, *, created_at, filename="calls.csv"):
    call_import = CallImport(id=uuid4(), organization_id=org_id, workspace_id=ws_id,
                             original_filename=filename, total_rows=10, status="completed")
    db_session.add(call_import)
    db_session.flush()
    evaluation = CallImportEvaluation(
        id=uuid4(), call_import_id=call_import.id, organization_id=org_id, workspace_id=ws_id,
        selected_metric_ids=[], status="completed", total_rows=10, completed_rows=10, failed_rows=0,
        created_at=created_at,
    )
    db_session.add(evaluation)
    db_session.commit()
    return evaluation


def test_metric_trend_combines_imports_and_simulations(
    db_session, org_id, default_workspace, make_metric, make_agent, run_tool, monkeypatch
):
    metric = make_metric(name="Resolution", metric_type="boolean")
    mid = metric.id
    this_week = NOW - timedelta(minutes=5)
    last_week = NOW - timedelta(days=8)
    e1 = _evaluation(db_session, org_id, default_workspace.id, created_at=this_week, filename="a.csv")
    e2 = _evaluation(db_session, org_id, default_workspace.id, created_at=this_week, filename="b.csv")
    e3 = _evaluation(db_session, org_id, default_workspace.id, created_at=last_week)
    fake = {
        e1.id: [_agg(mid, "Resolution", 10, values={"true": 9, "false": 1})],
        e2.id: [_agg(mid, "Resolution", 30, values={"true": 15, "false": 15})],
        e3.id: [_agg(mid, "Resolution", 20, values={"true": 18, "false": 2})],
    }
    monkeypatch.setattr(
        "app.services.copilot.tools.imports.evaluation_aggregates",
        lambda db, evaluation, compute=True: fake.get(evaluation.id),
    )
    agent = make_agent(agent_id="900001")
    db_session.add(SimulationRun(
        run_id="900002", organization_id=org_id, workspace_id=default_workspace.id, agent_id=agent.id,
        scenario_ids=[], persona_ids=[], n_attempts=1, n_concurrent=1, pass_threshold=0.7,
        status="completed", created_at=this_week,
        summary={"metrics": [{"metric_id": str(mid), "name": "Resolution", "mean": 0.5, "pass_rate": 0.5, "n": 4}]},
    ))
    db_session.commit()

    data = run_tool("get_metric_trend", {"metric": "resolution", "period": "last_7_days", "compare_to": "previous"})
    current = data["current"]
    assert current["imports"] == {"calls_scored": 40, "true_rate": 0.6}  # (9+15)/40, weighted by calls
    assert current["simulations"]["pass_rate"] == 0.5 and current["simulations"]["trials"] == 4
    assert data["previous"]["imports"]["true_rate"] == 0.9
    assert data["change"]["imports.true_rate"] == -0.3
    assert data["coverage"]["import_evaluations"] == 2

    by_source = run_tool("get_metric_trend", {"metric": str(mid), "period": "last_7_days",
                                               "compare_to": "none", "group_by": "source"})
    assert by_source["breakdown"]["import: a.csv"]["imports"]["true_rate"] == 0.9
    assert "simulations: Agent A" in by_source["breakdown"]

    worse = run_tool("compare_metrics", {"period": "last_7_days"})
    # Last week only had imports, so the comparison uses the import measure in both weeks.
    assert worse["got_worse"] == [{
        "metric_id": str(mid), "metric": "Resolution", "measure": "imports.true_rate",
        "current": 0.6, "previous": 0.9, "change": -0.3, "sample": {"current": 44, "previous": 20},
    }]


def test_metric_name_must_be_unambiguous(db_session, make_metric, ctx):
    make_metric(name="Empathy (voice)")
    make_metric(name="Empathy (chat)")
    result = execute(ctx, "get_metric_trend", {"metric": "empathy"},
                     session_factory=lambda: Session(bind=db_session.connection(), join_transaction_mode="create_savepoint"))
    assert result.status == "error" and "Several metrics match" in result.content


def test_import_tools(db_session, org_id, default_workspace, run_tool, enterprise, monkeypatch):
    evaluation = _evaluation(db_session, org_id, default_workspace.id, created_at=NOW, filename="billing.csv")
    listed = run_tool("list_imports", {"query": "billing"})
    assert listed["total"] == 1 and listed["imports"][0]["name"] == "billing.csv"
    detail = run_tool("get_import", {"call_import": "billing"})
    assert detail["recent_evaluations"][0]["id"] == str(evaluation.id)

    seen = {}

    async def fake_rows(**kwargs):
        seen.update(kwargs)
        row = SimpleNamespace(
            id=uuid4(), conversation_id="c-1", status="completed",
            metric_scores={"m": {"value": False}}, transcript="agent: hi " * 200,
            production_transcript=None, diarised_transcript=None,
        )
        return SimpleNamespace(items=[row], total=17)

    monkeypatch.setattr("app.api.v1.routes.call_import_evaluations.rows.list_call_import_evaluation_rows", fake_rows)
    rows = run_tool("search_import_rows", {"evaluation": str(evaluation.id), "metric_value": "false"})
    assert rows["total_matching"] == 17 and rows["rows"][0]["metric_scores"] == {"m": False}
    assert len(rows["rows"][0]["transcript_excerpt"]) <= 601
    # Every Query(...) parameter is passed explicitly (their defaults are truthy FieldInfo objects).
    from fastapi.params import Param

    assert not any(isinstance(v, Param) for v in seen.values())
    assert seen["metric_value"] == "false" and seen["page_size"] == 5


def test_import_tools_respect_enterprise_gate(db_session, ctx, monkeypatch):
    monkeypatch.setattr("app.core.license.is_feature_enabled", lambda feature, org: False)
    result = execute(ctx, "list_imports", {},
                     session_factory=lambda: Session(bind=db_session.connection(), join_transaction_mode="create_savepoint"))
    assert result.status == "error" and "Enterprise" in result.content


def test_simulation_run_tool(db_session, org_id, default_workspace, make_agent, run_tool):
    agent = make_agent(agent_id="900101")
    db_session.add(SimulationRun(
        run_id="900102", organization_id=org_id, workspace_id=default_workspace.id, agent_id=agent.id,
        scenario_ids=[], persona_ids=[], n_attempts=1, n_concurrent=1, pass_threshold=0.7,
        status="completed", expected_trials=4,
        summary={"pass_rate": 0.25, "combos": [
            {"scenario_name": "Refund", "persona_name": "Ann", "attempts": 2, "passed": 0, "mean_reward": 0.1},
            {"scenario_name": "Hours", "persona_name": "Ann", "attempts": 2, "passed": 2, "mean_reward": 1.0},
        ]},
    ))
    db_session.commit()
    runs = run_tool("list_simulation_runs", {})
    assert runs["runs"][0]["run_id"] == "900102"
    detail = run_tool("get_simulation_run", {"run": "900102"})
    assert detail["link"] == "/simulations/900102"
    assert [c["scenario_name"] for c in detail["failing_combinations"]] == ["Refund"]


def test_wizard_handoff_card(ctx, db_session):
    result = execute(ctx, "open_create_agent_wizard", {"name": "Billing Bot", "call_medium": "voice"},
                     session_factory=lambda: None)
    assert result.status == "ok"
    assert result.ui == {"type": "wizard", "wizard": {
        "kind": "create_agent", "name": "Billing Bot", "call_medium": "voice",
        "production_prompt": None, "description": None,
    }}


# --- MCP --------------------------------------------------------------------------------


def _rpc(client, method, params=None, rid=1):
    body = {"jsonrpc": "2.0", "method": method, "params": params or {}}
    if rid is not None:
        body["id"] = rid
    return client.post("/api/v1/copilot/mcp", json=body)


def test_mcp_lists_and_calls_tools(authenticated_client, make_agent):
    make_agent(name="Support bot", agent_id="808080")
    init = _rpc(authenticated_client, "initialize", {"protocolVersion": "2025-06-18"}).json()
    assert init["result"]["serverInfo"]["name"] == "efficientai-copilot"
    assert _rpc(authenticated_client, "notifications/initialized", rid=None).status_code == 202

    tools = _rpc(authenticated_client, "tools/list").json()["result"]["tools"]
    by_name = {t["name"]: t for t in tools}
    assert "list_agents" in by_name and by_name["list_agents"]["annotations"]["readOnlyHint"] is True
    assert by_name["propose_create_persona"]["annotations"]["readOnlyHint"] is False

    called = _rpc(authenticated_client, "tools/call", {"name": "search_docs", "arguments": {"query": "connect twilio"}}).json()
    assert called["result"]["isError"] is False
    assert "twilio" in called["result"]["content"][0]["text"].lower()

    unknown = _rpc(authenticated_client, "nope").json()
    assert unknown["error"]["code"] == -32601
    batch = authenticated_client.post("/api/v1/copilot/mcp", json=[
        {"jsonrpc": "2.0", "id": 1, "method": "ping"},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
    ]).json()
    assert batch == [{"jsonrpc": "2.0", "id": 1, "result": {}}]

