"""Tests for evaluator-result metric clustering and overview scenarios."""

from __future__ import annotations

import types
from datetime import datetime, timezone
from uuid import uuid4

import pytest


def _seed_clusterable_evaluator_result(
    db_session,
    *,
    make_agent,
    make_persona,
    make_scenario,
    make_evaluator,
    make_evaluator_result,
    make_metric,
):
    from app.models.database import EvaluatorSuite

    agent = make_agent(name="Cluster Scope Agent")
    persona = make_persona()
    scenario = make_scenario(agent_id=agent.id, name="Scope Scenario")
    suite = EvaluatorSuite(
        organization_id=agent.organization_id,
        workspace_id=agent.workspace_id,
        name="Scope Suite",
        agent_id=agent.id,
        persona_id=persona.id,
    )
    db_session.add(suite)
    db_session.commit()
    db_session.refresh(suite)

    metric = make_metric(name="Pass/Fail", metric_type="boolean")
    evaluator = make_evaluator(
        agent_id=agent.id,
        persona_id=persona.id,
        scenario_id=scenario.id,
        suite_id=suite.id,
    )
    result = make_evaluator_result(
        evaluator_id=evaluator.id,
        agent_id=agent.id,
        persona_id=persona.id,
        scenario_id=scenario.id,
        status="completed",
        metric_scores={
            str(metric.id): {
                "value": False,
                "type": "boolean",
                "metric_name": "Pass/Fail",
                "rationale": "Failed to confirm identity.",
            }
        },
    )
    return agent, scenario, result, metric


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


def test_evaluator_result_metric_clusters_requires_agent_id(authenticated_client):
    """GET must hit metric-clusters handler, not /evaluator-results/{id}."""
    response = authenticated_client.get("/api/v1/evaluator-results/metric-clusters")
    assert response.status_code == 400
    assert response.json()["detail"] == "agent_id is required"
    assert response.json()["detail"] != "Evaluator result not found"


def test_evaluator_result_metric_clusters_requires_license(
    authenticated_client,
    monkeypatch,
):
    monkeypatch.setattr(
        "app.dependencies.is_feature_enabled",
        lambda feature, organization_id=None: False,
    )
    response = authenticated_client.get(
        "/api/v1/evaluator-results/metric-clusters",
        params={"agent_id": str(uuid4())},
    )
    assert response.status_code == 403
    detail = response.json()["detail"]
    assert detail["error"] == "enterprise_feature_required"
    assert detail["feature"] == "evaluation_clustering"


def test_generate_evaluator_result_metric_clusters_persists_generation_scope(
    authenticated_client,
    db_session,
    make_ai_provider,
    make_agent,
    make_persona,
    make_scenario,
    make_evaluator,
    make_evaluator_result,
    make_metric,
    monkeypatch,
):
    make_ai_provider(provider="openai", is_active=True)
    agent, scenario, result, _metric = _seed_clusterable_evaluator_result(
        db_session,
        make_agent=make_agent,
        make_persona=make_persona,
        make_scenario=make_scenario,
        make_evaluator=make_evaluator,
        make_evaluator_result=make_evaluator_result,
        make_metric=make_metric,
    )
    result.timestamp = datetime(2026, 1, 15, tzinfo=timezone.utc)
    db_session.commit()

    def fake_apply_async(*, kwargs=None, **_kw):
        return types.SimpleNamespace(id="eval-cluster-task-2")

    monkeypatch.setattr(
        "app.workers.tasks.generate_evaluator_result_metric_clusters.generate_evaluator_result_metric_clusters_task.apply_async",
        fake_apply_async,
    )

    since = datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat()
    until = datetime(2026, 1, 31, tzinfo=timezone.utc).isoformat()
    post = authenticated_client.post(
        "/api/v1/evaluator-results/metric-clusters",
        params={
            "agent_id": str(agent.id),
            "scenario_ids": [str(scenario.id)],
            "since": since,
            "until": until,
        },
        json={"evaluation_row_ids": [str(result.id)]},
    )
    assert post.status_code == 200, post.text

    response = authenticated_client.get("/api/v1/evaluator-results/metric-clusters/scopes")
    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) >= 1
    match = next(
        item
        for item in body["items"]
        if item["generation_scope"]["agent_name"] == "Cluster Scope Agent"
    )
    assert match["status"] == "running"
    assert match["generation_scope"]["scenario_names"] == ["Scope Scenario"]


def _completed_cluster_params(agent, scenario):
    return {
        "agent_id": str(agent.id),
        "scenario_ids": [str(scenario.id)],
    }


def _seed_completed_cluster_job(
    db_session,
    *,
    agent,
    scenario,
    generated_at_completed_rows: int = 1,
):
    from app.services.evaluators.evaluator_result_metric_clusters import (
        build_generation_scope_snapshot,
        get_or_create_cluster_job,
    )

    job = get_or_create_cluster_job(
        db_session,
        organization_id=agent.organization_id,
        workspace_id=agent.workspace_id,
        agent_id=agent.id,
        scenario_ids=[scenario.id],
    )
    generation_scope = build_generation_scope_snapshot(
        db_session,
        job=job,
        eligible_call_count=generated_at_completed_rows,
        selected_call_count=generated_at_completed_rows,
    )
    job.metric_clusters = {
        "status": "completed",
        "groups": [
            {
                "metric_id": str(uuid4()),
                "metric_name": "Pass/Fail",
                "flagged_count": 1,
                "failure_reason": "",
                "clusters": [],
            }
        ],
        "discovered_problems": [],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generated_at_completed_rows": generated_at_completed_rows,
        "generation_scope": generation_scope,
    }
    db_session.commit()
    return job


def test_get_evaluator_result_metric_clusters_marks_stale_without_full_hydration(
    authenticated_client,
    db_session,
    make_agent,
    make_persona,
    make_scenario,
    make_evaluator,
    make_evaluator_result,
    make_metric,
    monkeypatch,
):
    agent, scenario, result, metric = _seed_clusterable_evaluator_result(
        db_session,
        make_agent=make_agent,
        make_persona=make_persona,
        make_scenario=make_scenario,
        make_evaluator=make_evaluator,
        make_evaluator_result=make_evaluator_result,
        make_metric=make_metric,
    )
    job = _seed_completed_cluster_job(
        db_session,
        agent=agent,
        scenario=scenario,
        generated_at_completed_rows=1,
    )

    def forbid_hydration(*_args, **_kwargs):
        raise AssertionError("clustering_context_for_job should not run on GET")

    monkeypatch.setattr(
        "app.api.v1.routes.evaluator_result_metric_clusters.clustering_context_for_job",
        forbid_hydration,
    )

    params = _completed_cluster_params(agent, scenario)
    fresh = authenticated_client.get(
        "/api/v1/evaluator-results/metric-clusters",
        params=params,
    )
    assert fresh.status_code == 200
    assert fresh.json()["is_stale"] is False

    from app.models.database import EvaluatorSuite

    persona = result.persona_id
    suite = EvaluatorSuite(
        organization_id=agent.organization_id,
        workspace_id=agent.workspace_id,
        name="Stale Suite",
        agent_id=agent.id,
        persona_id=persona,
    )
    db_session.add(suite)
    db_session.commit()
    evaluator = make_evaluator(
        evaluator_id="654322",
        agent_id=agent.id,
        persona_id=persona,
        scenario_id=scenario.id,
        suite_id=suite.id,
    )
    make_evaluator_result(
        result_id="112234",
        evaluator_id=evaluator.id,
        agent_id=agent.id,
        persona_id=persona,
        scenario_id=scenario.id,
        status="completed",
        metric_scores={
            str(metric.id): {
                "value": False,
                "type": "boolean",
                "metric_name": "Pass/Fail",
                "rationale": "Another failure.",
            }
        },
    )

    stale = authenticated_client.get(
        "/api/v1/evaluator-results/metric-clusters",
        params=params,
    )
    assert stale.status_code == 200
    assert stale.json()["is_stale"] is True
    assert job.scope_key


def test_get_evaluator_result_metric_clusters_by_job_id(
    authenticated_client,
    db_session,
    make_agent,
    make_persona,
    make_scenario,
    make_evaluator,
    make_evaluator_result,
    make_metric,
):
    agent, scenario, _result, _metric = _seed_clusterable_evaluator_result(
        db_session,
        make_agent=make_agent,
        make_persona=make_persona,
        make_scenario=make_scenario,
        make_evaluator=make_evaluator,
        make_evaluator_result=make_evaluator_result,
        make_metric=make_metric,
    )
    job = _seed_completed_cluster_job(
        db_session,
        agent=agent,
        scenario=scenario,
        generated_at_completed_rows=1,
    )

    response = authenticated_client.get(
        "/api/v1/evaluator-results/metric-clusters",
        params={"job_id": str(job.id), "agent_id": str(agent.id)},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert len(body["groups"]) == 1


def test_get_evaluator_result_metric_clusters_by_scope_key(
    authenticated_client,
    db_session,
    make_agent,
    make_persona,
    make_scenario,
    make_evaluator,
    make_evaluator_result,
    make_metric,
):
    agent, scenario, _result, _metric = _seed_clusterable_evaluator_result(
        db_session,
        make_agent=make_agent,
        make_persona=make_persona,
        make_scenario=make_scenario,
        make_evaluator=make_evaluator,
        make_evaluator_result=make_evaluator_result,
        make_metric=make_metric,
    )
    job = _seed_completed_cluster_job(
        db_session,
        agent=agent,
        scenario=scenario,
        generated_at_completed_rows=1,
    )

    response = authenticated_client.get(
        "/api/v1/evaluator-results/metric-clusters",
        params={"scope_key": job.scope_key, "agent_id": str(agent.id)},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert len(body["groups"]) == 1


def test_delete_evaluator_result_metric_clusters(
    authenticated_client,
    db_session,
    make_agent,
    make_persona,
    make_scenario,
    make_evaluator,
    make_evaluator_result,
    make_metric,
):
    from app.models.database import EvaluatorResultClusterJob

    agent, scenario, _result, _metric = _seed_clusterable_evaluator_result(
        db_session,
        make_agent=make_agent,
        make_persona=make_persona,
        make_scenario=make_scenario,
        make_evaluator=make_evaluator,
        make_evaluator_result=make_evaluator_result,
        make_metric=make_metric,
    )
    job = _seed_completed_cluster_job(
        db_session,
        agent=agent,
        scenario=scenario,
        generated_at_completed_rows=1,
    )

    delete = authenticated_client.delete(
        "/api/v1/evaluator-results/metric-clusters",
        params={"job_id": str(job.id), "agent_id": str(agent.id)},
    )
    assert delete.status_code == 204

    gone = (
        db_session.query(EvaluatorResultClusterJob)
        .filter(EvaluatorResultClusterJob.id == job.id)
        .first()
    )
    assert gone is None

    scopes = authenticated_client.get("/api/v1/evaluator-results/metric-clusters/scopes")
    assert scopes.status_code == 200
    assert not any(
        item["scope_key"] == job.scope_key for item in scopes.json()["items"]
    )
