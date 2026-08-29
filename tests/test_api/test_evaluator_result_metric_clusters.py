"""Tests for evaluator-result metric clustering and overview scenarios."""

from __future__ import annotations

from uuid import uuid4

import pytest


def test_overview_includes_scenarios_on_default_response(
    authenticated_client,
    db_session,
    make_agent,
    make_persona,
    make_scenario,
    make_evaluator,
    make_evaluator_result,
):
    from app.models.database import EvaluatorSuite

    agent = make_agent(name="Scenario Overview Agent")
    persona = make_persona()
    scenario = make_scenario(agent_id=agent.id, name="Hub Scenario")
    suite = EvaluatorSuite(
        organization_id=agent.organization_id,
        workspace_id=agent.workspace_id,
        name="Hub Suite",
        agent_id=agent.id,
        persona_id=persona.id,
    )
    db_session.add(suite)
    db_session.commit()
    db_session.refresh(suite)

    evaluator = make_evaluator(
        agent_id=agent.id,
        persona_id=persona.id,
        scenario_id=scenario.id,
        suite_id=suite.id,
    )
    make_evaluator_result(
        result_id="660001",
        evaluator_id=evaluator.id,
        agent_id=agent.id,
        persona_id=persona.id,
        scenario_id=scenario.id,
        status="completed",
    )

    response = authenticated_client.get("/api/v1/evaluator-results/overview")
    assert response.status_code == 200
    body = response.json()
    agent_entry = next(a for a in body["agents"] if a["agent_id"] == str(agent.id))
    suite_entry = next(s for s in agent_entry["suites"] if s["suite_id"] == str(suite.id))
    assert suite_entry["scenarios"]
    assert suite_entry["scenarios"][0]["scenario_name"] == "Hub Scenario"


def test_evaluator_result_metric_clusters_requires_license(
    authenticated_client,
    monkeypatch,
):
    monkeypatch.setattr(
        "app.core.license.is_feature_enabled",
        lambda feature, organization_id=None: False,
    )
    response = authenticated_client.get("/api/v1/evaluator-results/metric-clusters")
    assert response.status_code == 403
    detail = response.json()["detail"]
    assert detail["error"] == "enterprise_feature_required"
    assert detail["feature"] == "evaluation_clustering"
